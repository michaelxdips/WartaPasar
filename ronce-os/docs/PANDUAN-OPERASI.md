# Panduan Operasi Ronce

Cara menjalankan dan merawat Ronce. Semua perintah bisa disalin-tempel
ke Git Bash.

---

## 1. Menyalakan website

```bash
cd ronce-os
python start.py
```

Browser terbuka otomatis ke `http://127.0.0.1:4173`.

Kalau tidak terbuka sendiri, buka manual alamat tersebut.
**Mematikan:** tekan `Ctrl + C`.

### Halaman yang tersedia

| Navigasi | Isi |
|---|---|
| Orbit | Beranda: satu textbox pencarian, pintu masuk ke semua |
| Warta | Cerita edisi terbaru, tab per bagian, pemilih edisi |
| Jelajah | Tema, nama yang tercatat, bagian edisi |
| Kalender | Agenda ke depan dari Sectors (aksi korporasi, RUPS) |
| Emiten | Tabel emiten + grafik harga |
| Disimpan | Cerita yang ditandai |
| Profil proyek | Tentang Ronce, status edisi, cara menjalankan |

---

## 2. Membuat Warta baru

```bash
cd ronce-os
python ronce.py make
```

Hasilnya di `output/`:

```text
output/warta-<tanggal>.json   untuk program lain
output/warta-<tanggal>.txt    siap salin ke X atau Threads
output/warta-<tanggal>.md     untuk ditinjau editor
```

Perintah ini sekaligus menarik agenda ke depan dan menyimpan arsip edisi
ke `web/`, sehingga website ikut diperbarui.

### Pilihan tambahan

```bash
python ronce.py make --tanggal 2026-10-07   # tanggal tertentu
python ronce.py make --offline              # tanpa internet, pakai arsip
python ronce.py make --tanpa-ai             # tanpa AI, tulis sederhana
python ronce.py make --headline 5           # 5 berita utama (bawaan 3)
```

### Perintah lain

```bash
python ronce.py cek      # cek konfigurasi dan koneksi
python ronce.py contoh   # tampilkan hasil terakhir di layar
python ronce.py web      # salin edisi terbaru ke web/ saja
```

---

## 3. Cek sistem

```bash
python ronce.py cek       # Sectors OK, AI OK, jumlah arsip
python test_ronce.py      # 58 test, semua offline
python audit.py           # pemeriksa rahasia
```

Yang diharapkan muncul:

```text
Ran 58 tests in ...s
OK

SEMUA AMAN — siap di-commit
```

---

## 4. Kalau ada masalah

**Port 4173 sudah dipakai**

```bash
netstat -ano | grep 4173
taskkill //F //PID <nomor-pid>
```

**Sectors balas HTTP 403**

API Sectors menolak permintaan tanpa User-Agent browser. Ronce sudah
mengirimnya otomatis. Kalau masih gagal, periksa apakah API key masih aktif.

**AI balas HTTP 503 atau model_not_found**

Nama model salah. Cek daftar model yang tersedia di provider:

```bash
curl -H "Authorization: Bearer <key>" <base-url>/models
```

**Website menampilkan edisi lama**

Jalankan `python ronce.py web` untuk menyegarkan `web/warta.json`.

**Kalender kosong**

Sectors tidak mengembalikan agenda pada rentang itu. Sistem tidak mengisi
kekosongan dengan jadwal karangan.

---

## 5. Perintah ringkas

```bash
cd ronce-os && python start.py          # nyalakan website
cd ronce-os && python ronce.py make      # buat Warta
cd ronce-os && python ronce.py cek       # cek sistem
cd ronce-os && python test_ronce.py      # test
cd ronce-os && python audit.py           # audit rahasia
```

---

## 6. Sebelum push ke GitHub

```bash
python test_ronce.py    # harus lulus semua
python audit.py         # harus "SEMUA AMAN"
git status              # pastikan .env tidak ikut
git diff --cached       # baca sendiri perubahannya
```

Audit otomatis membantu, tapi tidak menggantikan pemeriksaan manual.
