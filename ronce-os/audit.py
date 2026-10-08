"""Audit keamanan Ronce — pastikan tidak ada rahasia yang bocor.

Jalankan sebelum commit atau push ke GitHub:

    python audit.py

Memeriksa:
1. File .env tidak akan ikut ter-commit
2. Tidak ada nilai rahasia di dalam kode
3. Tidak ada nilai rahasia di file hasil
4. Tidak ada file yang tidak seharusnya ada

Keluar dengan kode 1 kalau menemukan masalah.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Berkas yang memang berisi rahasia dan tidak boleh masuk repo.
RAHASIA = {".env", ".env.local", ".env.production"}

# Berkas yang memuat pola pencarian itu sendiri, jangan diperiksa.
LEWATI_FILE = {"audit.py"}

# Folder yang tidak ikut diperiksa isinya.
LEWATI = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

# Pola nilai rahasia yang mungkin bocor.
POLA_RAHASIA = [
    (r"sk-[a-zA-Z0-9]{16,}", "OpenAI-style key"),
    (r"sk-ant-[a-zA-Z0-9\-]{20,}", "Anthropic key"),
    (r"ghp_[a-zA-Z0-9]{20,}", "GitHub token"),
    (r"gho_[a-zA-Z0-9]{20,}", "GitHub OAuth token"),
    (r"eyJ[a-zA-Z0-9_\-]{30,}\.[a-zA-Z0-9_\-]{30,}\.[a-zA-Z0-9_\-]{10,}", "JWT token"),
    (r"Bearer\s+[a-zA-Z0-9_\-\.]{25,}", "Bearer token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    # Kunci asli selalu di awal baris; pola di dokumentasi biasanya di dalam tanda kurung.
    (r"^-----BEGIN [A-Z ]*PRIVATE KEY-----$", "private key"),
    (r"postgres://[^:]+:[^@]+@", "connection string dengan password"),
    (r"mysql://[^:]+:[^@]+@", "connection string dengan password"),
    (r"mongodb(\+srv)?://[^:]+:[^@]+@", "connection string dengan password"),
]

# Ekstensi yang perlu diperiksa isi teksnya.
TEKS = {".py", ".md", ".txt", ".json", ".sh", ".example", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".env"}

hijau, merah, kuning = "\033[92m", "\033[91m", "\033[93m", 
normal = "\033[0m"


def lewati(path: Path) -> bool:
    return any(bagian in LEWATI for bagian in path.parts)


def periksa_gitignore() -> list[str]:
    """Pastikan .env dilindungi .gitignore."""
    masalah = []
    gi = ROOT / ".gitignore"
    if not gi.exists():
        masalah.append(".gitignore tidak ada — .env bisa ikut ter-commit")
        return masalah
    isi = gi.read_text(encoding="utf-8")
    baris = [b.strip() for b in isi.splitlines() if b.strip() and not b.startswith("#")]
    if ".env" not in baris:
        masalah.append(".gitignore tidak memuat '.env'")
    if "output/" not in baris and "output" not in baris:
        masalah.append(".gitignore tidak memuat 'output/'")
    if "archive/" not in baris and "archive" not in baris:
        masalah.append(".gitignore tidak memuat 'archive/'")
    return masalah


def periksa_isi(path: Path) -> list[tuple[str, int, str]]:
    """Cari pola rahasia di dalam sebuah file. Mengembalikan (pola, baris, cuplikan)."""
    temuan = []
    try:
        isi = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return temuan
    for nomor, baris in enumerate(isi.splitlines(), 1):
        for pola, nama in POLA_RAHASIA:
            if re.search(pola, baris):
                # jangan laporkan baris yang jelas cuma contoh/dokumentasi
                if any(k in baris.lower() for k in ("contoh", "example", "xxx", "key-kamu",
                                                     "nama-model", "provider.com", "api.provider")):
                    continue
                cuplik = baris.strip()[:70]
                temuan.append((nama, nomor, cuplik))
    return temuan


def main() -> int:
    print("=" * 62)
    print(" AUDIT KEAMANAN RONCE")
    print("=" * 62)
    print()

    semua_masalah = []

    # --- 1. Berkas rahasia ---
    print("[1/4] Berkas rahasia...")
    for nama in RAHASIA:
        f = ROOT / nama
        if f.exists():
            print(f"  {kuning}!{normal} {nama} ada (normal untuk lokal, "
                  f"pasti tidak ikut commit)")
        else:
            print(f"  - {nama} tidak ada")

    masalah_gi = periksa_gitignore()
    if masalah_gi:
        for m in masalah_gi:
            print(f"  {merah}GAGAL{normal} {m}")
            semua_masalah.append(m)
    else:
        print(f"  {hijau}OK{normal} .gitignore melindungi .env, output/, archive/")
    print()

    # --- 2. Nilai rahasia di kode ---
    print("[2/4] Nilai rahasia di dalam kode...")
    diperiksa = 0
    ditemukan_kode = 0
    for f in ROOT.rglob("*"):
        if not f.is_file() or lewati(f):
            continue
        if f.name in RAHASIA or f.name in LEWATI_FILE:
            continue
        if f.suffix not in TEKS:
            continue
        diperiksa += 1
        for nama, nomor, cuplik in periksa_isi(f):
            print(f"  {merah}BAHAYA{normal} {f.relative_to(ROOT)}:{nomor} "
                  f"— {nama}: {cuplik}")
            ditemukan_kode += 1
            semua_masalah.append(f"rahasia di {f.relative_to(ROOT)}:{nomor}")
    if not ditemukan_kode:
        print(f"  {hijau}OK{normal} bersih ({diperiksa} file diperiksa)")
    print()

    # --- 3. Nilai rahasia di output ---
    print("[3/4] Nilai rahasia di folder hasil...")
    out = ROOT / "output"
    if not out.exists():
        print("  - folder output belum ada")
    else:
        ditemukan_out = 0
        for f in out.rglob("*"):
            if not f.is_file() or lewati(f):
                continue
            for nama, nomor, cuplik in periksa_isi(f):
                print(f"  {merah}BAHAYA{normal} {f.name}:{nomor} — {nama}")
                ditemukan_out += 1
                semua_masalah.append(f"rahasia di output/{f.name}:{nomor}")
        if not ditemukan_out:
            jumlah = len(list(out.rglob("*")))
            print(f"  {hijau}OK{normal} bersih ({jumlah} item diperiksa)")
    print()

    # --- 4. File yang tidak seharusnya ada ---
    print("[4/4] File yang tidak seharusnya ada...")
    aneh = []
    for f in ROOT.rglob("*"):
        if not f.is_file() or lewati(f):
            continue
        nama = f.name.lower()
        if nama.endswith((".key", ".pem", ".p12", ".pfx")):
            aneh.append(f.relative_to(ROOT))
        if nama in ("credentials.json", "secrets.json", "service-account.json"):
            aneh.append(f.relative_to(ROOT))
        if f.suffix == ".json" and f.parent == ROOT:
            aneh.append(f.relative_to(ROOT))
    if aneh:
        for a in aneh:
            print(f"  {kuning}!{normal} {a} ada di folder utama "
                  f"(sebaiknya di dalam folder)")
    else:
        print(f"  {hijau}OK{normal} tidak ada berkas mencurigakan")
    print()

    # --- Ringkasan ---
    print("=" * 62)
    if semua_masalah:
        print(f" {merah}ADA {len(semua_masalah)} MASALAH{normal}")
        print("=" * 62)
        for m in semua_masalah:
            print(f"  - {m}")
        print()
        print(" Jangan push sebelum masalah ini diperbaiki.")
        return 1
    print(f" {hijau}SEMUA AMAN — siap di-commit{normal}")
    print("=" * 62)
    print()
    print(" Catatan: audit ini memeriksa pola umum. Selalu periksa sendiri")
    print(" hasil 'git diff' sebelum push.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
