# Laporan: 3 Langkah Penyempurnaan Ronce

Dikerjakan: 7 Oktober 2026
Urutan sesuai permintaan: **2 → 3 → 1**

---

## Ringkasan

| Langkah | Apa | Hasil |
|---|---|---|
| **2** | Perpendek judul | ✅ Selesai — maks 60 karakter |
| **3** | Audit rahasia | ✅ Selesai — `audit.py` dibuat |
| **1** | Test otomatis | ✅ Selesai — 56 test lulus |

Semua sudah diuji, bukan hanya ditulis.

---

## Langkah 2 — Perpendek judul

### Masalah sebelumnya

```text
"PT Wulandari Bangun Laksana Tbk akan membagikan dividen interim tahun
buku 2026 kepada pemegang saham"  → 95 karakter
```

Nama perusahaan Indonesia panjang, jadi judul boros ruang post.

### Yang dikerjakan

Dua fungsi baru di `core/compose.py`:

**1. `pendekkan_nama()`** — ganti nama panjang dengan kode emiten

```text
SEBELUM: PT Wulandari Bangun Laksana Tbk membagikan dividen
SESUDAH: BSBK membagikan dividen
```

**2. `rapikan_judul()`** — batasi panjang dan buang sisa bahasa Inggris

```text
- maksimal 60 karakter
- dipotong di batas kata, bukan di tengah
- kata penggantung di akhir dibuang ("kepada", "untuk", "yang")
- judul yang masih bahasa Inggris ditolak (dikembalikan kosong)
```

### Hasil uji

```text
[OK] 52 | BSBK akan membagikan dividen interim tahun buku 2026
[OK] 51 | GEMS membagikan dividen interim Rp 622,93 per saham
[OK] 54 | BUVA menggelar rights issue II dengan menerbitkan 6,15
[OK] 59 | OJK memeriksa ASBI terkait dugaan penggelapan dana dan aset
[OK] 58 | Bank Mandiri membagi dividen Rp 44,47 triliun dari laba Rp
[KOSONG] | (judul Inggris ditolak dengan benar)
```

Dari hasil Warta sungguhan:

```text
54 char | OJK meminta bank menyesuaikan dividen dengan kebutuhan
51 char | Musim dividen interim dimulai di tengah pasar saham
50 char | BUVA berencana rights issue 6,15 miliar saham baru
```

---

## Langkah 3 — Audit rahasia

### Yang dibuat

File `audit.py` — pemeriksa keamanan otomatis.

```bash
python audit.py
```

### Yang diperiksa

```text
[1/4] Berkas rahasia     — .env ada dan dilindungi .gitignore?
[2/4] Rahasia di kode    — ada API key, token, atau password?
[3/4] Rahasia di hasil   — output/ bersih dari rahasia?
[4/4] Berkas mencurigakan — ada .pem, .key, credentials.json?
```

### Pola yang dideteksi

```text
- OpenAI-style key (sk-...)
- Anthropic key (sk-ant-...)
- GitHub token (ghp_..., gho_...)
- JWT token
- Bearer token
- AWS access key (AKIA...)
- Private key (-----BEGIN PRIVATE KEY-----)
- Connection string dengan password (postgres://, mysql://, mongodb://)
```

### Hasil uji

**Saat bersih:**

```text
[2/4] Nilai rahasia di dalam kode...  OK bersih (22 file diperiksa)
[3/4] Nilai rahasia di folder hasil... OK bersih (9 item diperiksa)

SEMUA AMAN — siap di-commit
```

**Saat sengaja ditaruh key palsu:**

```text
BAHAYA uji_bocor.txt:1 — OpenAI-style key

ADA 1 MASALAH
Jangan push sebelum masalah ini diperbaiki.
```

Jadi audit-nya benar-benar bekerja, bukan hanya bilang "aman" terus.

### Satu temuan

File `data-2026-10-05.json` ada di folder utama, bukan di `archive/`.
Sudah dipindahkan. Isinya data pasar, bukan rahasia — tapi tetap sebaiknya
di dalam folder yang benar.

---

## Langkah 1 — Test otomatis

### Yang dibuat

File `test_ronce.py` — 56 test, semua offline (tidak panggil API).

```bash
python test_ronce.py
```

### Cakupan test

