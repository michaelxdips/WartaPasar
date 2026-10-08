"""Susun Warta Ronce.

Struktur:
    Title    : WARTA RONCE <DD Bulan YYYY>
    Ringkasan: potongan pendek dipisah | , tanpa sentimen
    Konten   : enam bagian, urut dari yang paling penting
               1. HEADLINE UTAMA
               2. KETERBUKAAN INFORMASI
               3. AKSI KORPORASI
               4. RUPS
               5. SOROTAN EMITEN
    Sumber   : dikumpulkan di akhir, tanpa duplikat

Aturan:
- Bagian tanpa data tidak dimunculkan.
- Sumber tidak ditulis per entri.
- Post tidak boleh lebih dari batas byte platform.
"""
from __future__ import annotations

import re
from datetime import datetime

BULAN = {1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
         7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"}

MEDIA = {
    "kontan.co.id": "Kontan",
    "cnbcindonesia.com": "CNBC Indonesia",
    "cnnindonesia.com": "CNN Indonesia",
    "detik.com": "Detik",
    "bloombergtechnoz.com": "Bloomberg Technoz",
    "emitennews.com": "EmitenNews",
    "idnfinancials.com": "IDN Financials",
    "investor.id": "Investor Daily",
    "antaranews.com": "Antara",
    "jakartaglobe.id": "Jakarta Globe",
    "bisnis.com": "Bisnis.com",
    "katadata.co.id": "Katadata",
    "idx.co.id": "BEI",
}


def bersihkan_kode(kode: str) -> str:
    """Ambil kode emiten bersih: 'ASII.JK' -> 'ASII'."""
    return re.sub(r"\.JK$", "", (kode or "").strip())


def pendekkan_nama(teks: str, emiten: str) -> str:
    """Ganti nama perusahaan panjang dengan kode emiten.

    'PT Wulandari Bangun Laksana Tbk akan membagikan dividen'
    -> 'BSBK akan membagikan dividen'
    """
    if not emiten:
        return teks
    # pola nama perusahaan panjang: PT ... Tbk
    pola = r"\bPT\.?\s+[A-Z][\w'’\.\-]*(?:\s+[A-Z][\w'’\.\-]*){0,5}\s+Tbk\b"
    hasil = re.sub(pola, emiten, teks)
    # masih ada nama panjang tanpa PT? ganti frasa P... Tbk
    hasil = re.sub(r"\b[A-Z][\w'’\-]*(?:\s+[A-Z][\w'’\-]*){1,4}\s+Tbk\b", emiten, hasil)
    # buang "PT " yang tersisa di awal
    hasil = re.sub(r"^PT\.?\s+", "", hasil)
    # rapikan kalau kode dobel
    hasil = re.sub(rf"\b{re.escape(emiten)}\s+{re.escape(emiten)}\b", emiten, hasil)
    return re.sub(r"\s+", " ", hasil).strip()


def rapikan_bahasa(teks: str) -> str:
    """Buat bahasa jadi wajar, bukan bahasa robot.

    Masalah nyata dari keluaran sebelumnya: kalimat seperti
    "BSBK akan membagikan dividen interim tahun buku" terasa kaku dan
    menggantung karena ini kalimat berita yang dipotong, bukan bahasa
    yang ditulis untuk dibaca manusia.

    Penggantian di sini sederhana dan bisa diperiksa: frasa resmi
    korporat diganti padanan yang lebih wajar dipakai orang.
    """
    ganti = [
        (r"\bakan membagikan\b", "bagikan"),
        (r"\bmembagikan\b", "bagikan"),
        (r"\bakan menggelar\b", "akan gelar"),
        (r"\bakan menyelenggarakan\b", "akan gelar"),
        (r"\bmenggelar\b", "gelar"),
        (r"\bmengadakan\b", "adakan"),
        (r"\bmelaksanakan\b", "jalankan"),
        (r"\bmengumumkan\b", "umumkan"),
        (r"\bmenyelenggarakan\b", "gelar"),
        (r"\bmenerbitkan\b", "terbitkan"),
        (r"\bmengurangi kepemilikan\b", "kurangi porsi"),
        (r"\bmenambah kepemilikan\b", "tambah porsi"),
        (r"\bmelepas kepemilikan\b", "lepas porsi"),
        (r"\bsebesar\b", "senilai"),
        (r"\bper saham\b", "per lembar"),
        (r"\bakan datang\b", "mendatang"),
        (r"\bdilaksanakan\b", "digelar"),
        (r"\bbertempat di\b", "di"),
        (r"\btempatnya\b", "di"),
    ]
    hasil = teks
    for pola, ganti_ke in ganti:
        hasil = re.sub(pola, ganti_ke, hasil, flags=re.I)
    # Judul berita Indonesia lazim memakai bentuk sekarang, bukan "akan".
    # "akan gelar" terasa kaku, jadi "akan" dibuang saja.
    hasil = re.sub(r"\bakan (gelar|terbitkan|bagikan|adakan|jalankan)\b",
                   r"\1", hasil)
    return re.sub(r"\s+", " ", hasil).strip()


def _potong_kalimat_pertama(narasi: str) -> str:
    """Ambil kalimat pertama dengan aman.

    Jangan memotong di titik desimal: "50.04%" bukan akhir kalimat.
    Ini bug nyata — judul pernah keluar sebagai "dari 50" karena
    titik di "50.04" dianggap penutup kalimat.
    """
    if not narasi:
        return ""

    # Titik yang BUKAN akhir kalimat: titik di antara dua angka (desimal),
    # titik pada singkatan umum. Ditandai dulu supaya tidak ikut dipotong.
    TANDA = "\u0001TITIK\u0001"
    dilindungi = narasi
    dilindungi = re.sub(r"(?<=\d)\.(?=\d)", TANDA, dilindungi)      # 50.04
    dilindungi = re.sub(r"\b(PT|CV|Tbk|No|Jl|Rp)\.", r"\1" + TANDA, dilindungi)

    # Akhir kalimat = titik/tanya/seru yang diikuti spasi + huruf besar, atau akhir teks.
    pisah = re.split(r"(?<=[.!?])\s+(?=[A-Z])", dilindungi)
    kalimat = pisah[0] if pisah else dilindungi
    kalimat = kalimat.rstrip(".!?").strip()

    # Kembalikan titik yang dilindungi.
    return kalimat.replace(TANDA, ".")


def buat_judul_web(narasi: str, emiten: str = "", maks: int = 96) -> str:
    """Judul untuk halaman web: kalimat pertama, UTUH, tidak dipotong gantung.

    Ini dipisahkan dari `rapikan_judul` yang punya batas 60 karakter untuk
    post X/Threads. Sebelumnya keduanya memakai fungsi yang sama, sehingga
    web menampilkan judul yang terpotong di tengah, misalnya
    "BSBK akan membagikan dividen interim tahun buku" tanpa angka 2026.

    Aturan:
    - ambil kalimat pertama dari narasi (aman terhadap titik desimal)
    - ganti nama perusahaan panjang dengan kode emiten
    - pakai bahasa yang wajar, bukan bahasa robot
    - kalau kepanjangan, potong di batas KLAUSA, bukan di tengah frasa
    """
    kalimat = _potong_kalimat_pertama(narasi)
    if not kalimat:
        return ""

    kalimat = re.sub(r"\s*\([A-Z]{2,5}(?:\.JK)?\)\s*", " ", kalimat)
    kalimat = pendekkan_nama(kalimat, emiten) if emiten else kalimat
    kalimat = rapikan_bahasa(kalimat)
    kalimat = re.sub(r"\s+", " ", kalimat).strip(" .,:;—")

    if len(kalimat) <= maks:
        return kalimat

    # Terlalu panjang: potong di batas klausa terdekat SEBELUM batas.
    potong = kalimat[:maks]
    for pemisah in (", ", " dengan ", " senilai ", " untuk ", " pada ", " yang "):
        pos = potong.rfind(pemisah)
        if pos > maks * 0.55:
            potong = potong[:pos]
            break
    else:
        potong = potong.rsplit(" ", 1)[0]

    # Jangan biarkan berakhir di kata yang menggantung.
    penggantung = (r"(dan|atau|yang|untuk|dengan|akan|di|ke|dari|pada|oleh|ini|itu|"
                   r"sebagai|dalam|melalui|serta|kepada|terhadap|tentang|bagi|sejak|"
                   r"hingga|sampai|per|juta|miliar|triliun|rupiah|rp)$")
    for _ in range(3):
        baru = re.sub(r"\s+" + penggantung, "", potong, flags=re.I)
        if baru == potong:
            break
        potong = baru

    return re.sub(r"[\s,;:(—\-]+$", "", potong).strip()


def rapikan_judul(judul: str, emiten: str, narasi: str = "") -> str:
    """Buat judul PENDEK bahasa Indonesia untuk post X/Threads.

    Batas 60 karakter di sini karena satu post dibatasi 500 byte.
    Untuk halaman web, pakai `buat_judul_web` yang tidak memotong
    sampai gantung.
    """
    MAKS = 60

    def pendek(teks: str) -> str:
        teks = re.sub(r"\s*\([A-Z]{2,5}(?:\.JK)?\)\s*", " ", teks)
        teks = re.sub(r"\s+", " ", teks).strip(" .,:;—")
        teks = pendekkan_nama(teks, emiten)
        teks = rapikan_bahasa(teks)
        # Kalau masih bahasa Inggris, jangan dipakai sebagai judul.
        inggris = len(re.findall(r"\b(the|of|and|for|with|from|shares|stock|market|"
                                 r"asks|weigh|plans|says|is|are|to|in|on|by|as|its)\b",
                                 teks, re.I))
        if inggris >= 2:
            return ""
        if len(teks) <= MAKS:
            return teks
        # Potong di batas kata, lalu bersihkan ekor yang menggantung.
        potong = teks[:MAKS].rsplit(" ", 1)[0]
        # Buang kata yang membuat kalimat tidak selesai.
        penggantung = (
            r"(dan|atau|yang|untuk|dengan|akan|di|ke|dari|pada|oleh|ini|itu|sebagai|"
            r"dalam|melalui|serta|kepada|terhadap|tentang|bagi|sejak|hingga|sampai|"
            r"per|sebesar|senilai|sekitar|kurang|lebih|saham|lembar|buah|unit|"
            r"juta|miliar|triliun|rupiah|rp|kepada|menjadi|senilai)$"
        )
        for _ in range(4):
            baru = re.sub(r"\s+" + penggantung, "", potong, flags=re.I)
            if baru == potong:
                break
            potong = baru
        # Buang ekor angka yang menggantung (mis. "...sebesar Rp 622,93").
        # Tapi jangan buang kalau seluruh judul cuma angka.
        kandidat = re.sub(r"\s+(?:Rp\s*)?[\d.,]+(?:%|persen)?$", "", potong).rstrip(" ,;:—-")
        if kandidat and len(kandidat) >= 18:
            potong = kandidat
        # Jangan biarkan judul berakhir dengan tanda menggantung.
        potong = re.sub(r"[\s,;:(—\-]+$", "", potong)
        return potong

    # Dari narasi: pakai kalimat pertama.
    if narasi:
        kal = narasi.split(".")[0].strip()
        kal = re.sub(r"^" + re.escape(emiten) + r"\s+", "", kal) if emiten else kal
        kal = kal.strip(" .,:;—")
        # Judul harus punya subjek: kalau diawali kata kerja, tambahkan kodenya.
        if kal and re.match(r"^(meng|mem|men|me|ber|ter|di)\w+", kal.lower()):
            kal = f"{emiten} {kal}" if emiten else kal
        hasil = pendek(kal)
        if hasil:
            return hasil

    # Cadangan: bersihkan judul asli.
    t = judul or ""
    for k in re.findall(r"\b([A-Z]{2,5})\.JK\b", t):
        t = t.replace(f" {k}.JK", "")
    t = re.sub(r"\s+", " ", t).strip(" .,:;")
    inggris = len(re.findall(r"\b(the|of|and|for|with|from|shares|stock|market|"
                             r"announce|launch|says|is|are|to|in|on|by)\b", t, re.I))
    if inggris >= 3:
        return ""
    return pendek(t)


def nama_media(url: str) -> str:
    if not url:
        return ""
    bersih = re.sub(r"^https?://", "", url).split("/")[0].lower()
    bersih = bersih.replace("www.", "").replace("investasi.", "").replace("finance.", "")
    bersih = bersih.replace("keuangan.", "")
    if bersih in MEDIA:
        return MEDIA[bersih]
    for domain, nama in MEDIA.items():
        if bersih.endswith(domain) or domain in bersih:
            return nama
    bagian = bersih.split(".")
    return bagian[-2].title() if len(bagian) >= 2 else bersih.title()


def fmt_persen(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):g}%"
    except (TypeError, ValueError):
        return "-"


