import { coverage, displayTimestamp, manifest } from '@/lib/data';

export function ProvenanceNotice() {
  const inferred = coverage.interpretation?.time_basis === 'inferred_internal';
  return (
    <aside className="notice" aria-label="Asal dan kesegaran data">
      <p className="small">
        <strong>Edisi arsip</strong>, bukan edisi hari ini. Jendela berita sejak{' '}
        {displayTimestamp(coverage.since)} · ekspor dibuat {displayTimestamp(manifest.generated_at)} ·
        {' '}{coverage.articles} artikel · {manifest.counts.stories} cerita · {manifest.counts.claims} klaim disetujui ·
        {' '}kebijakan <span className="mono">{coverage.policy_version ?? 'tidak dicatat'}</span>.
      </p>
      {inferred && (
        <p className="small">
          <strong>Perhatian:</strong> zona waktu run ini adalah asumsi demo internal (+07:00), bukan
          konfirmasi penyedia; angka dari run semacam ini tidak boleh naik ke publikasi.
        </p>
      )}
      <p className="small muted">
        Permukaan baca hanya memuat edisi yang disetujui editor; isi artikel penuh tidak diekspor dan
        setiap cerita menampilkan tautan sumbernya.
      </p>
    </aside>
  );
}
