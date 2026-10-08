# Sistem Desain Ronce

Diturunkan dari Shape of Intelligence (palet + tipografi), digabung prinsip
Apple Design dan UI/UX Pro Max, dengan ide interaksi dari Dave Holloway,
Solar Journey, dan Tabadulat.

---

## 1. Palet Warna

Diambil langsung dari CSS Shape of Intelligence (`--blue`, `--carbon`, dst).

| Nama | Nilai | Fungsi di Ronce |
|---|---|---|
| `--bg` | `#090e13` | Latar terdalam |
| `--carbon` | `#202623` | Permukaan kartu |
| `--white` | `#f2f4f1` | Teks utama |
| `--silver` | `#b8c4c5` | Teks sekunder |
| `--ink-2` | `#5a625e` | Teks redup, label |
| `--blue` | `#234ae8` | Aksen utama, tautan, fokus |
| `--green` | `#406b5b` | Sinyal positif, status aman |
| `--coral` | `#c44d40` | Peringatan, status tidak aman |
| `--coral-ink` | `#a83a2e` | Teks peringatan |
| `--hair-on-carbon` | `#f2f4f129` | Garis pemisah di permukaan gelap |

**Aturan pemakaian:**

```text
Latar        : --bg untuk halaman, --carbon untuk kartu
Teks         : --white untuk judul, --silver untuk isi, --ink-2 untuk label
Aksen        : --blue untuk latar tombol/batang grafik;
               varian terang untuk TEKS (aksen asli hanya 2.97:1)
Status aman  : --green
Status bahaya: --coral
Garis        : --hair-on-carbon (jangan pakai putih solid)
```

Kontras sudah dicek:

| Kombinasi | Rasio | Status |
|---|---|---|
| `--white` di `--bg` | 17.8:1 | ✅ AAA |
| `--silver` di `--bg` | 9.4:1 | ✅ AAA |
| `--ink-2` teks di `--bg` | 6.1:1 | ✅ AA (varian terang untuk teks) |
| `--blue` teks di `--bg` | 7.1:1 | ✅ AAA (varian terang untuk teks) |

---

## 2. Tipografi

Font asli Shape of Intelligence: **ABC Diatype** (sans) + **ABC Diatype Mono**.

Karena ABC Diatype berlisensi berbayar, dipakai padanan gratis yang sangat
mirip supaya siapa pun bisa memakai proyek ini:

| Peran | Font asli | Padanan gratis | Sumber |
|---|---|---|---|
| Sans | ABC Diatype | **Inter** | Google Fonts |
| Mono | ABC Diatype Mono | **JetBrains Mono** | Google Fonts |

```css
--font-sans: "Inter", -apple-system, "Helvetica Neue", sans-serif;
--font-mono: "JetBrains Mono", ui-monospace, monospace;
```

**Skala ukuran** (dari CSS asli, disesuaikan):

```css
--text-display : clamp(2.5rem, 6vw, 4.5rem)   /* judul halaman */
--text-h1      : clamp(1.75rem, 3vw, 2.5rem)  /* judul bagian */
--text-h2      : 1.25rem                       /* judul kartu */
--text-body    : 1rem                          /* isi */
--text-small   : 0.875rem                      /* metadata */
--text-label   : 0.75rem                       /* label huruf besar */
```

**Aturan dari Apple Design (prinsip 15):**

```text
- letter-spacing NEGATIF untuk teks besar: -0.02em pada display
- letter-spacing positif kecil untuk label: 0.08em
- line-height 1.05 untuk display, 1.55 untuk isi (--leading-body asli)
- panjang baris maksimal 64ch (--measure asli)
- pakai rem, bukan px, supaya ikut setelan ukuran pengguna
```

---

## 3. Jarak dan Grid

```css
--gutter   : 24px      /* jarak tepi (asli: 16px mobile, 24px desktop) */
--margin   : 6vw       /* margin halaman (asli) */
--header-h : 64px      /* tinggi header mobile */
             92px      /* tinggi header desktop (asli) */
--radius   : 12px      /* sudut kartu */
--gap      : 20px      /* jarak antar kartu */
```

---

## 4. Gerak

Diambil dari CSS asli Shape of Intelligence:

```css
--ease-out-2   : cubic-bezier(.25, 1, .5, 1)
--ease-out-3   : cubic-bezier(.22, 1, .36, 1)
--dur-reveal   : .7s
--dur-settle   : .9s
```

**Aturan dari Apple Design:**

| Kejadian | Durasi | Jenis |
|---|---|---|
| Umpan balik tekan | 100ms | langsung, tanpa tunda |
| Hover | 150-200ms | `--ease-out-2` |
| Kartu muncul | 700ms | `--dur-reveal` |
| Buka panel | 400ms | spring, damping 1.0 |
| Seret/slide | ikut jari | 1:1, bisa dihentikan kapan saja |

**Wajib ada:**

```css
@media (prefers-reduced-motion: reduce) {
  /* ganti semua gerak dengan perubahan opacity saja */
}
```