def fmt_angka(v) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def fmt_tanggal(iso: str) -> str:
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return str(iso or "-")
    return f"{d.day} {BULAN[d.month]} {d.year}"


# --------------------------------------------------------------- bagian-bagian

def bagian_headline(data: dict, ditulis: list[dict], maks: int | None = None) -> tuple[list[dict], list[str]]:
    """Headline utama. Mengembalikan (entri, daftar_media)."""
    entri, media = [], []
    daftar = ditulis if maks is None else ditulis[:maks]
    for d in daftar:
        m = nama_media(d.get("sumber", ""))
        if m and m not in media:
            media.append(m)
        kode = bersihkan_kode((d.get("emiten") or "").split(",")[0].strip())
        narasi = d.get("narasi", "").strip()
        # Dua judul dengan keperluan berbeda:
        # - judul lengkap untuk web (tidak dipotong sampai menggantung)
        # - judul pendek untuk post X/Threads (batas 60 karakter)
        judul_web = buat_judul_web(narasi, kode)
        judul = judul_web or rapikan_judul(
            d.get("judul_id") or d.get("judul", ""), kode, narasi)
        # Buang pengulangan: kalau kalimat pertama narasi dipakai sebagai judul,
        # keluarkan kalimat itu dari narasi supaya tidak dobel.
        if judul and narasi:
            kalimat = [k.strip() for k in re.split(r"(?<=[.!?])\s+", narasi) if k.strip()]
            if len(kalimat) >= 2:
                pertama = re.sub(r"\s*\([A-Z]{2,5}(?:\.JK)?\)\s*", " ", kalimat[0])
                pertama_bersih = re.sub(r"\s+", " ", pertama).strip(" .,:;—")
                pokok_judul = judul.rstrip("…").rstrip(" .,:;—")
                # bandingkan awal keduanya
                if (pertama_bersih[:35].lower() == pokok_judul[:35].lower()
                        or pokok_judul[:35].lower() in pertama_bersih[:60].lower()):
                    narasi = " ".join(kalimat[1:])
        entri.append({
            "emiten": kode,
            "judul": judul,
            "narasi": narasi,
            "media": m,
        })
    return entri, media


