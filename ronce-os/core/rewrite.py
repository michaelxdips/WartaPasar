"""Tulis ulang berita jadi bahasa Indonesia gaya gen Z & milenial.

Memakai endpoint AI apa pun yang OpenAI-compatible.
Kalau AI tidak tersedia, pakai penulisan sederhana sebagai cadangan.

Aturan gaya bahasa (dari pemilik produk):
- Maksimal 3 kalimat per berita.
- Struktur SPOK jelas: siapa, melakukan apa, apa, kapan.
- Kalimat inti dulu, penjelas kemudian.
- Bahasa Indonesia, mudah dipahami orang awam.
- Tanpa slang (tidak pakai "Bjir" dan sejenisnya).
- Tanpa sentimen atau opini.
- Tidak menyalin judul sumber apa adanya.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

SYSTEM_PROMPT = """Kamu editor berita pasar modal Indonesia untuk pembaca gen Z dan milenial yang awam soal saham.

Tugasmu menulis ulang berita berbahasa Inggris menjadi bahasa Indonesia.

ATURAN KETAT:
1. MAKSIMAL 3 KALIMAT. Tidak boleh lebih. Ini aturan paling penting.
2. Setiap kalimat harus punya Subjek, Predikat, Objek yang jelas.
3. Kalimat pertama = inti berita (siapa melakukan apa).
   Kalimat kedua = angka penting atau dampaknya.
   Kalimat ketiga = konteks singkat (opsional, hanya kalau perlu).
4. Bahasa Indonesia sehari-hari yang mudah dipahami, tapi BUKAN slang.
   Jangan pakai kata seperti "bjir", "goks", "wkwk".
5. Tidak menambah opini, sentimen, atau kata seperti "sayangnya", "hebatnya".
6. Semua angka dan fakta harus dipertahankan persis seperti sumber.
7. Jangan pakai kata Inggris kecuali istilah pasar yang sudah umum
   (dividen, rights issue, buyback, emiten).
8. Selalu sebut nama atau kode emitennya, jangan "perusahaan ini".
9. PANJANG MAKSIMAL 320 KARAKTER. Pilih hanya fakta terpenting.
   Buang detail yang tidak mengubah pemahaman pembaca awam.

Balas HANYA dengan teks narasinya. Tanpa penjelasan, tanpa tanda kutip,
tanpa tanda pagar, tanpa daftar bernomor."""


def _panggil_ai(base_url: str, key: str, model: str, prompt: str,
                timeout: int = 90) -> str:
    """Panggil endpoint AI yang OpenAI-compatible."""
    url = base_url.rstrip("/") + "/chat/completions"
    isi = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(isi).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Ronce/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        jawab = json.loads(r.read().decode("utf-8"))
    return jawab["choices"][0]["message"]["content"].strip()


def tulis_ulang_ai(judul: str, isi: str, emiten: str, *,
                   base_url: str, key: str, model: str,
                   timeout: int = 90) -> str | None:
    """Tulis ulang satu berita pakai AI. None kalau gagal."""
    prompt = (
        f"Judul asli: {judul}\n"
        f"Kode emiten: {emiten or 'tidak disebut'}\n"
        f"Isi berita: {isi[:1200]}\n\n"
        f"Tulis ulang jadi narasi bahasa Indonesia, MAKSIMAL 3 KALIMAT "
        f"dan maksimal 320 karakter."
    )
    try:
        hasil = _panggil_ai(base_url, key, model, prompt, timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None
    if not hasil:
        return None
    hasil = hasil.strip().strip('"').strip("'").strip()

    # Paksa patuh: potong jadi maksimal 3 kalimat.
    import re
    kalimat = [k.strip() for k in re.split(r"(?<=[.!?])\s+", hasil) if k.strip()]
    if len(kalimat) > 3:
        kalimat = kalimat[:3]

    # Paksa patuh: batas 340 karakter, dipotong di batas kalimat.
    hasil = ""
    for k in kalimat:
        calon = (hasil + " " + k).strip()
        if len(calon) > 340:
            break
        hasil = calon
    if not hasil and kalimat:
        # Kalimat pertama sendiri sudah terlalu panjang: potong di batas kata.
        potong = kalimat[0][:340].rsplit(" ", 1)[0]
        # buang ekor yang menggantung (angka atau tanda baca setengah)
        potong = re.sub(r"[\s,;:(—-]+$", "", potong)
        hasil = potong.rstrip(".") + "."

    return hasil or None


def tulis_ulang_sederhana(judul: str, isi: str, emiten: str) -> str:
    """Cadangan tanpa AI: pakai isi berita apa adanya, dipangkas 3 kalimat.

    Hasilnya masih bisa kaku, tapi tetap jujur dan tidak mengarang.
    """
    import re
    teks = (isi or judul or "").strip()
    teks = re.sub(r"\s+", " ", teks)
    kalimat = [k.strip() for k in re.split(r"(?<=[.!?])\s+", teks) if k.strip()]
    if not kalimat:
        return judul
    return " ".join(kalimat[:3])


def tulis_ulang_banyak(daftar: list[dict], *, base_url: str = "", key: str = "",
                       model: str = "", timeout: int = 90,
                       verbose: bool = True) -> list[dict]:
    """Tulis ulang banyak berita sekaligus.

    Setiap item dict harus punya: judul, isi, emiten.
    Menambah kunci 'narasi' dan 'cara' (ai/sederhana).
    """
    punya_ai = bool(base_url and key and model)
    hasil = []
    for i, item in enumerate(daftar, 1):
        judul = item.get("judul", "")
        isi = item.get("isi", "")
        emiten = item.get("emiten", "")

        narasi = None
        cara = "sederhana"
        if punya_ai:
            narasi = tulis_ulang_ai(judul, isi, emiten, base_url=base_url,
                                    key=key, model=model, timeout=timeout)
            if narasi:
                cara = "ai"

        if not narasi:
            narasi = tulis_ulang_sederhana(judul, isi, emiten)

        if verbose:
            tanda = "AI" if cara == "ai" else "dasar"
            print(f"    [{i}/{len(daftar)}] {tanda:6s} {judul[:52]}")

        hasil.append({**item, "narasi": narasi, "cara": cara})
    return hasil