---

## 5. Struktur Halaman

Mengikuti pola Tabadulat (bagian jelas, banyak angka) + Solar Journey
(navigasi tab, detail panel) + Dave Holloway (kartu karya dengan hover).

```text
┌────────────┬─────────────────────────────────────┐
│ SIDEBAR    │ KONTEN                              │
│ (bisa      │                                     │
│  ditutup)  │  Setiap halaman punya kepala seksi  │
│            │  (label + judul + satu kalimat).    │
│  Orbit     │                                     │
│  Warta     │  Orbit   : sapaan + textbox + chip  │
│  Jelajah   │  Warta   : tab + kartu + pemilih    │
│  Kalender  │  Kalender: spine tanggal + konten   │
│  Emiten    │  Emiten  : tabel + grafik batang    │
│  ──────    │                                     │
│  Disimpan  │                                     │
│  Profil    │  FOOTER hanya di halaman Profil     │
└────────────┴─────────────────────────────────────┘

Di bawah 900px: sidebar jadi kepala ringkas,
navigasi pindah ke bilah bawah.
```

---

## 6. Interaksi Kunci

**a. Kartu berita (dari Dave Holloway)**

```text
- hover: naik 2px, garis tepi jadi --blue, tanpa menggeser tata letak
- klik: buka panel detail dari sisi kanan (bukan halaman baru)
- panel bisa ditutup dengan Esc, klik luar, atau geser
```

**b. Navigasi tab (dari Solar Journey)**

```text
- tab di atas konten, garis bawah bergerak mengikuti pilihan
- konten berganti dengan fade 200ms
- status tab disimpan di URL (bisa dibagikan)
```

**c. Angka statistik**

```text
- ditulis apa adanya, TANPA animasi hitung
- alasan: produk data tidak boleh menampilkan angka belum final,
  walau hanya sesaat
```

**d. Grafik harga**

```text
- SVG murni, tanpa pustaka luar
- diagram BATANG, bukan garis: tiap batang satu emiten berbeda
- skala linier: panjang batang harus jujur sebanding nilainya
- label nilai + persentase perubahan di tiap batang
```

**e. Kalender: spine + konten**

```text
- spine vertikal di kiri: garis + titik per tanggal yang punya agenda
- tanggal aktif menyala dengan cincin orbit yang berputar
- konten tanggal terpilih di kanan, menempel saat digeser
- daftar lengkap semua agenda di bawahnya
```

**f. Pencarian**

```text
- hasil muncul saat mengetik (debounce 200ms)
- kata yang cocok diberi sorotan
- navigasi dengan panah atas/bawah + Enter
```

---

## 7. Footer

Footer **hanya tampil di halaman Profil proyek**, tidak di halaman utama.
Menyantumkan nama tim dan sumber data.

```text
┌──────────────────────────────────────────────────┐
│ Ronce                                            │
│ Warta pasar harian dari data, untuk pembaca.     │
│                                                  │
│ Halaman      Produk         Sumber               │
│ ─────────    ──────────     ──────────           │
│ That team name is already taken   Orbit          Sectors API          │
│              Warta          IDX                  │
│              Emiten                              │
│              Kalender                            │
│                                                  │
│ ──────────────────────────────────────────────── │
│ © 2026 That team name is already taken. Bukan nasihat investasi.      │
│ Data pasar bisa tertunda. Selalu periksa sumber. │
└──────────────────────────────────────────────────┘
```

---

## 8. Aturan Wajib (dari UI/UX Pro Max)

```text
✅ Ikon pakai SVG, bukan emoji
✅ Semua elemen bisa diklik punya cursor: pointer
✅ Target sentuh minimal 44×44px
✅ Fokus keyboard terlihat jelas (outline --blue)
✅ Transisi 150-300ms untuk mikro-interaksi
✅ Tidak ada pergeseran tata letak saat hover
✅ Kontras teks minimal 4.5:1
✅ Alt text untuk semua gambar
✅ Tidak ada gulir horizontal di 375px
✅ Pakai transform/opacity, bukan width/height
```

---

## 9. Latar

Tema ruang angkasa, tiga lapis, tanpa dependensi:

```text
- Aurora   : gradien radial besar bergerak pelan (26s & 34s), blur 44px
- Kisi titik: pola titik 26px, memudar hanya di tepi layar
- Bintang  : dua lapis - 10 titik tersebar + taburan berulang 240px
```

Aurora dan kisi titik diadaptasi dari React Bits (Aurora, Dot Grid),
ditulis ulang dengan CSS murni supaya tidak perlu WebGL.

Semua efek berhenti saat `prefers-reduced-motion`.

---

## 10. Yang Tidak Dipakai

```text
❌ Gradien berlebihan
❌ Bayangan tebal ala material design
❌ Animasi yang tidak bisa dihentikan
❌ Teks abu-abu di atas permukaan tembus pandang (dari Apple Design)
❌ Emoji sebagai ikon antarmuka
❌ Warna sebagai satu-satunya penanda status
```
