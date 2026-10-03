import Link from 'next/link';
import { ProvenanceNotice } from '@/components/Provenance';
import { coverage, fixture, topicRows } from '@/lib/data';

export default function JelajahPage() {
  const archiveRows = topicRows('arsip');
  const fixtureRows = fixture ? topicRows('fixture') : [];
  return (
    <>
      <h1>Jelajah</h1>
      <p className="lede">
        Topik berasal dari registri yang disimpan, bukan dari pengelompokan ulang judul. Setiap baris
        menunjukkan berapa cerita yang masuk, berapa yang siap ditinjau, dan berapa klaim yang sudah
        disetujui editor pada jendela ini.
      </p>
      <ProvenanceNotice />

      <section aria-labelledby="topik-arsip">
        <h2 id="topik-arsip">Topik pada arsip</h2>
        {archiveRows.length === 0 ? (
          <p className="muted">Belum ada topik pada arsip ini.</p>
        ) : (
          <table>
            <caption className="sr-only">Topik arsip dengan jumlah cerita dan klaim</caption>
            <thead>
              <tr>
                <th scope="col">Topik</th>
                <th scope="col">Cerita</th>
                <th scope="col">Siap ditinjau</th>
                <th scope="col">Klaim disetujui</th>
                <th scope="col">Emiten</th>
              </tr>
            </thead>
            <tbody>
              {archiveRows.map((row) => (
                <tr key={row.id}>
                  <th scope="row"><Link href={`/jelajah/${row.id}/`}>{row.label}</Link></th>
                  <td>{row.stories}</td>
                  <td>{row.reviewable}</td>
                  <td>{row.claims}</td>
                  <td className="small">{row.symbols.slice(0, 6).join(', ')}{row.symbols.length > 6 ? '…' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {coverage && (
          <p className="small muted">
            Jendela arsip sejak {coverage.since ?? 'tidak dicatat'} · {coverage.articles} artikel ·{' '}
            {coverage.candidates} cerita · {coverage.reviewable} siap ditinjau.
          </p>
        )}
      </section>

      {fixtureRows.length > 0 && (
        <section aria-labelledby="topik-fixture">
          <h2 id="topik-fixture">Topik pada fixture sintetis</h2>
          <p className="small muted">
            Fixture uji dengan relasi dan dua revisi; bukan berita pasar nyata.
          </p>
          <ul className="plain">
            {fixtureRows.map((row) => (
              <li key={row.id}>
                <Link href={`/jelajah/${row.id}/`}>{row.label}</Link>{' '}
                <span className="chip">FIXTURE SINTETIS</span>
                <span className="small muted"> · {row.stories} cerita · {row.claims} klaim</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="small">
        Butuh daftar cerita? Mulai dari <Link href="/warta/">Warta</Link>, atau periksa{' '}
        <Link href="/ronce/">Ronce Thread</Link> untuk bukti per klaim.
      </p>
    </>
  );
}
