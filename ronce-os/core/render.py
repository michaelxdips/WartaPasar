"""Keluarkan hasil Warta: JSON, teks siap posting, dan Markdown."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# Folder akar proyek — dipakai untuk memastikan simpan_web hanya menulis
# ketika benar-benar diminta (bukan dari test dengan folder sementara).
ROOT = Path(__file__).resolve().parent.parent


def simpan_json(warta: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"warta-{warta['tanggal']}.json"
    target.write_text(json.dumps(warta, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def simpan_teks(warta: dict, out_dir: Path) -> Path:
    """Teks siap salin-tempel ke X atau Threads."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"warta-{warta['tanggal']}.txt"
    baris = [f"# {warta['judul']}", ""]
    for i, p in enumerate(warta["posts"], 1):
        baris.append(f"===== POST {i} ({len(p.encode('utf-8'))} byte) =====")
        baris.append(p)
        baris.append("")
    target.write_text("\n".join(baris), encoding="utf-8")
    return target


def simpan_markdown(warta: dict, out_dir: Path) -> Path:
    """Markdown untuk ditinjau editor."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"warta-{warta['tanggal']}.md"

    b = [f"# {warta['judul']}", ""]
    b.append(f"> Jendela: {warta.get('jendela', ['-', '-'])[0]} → {warta.get('jendela', ['-', '-'])[1]}")
    b.append(f"> Sumber data: {warta.get('sumber_data', '-')}")
    b.append(f"> Status: **belum boleh dipublikasikan** (menunggu persetujuan editor)")
    b.append("")
    b.append("---")
    b.append("")
    b.append("## RINGKASAN")
    b.append("")
    b.append("```text")
    b.append(warta["ringkasan"])
    b.append("```")
    b.append("")
    b.append("---")
    b.append("")
    b.append(f"## ISI — {warta['jumlah_post']} POST")
    b.append("")
    for i, p in enumerate(warta["posts"], 1):
        b.append(f"### POST {i} — {len(p.encode('utf-8'))} byte")
        b.append("")
        b.append("```text")
        b.append(p)
        b.append("```")
        b.append("")

    b.append("---")
    b.append("")
    b.append("## CEK TEKNIS")
    b.append("")
    b.append("| Post | Ukuran | Batas | Status |")
    b.append("|---|---|---|---|")
    for i, p in enumerate(warta["posts"], 1):
        u = len(p.encode("utf-8"))
        b.append(f"| {i} | {u} byte | 500 | {'OK' if u <= 500 else 'LEWAT'} |")
    b.append("")
    b.append(f"**Sumber:** {', '.join(warta.get('sumber', [])) or '-'}")
    b.append("")
    b.append(f"_Dibuat: {datetime.now().isoformat(timespec='seconds')}_")
    b.append("")

    target.write_text("\n".join(b), encoding="utf-8")
    return target


def simpan_web(warta: dict, out_dir: Path, paksa: bool = False) -> Path | None:
    """Salin Warta ke folder web sebagai warta.json.

    Dilengkapi data grafik dari harga penutupan, supaya website bisa
    menggambar grafik tanpa perlu memanggil API lagi.

    Hanya menulis bila `out_dir` memang folder keluaran resmi. Ini mencegah
    test (yang memakai folder sementara) menimpa data web yang sebenarnya.
    """
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if not web_dir.exists():
        return None

    # Jangan menulis kalau ini bukan folder keluaran resmi, kecuali dipaksa.
    if not paksa:
        try:
            out_dir = Path(out_dir).resolve()
            resmi = (ROOT / "output").resolve()
            if out_dir != resmi:
                return None
        except OSError:
            return None

    salinan = dict(warta)

    # Pastikan jumlah_berita ada untuk statistik di web.
    if "jumlah_berita" not in salinan:
        salinan["jumlah_berita"] = len(salinan.get("bagian", {}).get("HEADLINE UTAMA", []))

    # Susun data grafik dari bagian sorotan (harga penutupan).
    sorotan = warta.get("bagian", {}).get("SOROTAN EMITEN (data 2 Oktober 2026)") \
        or next((v for k, v in warta.get("bagian", {}).items()
                 if k.startswith("SOROTAN EMITEN")), [])
    titik = []
    for e in sorotan:
        m = re.search(r"Rp([\d.,]+)", e.get("narasi", ""))
        if not m:
            continue
        angka = float(m.group(1).replace(".", "").replace(",", "."))
        titik.append({"label": e.get("emiten", ""), "nilai": angka})

    if titik:
        # Titik-titik ini saham BERBEDA, jadi grafik garis dan persentase
        # perubahan akan menyesatkan. Yang jujur: perbandingan batang.
        salinan["grafik"] = {
            "jenis": "batang",
            "judul": "Harga penutupan emiten sorotan",
            "titik": titik,
            "catatan": "Perbandingan harga penutupan antar emiten berbeda, "
                       "bukan perubahan harga satu saham.",
        }

    target = web_dir / "warta.json"
    target.write_text(json.dumps(salinan, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def simpan_agenda(agenda: dict, out_dir: Path) -> Path | None:
    """Simpan agenda ke depan untuk halaman Kalender di web.

    Halaman Kalender bukan arsip: isinya jadwal yang BELUM terjadi
    (aksi korporasi, RUPS). Karena itu berkasnya terpisah dari warta.json
    dan selalu ditimpa dengan rentang terbaru.
    """
    web_dir = ROOT / "web"
    if not web_dir.exists():
        return None

    if not agenda:
        return None

    salinan = dict(agenda)
    salinan["_diperbarui"] = datetime.now().isoformat(timespec="seconds")

    target = web_dir / "agenda.json"
    target.write_text(
        json.dumps(salinan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def simpan_arsip(out_dir: Path) -> Path | None:
    """Kumpulkan ringkasan semua edisi untuk halaman Arsip.

    Tanpa ini, halaman Arsip di web tidak punya apa pun untuk ditampilkan.
    """
    web_dir = ROOT / "web"
    if not web_dir.exists():
        return None

    daftar = []
    for f in sorted(Path(out_dir).glob("warta-*.json")):
        try:
            w = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bagian = w.get("bagian", {}) or {}
        daftar.append({
            "tanggal": w.get("tanggal", ""),
            "judul": w.get("judul", ""),
            "ringkasan": (w.get("ringkasan") or "")[:300],
            "jumlah_bagian": sum(1 for v in bagian.values() if v),
            "jumlah_entri": sum(len(v) for v in bagian.values()),
            "sumber": w.get("sumber", []),
        })

    if not daftar:
        return None

    udah = {d["tanggal"]: d for d in daftar}
    target = web_dir / "arsip.json"
    target.write_text(
        json.dumps([udah[k] for k in sorted(udah)], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def simpan_semua(warta: dict, out_dir: Path) -> dict:
    hasil = {
        "json": simpan_json(warta, out_dir),
        "teks": simpan_teks(warta, out_dir),
        "markdown": simpan_markdown(warta, out_dir),
    }
    web = simpan_web(warta, out_dir)
    if web:
        hasil["web"] = web
        arsip = simpan_arsip(out_dir)
        if arsip:
            hasil["arsip"] = arsip
    return hasil
