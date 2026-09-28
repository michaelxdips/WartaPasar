# Ronce — MVP replay editorial

Pengambilan `/v2/news/` Sectors v2 tersedia lewat `fetch`, dan `replay` memutar arsip berzona waktu yang valid, mencatat keputusan di SQLite, dan membuat draf pemeriksaan editor. **Replay berita nyata yang layak publikasi tetap tertahan**: timestamp pada arsip IDX setempat tidak berzona waktu dan semantik waktu Sectors belum dikonfirmasi tertulis. Mode asumsi `+07:00` hanya untuk demo internal, diberi watermark, dan ditolak oleh jalur approval. Belum ada publikasi Threads/X, belum ada API write, dan belum ada klaim hot topic terverifikasi. Seluruh pengujian memakai artikel sintetis, bukan fakta pasar.

## Format arsip

Satu berkas JSON berisi daftar halaman **lengkap, berurutan**. `fetch` mengarsipkan `request`, `response`, dan `fetched_at` UTC; arsip mentah **tidak boleh** memuat `source_timezone` (replay menolaknya). Tanggal/URL di bawah hanya contoh skema. Arsip nyata lokal disimpan di `data/`, diabaikan Git; jangan commit atau sebar isi berita mentah. Tiap halaman:

```json
{
  "fetched_at": "2026-09-25T03:00:00+00:00",
  "request": {"extension": "idx", "start": "2026-09-24", "end": "2026-09-25", "limit": 30, "offset": 0},
  "response": {
    "results": [
      {
        "title": "<judul persis dari Sectors>",
        "body": "<isi persis dari Sectors>",
        "source": "https://<URL-asli>",
        "timestamp": "<timestamp publikasi asli>",
        "symbols": ["<ticker>"]
      }
    ],
    "pagination": {
      "offset": 0,
      "showing": 1,
      "has_next": false,
      "next_offset": null,
      "total_count": 1
    }
  }
}
```

Contoh di atas **hanya skema**, bukan data hasil API. Simpan seluruh `response` asli, jangan kurangi field. `fetch` menolak arsip parsial, tidak menimpa arsip yang sudah ada, dan menuntut `total_count` konsisten antarhalaman. `has_next=true` mensyaratkan halaman berikut dengan `offset=next_offset`; halaman terakhir wajib `has_next=false` dan `next_offset=null`. `replay` memeriksa ulang rantai pagination (offset, `showing`, `total_count`, urutan halaman terakhir) dan menolak arsip yang tidak lengkap.

## Interpretasi waktu (sidecar terpisah)

Hanya setelah konfirmasi tertulis Sectors, simpan `source_timezone`, `timestamp_meaning`, `filter_timezone`, `start_inclusive`, `end_inclusive`, dan `evidence` (URL/bukti tertulis) pada berkas sidecar terpisah, lalu berikan `--interpretation`. Tanpa sidecar, timestamp tanpa offset ditolak; sidecar tidak pernah mengubah payload arsip. Sidecar konsisten menambah aturan replay; aplikasi tidak dapat memverifikasi sendiri keaslian buktinya. Field `timestamp_meaning`, `filter_timezone`, `start_inclusive`, dan `end_inclusive` terekam pada identitas run, tetapi belum mengubah perilaku replay karena aturan batas provider belum terkonfirmasi.

## Jalankan

```bash
# Set SECTORS_API_KEY dalam lingkungan proses secara aman; jangan taruh key pada argumen CLI.
python ronce.py fetch --start 2026-09-24 --end 2026-09-25 --out path/to/pages.json
# Jangan replay berita live sampai interpretasi waktu dikonfirmasi tertulis Sectors.
python ronce.py replay path/to/pages.json --since 2026-09-24T06:00:00+07:00 --cutoff 2026-09-25T06:00:00+07:00 --db path/to/ronce.sqlite --interpretation path/to/provider-time-rules.json
# Sidecar `provider-time-rules.json`: source_timezone, timestamp_meaning, filter_timezone,
# start_inclusive, end_inclusive, evidence. Jangan buat tanpa konfirmasi Sectors.
python -m unittest discover -v
```

Validasi panjang X memerlukan Node.js dan pustaka resmi `twitter-text`: jalankan `npm ci --ignore-scripts` sebelum persetujuan edisi X. Jika pustaka gagal dijalankan, approval/preview X menolak, bukan menghitung secara kira-kira. Berkas `package.json`, `package-lock.json`, dan `x_length.mjs` termasuk allowlist Git; `node_modules/` tetap diabaikan.

Perintah tambahan offline: `python ronce.py fetch-companion --symbol BBCA --start 2026-09-24 --end 2026-09-25 --out path/to/companion.json` memerlukan `SECTORS_API_KEY` dan mengarsipkan tiga respons secara atomik, tanpa publikasi. `python ronce.py replay path/to/pages.json --since 2026-09-24T06:00:00+07:00 --cutoff 2026-09-25T06:00:00+07:00 --db path/to/ronce.sqlite --assume-timezone +07:00` menghasilkan demo internal yang tak bisa disetujui; jangan pakai outputnya untuk publikasi. `schedule-once` hanya mengeksekusi draf dari arsip lokal dengan `--at` tepat 06:00 WIB hari kerja, `--since`, `--db`, dan `--interpretation` berisi bukti penyedia; belum ada daemon, cron, ataupun dua eksekusi unattended nyata.

`SECTORS_API_KEY` harus tersedia pada lingkungan proses yang menjalankan `ronce.py`. Jangan simpan key dalam kode, argumen CLI, atau repo. Suite pengujian tidak menyentuh jaringan atau API write.

## Status implementasi lokal

