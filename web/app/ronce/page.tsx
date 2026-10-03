import Link from 'next/link';
import { claimsForDataset, fixture, stories } from '@/lib/data';

export default function RonceIndexPage() {
  const archiveClaims = claimsForDataset('arsip');
  const fixtureClaims = fixture ? claimsForDataset('fixture') : [];
  return (
    <>
      <h1>Ronce Thread</h1>
      <p className="lede">
        Satu klaim, satu halaman: angka bertipe, kutipan bukti yang persis, asal tinjauan, konteks
        revisi dan relasi yang tercatat. Bukti tidak pernah hanya bisa diakses lewat kontrol visual.
      </p>

      <section aria-labelledby="klaim-arsip">
        <h2 id="klaim-arsip">Klaim arsip</h2>
        {archiveClaims.length === 0 ? (
          <p className="muted">Belum ada klaim disetujui pada arsip ini.</p>
        ) : (
          <ul className="plain">
            {archiveClaims.map((claim) => (
              <li key={claim.id}>
                <Link href={`/ronce/${claim.id}/`}>{claim.text}</Link>
                <div className="small muted">
                  {claim.entity} · {claim.claim_type === 'analyst_opinion' ? 'opini' : 'fakta dilaporkan'} ·{' '}
                  {claim.source_counts
                    ? `${claim.source_counts.articles} artikel, ${claim.source_counts.publishers} penerbit`
                    : 'hitungan sumber tidak dicatat'}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {fixtureClaims.length > 0 && (
        <section aria-labelledby="klaim-fixture">
          <h2 id="klaim-fixture">Klaim fixture sintetis</h2>
          <p className="small muted">Uji sintetis dengan relasi dan dua revisi; bukan berita pasar nyata.</p>
          <ul className="plain">
            {fixtureClaims.map((claim) => (
              <li key={claim.id}>
                <Link href={`/ronce/${claim.id}/`}>{claim.text}</Link>{' '}
                <span className="chip">FIXTURE SINTETIS</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="small">
        Cerita yang belum punya klaim tetap bisa diperiksa di <Link href="/warta/">Warta</Link> (
        {stories.length} cerita arsip).
      </p>
    </>
  );
}
