import Link from 'next/link';
import { coverage, displayTimestamp, edition, manifest, stories } from '@/lib/data';

export default function ArsipPage() {
  const urls = new Map<string, { url: string; title: string | null; timestamp: string | null }>();
  for (const story of stories) {
    for (const source of story.sources) {
      if (!urls.has(source.url)) urls.set(source.url, { url: source.url, title: source.title, timestamp: source.timestamp });
    }
  }
  const rows = [...urls.values()].sort((a, b) => (b.timestamp ?? '').localeCompare(a.timestamp ?? ''));

  return (
    <>
      <h1>Arsip</h1>
      <p className="lede">
        Jendela editorial yang menghasilkan edisi {edition.edition_id}: {coverage.articles} artikel
        terkumpul dari {rows.length} sumber pada {coverage.candidates} cerita. Arsip asli tersimpan
        terpisah dan tidak ikut diekspor; halaman ini menampilkan apa yang boleh dibaca.
      </p>

      <section className="grid cols-3" aria-label="Cakupan arsip">
        <div className="card stat"><b>{coverage.articles}</b><span>artikel terkumpul</span></div>
        <div className="card stat"><b>{coverage.reviewable}</b><span>cerita siap ditinjau</span></div>
        <div className="card stat"><b>{rows.length}</b><span>sumber berbeda</span></div>
      </section>

      <section aria-labelledby="kebijakan">
        <h2 id="kebijakan">Kebijakan ekspor</h2>
        <dl className="receipt">
          <dt>Sejak</dt><dd>{displayTimestamp(coverage.since)}</dd>
          <dt>Dibuat</dt><dd>{displayTimestamp(manifest.generated_at)}</dd>
          <dt>Permukaan baca</dt><dd>{manifest.policy.reader_surface}</dd>
          <dt>Isi artikel penuh</dt><dd>{manifest.policy.bodies_exported ? 'diekspor' : 'tidak diekspor'}</dd>
          <dt>Publikasi live</dt><dd>{String(manifest.policy.live_publishing)}</dd>
        </dl>
      </section>

      <section aria-labelledby="daftar-sumber">
        <h2 id="daftar-sumber">Sumber pada jendela ini</h2>
        <table>
          <caption className="sr-only">Daftar sumber unik beserta judul dan waktu terbit</caption>
          <thead>
            <tr>
              <th scope="col">Waktu</th>
              <th scope="col">Judul</th>
              <th scope="col">Tautan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.url}>
                <td>{displayTimestamp(row.timestamp)}</td>
                <td>{row.title ?? '—'}</td>
                <td><a href={row.url} target="_blank" rel="noreferrer noopener">buka</a></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">
          Butuh cerita tertentu? Mulai dari <Link href="/warta/">Warta</Link> atau{' '}
          <Link href="/cari/">Cari</Link>.
        </p>
      </section>
    </>
  );
}
