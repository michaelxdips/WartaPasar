import Link from 'next/link';
import { Counts, DecisionChip } from '@/components/Chips';
import { ProvenanceNotice } from '@/components/Provenance';
import {
  COMPANION_FAMILY_LABELS, claims, companion, companionFamilyRecords, companionStatuses, coverage,
  decisions, displayTimestamp, edition, manifest, stories, topics,
} from '@/lib/data';

export default function OrbitPage() {
  const { review, abstain } = decisions();
  const storiesWithClaims = new Set(claims.map((claim) => claim.story_id));
  const topTopics = topics().slice(0, 5);

  return (
    <>
      <h1>Orbit edisi {edition.edition_id}</h1>
      <p className="lede">
        Ringkasan pagi ini: {stories.length} cerita dari {coverage.articles} artikel terkumpul,
        {' '}{review.length} siap ditinjau dan {abstain.length} ditahan mesin. Angka di setiap cerita
        berasal dari klaim yang disetujui editor, bukan dari prosa.
      </p>

      <ProvenanceNotice />

      <section className="grid cols-3" aria-label="Angka edisi" style={{ marginTop: '1.25rem' }}>
        <div className="card stat"><b>{coverage.articles}</b><span>artikel pada jendela editorial</span></div>
        <div className="card stat"><b>{review.length}</b><span>cerita siap ditinjau</span></div>
        <div className="card stat"><b>{claims.length}</b><span>klaim disetujui · {edition.posts.length} post</span></div>
      </section>

      <section aria-labelledby="sorotan">
        <h2 id="sorotan">Sorotan</h2>
        <div className="grid cols-2">
          {review.slice(0, 6).map((story) => (
            <article className="card" key={story.id}>
              <Link className="card-link" href={`/warta/${story.id}/`}>
                <h3>{story.symbol} — {story.topic}</h3>
              </Link>
              <p className="small muted">
                <DecisionChip decision={story.decision} /> {' '}
                <Counts counts={story.counts} /> · {story.date}
                {storiesWithClaims.has(story.id) ? ' · punya klaim disetujui' : ''}
              </p>
              <p className="small">{story.reason}</p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="edisi-terbit">
        <h2 id="edisi-terbit">Edisi terbit</h2>
        <div className="post">
          <p className="small muted">
            Disetujui {edition.approval.editor} · {displayTimestamp(String(edition.approval.approved_at))} ·
            platform {edition.platform} · publikasi live {String(manifest.policy.live_publishing)}
          </p>
          {edition.posts.map((post) => (
            <p key={post.ordinal}>
              <Link href={`/edisi/${edition.uid}/#post-${post.ordinal}`}>Post {post.ordinal}</Link>
              {' '}— <span className="small">{post.text.split('\n')[0]}</span>
            </p>
          ))}
        </div>
      </section>

      {companion && (
        <section aria-labelledby="bergerak">
          <h2 id="bergerak">Yang bergerak <span className="chip">FIXTURE SINTETIS</span></h2>
          <p className="small muted">
            Peringkat dari subset yang benar-benar diambil (classifications × periods), bukan peringkat
            seluruh pasar. Nilai companion adalah konteks pasar teratribusi — bukan klaim yang ditinjau
            editor dan tidak mewarisi persetujuan.
          </p>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Pergerakan teratas pada subset yang diambil</caption>
              <thead>
                <tr><th scope="col">Emiten</th><th scope="col">Klasifikasi</th><th scope="col">Perubahan</th>
                    <th scope="col">Harga terakhir</th><th scope="col">Tanggal</th><th scope="col">Periode</th></tr>
              </thead>
              <tbody>
                {companionFamilyRecords('movers').map((record) => (
                  <tr key={record.id}>
                    <th scope="row"><Link href={`/emiten/${record.symbol}/`}>{record.symbol}</Link></th>
                    <td className="small">{String(record.value.classification ?? '-')}</td>
                    <td className="small">{record.value.price_change === null ? 'tidak dicatat'
                      : `${(Number(record.value.price_change) * 100).toFixed(1)}%`}</td>
                    <td className="small">{record.value.last_close_price === null ? 'tidak dicatat'
                      : String(record.value.last_close_price)}</td>
                    <td className="small">{record.as_of ?? 'tidak dicatat'}</td>
                    <td className="small">{record.period ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            {companionStatuses().filter((row) => row.family === 'movers').map((row) =>
              `Sumber ${row.endpoint} · status ${row.status} · diambil ${displayTimestamp(row.retrieved_at)} · kontrak dicek ${row.contract_checked}`).join(' · ')}
          </p>
          <p className="small muted">
            Keluarga lain: {companionStatuses().map((row) =>
              `${COMPANION_FAMILY_LABELS[row.family] ?? row.family} ${row.status}`).join(' · ')}.
            {' '}<Link href="/kalender/">Buka Kalender</Link> untuk aksi korporasi.
          </p>
        </section>
      )}

      <section aria-labelledby="topik">
        <h2 id="topik">Topik teratas</h2>
        <ul className="plain">
          {topTopics.map((row) => (
            <li key={row.topic}>
              <Link href={`/jelajah/${row.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}/`}>
                {row.topic}
              </Link>
              <span className="small muted"> · {row.total} cerita · {row.reviewable} siap ditinjau</span>
            </li>
          ))}
        </ul>
        <p className="small">
          <Link href="/jelajah/">Buka Jelajah</Link> untuk ringkasan per topik, bukti yang tersedia, dan
          perbedaan yang tercatat.
        </p>
      </section>
    </>
  );
}
