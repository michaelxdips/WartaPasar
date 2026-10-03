import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Citation } from '@/components/Citation';
import {
  claimsForDataset, comparisonsFor, datasetOf, displayTimestamp, editionOf, fixture,
  latestRevisionFor, relationsFor, safeUrl, statusOf, type Claim, type DatasetName,
} from '@/lib/data';
import { citationText } from '@/lib/citation';

export const dynamicParams = false;

function allClaims(): { dataset: DatasetName; claim: Claim }[] {
  const rows: { dataset: DatasetName; claim: Claim }[] = claimsForDataset('arsip')
    .map((claim) => ({ dataset: 'arsip' as DatasetName, claim }));
  if (fixture) {
    rows.push(...claimsForDataset('fixture').map((claim) => ({ dataset: 'fixture' as DatasetName, claim })));
  }
  return rows;
}

export function generateStaticParams() {
  return allClaims().map(({ claim }) => ({ claim: claim.id }));
}

export default async function ThreadPage({ params }: { params: Promise<{ claim: string }> }) {
  const { claim: claimId } = await params;
  const entry = allClaims().find((row) => row.claim.id === claimId);
  if (!entry) notFound();
  const { dataset, claim } = entry;
  const data = datasetOf(dataset);
  const story = claim.story_id ? data.stories.find((item) => item.id === claim.story_id) : undefined;
  if (!story) notFound();
  const revision = latestRevisionFor(dataset, story.id);
  const archivedClaim = revision?.payload.claims.find((item) => item.text === claim.text);
  const relations = relationsFor(dataset, story.id);
  const pairs = comparisonsFor(dataset, story.id);
  const status = statusOf(dataset, story.id);
  const edition = editionOf(dataset);
  const threadLink = `/ronce/${claim.id}/`;

  const citation = citationText({
    claim: archivedClaim ?? {
      text: claim.text, entity: claim.entity, action: claim.action, value: claim.value, unit: claim.unit,
      scale: claim.scale, metric: claim.metric, period: claim.period, claim_type: claim.claim_type,
      attribution: claim.attribution, source_counts: claim.source_counts, evidence: claim.evidence,
    },
    revision: revision ?? {
      revision_id: 'tidak ada revisi', story_key: story.id, run_id: null, content_hash: '',
      decision: story.decision, created_at: '', payload: { story_key: story.id, decision: story.decision,
        reason: story.reason, status_at: status, policy_version: 'tidak dicatat', sources: [], claims: [] },
    },
    dataset, edition, link: threadLink, historical: status === 'withdrawn',
  });

  return (
    <>
      <p className="small muted">
        <Link href="/">← Orbit</Link> · <Link href="/ronce/">Ronce Thread</Link>
        {dataset === 'arsip'
          ? <> · <Link href={`/warta/${story.id}/`}>cerita {story.symbol}</Link></>
          : <> · <span className="chip">FIXTURE SINTETIS</span></>}
      </p>
      <h1>{claim.text}</h1>
      <p className="lede">
        {claim.entity} · {story.topic} · {story.action} · {claim.event_time} ·{' '}
        {claim.claim_type === 'analyst_opinion' ? 'opini berlabel' : 'fakta dilaporkan'} · status cerita {status}
      </p>
      <p className="small muted">
        Cerita <Link href={dataset === 'arsip' ? `/warta/${story.id}/` : threadLink}>#{story.id}</Link> ·{' '}
        keputusan mesin {story.decision} · {story.reason}
      </p>

      <section aria-labelledby="angka">
        <h2 id="angka">Angka bertipe</h2>
        <dl className="receipt">
          <dt>Metrik</dt><dd>{claim.metric ?? 'tidak dicatat'}</dd>
          <dt>Nilai</dt><dd>{claim.value ?? 'tidak dicatat'} {claim.unit ?? ''}{claim.scale ? ` · skala ${claim.scale}` : ''}</dd>
          <dt>Periode</dt><dd>{claim.period ?? 'tidak dicatat'}</dd>
          <dt>Entitas</dt><dd>{claim.entity}</dd>
          {claim.claim_type === 'analyst_opinion' && (
            <>
              <dt>Atribusi opini</dt><dd>{claim.attribution ?? 'tidak dicatat'}</dd>
            </>
          )}
          <dt>Hitungan sumber</dt>
          <dd>
            {claim.source_counts
              ? `${claim.source_counts.articles} artikel · ${claim.source_counts.publishers} penerbit · ${claim.source_counts.reviewed_origins} asal ditinjau`
              : 'tidak dicatat'}
          </dd>
          <dt>Basis waktu</dt>
          <dd>
            {dataset === 'arsip' && edition
              ? `jendela arsip, waktu sumber +07:00, ekspor ${displayTimestamp(edition.approval.approved_at)}`
              : 'fixture sintetis; waktu uji'}
          </dd>
        </dl>
        <p className="small muted">
          Pemeriksaan angka bersifat leksikal dan metadata: nilai, satuan, skala, periode dan tanda harus
          cocok dengan kutipan, dan metrik harus muncul di teks kutipan. Itu bukan bukti semantik.
        </p>
      </section>

      <section aria-labelledby="bukti">
        <h2 id="bukti">Kutipan bukti</h2>
        {claim.evidence.map((item) => {
          const url = safeUrl(item.url);
          return (
            <article className="card" key={`${item.url}-${item.origin}`}>
              <blockquote><q>{item.quote}</q></blockquote>
              <p className="small muted">
                asal: {item.origin} · {item.origin_basis === 'independent_review'
                  ? 'asal berdiri sendiri (keputusan editorial tercatat)'
                  : 'asal belum dinyatakan'}
              </p>
              {url ? (
                <p className="small">
                  <a href={url} target="_blank" rel="noreferrer noopener">{url}</a>
                </p>
              ) : (
                <p className="small muted">Tautan sumber tidak ditampilkan: skema tidak sah.</p>
              )}
            </article>
          );
        })}
      </section>

      <section aria-labelledby="relasi">
        <h2 id="relasi">Relasi tercatat</h2>
        {relations.length === 0 ? (
          <p className="small muted">
            Tidak ada relasi bertipe untuk cerita ini. Topik atau emiten yang sama bukan korelasi,
            koreksi, atau pembenaran tambahan — jadi tidak ada yang ditampilkan.
          </p>
        ) : (
          <>
            <ul className="plain">
              {relations.map((relation) => (
                <li key={relation.relation_id} className="small">
                  <span className="chip">{relation.kind}</span> {relation.reason}{' '}
                  <span className="muted">· bukti: {relation.evidence}</span>
                </li>
              ))}
            </ul>
            <h3>Tampilan dua arah (terbatas)</h3>
            <table>
              <caption className="sr-only">Relasi klaim ini dengan cerita lain</caption>
              <thead>
                <tr><th scope="col">Dari</th><th scope="col">Jenis</th><th scope="col">Ke</th></tr>
              </thead>
              <tbody>
                {relations.slice(0, 6).map((relation) => (
                  <tr key={`pair-${relation.relation_id}`}>
                    <td className="small">{relation.from_story === story.id ? story.symbol : relation.from_story.slice(0, 8)}</td>
                    <td className="small">{relation.kind}</td>
                    <td className="small">{relation.to_story === story.id ? story.symbol : relation.to_story.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="small muted">Daftar di atas adalah bentuk lengkap; tabel hanya ringkas dan dibatasi enam baris.</p>
          </>
        )}
      </section>

      <section aria-labelledby="riwayat">
        <h2 id="riwayat">Riwayat revisi dan banding</h2>
        {revision ? (
          <p className="small muted">
            Revisi terakhir <span className="mono">{revision.revision_id}</span> ·{' '}
            {displayTimestamp(revision.created_at)} · status saat itu {revision.payload.status_at} · kebijakan{' '}
            {revision.payload.policy_version}
          </p>
        ) : (
          <p className="small muted">Belum ada revisi tercatat untuk cerita ini.</p>
        )}
        {pairs.length === 0 ? (
          <p className="small muted">Belum ada revisi pembanding.</p>
        ) : (
          <ul className="plain">
            {pairs.map((pair) => (
              <li key={pair.to_revision} className="small">
                <Link href={`/banding/${story.id}/${pair.from_revision}/${pair.to_revision}/`}>
                  Bandingkan {pair.changes.length} perubahan dengan revisi sebelumnya
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="kutip-thread">
        <h2 id="kutip-thread">Kutip dengan sumber</h2>
        <Citation text={citation} label={status === 'withdrawn' ? 'Salin kutipan historis' : 'Salin kutipan'} />
      </section>
    </>
  );
}