def bagian_keterbukaan(data: dict, maks: int = 3) -> tuple[list[dict], list[str]]:
    fil = (data.get("filings") or {}).get("results", [])
    entri = []
    for f in fil:
        sebelum = f.get("share_percentage_before")
        sesudah = f.get("share_percentage_after")
        # Lewati catatan yang persentasenya tidak berubah.
        if sebelum is not None and sesudah is not None:
            try:
                if float(sebelum) == float(sesudah):
                    continue
            except (TypeError, ValueError):
                pass
        kode = bersihkan_kode(f.get("symbol", ""))
        aksi = {"buy": "menambah", "sell": "mengurangi"}.get(
            (f.get("transaction_type") or "").lower())
        if not aksi:
            try:
                aksi = "menambah" if float(sesudah or 0) > float(sebelum or 0) else "mengurangi"
            except (TypeError, ValueError):
                aksi = "mengubah"
        pemilik = f.get("holder_name", "") or "Investor"
        narasi = (f"{pemilik} {aksi} kepemilikan di {kode} "
                  f"dari {fmt_persen(sebelum)} menjadi {fmt_persen(sesudah)}.")
        if f.get("amount_transaction"):
            narasi += f" Jumlah sahamnya {fmt_angka(f['amount_transaction'])} lembar"
            if f.get("price"):
                narasi += f" dengan harga Rp{float(f['price']):g} per lembar"
            narasi += "."

        # Judul: siapa, berbuat apa, di emiten mana. Bukan potongan kalimat.
        aksi_wajar = {"menambah": "tambah porsi", "mengurangi": "kurangi porsi",
                      "mengubah": "ubah porsi"}.get(aksi, "ubah porsi")
        entri.append({
            "emiten": kode,
            "judul": f"{pemilik} {aksi_wajar} di {kode}",
            "narasi": narasi,
        })
        if len(entri) >= maks:
            break
    return entri, ["Sectors"]


