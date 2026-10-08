"""Ronce — Warta pasar harian dari data Sectors.

Satu perintah untuk membuat Warta lengkap.

Contoh pakai:
    python ronce.py make                    # hari ini
    python ronce.py make --tanggal 2026-10-05
    python ronce.py make --offline           # pakai arsip lokal
    python ronce.py cek                      # cek konfigurasi
    python ronce.py contoh                   # lihat contoh hasil
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import config                                    # noqa: E402
from core import compose, render, rewrite, sectors           # noqa: E402

WIB = ZoneInfo("Asia/Jakarta")


# ------------------------------------------------------------------ perintah

def cmd_cek(_args) -> int:
    """Cek konfigurasi dan koneksi."""
    print("=== KONFIGURASI RONCE ===\n")
    for k, v in config.ringkas().items():
        print(f"  {k:14s}: {v}")

    print("\n=== CEK KONEKSI ===\n")

    # Sectors
    if config.punya_sectors() and not config.offline:
        try:
            sectors.panggil(config.sectors_base, "companies/?limit=1", config.sectors_key)
            print("  Sectors       : OK (bisa diakses)")
        except sectors.SectorsError as exc:
            print(f"  Sectors       : GAGAL — {exc}")
    else:
        print("  Sectors       : dilewati (offline atau key belum diset)")

    # AI
    if config.punya_ai():
        try:
            rewrite._panggil_ai(config.ai_base, config.ai_key, config.ai_model,
                                "Balas dengan kata: siap", timeout=30)
            print(f"  AI ({config.ai_model}) : OK (bisa diakses)")
        except Exception as exc:                              # noqa: BLE001
            print(f"  AI            : GAGAL — {type(exc).__name__}: {exc}")
    else:
        print("  AI            : belum diset (Warta tetap bisa dibuat, "
              "tapi bahasa tidak ditulis ulang AI)")

    # Arsip
    arsip = sorted(config.archive_dir.glob("data-*.json")) if config.archive_dir.exists() else []
    print(f"  Arsip offline : {len(arsip)} file di {config.archive_dir}")

    print()
    return 0


def cmd_make(args) -> int:
    """Buat Warta."""
    tanggal = (datetime.fromisoformat(args.tanggal).replace(tzinfo=WIB)
               if args.tanggal else datetime.now(WIB))

    offline = args.offline or config.offline

    print(f"=== MEMBUAT WARTA {tanggal.date().isoformat()} ===\n")

    # 1. Ambil data
    print("[1/4] Mengambil data Sectors...")
    try:
        data = sectors.tarik_semua(
            config.sectors_base, config.sectors_key, tanggal,
            arsip_dir=config.archive_dir, offline=offline)
    except sectors.SectorsError as exc:
        print(f"  GAGAL: {exc}")
        return 1
    print(f"  sumber data: {data.get('_sumber')}")
    if data.get("_gagal"):
        for g in data["_gagal"]:
            print(f"  peringatan: {g}")

    # 2. Pilih headline
    print("\n[2/4] Memilih berita utama...")
    pilihan = compose.pilih_headline(data, maks=args.headline)
    print(f"  {len(pilihan)} berita dipilih")

    # 3. Tulis ulang
    print("\n[3/4] Menulis ulang bahasa...")
    if config.punya_ai() and not args.tanpa_ai:
        print(f"  memakai AI: {config.ai_model}")
    else:
        print("  memakai penulisan sederhana (AI tidak diset atau dimatikan)")
    ditulis = rewrite.tulis_ulang_banyak(
        pilihan,
        base_url=config.ai_base if not args.tanpa_ai else "",
        key=config.ai_key if not args.tanpa_ai else "",
        model=config.ai_model if not args.tanpa_ai else "",
        timeout=config.ai_timeout,
    )

    # 4. Harga + agenda + susun
    print("\n[4/4] Menyusun Warta...")
    simbol: list[str] = []
    for d in ditulis:
        for s in (d.get("emiten") or "").split(","):
            s = s.strip()
            if s and s not in simbol:
                simbol.append(s)
    harga = sectors.tarik_harga(config.sectors_base, config.sectors_key,
                                simbol[:6], tanggal, offline=offline)

    # Agenda ke depan untuk halaman Kalender. Ini bukan bagian dari
    # narasi Warta harian, jadi kegagalannya tidak menghentikan proses.
    agenda = sectors.tarik_agenda(config.sectors_base, config.sectors_key,
                                  tanggal, offline=offline)
    if agenda:
        jumlah_agenda = sum(len(v["agenda"]) for k, v in agenda.items()
                            if isinstance(v, dict))
        print(f"  agenda ke depan: {jumlah_agenda} jadwal")

    warta = compose.susun(data, ditulis, harga, tanggal,
                          batas_byte=config.threads_max_bytes)

    hasil = render.simpan_semua(warta, config.out_dir)
    if agenda:
        render.simpan_agenda(agenda, config.out_dir)

    print(f"\n=== SELESAI ===")
    print(f"  judul : {warta['judul']}")
    print(f"  post  : {warta['jumlah_post']}")
    print(f"  sumber: {', '.join(warta['sumber']) or '-'}")
    for nama, isi in warta["bagian"].items():
        print(f"    {nama:26s}: {len(isi)} entri")
    print(f"\n  hasil:")
    for jenis, path in hasil.items():
        print(f"    {jenis:9s}: {path}")

    # peringatan kalau ada post lewat batas
    lewat = [i for i, p in enumerate(warta["posts"], 1)
             if len(p.encode("utf-8")) > config.threads_max_bytes]
    if lewat:
        print(f"\n  PERINGATAN: post {lewat} melewati batas {config.threads_max_bytes} byte")
    return 0


def cmd_contoh(args) -> int:
    """Tampilkan contoh hasil Warta."""
    kandidat = sorted(config.out_dir.glob("warta-*.json"))
    if not kandidat:
        print("Belum ada hasil. Jalankan: python ronce.py make")
        return 1
    import json
    warta = json.loads(kandidat[-1].read_text(encoding="utf-8"))
    print(f"{warta['judul']}\n")
    print(warta["ringkasan"])
    print()
    for i, p in enumerate(warta["posts"], 1):
        print("=" * 60)
        print(f"POST {i} ({len(p.encode('utf-8'))} byte)")
        print("=" * 60)
        print(p)
        print()
    return 0


# ------------------------------------------------------------------ utama

def cmd_web(args) -> int:
    """Salin edisi terbaru ke website."""
    import json as _json

    kandidat = []
    for f in sorted(config.out_dir.glob("warta-*.json")):
        try:
            w = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        if args.tanggal and w.get("tanggal") != args.tanggal:
            continue
        kandidat.append((w.get("tanggal", ""), len(w.get("bagian", {})), f, w))

    if not kandidat:
        print("Belum ada Warta. Jalankan: python ronce.py make")
        return 1

    kandidat.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, f, w = kandidat[0]

    web = render.simpan_web(w, config.out_dir)
    if not web:
        print("Folder web/ tidak ditemukan.")
        return 1

    # Arsip ikut diperbarui supaya halaman Arsip punya data.
    arsip = render.simpan_arsip(config.out_dir)

    # Baca ulang berkas web supaya jumlah grafik yang dilaporkan benar.
    try:
        tersimpan = _json.loads(web.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        tersimpan = w

    print("Website diperbarui:")
    print(f"  edisi  : {tersimpan['judul']}")
    print(f"  bagian : {len(tersimpan['bagian'])}")
    print(f"  grafik : {len(tersimpan.get('grafik', {}).get('titik', []))} batang")
    if arsip:
        try:
            n = len(_json.loads(arsip.read_text(encoding="utf-8")))
            print(f"  arsip  : {n} edisi tersimpan")
        except (OSError, _json.JSONDecodeError):
            pass
    print(f"  berkas : {web}")
    print()
    print("  Buka: python start.py  lalu  http://127.0.0.1:4173")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ronce — Warta pasar harian dari data Sectors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="perintah", required=True)

    p_make = sub.add_parser("make", help="buat Warta")
    p_make.add_argument("--tanggal", help="YYYY-MM-DD (bawaan: hari ini WIB)")
    p_make.add_argument("--offline", action="store_true", help="pakai arsip lokal")
    p_make.add_argument("--tanpa-ai", action="store_true", help="jangan pakai AI")
    p_make.add_argument("--headline", type=int, default=3, help="jumlah headline (bawaan 3)")
    p_make.set_defaults(fn=cmd_make)

    p_cek = sub.add_parser("cek", help="cek konfigurasi dan koneksi")
    p_cek.set_defaults(fn=cmd_cek)

    p_contoh = sub.add_parser("contoh", help="tampilkan hasil terakhir")
    p_contoh.set_defaults(fn=cmd_contoh)

    p_web = sub.add_parser("web", help="salin edisi terbaru ke website")
    p_web.add_argument("--tanggal", help="YYYY-MM-DD (bawaan: edisi terbaru)")
    p_web.set_defaults(fn=cmd_web)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