- **fetch**: arsip atomik, tolak overwrite, tolak pagination tidak lengkap/konsisten, `fetched_at` UTC, tidak pernah menambah `source_timezone`.
- **replay**: cutoff/since wajib berzona; menolak `source_timezone` di dalam arsip; validasi pagination; dedup URL; jendela editorial (`since`/`cutoff`/`fetched_at`); grup kandidat per tema+aksi+ticker+tanggal; keputusan `review`/`abstain`; run id = SHA-256 arsip+cutoff+since+interpretasi+versi kebijakan pembanding; penulisan SQLite idempoten.
- **approval** (`approve_packet`): teks pertama tersimpan dengan hash teks, kutipan verbatim pada artikel run, dua asal laporan berbeda, sumber bukti ⊂ satu kandidat `review`, entity klaim ⊂ symbol kandidat (`PASAR` bebas) dan `event_time` cocok tanggal kandidat, editor/waktu; `reviewed=True` hanyalah pernyataan eksplisit editor, bukan autentikasi. Revisi non-identik belum didukung (ditolak).
- **preview** (`preview_packet`): memeriksa hash teks, klaim, atribusi, **kutipan, dan asal bukti terhadap arsip tersimpan**; mengukur byte/karakter; `limit_check=not_performed` berarti batas platform belum dihitung. Tidak ada API write.
- **edisi baru** (`review_claims` → `render_draft` → `approve_edition` → `preview_edition`): satu sampai enam post per platform berisi teks klaim yang ditinjau persis beserta URL sumber; approval X dan Threads terpisah, teks/urutan/sumber/metadata approval diikat hash. Perubahan fakta memerlukan run/review dan edisi baru. Pemeriksaan angka hanya mencocokkan token angka pada teks terhadap nilai dan kutipan kedua bukti; tidak membuktikan unit, periode, makna ekonomi, atau kebenaran klaim. `reviewed=True` dan hash lokal bukan autentikasi editor atau tanda tangan anti-penyusup. Preview tetap offline; beberapa post Threads adalah draf terpisah, bukan bukti thread terbit.
- **batas platform edisi baru**: X memakai `twitter-text` 3.1.0 untuk batas biasa 280 berbobot; Threads memakai plafon konservatif 500 byte UTF-8 per post. Label `documented_rules_applied`, bukan `platform_verified`. API legacy `preview_packet` tetap `not_performed`.
- **skoring** (`score_candidate`): fungsi murni skor per aturan Bab 8.2 dengan input yang dinyatakan telah ditinjau; belum ada ranking lintas kategori, perhitungan metrik dari endpoint, atau promosi kandidat `abstain`.
- **fetch pendamping** (`fetch_companion`): mengarsipkan respons mentah top-changes, foreign-flow satu ticker, dan quarterly satu ticker; kontrak respons diuji sintetis, belum diuji dengan API penyedia saat ini. Tidak menyimpulkan klaim pasar.
- **slot draf** (`draft_schedule`/`schedule-once`): hanya satu invokasi eksplisit per slot 06:00 WIB hari kerja, idempoten terhadap run yang sama, tanpa post. Ini bukan penjadwalan unattended.
- **mock** (`record_mock_attempt`): simulator lokal status ambigu/timeout; menuntut readback akun/ID/teks sebelum retry; bukan bukti post live.
- **adapter** (`adapters.py`): kontrak offline X/Threads — builder request, klasifikasi respons (`created`/`failed`/`ambiguous`/`rate_limited`/`auth_expired`), rencana aksi anti-duplikasi, verifikasi readback akun/teks/tautan; **tanpa kode jaringan**, tanpa transport, `LIVE_PUBLISHING=False`; diuji dengan 42 tes mock.
- **kosakata tema**: dwibahasa ID/EN, 12 keluarga; judul digest `roundup` abstain; hyphen U+2010/U+2011 dinormalkan; kelas aksi dividen dibedakan antara pengumuman dan pembayaran. Pembanding angka judul menormalkan IDR/Rp, angka desimal, persen, dan satuan ID/EN sebelum membandingkan nilai dengan satuan yang sepadan. Pengukuran arsip lokal: 178 kandidat, 9 `review`, 169 `abstain`; ini **bukan** persetujuan untuk menerbitkan klaim.

## Batas yang diketahui

- Replay berita nyata diblokir sampai Sectors mengonfirmasi tertulis zona waktu, makna timestamp, zona filter tanggal, dan inklusivitas `start`/`end`.
- Demo arsip nyata dengan offset asumsi dapat menghasilkan kandidat `review` untuk pemeriksaan internal saja; keputusan itu bukan replay temporal terkonfirmasi atau izin publikasi.
- Domain berbeda **bukan** bukti sumber independen; sindikasi yang disunting tidak terdeteksi otomatis. Label asal laporan tetap pernyataan editor.
- Klaim approval dicek terhadap symbol kandidat (`PASAR` bebas) dan tanggal `event_time`.
- Preview edisi baru memeriksa panjang menurut dokumentasi; preview legacy belum. Adapter hanya kontrak offline: belum ada transport/kredensial. Dokumentasi Threads untuk `reply_to_id` terverifikasi; builder offline `build_threads_reply` tersedia, tetapi alur balasan berantai belum diimplementasikan sebagai orkestrasi atau diuji pada akun nyata.
- SQLite mengaktifkan foreign key per koneksi aplikasi; koneksi eksternal wajib mengaktifkannya sendiri. Tidak ada WAL/schema versioning.
- Pencocokan angka hanya membandingkan judul, bukan isi artikel atau periode/cakupan angka. Angka ambigu seperti `1.000` ditahan untuk pemeriksaan manual. Jumlah uang yang muncul hanya di satu laporan juga ditahan; tambahan angka saham yang tidak memiliki pembanding tidak otomatis konflik. Aturan ini tidak membuktikan dua berita menggambarkan peristiwa yang sama.
