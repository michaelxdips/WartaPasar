import Link from 'next/link';
import { notFound } from 'next/navigation';
import { SaveButton } from '@/components/Saved';
import { claims, coverage, displayTimestamp, edition, manifest } from '@/lib/data';

export const dynamicParams = false;

export function generateStaticParams() {
  return [{ uid: edition.uid }];
}

export default async function EditionPage({ params }: { params: Promise<{ uid: string }> }) {
  const { uid } = await params;
  if (uid !== edition.uid) notFound();

  return (
    <>
      <p className="small muted">
        <Link href="/">← Orbit</Link> · edisi {edition.uid}
      </p>
      <h1>Edisi {edition.edition_id}</h1>
      <p className="lede">
        {edition.posts.length} post disetujui {edition.approval.editor} pada{' '}
        {displayTimestamp(String(edition.approval.approved_at))} untuk platform {edition.platform}.
        Publikasi live: {String(manifest.policy.live_publishing)}.
      </p>
      <p>
        <SaveButton
          item={{ id: `edition:${edition.uid}`, kind: 'Edisi', title: `Edisi ${edition.edition_id}`, href: `/edisi/${edition.uid}/` }}
        />
      </p>

      <section aria-labelledby="post">
        <h2 id="post">Post yang disetujui</h2>
        {edition.posts.map((post) => {
          const linked = claims.find((claim) => claim.id === post.claim_id);
          return (
            <article className="post" key={post.ordinal} id={`post-${post.ordinal}`} style={{ marginBottom: '1rem' }}>
              <h3>Post {post.ordinal}</h3>
              <pre>{post.text}</pre>
              <p className="small muted">
                SHA256 teks: <span className="mono">{post.text_hash}</span>
              </p>
              {linked && (
                <p className="small">
                  Klaim: <Link href={`/warta/${linked.story_id}/#${linked.id}`}>{linked.text}</Link>
                  {' '}· angka {linked.value ?? 'tidak dicatat'} {linked.unit ?? ''}
                  {linked.scale ? ` (skala ${linked.scale})` : ''}
                </p>
              )}
            </article>
          );
        })}
      </section>

      <section aria-labelledby="resit">
        <h2 id="resit">Resit ekspor</h2>
        <dl className="receipt">
          <dt>Hash edisi</dt>
          <dd className="mono">{edition.hash}</dd>
          <dt>Hash berkas</dt>
          {Object.entries(manifest.files).map(([name, digest]) => (
            <dd key={name} className="mono">{name}: {digest}</dd>
          ))}
          <dt>Jendela editorial</dt>
          <dd>
            sejak {displayTimestamp(coverage.since)} · {coverage.articles} artikel · {coverage.candidates} cerita
            ({coverage.reviewable} siap ditinjau)
          </dd>
          <dt>Interpretasi waktu</dt>
          <dd>
            {coverage.interpretation
              ? `sumber ${coverage.interpretation.source_timezone}, filter ${coverage.interpretation.filter_timezone}, bukti: ${coverage.interpretation.evidence}`
              : 'tanpa sidecar interpretasi pada ekspor ini'}
          </dd>
          <dt>Kebijakan</dt>
          <dd>
            hanya edisi disetujui · isi artikel penuh tidak diekspor · kredensial tidak pernah masuk ekspor
          </dd>
        </dl>
      </section>
    </>
  );
}
