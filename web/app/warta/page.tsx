import { Suspense } from 'react';
import { WartaExplorer } from '@/components/WartaExplorer';
import { coverage, manifest, stories } from '@/lib/data';

export default function WartaPage() {
  return (
    <>
      <h1>Warta</h1>
      <p className="lede">
        Setiap cerita adalah satu kombinasi emiten, topik, aksi dan tanggal. “Siap ditinjau” berarti
        minimal dua penerbit berbeda sepakat pada angka yang sama; “ditahan” berarti mesin menemukan
        benturan atau sindikasi. Saringan hidup di URL, jadi tautan yang dibagikan membuka daftar yang sama.
      </p>
      <Suspense fallback={<p className="muted">Memuat daftar…</p>}>
        <WartaExplorer
          stories={stories}
          dataset="arsip"
          generatedAt={manifest.generated_at}
          windowSince={coverage.since}
          policyVersion={coverage.policy_version}
          freshnessNote={`arsip historis; ekspor ${manifest.generated_at.slice(0, 16)}Z tercatat pada manifest`}
          availabilityNote="lengkap untuk berita arsip; data pendamping belum terpasang"
        />
      </Suspense>
    </>
  );
}
