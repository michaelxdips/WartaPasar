import { Suspense } from 'react';
import Link from 'next/link';
import { CalendarList } from '@/components/CalendarList';
import { companion, companionCalendar, companionStatuses, displayTimestamp, manifest, stories } from '@/lib/data';

export default function KalenderPage() {
  const events = companionCalendar();
  const status = companionStatuses().find((row) => row.family === 'corporate_actions');
  const dateKinds = companion?.date_kinds ?? ['announcement', 'cum', 'ex', 'record', 'payment', 'meeting'];
  const timeline = stories
    .map((story) => ({ id: story.id, symbol: story.symbol, topic: story.topic, date: story.date }))
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, 8);

  return (
    <>
      <h1>Kalender</h1>
      <p className="lede">
        Aksi korporasi dengan jenis tanggal yang terpisah — pengumuman, cum, ex, pencatatan, pembayaran
        dan rapat — plus garis waktu edisi/berita. Tanggal peristiwa bukan tanggal terbit berita, dan
        tanggal yang tidak ada tetap kosong.
      </p>

      <section aria-labelledby="aksi-korporasi">
        <h2 id="aksi-korporasi">
          Aksi korporasi {events.length > 0 ? <span className="chip">FIXTURE SINTETIS</span> : null}
        </h2>
        {events.length === 0 ? (
          <p className="muted">
            Belum ada aksi korporasi pada data yang tersedia.
            {status
              ? ` Status keluarga ini: ${status.status}.`
              : ' Keluarga ini belum dikonfigurasi pada run arsip ini.'}
            {' '}Kontraknya terdokumentasi dan dapat diisi saat lingkup/anggaran akses disetujui;
            tidak ada peristiwa yang dikarang untuk mengisi halaman ini.
          </p>
        ) : (
          <Suspense fallback={<p className="muted">Memuat kalender…</p>}>
            <CalendarList
              events={events}
              dateKinds={dateKinds}
              statusNote={status ? `status ${status.status} · kontrak dicek ${status.contract_checked}` : ''}
            />
          </Suspense>
        )}
      </section>

      <section aria-labelledby="garis-waktu">
        <h2 id="garis-waktu">Garis waktu edisi dan berita</h2>
        <p className="small muted">
          Tanggal terbit berita dari jendela arsip (ekspor {displayTimestamp(manifest.generated_at)});
          ini bukan kalender peristiwa dan tidak menandakan rapat atau dividen yang akan datang.
        </p>
        <ul className="plain">
          {timeline.map((row) => (
            <li key={row.id} className="small">
              {row.date} · <Link href={`/warta/${row.id}/`}>{row.symbol} — {row.topic}</Link>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