def bagian_aksi_korporasi(data: dict, maks: int = 3) -> tuple[list[dict], list[str]]:
    ca = data.get("corp_actions") or {}
    entri = []
    for d in (ca.get("dividend") or []):
        kode = bersihkan_kode(d.get("symbol", ""))
        nominal = float(d.get("dividend_amount") or 0)
        entri.append({
            "emiten": kode,
            "judul": f"{kode} bagikan dividen Rp{nominal:g} per lembar",
            "narasi": (f"{kode} bagikan dividen "
                       f"Rp{nominal:g} per lembar. "
                       f"Ex date {fmt_tanggal(d.get('ex_date'))}, "
                       f"pembayaran {fmt_tanggal(d.get('payment_date'))}."),
        })
        if len(entri) >= maks:
            break
    for r in (ca.get("right_issue") or []):
        if len(entri) >= maks:
            break
        kode = bersihkan_kode(r.get("symbol", ""))
        harga = float(r.get("price") or 0)
        entri.append({
            "emiten": kode,
            "judul": f"{kode} rights issue di harga Rp{harga:g}",
            "narasi": (f"{kode} gelar rights issue dengan harga "
                       f"Rp{harga:g} per lembar. "
                       f"Periode perdagangan {fmt_tanggal(r.get('trading_period_start'))} "
                       f"sampai {fmt_tanggal(r.get('trading_period_end'))}."),
        })
    return entri, ["Sectors"]


