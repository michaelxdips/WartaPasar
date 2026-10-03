import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Citation } from '@/components/Citation';
import {
  CHANGE_LABELS, comparisonsFor, datasetOf, displayTimestamp, edition, fixture, relationsFor,
  revisionOf, stories, statusOf, type DatasetName, type Revision, type RevisionClaim,
} from '@/lib/data';
import { citationText } from '@/lib/citation';

export const dynamicParams = false;

function pairs(): { dataset: DatasetName; story: string; from: string; to: string }[] {
  const rows: { dataset: DatasetName; story: string; from: string; to: string }[] = [];
  for (const name of ['arsip', 'fixture'] as DatasetName[]) {
    if (name === 'fixture' && !fixture) continue;
    for (const pair of comparisonsFor(name)) {
      rows.push({ dataset: name, story: pair.story_key, from: pair.from_revision, to: pair.to_revision });
    }
  }
  return rows;
}

export function generateStaticParams() {
  return pairs().map((row) => ({ story: row.story, from: row.from, to: row.to }));
}

function RevisionCard({ revision, title, anchor }: { revision: Revision; title: string; anchor: string }) {
  return (
    <article className="card" id={anchor}>
      <h3>{title}</h3>
      <p className="small muted">
        revisi <span className="mono">{revision.revision_id}</span> · konten{' '}
        <span className="mono">{revision.content_hash.slice(0, 12)}…</span> ·{' '}
        {displayTimestamp(revision.created_at)} · status saat itu {revision.payload.status_at} · keputusan{' '}
        {revision.decision}
      </p>
      <p className="small">{revision.payload.reason}</p>
      <h4>Klaim</h4>
      {revision.payload.claims.length === 0
        ? <p className="small muted">Tidak ada klaim disetujui pada revisi ini.</p>
        : (
          <ul className="plain">
            {revision.payload.claims.map((claim) => (
              <li key={claim.text}>
                {claim.text}
                <div className="small muted">
                  {claim.metric ?? 'metrik tidak dicatat'} · {claim.value ?? '-'} {claim.unit ?? ''}
                  {claim.scale && claim.scale !== 'unit' ? ` (skala ${claim.scale})` : ''}
                  {claim.period ? ` · periode ${claim.period}` : ''}
                  {claim.claim_type === 'analyst_opinion' ? ` · opini: ${claim.attribution ?? 'tanpa atribusi'}` : ''}
                </div>
                <ul className="plain">
                  {claim.evidence.map((item) => (
                    <li key={`${item.url}-${item.origin}`} className="small">
                      <q>{item.quote}</q>{' '}
                      <span className="muted">({item.origin} · {item.origin_basis === 'independent_review'
                        ? 'asal berdiri sendiri' : 'asal belum dinyatakan'})</span>{' '}
                      <a href={item.url} target="_blank" rel="noreferrer noopener">{item.url}</a>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      <h4>Sumber</h4>
      <ul className="plain">
        {revision.payload.sources.map((source) => (
          <li key={source.url} className="small">
            {source.title ?? source.url} <span className="muted">{displayTimestamp(source.timestamp)}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

export default async function BandingPage({ params }: { params: Promise<{ story: string; from: string; to: string }> }) {
  const { story, from, to } = await params;
  const row = pairs().find((item) => item.story === story && item.from === from && item.to === to);
  if (!row) notFound();
  const datasetName: DatasetName = row.dataset;
  const dataset = datasetOf(datasetName);
  const older = revisionOf(datasetName, from);
  const newer = revisionOf(datasetName, to);
  if (!older || !newer || older.story_key !== story || newer.story_key !== story) notFound();
  const pair = comparisonsFor(datasetName, story).find((item) => item.from_revision === from && item.to_revision === to);
  if (!pair) notFound();
  const relations = relationsFor(datasetName, story);
  const status = statusOf(datasetName, story);
  const storyInArchive = stories.some((item) => item.id === story);
  const link = `/banding/${story}/${from}/${to}/`;

  function citation(claim: RevisionClaim, revision: Revision, historical: boolean) {
    return citationText({
      claim, revision, dataset: datasetName, edition: datasetName === 'arsip' ? edition : null,
      link: `${link}#${revision.revision_id}`, historical,
    });
  }

  return (
    <>
      <p className="small muted">
        <Link href="/">← Orbit</Link>
        {storyInArchive ? <> · <Link href={`/warta/${story}/`}>cerita {story}</Link></> : null}
        {' '}· perbandingan revisi {dataset.label}
      </p>
      <h1>Bandingkan revisi</h1>
      {dataset.synthetic ? (
        <p className="notice small" role="note">
          <strong>FIXTURE SINTETIS.</strong> Kedua revisi di halaman ini berasal dari fixture uji yang
          diproses mesin yang sama, bukan berita pasar nyata. Setiap kutipan yang disalin ikut membawa label ini.
        </p>
      ) : (
        <p className="small muted">
          Perbandingan dari arsip nyata; status cerita saat ini: {status}. Revisi lama disimpan apa adanya.
        </p>
      )}
      <p className="small muted">
        {displayTimestamp(pair.from_captured_at)} → {displayTimestamp(pair.to_captured_at)} ·{' '}
        {pair.changes.length} perubahan tercatat
      </p>

      <section aria-labelledby="perubahan">
        <h2 id="perubahan">Perubahan</h2>
        {pair.changes.length === 0
          ? <p className="muted">Tidak ada perubahan konten yang terdeteksi antara dua revisi ini.</p>
          : (
            <ul className="plain">
              {pair.changes.map((change, index) => (
                <li key={`${change.kind}-${index}`}>
                  <span className="chip">{CHANGE_LABELS[change.kind] ?? change.kind}</span>{' '}
                  <span className="small">{change.detail}</span>
                  {change.basis ? <span className="small muted"> · dasar: {change.basis}</span> : null}
                  {change.before && change.after ? (
                    <div className="small muted mono">
                      {JSON.stringify(change.before)} → {JSON.stringify(change.after)}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
      </section>

      <div className="grid cols-2">
        <RevisionCard revision={older} title="Revisi lama (tidak berubah)" anchor={older.revision_id} />
        <RevisionCard revision={newer} title="Revisi baru" anchor={newer.revision_id} />
      </div>

      {relations.length > 0 && (
        <section aria-labelledby="relasi">
          <h2 id="relasi">Relasi tercatat</h2>
          <ul className="plain">
            {relations.map((relation) => (
              <li key={relation.relation_id} className="small">
                <span className="chip">{relation.kind}</span> {relation.reason}{' '}
                <span className="muted">· bukti: {relation.evidence}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="kutip">
        <h2 id="kutip">Kutip dengan sumber</h2>
        <p className="small muted">
          Teks kutipan dibuat dari catatan klaim bertipe pada revisi terpilih; tidak ada tafsir baru.
        </p>
        {newer.payload.claims.map((claim) => (
          <div key={`new-${claim.text}`} className="card">
            <p className="small"><strong>Revisi baru</strong> — {claim.text}</p>
            {claim.claim_type === 'analyst_opinion' ? (
              <p className="small muted">Opini· {claim.attribution ?? 'tanpa atribusi'}</p>
            ) : null}
            <Citation text={citation(claim, newer, status === 'withdrawn')} />
          </div>
        ))}
        {older.payload.claims.map((claim) => (
          <div key={`old-${claim.text}`} className="card">
            <p className="small"><strong>Revisi lama</strong> — {claim.text}</p>
            <Citation text={citation(claim, older, true)} label="Salin kutipan historis" />
          </div>
        ))}
      </section>
    </>
  );
}
