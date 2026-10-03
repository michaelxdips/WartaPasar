import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Counts, DecisionChip } from '@/components/Chips';
import {
  CHANGE_LABELS, claimsForDataset, comparisonsFor, datasetOf, fixture,
  relationsFor, statusOf, storiesForTopic, topicRows, type DatasetName,
} from '@/lib/data';

export const dynamicParams = false;

export function generateStaticParams() {
  const ids = new Set([...topicRows('arsip').map((row) => row.id),
                       ...(fixture ? topicRows('fixture').map((row) => row.id) : [])]);
  return [...ids].map((topic) => ({ topic }));
}

function TopicSection({ dataset, topicId }: { dataset: DatasetName; topicId: string }) {
  const row = topicRows(dataset).find((item) => item.id === topicId);
  if (!row) return null;
  const stories = storiesForTopic(dataset, topicId);
  const claims = claimsForDataset(dataset).filter((claim) =>
    stories.some((story) => story.id === claim.story_id));
  const disagreements = stories.flatMap((story) =>
    relationsFor(dataset, story.id).map((relation) => ({ story, relation })));
  return (
    <section aria-labelledby={`topik-${dataset}`}>
      <h2 id={`topik-${dataset}`}>
        {dataset === 'fixture' ? 'Fixture sintetis' : 'Arsip'}
        {dataset === 'fixture' ? <span className="chip"> FIXTURE SINTETIS</span> : null}
      </h2>
      <p className="small muted">
        {row.stories} cerita · {row.reviewable} siap ditinjau · {row.claims} klaim disetujui ·{' '}
        {row.symbols.length} emiten
        {row.firstDate ? ` · ${row.firstDate}${row.lastDate && row.lastDate !== row.firstDate ? ` – ${row.lastDate}` : ''}` : ''}
        {dataset === 'arsip' ? ' · jendela arsip' : ''}
      </p>

      <h3>Cerita pendukung</h3>
      {stories.length === 0 ? (
        <p className="muted">Tidak ada cerita pada topik ini.</p>
      ) : (
        <ul className="plain">
          {stories.slice(0, 24).map((story) => (
            <li key={story.id}>
              <Link href={dataset === 'arsip' ? `/warta/${story.id}/` : `/jelajah/${topicId}/#${story.id}`}>
                {story.symbol} — {story.topic}
              </Link>{' '}
              <DecisionChip decision={story.decision} />
              <div className="small muted">
                <Counts counts={story.counts} /> · {story.date} · {story.reason}
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3>Bukti yang tersedia</h3>
      {claims.length === 0 ? (
        <p className="small muted">
          Belum ada klaim disetujui pada topik ini. Cerita yang “siap ditinjau” tetap menunggu keputusan
          editor dan angka apa pun darinya belum boleh dipakai.
        </p>
      ) : (
        <ul className="plain">
          {claims.map((claim) => (
            <li key={claim.id}>
              <Link href={`/ronce/${claim.id}/`}>{claim.text}</Link>
              <div className="small muted">
                {claim.metric ?? 'metrik tidak dicatat'} · {claim.value ?? '-'} {claim.unit ?? ''}
                {claim.scale && claim.scale !== 'unit' ? ` (skala ${claim.scale})` : ''}
                {claim.period ? ` · periode ${claim.period}` : ''} ·{' '}
                {claim.source_counts
                  ? `${claim.source_counts.articles} artikel, ${claim.source_counts.publishers} penerbit, ${claim.source_counts.reviewed_origins} asal ditinjau`
                  : 'hitungan sumber tidak dicatat'}
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3>Perbedaan yang tercatat</h3>
      {disagreements.length === 0 ? (
        <p className="small muted">
          Tidak ada relasi bertipe pada topik ini, jadi tidak ada perbedaan atau koreksi yang bisa
          ditampilkan. Topik yang sama bukan bukti korelasi atau pertentangan.
        </p>
      ) : (
        <ul className="plain">
          {disagreements.map(({ story, relation }) => (
            <li key={relation.relation_id} className="small">
              <span className="chip">{relation.kind}</span> {relation.reason}{' '}
              <span className="muted">· bukti: {relation.evidence} · cerita {story.symbol}</span>
            </li>
          ))}
        </ul>
      )}

      <h3>Versi dan perbandingan</h3>
      {(() => {
        const pairs = stories.flatMap((story) => comparisonsFor(dataset, story.id).map((pair) => ({ story, pair })));
        if (pairs.length === 0) return <p className="small muted">Belum ada revisi pembanding pada topik ini.</p>;
        return (
          <ul className="plain">
            {pairs.map(({ story, pair }) => (
              <li key={pair.to_revision} className="small">
                <Link href={`/banding/${story.id}/${pair.from_revision}/${pair.to_revision}/`}>
                  {story.symbol}: {pair.changes.length} perubahan
                </Link>{' '}
                <span className="muted">
                  {pair.changes.slice(0, 3).map((change) => CHANGE_LABELS[change.kind] ?? change.kind).join(', ')}
                </span>
              </li>
            ))}
          </ul>
        );
      })()}
      <p className="small muted">Status tema saat ini: {stories.length > 0 ? statusOf(dataset, stories[0].id) : 'tidak ada cerita'}.</p>
    </section>
  );
}

export default async function TopicPage({ params }: { params: Promise<{ topic: string }> }) {
  const { topic } = await params;
  const inArchive = topicRows('arsip').some((row) => row.id === topic);
  const inFixture = fixture ? topicRows('fixture').some((row) => row.id === topic) : false;
  if (!inArchive && !inFixture) notFound();
  const label = topicRows(inArchive ? 'arsip' : 'fixture').find((row) => row.id === topic)?.label ?? topic;

  return (
    <>
      <p className="small muted">
        <Link href="/">← Orbit</Link> · <Link href="/jelajah/">Jelajah</Link>
      </p>
      <h1>{label}</h1>
      <p className="lede">
        Ringkasan topik dihitung dari catatan mesin dan registri: jumlah cerita, keputusan, hitungan
        sumber, dan klaim yang sudah disetujui. Tidak ada penjelasan ekonomi yang dikarang dari
        kebetulan judul.
      </p>
      {inArchive ? <TopicSection dataset="arsip" topicId={topic} /> : null}
      {inFixture ? <TopicSection dataset="fixture" topicId={topic} /> : null}
      <p className="small">
        <Link href="/warta/">Warta</Link> · <Link href="/ronce/">Ronce Thread</Link> ·{' '}
        <Link href="/jelajah/">kembali ke Jelajah</Link>
      </p>
    </>
  );
}