def bagian_rups(data: dict, maks: int = 3) -> tuple[list[dict], list[str]]:
    ca = data.get("corp_actions") or {}
    entri = []
    for a in (ca.get("agm") or [])[:maks]:
        kode = bersihkan_kode(a.get("symbol", ""))
        tempat = (a.get("agm_place") or "").strip()
        if len(tempat) > 50:
            tempat = tempat[:47].rsplit(" ", 1)[0] + "…"
        tanggal = fmt_tanggal(a.get("agm_date"))
        jam = str(a.get("agm_time", ""))[:5]
        narasi = f"{kode} gelar RUPS pada {tanggal}"
        if jam:
            narasi += f" pukul {jam} WIB"
        narasi += "."
        if tempat:
            narasi += f" Tempatnya di {tempat}."
        entri.append({
            "emiten": kode,
            "judul": f"{kode} gelar RUPS {tanggal}" + (f" pukul {jam}" if jam else ""),
            "narasi": narasi,
        })
    return entri, ["Sectors"]


def bagian_sorotan(harga: dict, maks: int = 3) -> tuple[list[dict], list[str], str]:
    entri = []
    tanggal_data = ""
    for sym, info in list(harga.items())[:maks]:
        if not tanggal_data:
            tanggal_data = info.get("tanggal", "")
        kode = bersihkan_kode(sym)
        baris = f"Rp{info['close']:g}"
        ubah = info.get("ubah_persen")
        if ubah is not None:
            tanda = "+" if ubah >= 0 else ""
            baris += f" ({tanda}{ubah:.2f}%)"
        entri.append({
            "emiten": kode,
            "judul": f"{kode} {baris}",
            "narasi": baris,
        })
    judul = "SOROTAN EMITEN"
    if tanggal_data:
        judul += f" (data {fmt_tanggal(tanggal_data)})"
    return entri, ["Sectors"], judul


# --------------------------------------------------------------- peringkat berita

