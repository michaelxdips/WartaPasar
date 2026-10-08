# Ronce

Warta pasar harian dari data Sectors, ditulis ulang jadi bahasa Indonesia
yang mudah dipahami, lalu siap diposting ke X atau Threads.

Dibuat untuk dijalankan sendiri oleh siapa saja. Tidak butuh server.

---

## Apa yang dilakukan Ronce

```text
1. Ambil data dari API Sectors
      berita, keterbukaan informasi, aksi korporasi, harga harian,
      agenda ke depan (RUPS, dividen, rights issue)

2. Tulis ulang bahasa Inggris jadi bahasa Indonesia
      memakai AI apa pun yang kamu punya (opsional)

3. Susun jadi Warta dengan struktur tetap
      Judul → Ringkasan → 6 bagian → Sumber

4. Keluarkan hasil dalam 4 format
      JSON, TXT (siap posting), Markdown (review), dan website
```

Sekaligus membuat **website Ronce** — beranda Orbit, Warta, Jelajah,
Kalender (agenda ke depan), dan Emiten. Jalankan `python start.py`.

Hasilnya seperti ini:

```text
WARTA RONCE 05 Oktober 2026

Grup Astra mengumumkan dividen interim 2026: ASII membagi... | OJK
menggelar pemeriksaan terhadap PT Asuransi Bintang Tbk... | OJK
menyebut penurunan harga saham minimum dari Rp 50 jadi...

── HEADLINE UTAMA ──
Grup Astra mengumumkan dividen interim 2026: ASII membagi Rp 3,89 triliun... (ASII)
    AUTO dan AALI menyusul masing-masing Rp 349,52 miliar dan Rp 449,02 miliar...

── KETERBUKAAN INFORMASI ──
CRSN — Sheila Maria Tiwan mengurangi kepemilikan di CRSN dari 50.04% menjadi 50.03%...

Sumber: Kontan, Jakarta Globe, Sectors
```

---

## Pemasangan

### Yang dibutuhkan

