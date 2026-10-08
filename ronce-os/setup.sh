#!/usr/bin/env bash
# Pemasang Ronce — jalankan sekali, langsung siap pakai.
#
# Cara pakai:
#   bash setup.sh
#
set -e

echo "=================================================="
echo " PEMASANG RONCE"
echo "=================================================="
echo

# --- 1. Cek Python ---
echo "[1/4] Memeriksa Python..."
if ! command -v python >/dev/null 2>&1; then
  echo "  GAGAL: Python belum terpasang."
  echo "  Pasang Python 3.10 atau lebih baru dari https://python.org"
  exit 1
fi
VERSI=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $VERSI ditemukan"

python - <<'PY' || { echo "  GAGAL: butuh Python 3.10 atau lebih baru"; exit 1; }
import sys
if sys.version_info < (3, 10):
    raise SystemExit(1)
PY

# --- 2. Buat .env kalau belum ada ---
echo
echo "[2/4] Menyiapkan file konfigurasi..."
if [ -f .env ]; then
  echo "  .env sudah ada, tidak diubah"
else
  cp env.contoh .env
  echo "  .env dibuat dari env.contoh"
  echo "  >> BUKA .env dan isi SECTORS_API_KEY"
fi

# --- 3. Buat folder yang dibutuhkan ---
echo
echo "[3/4] Menyiapkan folder..."
mkdir -p output archive docs
echo "  output/  : hasil Warta"
echo "  archive/ : data untuk mode offline"

# --- 4. Uji jalan ---
echo
echo "[4/4] Menguji sistem..."
if python ronce.py cek; then
  echo
  echo "=================================================="
  echo " SIAP DIPAKAI"
  echo "=================================================="
  echo
  echo " Langkah berikutnya:"
  echo "   1. Buka .env, isi SECTORS_API_KEY"
  echo "   2. (Opsional) isi RONCE_AI_BASE_URL, RONCE_AI_API_KEY, RONCE_AI_MODEL"
  echo "   3. Jalankan: python ronce.py make"
  echo
else
  echo
  echo " Pemasangan selesai, tapi ada yang perlu diperbaiki."
  echo " Baca pesan di atas, lalu jalankan lagi: python ronce.py cek"
  echo
fi
