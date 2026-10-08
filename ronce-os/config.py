"""Konfigurasi Ronce.

Semua pengaturan dibaca dari file .env atau environment.
Tidak ada kredensial yang ditulis ke kode atau output.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def _baca_env() -> None:
    """Baca .env kalau ada. Tidak menimpa environment yang sudah diset."""
    if not ENV_FILE.exists():
        return
    for baris in ENV_FILE.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, _, nilai = baris.partition("=")
        kunci = kunci.strip()
        nilai = nilai.strip().strip('"').strip("'")
        if kunci and kunci not in os.environ:
            os.environ[kunci] = nilai


_baca_env()


def _env(kunci: str, bawaan: str = "") -> str:
    return os.environ.get(kunci, bawaan).strip()


def _env_bool(kunci: str, bawaan: bool = False) -> bool:
    nilai = os.environ.get(kunci)
    if nilai is None:
        return bawaan
    return nilai.strip().lower() in ("1", "true", "ya", "yes", "on")


@dataclass
class Config:
    # --- Sectors (sumber data) ---
    sectors_key: str = field(default_factory=lambda: _env("SECTORS_API_KEY"))
    sectors_base: str = field(default_factory=lambda: _env("SECTORS_BASE", "https://api.sectors.app/v2/"))

    # --- AI (untuk tulis ulang bahasa) ---
    # Format OpenAI-compatible: bisa dipakai provider apa saja.
    ai_base: str = field(default_factory=lambda: _env("RONCE_AI_BASE_URL"))
    ai_key: str = field(default_factory=lambda: _env("RONCE_AI_API_KEY"))
    ai_model: str = field(default_factory=lambda: _env("RONCE_AI_MODEL", "gpt-4o-mini"))
    ai_timeout: int = field(default_factory=lambda: int(_env("RONCE_AI_TIMEOUT", "90") or 90))

    # --- Perilaku ---
    offline: bool = field(default_factory=lambda: _env_bool("RONCE_OFFLINE", False))
    out_dir: Path = field(default_factory=lambda: Path(_env("RONCE_OUT_DIR", str(ROOT / "output"))))
    archive_dir: Path = field(default_factory=lambda: Path(_env("RONCE_ARCHIVE_DIR", str(ROOT / "archive"))))

    # --- Batas platform ---
    threads_max_bytes: int = 500
    maks_post: int = 8

    def punya_sectors(self) -> bool:
        return bool(self.sectors_key)

    def punya_ai(self) -> bool:
        return bool(self.ai_base and self.ai_key and self.ai_model)

    def ringkas(self) -> dict:
        """Ringkasan aman untuk ditampilkan (tanpa nilai rahasia)."""
        return {
            "sectors_key": "ADA" if self.sectors_key else "belum diset",
            "ai_base_url": self.ai_base or "belum diset",
            "ai_model": self.ai_model or "belum diset",
            "ai_key": "ADA" if self.ai_key else "belum diset",
            "mode": "offline" if self.offline else "online",
        }


config = Config()
