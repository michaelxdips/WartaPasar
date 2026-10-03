import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
import { edition, manifest } from '@/lib/data';

export const metadata: Metadata = {
  title: 'Ronce — Warta Pasar',
  description: 'Edisi pasar yang ditinjau editor: klaim, bukti, dan jejak keputusan. Bukan nasihat investasi.',
};

const NAV = [
  { href: '/', label: 'Orbit' },
  { href: '/jelajah/', label: 'Jelajah' },
  { href: '/warta/', label: 'Warta' },
  { href: '/ronce/', label: 'Ronce' },
  { href: '/emiten/', label: 'Emiten' },
  { href: '/kalender/', label: 'Kalender' },
  { href: '/cari/', label: 'Cari' },
  { href: '/arsip/', label: 'Arsip' },
  { href: '/disimpan/', label: 'Disimpan' },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>
        <a className="skip" href="#konten">Lewati ke konten</a>
        <header className="shell">
          <div className="shell-inner">
            <Link className="brand" href="/">
              Ronce
              <small>Warta Pasar · edisi {edition.edition_id}</small>
            </Link>
            <nav aria-label="Navigasi utama">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href}>{item.label}</Link>
              ))}
            </nav>
          </div>
        </header>
        <main id="konten" className="page">{children}</main>
        <footer className="foot">
          <div className="foot-inner">
            <p>
              Permukaan baca hanya memuat edisi yang disetujui editor. Isi artikel penuh tidak pernah
              diekspor; angka dirender dari catatan klaim, bukan dari prosa.
            </p>
            <p>
              Kontrak skema v{manifest.schema_version} · edisi {edition.edition_id} ({edition.platform}) ·
              disetujui {edition.approval.editor} · publikasi live: {String(manifest.policy.live_publishing)}.
              Bukan nasihat investasi.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