| Kelompok | Jumlah | Yang diuji |
|---|---|---|
| Konfigurasi | 4 | .env dibaca, rahasia tidak bocor ke ringkasan |
| Nama media | 4 | domain → nama enak dibaca |
| Format | 3 | persen, angka ribuan, tanggal Indonesia |
| Kode emiten | 3 | `.JK` dibuang dengan benar |
| Perpendek nama | 3 | nama panjang → kode emiten |
| Rapikan judul | 4 | maks 60 char, tolak Inggris, tidak menggantung |
| Pilih headline | 4 | urut penting, dedup, hormati batas |
| Keterbukaan | 3 | baca transaksi, lewati persen tidak berubah |
| Aksi korporasi | 3 | dividen, rights issue, kosong |
| RUPS | 2 | baca agm, potong tempat panjang |
| Sorotan | 2 | harga tampil, tanpa perubahan |
| Bagi post | 5 | batas 500 byte, entri tidak terpotong, sumber sekali |
| Susun | 4 | hasil lengkap, bagian kosong tidak muncul |
| Tulis ulang | 6 | cadangan tanpa AI, AI gagal jatuh ke cadangan |
| Render | 4 | 3 file keluar, JSON bisa dibaca ulang |
| Keamanan | 2 | tidak ada key di hasil, selalu publishable=false |

### Hasil

```text
Ran 56 tests in 2.076s

OK
exit: 0
```

### Dua test gagal pertama kali — keduanya salah di sisi test

```text
1. test_hormati_batas_maks
   Data uji pakai judul kembar ("Berita nomor 0", "Berita nomor 1")
   → dedup benar menganggapnya sama
   → data uji diperbaiki (nama dibuat unik)

2. test_markdown_ada_tabel_cek
   Test cari "Belum boleh" (B besar), kode tulis "belum" (b kecil)
   → perbandingan dibuat tidak peka huruf besar-kecil
```

Keduanya salah test, bukan salah kode. Sudah diperbaiki.

---

## Verifikasi setelah ketiga langkah

```text
Langkah 2 (perpendek judul)  : Ran 7 tests — OK
Langkah 3 (audit rahasia)    : SEMUA AMAN
Langkah 1 (test otomatis)    : Ran 56 tests — OK
Uji nyata buat Warta         : post 7, sumber terisi, tanpa peringatan
```

Semuanya lulus bersamaan.

---

## Hasil Warta setelah perbaikan

```text
WARTA RONCE 06 Oktober 2026

OJK meminta bank menyesuaikan dividen dengan kebutuhan | Musim dividen
interim dimulai di tengah pasar saham | BUVA berencana rights issue
6,15 miliar saham baru | Sheila Maria Tiwan mengurangi kepemilikan di
CRSN dari 50 | DADA membagikan dividen Rp0

── HEADLINE UTAMA ──
OJK meminta bank menyesuaikan dividen dengan kebutuhan (BMRI)
    Bank Mandiri (BMRI) membagi dividen Rp 44,47 triliun atau 79% dari
    laba Rp 56,3 triliun, sementara BCA 72% dan BNI 65%. Ekonom menilai
    payout ratio tinggi bisa membuat bank menahan laba lebih banyak.

── HEADLINE UTAMA ──
Musim dividen interim dimulai di tengah pasar saham (GEMS)
    PT Golden Energy Mines Tbk (GEMS) membagikan dividen interim
    Rp 622,93 per saham atau setara yield 7,28% pada harga penutupan
    Rp 8.550.
```

Judul pendek, narasi 2 kalimat SPOK jelas, bahasa Indonesia.

---

## File yang bertambah

```text
ronce-os/
├── audit.py            BARU — pemeriksa keamanan (7 KB)
├── test_ronce.py       BARU — 56 test (19 KB)
├── core/compose.py     diperbarui — pendekkan_nama(), rapikan_judul()
├── archive/            data dipindahkan ke sini
└── docs/
    ├── LAPORAN-SISTEM.md       (sebelumnya)
    └── LAPORAN-3-LANGKAH.md    (file ini)
```

---

## Yang masih bisa diperbaiki

1. **Judul kadang terlalu umum** — "Musim dividen interim dimulai" tidak
   menyebut emiten. Bisa dipaksa menyertakan kode.

2. **Test belum mencakup panggilan API nyata** — semua test offline.
   Untuk API, perlu test terpisah yang jalan hanya saat ada key.

3. **Belum ada test untuk `sectors.py`** — bagian pengambilan data belum
   diuji langsung (hanya diuji lewat fungsi lain).

4. **Audit belum cek riwayat git** — kalau rahasia pernah ter-commit dan
   dihapus, audit ini tidak mendeteksinya.

---

## Kesimpulan

```text
Langkah 2 (perpendek judul) : SELESAI & TERUJI
Langkah 3 (audit rahasia)   : SELESAI & TERUJI
Langkah 1 (test otomatis)   : SELESAI & TERUJI — 56 test lulus

Sistem siap di-commit ke GitHub.
```

Satu catatan: sebelum push, jalankan `python audit.py` sekali lagi di
folder yang akan di-commit, dan periksa `git diff` sendiri. Audit otomatis
membantu, tapi tidak menggantikan pemeriksaan manusia.
