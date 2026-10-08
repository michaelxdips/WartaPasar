"""Nyalakan semua yang dibutuhkan Ronce — satu perintah.

    python start.py

Menjalankan:
1. Website Ronce (halaman penuh: Orbit, Warta, Emiten, Kalender, dll)
2. Menampilkan alamat yang harus dibuka di browser

Tekan Ctrl+C untuk mematikan semuanya.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Folder website yang sudah dibuild.
KANDIDAT_WEB = [
    ROOT / "web",              # website Ronce (desain baru)
    Path("D:/ronce-audit/web/out"),
]

PORT_WEB = 4173


def cari_web() -> Path | None:
    for p in KANDIDAT_WEB:
        if p.exists() and (p / "index.html").exists():
            return p
    return None


def main() -> int:
    print("=" * 62)
    print(" RONCE — MENYALAKAN SISTEM")
    print("=" * 62)
    print()

    web = cari_web()
    if not web:
        print("  Website tidak ditemukan.")
        print("  Dicari di:")
        for p in KANDIDAT_WEB:
            print(f"    - {p}")
        print()
        print("  Jalankan dulu: cd AUDIT-CEK/web && npm run build")
        return 1

    print(f"  Website : {web}")
    print(f"  Alamat  : http://127.0.0.1:{PORT_WEB}")
    print()
    print("  Buka alamat itu di browser.")
    print("  Halaman yang tersedia:")
    print("    /           Orbit (beranda)")
    print("    /warta/     Daftar Warta")
    print("    /emiten/    Daftar emiten")
    print("    /ronce/     Daftar klaim")
    print("    /jelajah/   Jelajah topik")
    print("    /kalender/  Kalender")
    print("    /cari/      Pencarian")
    print("    /arsip/     Kebijakan arsip")
    print()
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 62)
    print()

    # Nyalakan server website.
    proses = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT_WEB), "--bind", "127.0.0.1"],
        cwd=str(web),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Beri waktu server siap, lalu buka browser.
    time.sleep(1.5)
    threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT_WEB}")).start()

    try:
        proses.wait()
    except KeyboardInterrupt:
        print("\n  Mematikan server...")
        proses.terminate()
        try:
            proses.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proses.kill()
        print("  Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
