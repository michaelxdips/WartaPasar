"""Ambil data dari API Sectors.

Penting: API Sectors menolak request tanpa User-Agent browser
(Cloudflare membalas HTTP 403 dengan kode 1010).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")

# Cloudflare menolak request tanpa User-Agent browser.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class SectorsError(RuntimeError):
    pass


def panggil(base: str, path: str, key: str, timeout: int = 45):
    """Satu panggilan ke Sectors. Mengembalikan JSON."""
    if not key:
        raise SectorsError("SECTORS_API_KEY belum diset")
    url = base.rstrip("/") + "/" + path.lstrip("/")
    req = urllib.request.Request(url, headers={
        "Authorization": key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SectorsError(
                "HTTP 403 — kemungkinan User-Agent tidak dikirim, atau key tidak aktif"
            ) from exc
        raise SectorsError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SectorsError(f"tidak bisa menghubungi Sectors: {exc.reason}") from exc


def tarik_semua(base: str, key: str, tanggal: datetime | None = None,
                arsip_dir: Path | None = None, offline: bool = False) -> dict:
    """Tarik semua data untuk jendela 24 jam.

    Kalau offline=True atau key kosong, pakai arsip lokal.
    """
    tanggal = tanggal or datetime.now(WIB)
    akhir = tanggal.date().isoformat()
    awal = (tanggal - timedelta(hours=24)).date().isoformat()

    if offline or not key:
        return dari_arsip(arsip_dir, akhir)

    data: dict = {"tanggal": akhir, "jendela": [awal, akhir], "_sumber": "api"}
    gagal: list[str] = []

    def aman(nama, path):
        try:
            data[nama] = panggil(base, path, key)
        except SectorsError as exc:
            data[nama] = None
            gagal.append(f"{nama}: {exc}")

    aman("berita", f"news/?extension=idx&start={awal}&end={akhir}&limit=100")
    aman("filings", "filings/?limit=100")
    aman("corp_actions", f"corporate-actions/?start={awal}&end={akhir}")

    if gagal:
        data["_gagal"] = gagal

    # Simpan ke arsip supaya bisa dipakai offline lain kali.
    if arsip_dir and not gagal:
        arsip_dir.mkdir(parents=True, exist_ok=True)
        target = arsip_dir / f"data-{akhir}.json"
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        data["_arsip"] = str(target)

    return data


def tarik_agenda(base: str, key: str, tanggal: datetime | None = None,
                 hari_ke_depan: int = 120, offline: bool = False,
                 timeout: int = 45) -> dict:
    """Agenda ke depan dari Sectors: aksi korporasi dan RUPS.

    Bentuk respons API (terverifikasi): objek dengan kunci `start`, `end`,
    lalu satu kunci per JENIS agenda, masing-masing berisi daftar item:

        {"start": "...", "end": "...",
         "dividend": [...], "upcoming_dividend": [...], "stock_split": [...],
         "bonus": [...], "right_issue": [...], "warrant": [...], "agm": [...]}

    Nama field tanggal berbeda per jenis (dividend pakai `ex_date`,
    right_issue pakai `ex_date` + `recording_date`, agm pakai
    `meeting_date`). Karena itu tiap field dikumpulkan terpisah dan
    labelnya disimpan, bukan diseragamkan.

    Tidak ada field yang dikarang: kalau tidak ada di respons,
    tidak muncul di keluaran.
    """
    if offline or not key:
        return {}

    mulai = (tanggal or datetime.now(WIB)).date()
    sampai = mulai + timedelta(days=hari_ke_depan)

    try:
        data = panggil(
            base,
            f"corporate-actions/?start={mulai.isoformat()}&end={sampai.isoformat()}",
            key, timeout,
        )
    except SectorsError:
        return {}

    if not isinstance(data, dict):
        return {}

    # Label yang enak dibaca untuk tiap jenis agenda.
    NAMA_JENIS = {
        "dividend": "Dividen",
        "upcoming_dividend": "Dividen (akan datang)",
        "stock_split": "Pemecahan saham",
        "bonus": "Saham bonus",
        "right_issue": "Rights issue",
        "warrant": "Waran",
        "agm": "RUPS",
    }

    # Label untuk nama field tanggal yang dipakai API.
    NAMA_TANGGAL = {
        "announcement_date": "pengumuman",
        "ex_date": "ex",
        "cum_date": "cum",
        "record_date": "record",
        "recording_date": "pencatatan",
        "payment_date": "pembayaran",
        "meeting_date": "rapat",
        "trading_period_start": "mulai perdagangan",
        "trading_period_end": "akhir perdagangan",
        "subscription_date": "penebusan",
    }

    # Field yang bukan tanggal dan bukan angka; dipakai sebagai keterangan.
    FIELD_TEKS = ("title", "name", "description", "notes", "venue", "place",
                  "city", "time", "agenda", "type")

    hasil: dict = {}
    for jenis, isi in data.items():
        if jenis in ("start", "end") or not isinstance(isi, list) or not isi:
            continue

        daftar = []
        for b in isi:
            if not isinstance(b, dict):
                continue

            tanggal_penting = []
            keterangan = []
            for kunci, nilai in b.items():
                if nilai in (None, "", []):
                    continue
                if kunci in NAMA_TANGGAL:
                    tanggal_penting.append({
                        "tanggal": str(nilai)[:10],
                        "label": NAMA_TANGGAL[kunci],
                    })
                elif kunci in FIELD_TEKS:
                    keterangan.append(str(nilai).strip())
                elif kunci.endswith("_date") and isinstance(nilai, str):
                    # Tanggal lain yang belum terpetakan — tetap disimpan.
                    tanggal_penting.append({
                        "tanggal": str(nilai)[:10],
                        "label": kunci.replace("_date", "").replace("_", " "),
                    })

            if not tanggal_penting:
                continue

            daftar.append({
                "simbol": str(b.get("symbol") or "").strip(),
                "tanggal": sorted(tanggal_penting, key=lambda x: x["tanggal"]),
                "keterangan": " · ".join(k for k in keterangan if k),
                "angka": {
                    k: v for k, v in b.items()
                    if isinstance(v, (int, float)) and k not in ("id",)
                },
            })

        if daftar:
            daftar.sort(key=lambda x: x["tanggal"][0]["tanggal"])
            hasil[jenis] = {
                "nama": NAMA_JENIS.get(jenis, jenis.replace("_", " ").title()),
                "agenda": daftar,
            }

    # Sebutkan rentang yang benar-benar dicakup, supaya UI bisa jujur.
    if hasil:
        hasil["_rentang"] = str(data.get("start") or mulai.isoformat())[:10], \
                            str(data.get("end") or sampai.isoformat())[:10]

    return hasil


def dari_arsip(arsip_dir: Path | None, tanggal: str) -> dict:
    """Baca data dari arsip lokal."""
    if not arsip_dir or not arsip_dir.exists():
        raise SectorsError(
            "mode offline tapi tidak ada arsip. Jalankan sekali dengan online "
            "supaya arsip terbentuk, atau taruh file arsip di folder archive/."
        )
    kandidat = sorted(arsip_dir.glob("data-*.json"))
    if not kandidat:
        raise SectorsError(f"tidak ada file arsip di {arsip_dir}")
    # pakai yang paling baru
    terbaru = kandidat[-1]
    data = json.loads(terbaru.read_text(encoding="utf-8"))
    data["_sumber"] = "arsip"
    data["_arsip"] = str(terbaru)
    return data


def tarik_harga(base: str, key: str, simbol: list[str], tanggal: datetime,
                offline: bool = False, timeout: int = 30) -> dict:
    """Harga penutupan + perubahan. Mengembalikan data terakhir yang ada."""
    if offline or not key:
        return {}
    akhir = tanggal.date().isoformat()
    awal = (tanggal - timedelta(days=10)).date().isoformat()
    hasil: dict = {}
    for sym in simbol:
        try:
            seri = panggil(base, f"daily/{sym}/?start={awal}&end={akhir}", key, timeout)
        except SectorsError:
            continue
        if not isinstance(seri, list) or not seri:
            continue
        terakhir = seri[-1]
        ubah = None
        if len(seri) >= 2 and seri[-2].get("close"):
            dasar = seri[-2]["close"]
            if dasar:
                ubah = (terakhir["close"] - dasar) / dasar * 100
        hasil[sym] = {"close": terakhir["close"], "tanggal": terakhir["date"],
                      "ubah_persen": ubah}
    return hasil
