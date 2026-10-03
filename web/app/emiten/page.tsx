import Link from 'next/link';
import { symbols } from '@/lib/data';

export default function EmitenIndexPage() {
  const rows = symbols();
  return (
    <>
      <h1>Emiten</h1>
      <p className="lede">
        Daftar emiten yang muncul pada jendela editorial ini beserta jumlah cerita dan klaim yang
        sudah ditinjau. Halaman emiten menggabungkan apa yang mesin temukan, bukan profil perusahaan.
      </p>
      <table>
        <caption className="sr-only">Jumlah cerita dan klaim per emiten</caption>
        <thead>
          <tr>
            <th scope="col">Emiten</th>
            <th scope="col">Cerita</th>
            <th scope="col">Siap ditinjau</th>
            <th scope="col">Klaim disetujui</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <th scope="row"><Link href={`/emiten/${row.symbol}/`}>{row.symbol}</Link></th>
              <td>{row.stories}</td>
              <td>{row.reviewable}</td>
              <td>{row.claims}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