PENTING = [
    (r"kebijakan|regulasi|aturan|bei |bursa|ojk", 58),
    (r"akuisisi|merger|ambil alih|caplok|tender", 52),
    (r"dividen|buyback|rights issue|ipo", 46),
    (r"suspensi|digembok|disuspensi|uma\b", 44),
    (r"laba|rugi|kinerja|pendapatan|margin", 38),
    (r"anjlok|melonjak|melesat|turun|naik", 30),
    (r"direktur|komisaris|mundur", 20),
    (r"target harga|rekomendasi|analis", 18),
]


def skor(judul: str, simbol: list) -> int:
    t = (judul or "").lower()
    nilai = sum(poin for pola, poin in PENTING if re.search(pola, t))
    nilai += min(len(simbol or []), 10) * 3
    return nilai


def pilih_headline(data: dict, maks: int = 3) -> list[dict]:
    berita = (data.get("berita") or {}).get("results", [])
    # Buang berita kembar: judul hampir sama dianggap sama.
    unik, kunci = [], set()
    for b in berita:
        judul = (b.get("title") or "").lower()
        # kunci dari kata-kata awal judul + kode emiten
        kata = re.findall(r"[a-z]{4,}", judul)[:6]
        simbol = tuple(sorted((b.get("symbols") or [])[:2]))
        k = (tuple(kata), simbol)
        # cek juga apakah salah satu kunci lama punya irisan besar
        if k in kunci:
            continue
        duplikat = False
        for lama in kunci:
            if not isinstance(lama, tuple) or len(lama) != 2:
                continue
            kata_lama, simbol_lama = lama
            if simbol_lama != simbol or not kata_lama or not kata:
                continue
            irisan = len(set(kata) & set(kata_lama))
            if irisan >= 4:          # 4 dari 6 kata awal sama = berita kembar
                duplikat = True
                break
        if duplikat:
            continue
        kunci.add(k)
        unik.append(b)
    unik.sort(key=lambda b: -skor(b.get("title", ""), b.get("symbols", [])))
    return [{
        "judul": b.get("title", ""),
        "isi": b.get("body", "") or b.get("title", ""),
        "emiten": ", ".join([s for s in (b.get("symbols") or []) if s][:2]),
        "sumber": b.get("source", ""),
        "timestamp": b.get("timestamp", ""),
    } for b in unik[:maks]]


def ringkasan_dari(headline: list[dict], keterbukaan: list[dict],
                   aksi: list[dict]) -> str:
    """Potongan pendek dipisah | , langsung ke inti.

    Diambil dari narasi bahasa Indonesia, bukan judul asing.
    """
    potongan = []
    for h in headline[:3]:
        # Pakai judul (sudah bahasa Indonesia) untuk ringkasan.
        n = (h.get("judul") or "").strip()
        if not n:
            n = (h.get("narasi") or "").strip()
        if not n:
            continue
        kal = n.split(".")[0].strip()
        kal = re.sub(r"\s*\([A-Z]{2,5}(?:\.JK)?\)\s*", " ", kal)
        kal = re.sub(r"\s+", " ", kal).strip(" .,:;—")
        if len(kal) > 62:
            kal = kal[:59].rsplit(" ", 1)[0] + "…"
        if kal:
            potongan.append(kal)
    for k in keterbukaan[:1]:
        n = (k.get("narasi") or "").strip()
        if n:
            kal = n.split(".")[0].strip()
            if len(kal) > 62:
                kal = kal[:59].rsplit(" ", 1)[0] + "…"
            potongan.append(kal)
    for a in aksi[:1]:
        n = (a.get("narasi") or "").strip()
        if n:
            kal = n.split(".")[0].strip()
            if len(kal) > 62:
                kal = kal[:59].rsplit(" ", 1)[0] + "…"
            potongan.append(kal)
    return " | ".join(potongan[:5])


# --------------------------------------------------------------- susun post