- **Python 3.10 atau lebih baru** — [python.org](https://python.org)
- **API key Sectors** — [sectors.app](https://sectors.app)
- (Opsional) **API key model AI** — untuk menulis ulang bahasa

Tidak perlu install paket apa pun. Ronce hanya pakai pustaka bawaan Python.

### Langkah

```bash
# 1. Masuk ke folder
cd ronce-os

# 2. Jalankan pemasang
bash setup.sh

# 3. Buka file .env, isi minimal ini:
SECTORS_API_KEY=key-kamu-dari-sectors

# 4. Cek sudah benar
python ronce.py cek
```

---

## Cara pakai

### Buat Warta

```bash
python ronce.py make
```

Membuat Warta untuk hari ini.

```bash
python ronce.py make --tanggal 2026-10-05
```

Membuat Warta untuk tanggal tertentu.

### Menyalakan website

```bash
python start.py
```

Browser terbuka di `http://127.0.0.1:4173`.

### Perintah lain

```bash
python ronce.py cek       # cek konfigurasi dan koneksi
python ronce.py contoh    # tampilkan hasil terakhir di layar
python ronce.py web       # salin edisi terbaru ke web/ saja
python audit.py           # periksa rahasia sebelum commit
```

### Pilihan tambahan

```bash
python ronce.py make --offline     # pakai data arsip, tanpa internet
python ronce.py make --tanpa-ai    # jangan pakai AI, tulis sederhana
python ronce.py make --headline 5  # ambil 5 berita utama (bawaan 3)
```

---

## Pengaturan AI

Ronce bisa memakai model AI apa pun yang formatnya **OpenAI-compatible**.
Artinya hampir semua provider bisa dipakai.

Isi tiga baris ini di `.env`:

```bash
RONCE_AI_BASE_URL=https://api.provider.com/v1
RONCE_AI_API_KEY=key-kamu
RONCE_AI_MODEL=nama-model
```

Contoh untuk beberapa provider:

| Provider | Base URL | Contoh model |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenRouter | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.1-70b-instruct` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Ollama (lokal) | `http://localhost:11434/v1` | `llama3.1` |
| LM Studio (lokal) | `http://localhost:1234/v1` | `local-model` |

**AI tidak wajib.** Tanpa AI, Warta tetap dibuat, tapi bahasanya belum
ditulis ulang — hanya dipangkas jadi 3 kalimat.

### Pakai model lokal (gratis, tanpa internet)

Kalau kamu punya [Ollama](https://ollama.com):

```bash
ollama pull llama3.1
ollama serve
```

Lalu di `.env`:

```bash
RONCE_AI_BASE_URL=http://localhost:11434/v1
RONCE_AI_API_KEY=ollama
RONCE_AI_MODEL=llama3.1
```

---

## Mode offline

Ronce otomatis menyimpan data yang diambil ke folder `archive/`.
Kalau nanti internet mati, kamu bisa tetap membuat Warta:

```bash
python ronce.py make --offline
```

Atau paksa selalu offline lewat `.env`:

```bash
RONCE_OFFLINE=1
```

---

## Struktur Warta

```text
Title     : WARTA RONCE <DD Bulan YYYY>
Ringkasan : potongan pendek dipisah | , langsung ke inti
Konten    : 1. HEADLINE UTAMA
            2. KETERBUKAAN INFORMASI
            3. AKSI KORPORASI
            4. RUPS
            5. SOROTAN EMITEN
Sumber    : dikumpulkan di akhir, tanpa duplikat
```

Aturan:

- Bagian tanpa data tidak dimunculkan.
- Sumber tidak ditulis berulang di tiap entri.
- Narasi maksimal 3 kalimat, struktur SPOK jelas.
- Satu post tidak lebih dari 500 byte (batas Threads).
- Tidak ada tautan panjang di dalam post — cukup nama media.

---

## Agenda ke depan

Selain berita, Ronce menarik **agenda aksi korporasi dan RUPS** yang belum
terjadi, lalu menampilkannya di halaman Kalender:

```text
Sumber    : /v2/corporate-actions/ dengan rentang tanggal
Jenis     : dividend, stock_split, bonus, right_issue, warrant, agm (RUPS)
Tahap     : announcement, cum, ex, record, payment, meeting
Rentang   : 120 hari ke depan
```

Satu agenda bisa punya beberapa tanggal (mis. RUPS punya tanggal pencatatan
dan tanggal rapat). Tiap tanggal ditampilkan sebagai baris terpisah supaya
tidak ada informasi yang hilang.

Kalau tidak ada agenda pada rentang itu, halaman Kalender mengatakannya
kosong — bukan diisi jadwal karangan.

---

## Hasil

Setiap kali dijalankan, Ronce membuat tiga file di `output/`:

| File | Untuk apa |
|---|---|
| `warta-<tanggal>.json` | Dipakai program lain (web, bot) |
| `warta-<tanggal>.txt` | Siap salin-tempel ke X atau Threads |
| `warta-<tanggal>.md` | Untuk ditinjau editor |

Website Ronce juga ikut diperbarui: `python ronce.py web` menyalin edisi
terbaru ke `web/warta.json`. Perintah lain tidak menyentuh folder `web/`,
jadi menjalankan test atau membuat Warta baru tidak akan mengubah isi
website secara tidak sengaja.

Semua hasil selalu berstatus:

```text
publishable       : false
editor_approval   : required
api_write         : false
```

**Ronce tidak pernah memposting sendiri.** Kamu yang memutuskan.

---

## Struktur folder

```text
ronce-os/
├── ronce.py            satu perintah untuk semua
├── config.py           baca pengaturan dari .env
├── setup.sh            pemasang otomatis
├── env.contoh          contoh konfigurasi
├── audit.py            pemeriksa rahasia sebelum commit
├── test_ronce.py       58 test, semua offline
├── start.py            nyalakan website
├── app.py              pratinjau ringkas di terminal
├── core/
│   ├── sectors.py      ambil data dari Sectors
│   ├── rewrite.py      tulis ulang bahasa pakai AI
│   ├── compose.py      susun jadi Warta
│   └── render.py       keluarkan hasil
├── web/                website Ronce (HTML/CSS/JS, tanpa build)
├── output/             hasil Warta
├── archive/            data untuk mode offline
└── docs/               laporan dan panduan
```

---

## Kalau ada masalah

**Sectors balas HTTP 403**

API Sectors menolak request tanpa User-Agent browser. Ronce sudah
mengirimnya otomatis. Kalau masih gagal, periksa apakah API key kamu
masih aktif.

**AI balas HTTP 503 atau model_not_found**

Nama model salah. Cek daftar model yang tersedia:

```bash
curl -H "Authorization: Bearer KEY-KAMU" https://api.provider.com/v1/models
```

**Post melewati batas 500 byte**

Kurangi jumlah berita: `python ronce.py make --headline 2`

**Tidak ada data di bagian tertentu**

Itu normal. Bagian tanpa data memang tidak dimunculkan, bukan diisi
data palsu.

---

## Catatan penting

- Ronce **tidak memberi nasihat investasi**.
- Semua angka berasal dari API Sectors, bukan karangan.
- Warta selalu perlu ditinjau editor sebelum dipublikasikan.
- Jangan commit file `.env` — isinya rahasia.

---

## Lisensi

Bebas dipakai dan diubah.
