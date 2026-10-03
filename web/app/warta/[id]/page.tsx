import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Counts, DecisionChip } from '@/components/Chips';
import { ProvenanceNotice } from '@/components/Provenance';
import { ReadingPosition } from '@/components/ReadingPosition';
import { SaveButton } from '@/components/Saved';
import { ClaimCard, SourceList } from '@/components/Sources';
import { claimsForStory, comparisonsFor, displayTimestamp, manifest, storyById, stories } from '@/lib/data';

export const dynamicParams = false;

export function generateStaticParams() {
  return stories.map((story) => ({ id: story.id }));
}

export default async function StoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const story = storyById(id);
  if (!story) notFound();
  const claims = claimsForStory(story.id);

  return (
    <>
      <p className="small muted">
        <Link href="/warta/">← Warta</Link> · cerita {story.id}
      </p>
      <h1>{story.symbol} — {story.topic}</h1>
      <p className="lede">
        <DecisionChip decision={story.decision} /> {' '}
        <Counts counts={story.counts} /> · aksi {story.action} · {story.date}
        {story.status === 'withdrawn' ? ' · ditarik' : ''}
      </p>
      <p className="small muted">
        {story.revision
          ? <>revisi <span className="mono">{story.revision.revision_id}</span> · konten <span className="mono">{story.revision.content_hash.slice(0, 12)}…</span></>
          : 'belum ada revisi terdaftar'}
        {(story.relations ?? []).length > 0 ? ` · ${(story.relations ?? []).length} relasi tercatat` : ''}
      </p>
      <p className="small">
        <strong>Alasan mesin:</strong> {story.reason}
      </p>
      <ProvenanceNotice />
      <ReadingPosition story={story.id} revision={story.revision?.revision_id ?? null} />
      {(() => {
        const pair = comparisonsFor('arsip', story.id)[0];
        return pair ? (
          <p className="small">
            <Link href={`/banding/${story.id}/${pair.from_revision}/${pair.to_revision}/`}>
              Bandingkan {pair.changes.length} perubahan dengan revisi sebelumnya
            </Link>
          </p>
        ) : (
          <p className="small muted">Satu revisi tercatat: belum ada versi pembanding untuk dibandingkan.</p>
        );
      })()}
      {story.score_detail.length > 0 && (
        <ul className="plain small">
          {story.score_detail.map((row) => (
            <li key={row.rule}>
              aturan <span className="mono">{row.rule}</span> · {row.points} poin ·{' '}
              <span className="mono">{JSON.stringify(row.observed)}</span>
            </li>
          ))}
        </ul>
      )}
      <p>
        <SaveButton item={{ id: `story:${story.id}`, kind: 'Cerita', title: `${story.symbol} — ${story.topic}`, href: `/warta/${story.id}/` }} />
      </p>

      <section aria-labelledby="klaim">
        <h2 id="klaim">Klaim yang disetujui editor</h2>
        {claims.length === 0 ? (
          <p className="muted">
            Belum ada klaim yang ditinjau untuk cerita ini. Angka apa pun dari cerita ini tidak boleh
            dipakai sampai editor menyetujui klaimnya.
          </p>
        ) : (
          claims.map((claim) => <ClaimCard key={claim.id} claim={claim} />)
        )}
      </section>

      <SourceList sources={story.sources} heading="Artikel sumber" />

      <section aria-labelledby="catatan">
        <h2 id="catatan">Catatan bukti</h2>
        <p className="small muted">
          Ekspor ini memuat judul, waktu terbit, dan tautan sumber; isi artikel penuh tidak disalin.
          Waktu ditampilkan apa adanya dari arsip (WIB). Ekspor dibuat {displayTimestamp(manifest.generated_at)}.
        </p>
      </section>
    </>
  );
}