def bagi_post(judul: str, ringkasan: str, bagian: list[tuple[str, list[dict]]],
              sumber: list[str], batas_byte: int = 500) -> list[str]:
    """Bagi jadi beberapa post. Tidak memotong di tengah entri.

    Nomor halaman dihitung sejak awal supaya post tidak melewati batas.
    """
    def uk(t: str) -> int:
        return len(t.encode("utf-8"))

    LIMIT = batas_byte - 12          # ruang untuk "\n\n(nn/nn)"
    posts: list[str] = []
    sedang = f"{judul}\n\n{ringkasan}"
    header_sudah: set[str] = set()

    for nama, entri_list in bagian:
        if not entri_list:
            continue
        for it in entri_list:
            teks = it.get("narasi", "")
            kode = it.get("emiten", "")
            judul = it.get("judul", "")
            # Buang kode di awal narasi kalau sudah dipakai sebagai label.
            if kode and teks.startswith(f"{kode} "):
                teks = teks[len(kode) + 1:]
            if judul:
                teks = f"{judul} ({kode})\n    {teks}".rstrip() if kode else f"{judul}\n    {teks}".rstrip()
            else:
                teks = f"{kode} — {teks}" if kode else teks

            perlu = nama not in header_sudah
            header = f"\n\n── {nama} ──" if perlu else ""
            calon = sedang + header + "\n" + teks
            if uk(calon) <= LIMIT:
                sedang = calon
                if perlu:
                    header_sudah.add(nama)
            else:
                posts.append(sedang.rstrip())
                sedang = f"── {nama} ──\n{teks}"
                header_sudah = {nama}

    if sedang.strip():
        posts.append(sedang.rstrip())

    # Baris sumber di akhir, sekali saja.
    # Gabungkan ke post terakhir yang ada isinya, jangan bikin post baru.
    baris_sumber = "Sumber: " + ", ".join(sumber) if sumber else ""
    if baris_sumber:
        # cari post terakhir yang punya isi (bukan cuma header)
        for i in range(len(posts) - 1, -1, -1):
            kandidat = posts[i] + "\n\n" + baris_sumber
            if uk(kandidat) <= batas_byte:
                posts[i] = kandidat
                break
        else:
            # tidak ada yang muat: sisipkan ke post terakhir, buang header kalau perlu
            if posts:
                tanpa_header = "\n".join(posts[-1].split("\n")[1:]) if posts[-1].startswith("──") else posts[-1]
                if uk(tanpa_header + "\n\n" + baris_sumber) <= batas_byte:
                    posts[-1] = tanpa_header + "\n\n" + baris_sumber
                else:
                    posts.append(baris_sumber)
            else:
                posts.append(baris_sumber)

    total = len(posts)
    return [p if i == 0 else f"{p}\n\n({i+1}/{total})" for i, p in enumerate(posts)]


def susun(data: dict, ditulis: list[dict], harga: dict, tanggal: datetime,
          batas_byte: int = 500) -> dict:
    """Susun Warta lengkap dari data dan hasil tulis ulang."""
    judul = f"WARTA RONCE {tanggal.day:02d} {BULAN[tanggal.month]} {tanggal.year}"

    headline, media_headline = bagian_headline(data, ditulis)
    keterbukaan, media_ket = bagian_keterbukaan(data)
    aksi, media_aksi = bagian_aksi_korporasi(data)
    rups, media_rups = bagian_rups(data)
    sorotan, media_sor, judul_sorotan = bagian_sorotan(harga)

    ringkasan = ringkasan_dari(headline, keterbukaan, aksi)

    bagian = [
        ("HEADLINE UTAMA", headline),
        ("KETERBUKAAN INFORMASI", keterbukaan),
        ("AKSI KORPORASI", aksi),
        ("RUPS", rups),
        (judul_sorotan, sorotan),
    ]
    bagian = [(n, i) for n, i in bagian if i]

    # Sumber unik, urut sesuai kemunculan.
    sumber: list[str] = []
    for daftar in (media_headline, media_ket, media_aksi, media_rups, media_sor):
        for m in daftar:
            if m and m not in sumber:
                sumber.append(m)

    posts = bagi_post(judul, ringkasan, bagian, sumber, batas_byte)

    return {
        "judul": judul,
        "ringkasan": ringkasan,
        "tanggal": tanggal.date().isoformat(),
        "jendela": data.get("jendela"),
        "sumber": sumber,
        "bagian": {n: i for n, i in bagian},
        "posts": posts,
        "jumlah_post": len(posts),
        "publishable": False,
        "editor_approval": "required",
        "api_write": False,
        "sumber_data": data.get("_sumber", "tidak diketahui"),
    }
