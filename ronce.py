"""Archive Sectors v2 news; replay into an auditable editorial draft.

No financial advice or social publishing; this tool never asserts
that separate publishers are independent or that article numbers are true.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
import re
import subprocess
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

JAKARTA = timezone(timedelta(hours=7))
TOPICS = {
# Bilingual (ID/EN) theme vocabulary; dict order = priority (first match wins).
# "dividen" vetoes headlines without a clear announce/pay verb; digest titles abstain.
    "dividen": r"\bdividen\b|\bdividend\b",
    "obligasi": r"\bobligasi\b|\bbonds?\b|\bsukuk\b|\bdebt\b",
    "suspensi": r"\bsuspensi\b|\bdisuspensi\b|\bsuspend(?:ed|s|ing)?\b|\bsuspension\b|\bdelist(?:ed|ing)?\b|\bspecial monitoring\b",
    "laporan keuangan": r"\blaporan keuangan\b|\blaba\b|\brugi\b|\bpendapatan\b|\bnet profit\b|\bnet loss\b|\bearnings\b|\brevenue\b|\bprofit\b(?![\s-]taking)|\bloss(?:es)?\b|\bfinancial (?:report|statement)s?\b",
    "suku bunga": r"\bsuku bunga\b|\bbi rate\b|\binterest rate\b|\brate (?:cut|hike|decision|hold)\b|\bholds? (?:the )?rate\b",
    "akuisisi": r"\bakuisisi\b|\bmengakuisisi\b|\bacquisition\b|\bacquires?\b|\bacquired\b|\btakeover\b|\btender offer\b|\bvoluntary tender\b|\bdivestiture\b|\bdivestment\b|\bdivests?\b|\bmerger\b|\bmerg(?:e|es|ed)\b|\bstake\b",
    "rights issue": r"\bright[s]? issue\b|\bhmetd\b",
    "buyback": r"\bbuyback\b|\bpembelian kembali saham\b|\brepurchase\b|\bbuy[\s-]?back\b",
    "ipo": r"\bipo\b|\bpenawaran umum perdana\b|\binitial public offering\b",
    "aliran asing": r"\bforeign investors?\b|\bforeign net\b|\bnet foreign\b",
    "gangguan operasi": r"\bforce majeure\b",
    "regulasi bursa": r"\bminimum (?:stock )?price\b|\bfloor price\b|\bprice[\s-]?floor\b",
}


def fetch_news(start, end, *, api_key, max_pages=100):
    """Archive complete IDX date-range pages; never infer article timezone."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("SECTORS_API_KEY wajib tersedia di lingkungan proses")
    if not isinstance(start, str) or not isinstance(end, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        raise ValueError("start/end harus YYYY-MM-DD")
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("start setelah end")
    except ValueError as exc:
        raise ValueError("rentang tanggal tidak valid") from exc
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_pages harus bilangan positif")
    pages, offset, total = [], 0, None
    for _ in range(max_pages):
        params = {"extension": "idx", "start": start, "end": end, "limit": 30, "offset": offset}
        request = Request("https://api.sectors.app/v2/news/?" + urlencode(params),
                          headers={"Authorization": api_key, "Accept": "application/json",
                                   "User-Agent": "Ronce-MVP/0.1"})
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.load(response)
                fetched_at = datetime.now(timezone.utc).isoformat()
        except HTTPError as exc:
            raise ValueError(f"Sectors HTTP {exc.code}; arsip tidak disimpan") from exc
        except (URLError, TimeoutError) as exc:
            raise ValueError("Sectors tidak dapat dihubungi; arsip tidak disimpan") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or not isinstance(payload.get("pagination"), dict):
            raise ValueError("respons news tidak memuat results/pagination")
        pg = payload["pagination"]
        if (type(pg.get("offset")) is not int or pg["offset"] != offset
                or type(pg.get("showing")) is not int or pg["showing"] != len(payload["results"])
                or len(payload["results"]) > 30 or type(pg.get("has_next")) is not bool
                or type(pg.get("total_count")) is not int or pg["total_count"] < 0
                or (total is not None and pg["total_count"] != total)):
            raise ValueError("pagination tidak konsisten; arsip tidak disimpan")
        total = pg["total_count"]
        more, next_offset = pg["has_next"], pg.get("next_offset")
        if ((more and (not payload["results"] or type(next_offset) is not int
                       or next_offset != offset + len(payload["results"])
                       or offset + len(payload["results"]) >= total))
                or (not more and (next_offset is not None or offset + len(payload["results"]) != total))):
            raise ValueError("pagination next_offset tidak konsisten; arsip tidak disimpan")
        pages.append({"fetched_at": fetched_at, "request": params, "response": payload})
        if not more:
            return pages
        offset = next_offset
    raise ValueError("batas max_pages tercapai sebelum halaman terakhir; arsip tidak disimpan")


def fetch_companion(symbol, start, end, out, *, api_key):
    """Capture three documented GET responses; no archive on partial failure."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("SECTORS_API_KEY wajib tersedia di lingkungan proses")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z]{4}(?:\.[Jj][Kk])?", symbol):
        raise ValueError("symbol IDX harus empat huruf, opsional .JK")
    try:
        if (not isinstance(start, str) or not isinstance(end, str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)
                or not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 90):
            raise ValueError("rentang foreign-flow wajib 0–90 hari")
    except ValueError as exc:
        raise ValueError("rentang foreign-flow wajib tanggal valid 0–90 hari") from exc
    target = Path(out)
    if target.exists():
        raise FileExistsError(f"arsip sudah ada: {target}")
    specs = [("top_changes", "companies/top-changes/", {"classifications": "top_gainers,top_losers", "periods": "1d,7d"}),
             ("foreign_flow", f"foreign-flow/{symbol.upper()}/", {"start": start, "end": end}),
             ("quarterly", f"financials/quarterly/{symbol.upper()}/", {"n_quarters": 1})]
    captured = []
    for kind, path, params in specs:
        request = Request("https://api.sectors.app/v2/" + path + "?" + urlencode(params),
                          headers={"Authorization": api_key, "Accept": "application/json", "User-Agent": "Ronce-MVP/0.1"})
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.load(response)
                fetched_at = datetime.now(timezone.utc).isoformat()
        except HTTPError as exc:
            raise ValueError(f"Sectors HTTP {exc.code}; arsip tidak disimpan") from exc
        except (URLError, TimeoutError) as exc:
            raise ValueError("Sectors tidak dapat dihubungi; arsip tidak disimpan") from exc
        if ((kind == "top_changes" and (not isinstance(payload, dict) or not any(
                isinstance(payload.get(k), dict) for k in ("top_gainers", "top_losers"))))
                or (kind == "foreign_flow" and (not isinstance(payload, dict) or not isinstance(payload.get("data"), list)))
                or (kind == "quarterly" and not isinstance(payload, list))):
            raise ValueError(f"respons {kind} tidak sesuai bentuk dokumentasi; arsip tidak disimpan")
        captured.append({"endpoint": kind, "request": params, "fetched_at": fetched_at, "response": payload})
    save_archive(target, captured)
    return captured

def save_archive(path, pages):
    """Do not expose partial archives on fetch/write failure."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".ronce-", suffix=".json", delete=False) as handle:
            name = handle.name
            json.dump(pages, handle, ensure_ascii=False, indent=2)
        try:
            os.link(name, target)  # Atomic, exclusive publish on same filesystem.
        except FileExistsError as exc:
            raise FileExistsError(f"arsip sudah ada: {target}") from exc
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _time(value, naive_timezone=None):
    """Reject ambiguous wall-clock time unless snapshot declares its offset."""
    if not isinstance(value, str):
        raise ValueError("timestamp harus teks ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"timestamp tidak valid: {value!r}") from exc
    if parsed.tzinfo is None:
        if naive_timezone is None or not re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", naive_timezone):
            raise ValueError("timestamp tanpa zona waktu butuh source_timezone eksplisit, contoh +07:00")
        sign = 1 if naive_timezone[0] == "+" else -1
        hours, minutes = map(int, naive_timezone[1:].split(":"))
        parsed = parsed.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    return parsed


def _publisher(url):
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host or parsed.scheme not in ("http", "https"):
        raise ValueError("source harus URL HTTP(S)")
    parts = host.lower().removeprefix("www.").split(".")
    # ponytail: common co.id only; use public-suffix list after seeing real source mix.
    if len(parts) > 2 and parts[-2:] == ["co", "id"]:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) > 1 else host.lower()


def _event(title):
    """Conservative rules: bilingual theme + action; unknown action abstains."""
    text = title.lower().replace("\u2011", "-").replace("\u2010", "-")
    if re.search(r"\broundup\b", text):
        return None  # Digest titles mix unrelated stories; never one event.
    for name, pattern in TOPICS.items():
        if not re.search(pattern, text):
            continue
        if name == "dividen":
            announced = bool(re.search(r"\bumumkan\b|\bdiumumkan\b|\bmengumumkan\b|\bannounce[ds]?\b|\brais(?:e|es|ed)\b|\bincreas(?:e|es|ed)\b|\bcut(?:s)?\b|\bdeclar(?:e|es|ed)\b", text))
            paid = bool(re.search(r"\bbayar\b|\bdibayar\b|\bpembayaran\b|\bmembayar\b|\bmembagikan\b|\bpaid\b|\bpayment\b|\bpays?\b", text))
            if announced == paid:
                return None
            return name, "pengumuman" if announced else "pembayaran"
        return name, "peristiwa belum dirinci"
    return None


def _ingest(pages, cutoff, since, interpretation=None):
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages harus daftar halaman tidak kosong")
    seen = set()
    rows = []
    expected_offset = 0
    total_seen = None
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or "fetched_at" not in page:
            raise ValueError("halaman harus memuat fetched_at")
        source_timezone = interpretation["source_timezone"] if interpretation else None
        fetched_at = _time(page["fetched_at"], source_timezone)
        if fetched_at > cutoff:
            raise ValueError("fetched_at setelah cutoff: replay tidak boleh melihat masa depan")
        response = page.get("response")
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise ValueError("response.results harus daftar")
        pagination = response.get("pagination")
        if (not isinstance(pagination, dict) or type(pagination.get("offset")) is not int
                or pagination["offset"] != expected_offset
                or type(pagination.get("showing")) is not int
                or pagination["showing"] != len(response["results"])):
            raise ValueError("pagination offset/showing tidak cocok")
        more = pagination.get("has_next")
        next_offset = pagination.get("next_offset")
        total = pagination.get("total_count")
        consumed = expected_offset + len(response["results"])
        if (type(more) is not bool or type(total) is not int or total < 0
                or (more and (index == len(pages) - 1 or not response["results"]
                              or type(next_offset) is not int
                              or next_offset != consumed or consumed >= total))
                or (not more and (index != len(pages) - 1 or next_offset is not None
                                  or consumed != total))):
            raise ValueError("pagination tidak lengkap atau urutan salah")
        if total_seen is None:
            total_seen = total
        elif total != total_seen:
            raise ValueError("pagination total_count antar-halaman tidak konsisten")
        expected_offset = next_offset if more else consumed
        for row in response["results"]:
            if not isinstance(row, dict) or not isinstance(row.get("title"), str) or not isinstance(row.get("source"), str):
                raise ValueError("artikel harus memuat title, source, timestamp")
            if row.get("body") is not None and not isinstance(row.get("body"), str):
                raise ValueError("body artikel harus teks")
            when = _time(row.get("timestamp"), source_timezone)
            url = row["source"]
            _publisher(url)
            if when < since or when > cutoff or when > fetched_at or url in seen:
                continue
            seen.add(url)
            rows.append((row, when))
    return rows


_AMOUNT = re.compile(
    r"(?<![\w.])(?:(?P<currency>US\$|USD|IDR|Rp)\s*)?"
    r"(?P<number>\d+(?:[.,\u202f ]\d+)*)\s*"
    r"(?P<unit>triliun|trillion|miliar|billion|juta|million|rupiah|persen|%|shares?|saham)?"
    r"(?!\w)", re.I)
_SCALE = {"juta": 1000000, "million": 1000000, "miliar": 1000000000,
          "billion": 1000000000, "triliun": 1000000000000, "trillion": 1000000000000}

def _headline_amounts(title):
    """Normalize comparable headline units; ambiguous number formats block review."""
    amounts, uncertain = {}, False
    for match in _AMOUNT.finditer(title):
        unit = (match['unit'] or '').lower()
        currency = (match['currency'] or '').lower()
        if not unit and not currency:
            continue
        raw = match['number'].replace('\u202f', '').replace(' ', '')
        if '.' in raw and ',' in raw:
            sep = '.' if raw.rfind('.') > raw.rfind(',') else ','
            raw = raw.replace(',' if sep == '.' else '.', '').replace(sep, '.')
        elif raw.count('.') + raw.count(',') == 1:
            sep = '.' if '.' in raw else ','
            if len(raw.split(sep)[1]) == 3:
                uncertain = True  # ponytail: 1.000 ambiguous; require editor or explicit locale metadata.
                continue
            raw = raw.replace(',', '.')
        elif '.' in raw or ',' in raw:
            sep = '.' if '.' in raw else ','
            parts = raw.split(sep)
            if not all(len(part) == 3 for part in parts[1:]):
                uncertain = True
                continue
            raw = ''.join(parts)
        value = Decimal(raw) * _SCALE.get(unit, 1)
        if unit in ('%', 'persen'):
            kind = 'percent'
        elif unit in ('share', 'shares', 'saham'):
            kind = 'shares'
        else:
            kind = 'money' if currency or unit == 'rupiah' else 'scaled'
        code = 'USD' if currency in ('us$', 'usd') else 'IDR' if currency in ('rp', 'idr') or unit == 'rupiah' else ''
        amounts.setdefault((kind, code), set()).add(value)
    return amounts, uncertain

def _candidates(rows):
    groups = {}
    for row, when in rows:
        event = _event(row["title"])
        if event is None:
            continue
        topic, action = event
        symbols = row.get("symbols") or []
        if not isinstance(symbols, list) or any(not isinstance(s, str) for s in symbols):
            raise ValueError("symbols harus daftar ticker")
        # Multi-ticker articles may enter several groups, never extra votes within one.
        for symbol in set(s.upper().removesuffix(".JK") for s in symbols) or {"PASAR"}:
            if not re.fullmatch(r"[A-Z]{4}|PASAR", symbol):
                continue
            key = (topic, action, symbol, when.astimezone(JAKARTA).date().isoformat())
            groups.setdefault(key, []).append(row)
    candidates = []
    for (topic, action, symbol, date), articles in sorted(groups.items()):
        bodies = {}
        for a in articles:
            body = re.sub(r"\s+", " ", (a.get("body") or a["title"]).strip()).casefold()
            bodies.setdefault(body, []).append(a)
        syndicated = any(len({ _publisher(a["source"]) for a in copies }) > 1
                         for copies in bodies.values() if copies)
        independent_articles = [a for copies in bodies.values() for a in copies[:1]]
        publishers = {_publisher(a["source"]) for a in independent_articles}
        amounts = [_headline_amounts(a['title']) for a in independent_articles]
        populated = [values for values, _ in amounts if values]
        keys = set().union(*(values for values in populated)) if populated else set()
        shared = {key for key in keys
                  if sum(key in values for values in populated) > 1} if populated else set()
        conflict = (any(uncertain for _, uncertain in amounts)
                    or bool(populated) and len(populated) != len(amounts)
                    or len(populated) > 1 and not shared
                    or any(key[0] == 'money' and key not in shared for key in keys)
                    or any(len({frozenset(values[key]) for values in populated if key in values}) > 1
                           for key in shared))
        reviewable = len(publishers) >= 2 and not conflict and not syndicated
        candidates.append({"topic": topic, "action": action, "symbol": symbol, "date": date,
                           "source_count": len(publishers), "article_count": len(independent_articles),
                           "sources": sorted(a["source"] for a in articles),
                           "decision": "review" if reviewable else "abstain",
                           "reason": ("Sindikasi identik lintas domain; jangan hitung sebagai laporan independen."
                                      if syndicated else "Angka pada judul bertentangan atau tidak sepadan; periksa manual."
                                      if conflict else "Penerbit berbeda; kesamaan klaim dan independensi sumber belum diverifikasi."
                                      if reviewable else "Bukti penerbit berbeda belum cukup.")})
    return sorted(candidates, key=lambda c: (-c["source_count"], -c["article_count"], c["topic"], c["symbol"], c["date"]))


def score_candidate(candidate):
    """Bab 8.2 per-rule score only; no ranking or inference from headlines."""
    if not isinstance(candidate, dict) or any(candidate.get(k) is not v for k, v in
            (("reviewed", True), ("endpoint_available", True), ("stale_repeat", False))):
        return None
    rule = candidate.get("rule")
    if rule == "foreign_streak":
        days = candidate.get("streak")
        return days * 2 if type(days) is int and days >= 5 else None
    if rule == "mover_persistent":
        return 6 if type(candidate.get("consecutive_days")) is int and candidate["consecutive_days"] >= 3 else None
    if rule == "mover_outlier":
        try:
            ratio = Decimal(str(candidate["ratio"]))
        except (KeyError, ValueError, ArithmeticError):
            return None
        return 5 if ratio.is_finite() and ratio > 2 else None
    if rule == "quarterly_new":
        return 7 if candidate.get("new_report") is True else None
    if rule == "news_two_large":
        return 4 if candidate.get("has_number") is True and type(candidate.get("large_tickers")) is int and candidate["large_tickers"] >= 2 else None
    if rule == "news_one_ticker":
        return 3 if candidate.get("has_number") is True and type(candidate.get("ticker_count")) is int and candidate["ticker_count"] == 1 else None
    return None

def _connect(db):
    con = sqlite3.connect(db, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con

def _store(db, run_id, cutoff, since, interpretation, rows, candidates):
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, cutoff TEXT NOT NULL, saved_at TEXT NOT NULL, decision_json TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS articles (run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, source))")
        con.execute("CREATE TABLE IF NOT EXISTS run_context (run_id TEXT PRIMARY KEY REFERENCES runs(id), since TEXT NOT NULL, interpretation_json TEXT NOT NULL)")
        con.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?)",
                    (run_id, cutoff.isoformat(), datetime.now(timezone.utc).isoformat(),
                     json.dumps(candidates, ensure_ascii=False, sort_keys=True)))
        context = json.dumps(interpretation or {}, ensure_ascii=False, sort_keys=True)
        con.execute("INSERT OR IGNORE INTO run_context VALUES (?, ?, ?)",
                    (run_id, since.isoformat(), context))
        existing_context = con.execute("SELECT since, interpretation_json FROM run_context WHERE run_id=?",
                                       (run_id,)).fetchone()
        if existing_context != (since.isoformat(), context):
            raise ValueError("identitas run berbenturan dengan cutoff, since, atau interpretasi")
        con.executemany("INSERT OR IGNORE INTO articles VALUES (?, ?, ?)",
                        ((run_id, a["source"], json.dumps(a, ensure_ascii=False, sort_keys=True)) for a, _ in rows))

def approve_packet(db, run_id, editor, text, claims, *, reviewed=False):
    """Explicit human-reviewed assertion; origin identities remain editor assertions."""
    if not all(isinstance(v, str) and v.strip() for v in (run_id, editor, text)):
        raise ValueError("run_id, editor, dan teks final wajib ada")
    if not isinstance(claims, list) or not claims:
        raise ValueError("klaim wajib ada")
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS packets (run_id TEXT PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL)")

        run = con.execute("SELECT cutoff, decision_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("run tidak ditemukan")
        _require_confirmed_time(con, run_id)
        current = con.execute("SELECT payload FROM packets WHERE run_id=?", (run_id,)).fetchone()
        if current:
            previous = json.loads(current[0])
            if (previous["text_hash"] == text_hash and previous["claims"] == claims
                    and previous["approval"]["editor"] == editor):
                return previous
            raise ValueError("revisi perlu persetujuan editor baru; persetujuan lama tetap berlaku untuk versi tersimpan")
        eligible = [c for c in json.loads(run[1]) if c["decision"] == "review"]
        if eligible and not reviewed:
            raise ValueError("kandidat review belum dinyatakan diverifikasi editor; lampirkan keputusan review eksplisit")
        if not eligible:
            raise ValueError("tidak ada kandidat review; abstain tidak bisa dinaikkan otomatis")
        checked = _validate_claims(con, run_id, claims, text)
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        packet = {"run_id": run_id, "cutoff": run[0], "claims": checked, "text": text,
                  "text_hash": fingerprint, "approval": {"editor": editor,
                  "approved_at": datetime.now(timezone.utc).isoformat()}}
        con.execute("INSERT INTO packets VALUES (?, ?)",
                    (run_id, json.dumps(packet, ensure_ascii=False, sort_keys=True)))
        return packet

def _validate_claims(con, run_id, claims, text=None, *, strict=False):
    run = con.execute("SELECT cutoff, decision_json FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("run tidak ditemukan")
    eligible = [c for c in json.loads(run[1]) if c["decision"] == "review"]
    if not eligible:
        raise ValueError("tidak ada kandidat review; abstain tidak bisa dinaikkan otomatis")
    if not isinstance(claims, list) or not claims:
        raise ValueError("klaim wajib ada")
    articles = {url: json.loads(body) for url, body in con.execute(
        "SELECT source, payload FROM articles WHERE run_id=?", (run_id,))}
    checked = []
    for claim in claims:
            if not isinstance(claim, dict) or any(not isinstance(claim.get(k), str) or not claim[k].strip()
                                                 for k in ("text", "entity", "action", "event_time")):
                raise ValueError("klaim perlu teks, entitas, aksi, dan waktu")
            if text is not None and claim["text"] not in text:
                raise ValueError("teks klaim tidak ada pada teks final")
            if claim.get("value") is not None and any(not isinstance(claim.get(k), str) or not claim[k].strip()
                                                       for k in ("value", "unit", "period")):
                raise ValueError("angka perlu nilai, satuan, dan periode")
            if strict:
                numeric = re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", claim["text"])
                if numeric and (not claim.get("value") or not claim.get("unit") or not claim.get("period")
                                or any(number not in claim["value"] for number in numeric)):
                    raise ValueError("angka pada teks perlu nilai, satuan, dan periode yang ditinjau")
                if numeric and any(any(number not in re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", item.get("quote", ""))
                                       for number in numeric) for item in claim.get("evidence", [])):
                    raise ValueError("angka pada teks tidak ada pada setiap kutipan sumber")
                when_value = claim["event_time"].strip()
                if "T" in when_value or " " in when_value:
                    try:
                        instant = _time(when_value)
                    except ValueError as exc:
                        raise ValueError("waktu klaim wajib zona waktu") from exc
                    if instant > _time(run[0]):
                        raise ValueError("waktu klaim setelah cutoff")
            evidence = claim.get("evidence")
            if not isinstance(evidence, list) or len(evidence) < 2:
                raise ValueError("klaim perlu dua bukti laporan")
            origins = set()
            verified = []
            for item in evidence:
                if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
                                                     for k in ("source", "quote", "origin")):
                    raise ValueError("bukti perlu sumber, kutipan, dan asal")
                row = articles.get(item["source"])
                if row is None or item["quote"] not in ((row.get("title") or "") + "\n" + (row.get("body") or "")):
                    raise ValueError("kutipan tidak ada pada artikel arsip")
                if text is not None and item["source"] not in text:
                    raise ValueError("sumber bukti tidak ada pada teks final")
                origin = item["origin"].strip().casefold()
                origins.add(origin)
                verified.append({**item, "page": _source_page(con, run_id, item["source"])})
            if len(origins) < 2:
                raise ValueError("asal laporan tidak independen")
            matched = [c for c in eligible if {e["source"] for e in verified}.issubset(set(c["sources"]))]
            if not matched:
                raise ValueError("sumber klaim bukan satu kandidat review; peristiwa berbeda")
            entity = claim["entity"].strip().upper().removesuffix(".JK")
            when = claim["event_time"].strip()
            symbol_matched = [c for c in matched if c["symbol"] == "PASAR" or c["symbol"] == entity]
            if not symbol_matched:
                raise ValueError("entity klaim tidak cocok dengan symbol kandidat review")
            if strict and not any(c["action"] == "peristiwa belum dirinci" or
                                  claim["action"].strip().casefold() in
                                  ({"pengumuman", "umumkan", "mengumumkan"} if c["action"] == "pengumuman" else
                                   {"pembayaran", "bayar", "membayar"} if c["action"] == "pembayaran" else
                                   {c["action"]}) for c in symbol_matched):
                raise ValueError("aksi klaim tidak cocok dengan kandidat review")
            if not any(when == c["date"] or when.startswith(c["date"] + "T") or when.startswith(c["date"] + " ")
                       for c in symbol_matched):
                raise ValueError("event_time klaim tidak cocok dengan tanggal kandidat review")
            checked.append({**claim, "evidence": verified})
    return checked

def _edition_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _edition_hash(value):
    return hashlib.sha256(_edition_json(value).encode("utf-8")).hexdigest()

def _require_confirmed_time(con, run_id):
    row = con.execute("SELECT interpretation_json FROM run_context WHERE run_id=?", (run_id,)).fetchone()
    if row and json.loads(row[0]).get("time_basis") == "inferred_internal":
        raise ValueError("run dengan asumsi waktu hanya untuk demo internal; approval ditahan")

def check_platform_text(platform, text):
    """Documented length checks, not a platform acceptance guarantee."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("teks post wajib ada")
    if platform == "threads":
        size = len(text.encode("utf-8"))
        return {"valid": size <= 500, "length": size, "status": "documented_rules_applied"}
    if platform != "x":
        raise ValueError("platform tidak dikenal")
    try:
        result = subprocess.run(["node", str(Path(__file__).with_name("x_length.mjs"))],
                                input=text, text=True, capture_output=True, timeout=10,
                                cwd=Path(__file__).parent, check=True)
        parsed = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("twitter-text gagal: validasi X ditahan") from exc
    if type(parsed.get("weighted_length")) is not int or type(parsed.get("valid")) is not bool:
        raise ValueError("twitter-text mengembalikan hitungan tidak valid")
    return {"valid": parsed["valid"] and parsed["weighted_length"] <= 280,
            "length": parsed["weighted_length"], "status": "documented_rules_applied"}

def review_claims(db, run_id, editor, claims, *, reviewed=False):
    """Record editor's assertions, not verification of economic truth or identity."""
    if not isinstance(editor, str) or not editor.strip() or not reviewed:
        raise ValueError("review editor eksplisit wajib ada")
    with closing(_connect(db)) as con, con:
        _require_confirmed_time(con, run_id)
        con.execute("CREATE TABLE IF NOT EXISTS reviewed_claims (run_id TEXT PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL)")
        checked = _validate_claims(con, run_id, claims, strict=True)
        record = {"run_id": run_id, "editor": editor, "claims": checked,
                  "reviewed_at": datetime.now(timezone.utc).isoformat()}
        previous = con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?", (run_id,)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if old["editor"] == editor and old["claims"] == checked:
                return old
            raise ValueError("revisi klaim perlu run baru dan review ulang")
        con.execute("INSERT INTO reviewed_claims VALUES (?, ?)", (run_id, _edition_json(record)))
        return record

def _read_review(con, run_id):
    row = con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError("klaim belum ditinjau")
    record = json.loads(row[0])
    if record.get("run_id") != run_id or not record.get("editor") or not record.get("reviewed_at"):
        raise ValueError("integritas review rusak")
    if _validate_claims(con, run_id, record["claims"], strict=True) != record["claims"]:
        raise ValueError("integritas bukti review rusak")
    return record

def _edition_posts(claims, indexes):
    if (not isinstance(indexes, list) or not 1 <= len(indexes) <= 6
            or any(type(i) is not int or i < 0 or i >= len(claims) for i in indexes)
            or len(set(indexes)) != len(indexes)):
        raise ValueError("pilih satu sampai enam klaim berbeda")
    return [claims[i]["text"] + "\nSumber: " + " ".join(
        dict.fromkeys(item["source"] for item in claims[i]["evidence"])) for i in indexes]

def render_draft(db, run_id, edition_id, platform, indexes):
    """One post per selected reviewed claim; no fabricated connective prose."""
    if platform not in ("x", "threads") or not isinstance(edition_id, str) or not edition_id.strip():
        raise ValueError("platform dan edisi wajib valid")
    with closing(_connect(db)) as con:
        record = _read_review(con, run_id)
        return _edition_posts(record["claims"], indexes)

def approve_edition(db, run_id, edition_id, platform, editor, posts):
    """Bind one platform's exact posts and reviewed sources to one edition."""
    if (platform not in ("x", "threads") or not isinstance(edition_id, str) or not edition_id.strip()
            or not isinstance(editor, str) or not editor.strip()):
        raise ValueError("edisi, platform, dan editor wajib valid")
    with closing(_connect(db)) as con, con:
        review = _read_review(con, run_id)
        if not isinstance(posts, list):
            raise ValueError("teks final harus daftar post")
        matches = []
        for post in posts:
            indexes = [i for i in range(len(review["claims"])) if _edition_posts(review["claims"], [i])[0] == post]
            if len(indexes) != 1:
                raise ValueError("teks final bukan klaim ditinjau beserta sumber persis")
            matches.append(indexes[0])
        if _edition_posts(review["claims"], matches) != posts:
            raise ValueError("post kosong, duplikat, atau melebihi enam bagian")
        if any(not check_platform_text(platform, post)["valid"] for post in posts):
            raise ValueError("post melewati batas konservatif platform")
        con.execute("CREATE TABLE IF NOT EXISTS editions (run_id TEXT NOT NULL REFERENCES runs(id), edition_id TEXT NOT NULL, platform TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, edition_id, platform))")
        bound = {"run_id": run_id, "edition_id": edition_id, "platform": platform,
                 "posts": posts, "indexes": matches, "review_hash": _edition_hash(review)}
        previous = con.execute("SELECT payload FROM editions WHERE run_id=? AND edition_id=? AND platform=?",
                               (run_id, edition_id, platform)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if old.get("bound") == bound and old.get("approval", {}).get("editor") == editor:
                return old
            raise ValueError("edisi terkunci; revisi perlu edisi baru")
        approval = {"editor": editor, "approved_at": datetime.now(timezone.utc).isoformat()}
        saved = {"bound": bound, "hash": _edition_hash({"bound": bound, "approval": approval}),
                 "approval": approval}
        con.execute("INSERT INTO editions VALUES (?, ?, ?, ?)", (run_id, edition_id, platform, _edition_json(saved)))
        return saved

def preview_edition(db, run_id, edition_id, platform, *, posts=None):
    """Fail closed on text, order, provenance, or approval changes; no API write."""
    if platform not in ("x", "threads"):
        raise ValueError("platform tidak dikenal")
    with closing(_connect(db)) as con:
        try:
            row = con.execute("SELECT payload FROM editions WHERE run_id=? AND edition_id=? AND platform=?",
                              (run_id, edition_id, platform)).fetchone()
        except sqlite3.OperationalError as exc:
            raise ValueError("edisi belum disetujui") from exc
        if row is None:
            raise ValueError("edisi belum disetujui")
        saved = json.loads(row[0])
        bound = saved.get("bound")
        if (not isinstance(bound, dict) or saved.get("hash") != _edition_hash(
                {"bound": bound, "approval": saved.get("approval")})
                or any(bound.get(k) != v for k, v in (("run_id", run_id), ("edition_id", edition_id), ("platform", platform)))
                or not saved.get("approval", {}).get("editor") or not saved["approval"].get("approved_at")):
            raise ValueError("integritas persetujuan rusak")
        review = _read_review(con, run_id)
        if (bound["review_hash"] != _edition_hash(review)
                or _edition_posts(review["claims"], bound["indexes"]) != bound["posts"]
                or (posts is not None and posts != bound["posts"])):
            raise ValueError("teks, urutan, atau sumber berubah; persetujuan baru diperlukan")
        checks = [check_platform_text(platform, post) for post in bound["posts"]]
        if any(not check["valid"] for check in checks):
            raise ValueError("post melewati batas konservatif platform")
        return {"run_id": run_id, "edition_id": edition_id, "platform": platform,
                "posts": bound["posts"], "approval": saved["approval"],
                "hash": saved["hash"], "limit_check": "documented_rules_applied",
                "lengths": [check["length"] for check in checks], "api_write": False}

def approve_revision(db, run_id, editor, text, claims):
    """Append explicitly approved revision; never replace prior approval evidence."""
    raise ValueError("revisi non-identik belum tersedia; buat run dan approval baru")

def _source_page(con, run_id, source):
    row = con.execute("SELECT page_index FROM article_pages WHERE run_id=? AND source=?",
                      (run_id, source)).fetchone()
    if row is None:
        raise ValueError("halaman sumber tidak ditemukan")
    return row[0]

def preview_packet(db, run_id, *, text=None):
    """Conservative dry run; no platform requests or platform access claims."""
    with closing(_connect(db)) as con:
        try:
            saved = con.execute("SELECT payload FROM packets WHERE run_id=?", (run_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise ValueError("paket belum disetujui") from exc
    if saved is None:
        raise ValueError("paket belum disetujui")
    packet = json.loads(saved[0])
    final = packet["text"] if text is None else text
    if (final != packet["text"] or
            hashlib.sha256(final.encode("utf-8")).hexdigest() != packet["text_hash"]):
        raise ValueError("teks tidak disetujui atau integritas berubah")
    if not packet.get("approval", {}).get("editor") or not packet["approval"].get("approved_at"):
        raise ValueError("paket belum disetujui")
    with closing(_connect(db)) as con:
        stored = con.execute("SELECT payload FROM packets WHERE run_id=?", (run_id,)).fetchone()
        archived = {url: json.loads(body) for url, body in con.execute(
            "SELECT source, payload FROM articles WHERE run_id=?", (run_id,))}
    if stored is None:
        raise ValueError("paket hilang")
    if stored[0] != saved[0]:
        raise ValueError("paket berubah saat dibaca")
    if packet["text_hash"] != hashlib.sha256(packet["text"].encode("utf-8")).hexdigest():
        raise ValueError("integritas paket rusak")
    for claim in packet["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str) or claim["text"] not in final:
            raise ValueError("integritas klaim berubah; approval baru diperlukan")
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or len(evidence) < 2:
            raise ValueError("integritas bukti berubah; approval baru diperlukan")
        origins = set()
        for item in evidence:
            if (not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
                                                  for k in ("source", "quote", "origin"))):
                raise ValueError("integritas bukti berubah; approval baru diperlukan")
            article = archived.get(item["source"])
            if article is None or item["quote"] not in ((article.get("title") or "") + "\n" + (article.get("body") or "")):
                raise ValueError("integritas kutipan berubah; approval baru diperlukan")
            if item["source"] not in final:
                raise ValueError("integritas atribusi berubah; approval baru diperlukan")
            origins.add(item["origin"].strip().casefold())
        if len(origins) < 2:
            raise ValueError("integritas asal bukti berubah; approval baru diperlukan")
    # ponytail: count only; validate platform weighted-length/URL rules before any live integration.
    return {"run_id": run_id, "approval": packet["approval"], "text_hash": packet["text_hash"],
            "threads": {"text": final, "utf8_bytes": len(final.encode("utf-8")), "limit_check": "not_performed"},
            "x": {"text": final, "raw_characters": len(final), "limit_check": "not_performed"}, "api_write": False}

def record_mock_attempt(db, run_id, platform, account, outcome, *, external_id=None, readback=None):
    """Offline-only failure-state simulator; never retries ambiguous writes."""
    if platform not in ("threads", "x") or not isinstance(account, str) or not account.strip():
        raise ValueError("platform dan akun mock wajib valid")
    if outcome not in ("timeout", "expired_token", "partial_failure", "created"):
        raise ValueError("hasil mock tidak dikenal")
    preview = preview_packet(db, run_id)
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS mock_posts (run_id TEXT NOT NULL, platform TEXT NOT NULL, ordinal INTEGER NOT NULL, account TEXT NOT NULL, text_hash TEXT NOT NULL, status TEXT NOT NULL, external_id TEXT, readback_json TEXT, PRIMARY KEY (run_id, platform, ordinal))")
        previous = con.execute("SELECT status FROM mock_posts WHERE run_id=? AND platform=? AND ordinal=1",
                               (run_id, platform)).fetchone()
        if previous and previous[0] in ("ambiguous", "mock_verified"):
            raise ValueError("hasil ambigu: perlu baca balik akun/ID tepat sebelum retry; simulasi terkunci")
        if outcome == "created":
            if not isinstance(external_id, str) or not external_id or not isinstance(readback, dict):
                status = "ambiguous"
            else:
                status = ("mock_verified" if readback.get("id") == external_id
                          and readback.get("account") == account
                          and readback.get("text") == preview[platform]["text"] else "ambiguous")
        elif outcome == "expired_token":
            status = "failed"
        else:
            status = "ambiguous"
        con.execute("INSERT INTO mock_posts VALUES (?, ?, 1, ?, ?, ?, ?, ?) ON CONFLICT(run_id, platform, ordinal) DO UPDATE SET status=excluded.status, external_id=excluded.external_id, readback_json=excluded.readback_json WHERE mock_posts.status='failed'",
                    (run_id, platform, account, preview["text_hash"], status, external_id,
                     json.dumps(readback, ensure_ascii=False) if readback is not None else None))
        return {"run_id": run_id, "platform": platform, "status": status,
                "external_id": external_id, "simulation_only": True}


def replay_assumed(pages, cutoff, db, *, since, assume_timezone):
    """Internal demonstration only; the assumed offset is not provider evidence."""
    if assume_timezone != "+07:00":
        raise ValueError("mode asumsi internal hanya +07:00 yang diputuskan pemilik")
    interpretation = {"source_timezone": assume_timezone, "timestamp_meaning": "unknown",
                      "filter_timezone": assume_timezone, "start_inclusive": True,
                      "end_inclusive": True, "evidence": "asumsi demo internal; bukan konfirmasi penyedia",
                      "time_basis": "inferred_internal"}
    result = replay(pages, cutoff, db, since=since, interpretation=interpretation)
    return result

def replay(pages, cutoff, db, *, since, interpretation=None):
    """Return draft and decision trail; never assert causality or numeric claims."""
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages harus daftar halaman tidak kosong")
    if not isinstance(cutoff, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", cutoff):
        raise ValueError("cutoff harus menyertakan zona waktu")
    if not isinstance(since, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", since):
        raise ValueError("since harus menyertakan zona waktu")
    moment, beginning = _time(cutoff), _time(since)
    if beginning > moment:
        raise ValueError("since setelah cutoff")
    if any(isinstance(page, dict) and "source_timezone" in page for page in pages):
        raise ValueError("arsip mentah tidak boleh memuat source_timezone; interpretasi harus terpisah pada sidecar")
    if interpretation is not None:
        if not isinstance(interpretation, dict) or any(
                not isinstance(interpretation.get(k), str) or not interpretation[k].strip()
                for k in ("source_timezone", "timestamp_meaning", "filter_timezone", "evidence")):
            raise ValueError("interpretasi waktu butuh bukti/evidence tertulis dan semantik lengkap")
        for key in ("source_timezone", "filter_timezone"):
            _time("2026-01-01T00:00:00", interpretation[key])
        if any(type(interpretation.get(k)) is not bool for k in ("start_inclusive", "end_inclusive")):
            raise ValueError("batas inklusif start/end perlu dinyatakan")
        if interpretation.get("time_basis") == "inferred_internal" and (
                interpretation.get("evidence") != "asumsi demo internal; bukan konfirmasi penyedia"
                or interpretation["source_timezone"] != "+07:00"
                or interpretation["filter_timezone"] != "+07:00"):
            raise ValueError("mode asumsi tidak menerima zona lain atau bukti penyedia palsu")
    rows = _ingest(pages, moment, beginning, interpretation)
    candidates = _candidates(rows)
    selected = next((c for c in candidates if c["decision"] == "review"), None)
    digest = hashlib.sha256(json.dumps({"policy": "numeric-v2", "cutoff": moment.isoformat(), "since": beginning.isoformat(), "pages": pages,
                                        "interpretation": interpretation},
                                    ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    _store(db, digest, moment, beginning, interpretation, rows, candidates)
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS article_pages (run_id TEXT NOT NULL, source TEXT NOT NULL, page_index INTEGER NOT NULL, page_hash TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (run_id, source))")
        included = {a["source"] for a, _ in rows}
        for i, page in enumerate(pages):
            checksum = hashlib.sha256(json.dumps(page, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            con.executemany("INSERT OR IGNORE INTO article_pages VALUES (?, ?, ?, ?, ?)",
                            ((digest, a["source"], i, checksum, page["fetched_at"])
                             for a in page["response"]["results"] if a["source"] in included))
    if selected:
        draft = (f"DRAF — BELUM UNTUK PUBLIKASI\nTema: {selected['topic']} ({selected['action']}) — {selected['symbol']} "
                 f"({selected['date']}).\nSejumlah artikel membahas tema ini. "
                 "Rincian peristiwa, angka, dan independensi sumber harus diperiksa editor. "
                 "Belum ada klaim sebab-akibat atau saran investasi.")
        notes = (f"Periksa kesamaan klaim antar artikel dan tanggal publikasi; sumber:\n" +
                 "\n".join(selected["sources"]))
    else:
        draft = "TIDAK ADA DRAF: belum ada tema dengan bukti penerbit berbeda yang layak ditinjau."
        notes = "Abstain. Tidak ada headline otomatis."
    inferred = interpretation is not None and interpretation.get("time_basis") == "inferred_internal"
    if inferred:
        draft = "ASUMSI ZONA WAKTU +07:00 — DEMO INTERNAL; JANGAN PUBLIKASIKAN\n" + draft
    return {"run_id": digest, "time_interpretation": interpretation,
            **({"time_basis": "inferred_internal", "publishable": False} if inferred else {}),
            "status": "review" if selected else "abstain",
            "eligible_articles": len(rows), "candidates": candidates,
            "draft": draft, "editorial_notes": notes}


def draft_schedule(pages, now, db, *, since, interpretation=None):
    """Explicit offline business slot; caller owns invocation, not an unattended daemon."""
    moment = _time(now)
    local = moment.astimezone(JAKARTA)
    if local.weekday() >= 5 or (local.hour, local.minute, local.second, local.microsecond) != (6, 0, 0, 0):
        raise ValueError("jadwal draft hanya hari kerja 06:00 WIB")
    if (not isinstance(interpretation, dict)
            or interpretation.get("time_basis") == "inferred_internal"
            or not isinstance(interpretation.get("evidence"), str)
            or not interpretation["evidence"].strip()):
        raise ValueError("interpretasi waktu belum dikonfirmasi; jadwal ditahan")
    result = replay(pages, now, db, since=since, interpretation=interpretation)
    slot = local.date().isoformat()
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS draft_schedules (slot TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL)")
        previous = con.execute("SELECT run_id, payload FROM draft_schedules WHERE slot=?", (slot,)).fetchone()
        if previous:
            if previous[0] != result["run_id"]:
                raise ValueError("slot jadwal sudah memiliki run berbeda; tahan edisi")
            return json.loads(previous[1])
        output = {"slot": slot, "run_id": result["run_id"], "status": "draft_only",
                  "review_status": result["status"], "api_write": False}
        con.execute("INSERT INTO draft_schedules VALUES (?, ?, ?)",
                    (slot, result["run_id"], _edition_json(output)))
        return output

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="archive all Sectors IDX news pages for date range")
    fetch.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    fetch.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    fetch.add_argument("--out", type=Path, required=True, help="archive path")
    companion = sub.add_parser("fetch-companion", help="archive three companion endpoint responses")
    companion.add_argument("--symbol", required=True)
    companion.add_argument("--start", required=True)
    companion.add_argument("--end", required=True)
    companion.add_argument("--out", type=Path, required=True)
    scheduled = sub.add_parser("schedule-once", help="offline draft-only invocation at explicit WIB business slot")
    scheduled.add_argument("pages", type=Path)
    scheduled.add_argument("--at", required=True, help="explicit ISO 8601 instant")
    scheduled.add_argument("--since", required=True)
    scheduled.add_argument("--db", type=Path, required=True)
    scheduled.add_argument("--interpretation", type=Path, required=True)
    command = sub.add_parser("replay", help="replay archived Sectors /v2/news/ JSON pages")
    command.add_argument("pages", type=Path, help="JSON list of {fetched_at, request, response} pages")
    command.add_argument("--cutoff", required=True, help="ISO 8601 timestamp; include timezone")
    command.add_argument("--since", required=True, help="ISO 8601 earliest editorial timestamp; include timezone")
    command.add_argument("--db", type=Path, default=Path("ronce.sqlite"))
    command.add_argument("--interpretation", type=Path, help="separate JSON sidecar, only after authoritative written provider confirmation")
    command.add_argument("--assume-timezone", choices=["+07:00"], help="internal demo only; blocks approval and publication")
    args = parser.parse_args()
    try:
        if args.command == "fetch":
            if args.out.exists():
                raise FileExistsError(f"arsip sudah ada: {args.out}")
            pages = fetch_news(args.start, args.end, api_key=os.environ.get("SECTORS_API_KEY"))
            save_archive(args.out, pages)
            print(json.dumps({"archive": str(args.out), "pages": len(pages),
                              "articles": sum(len(p["response"]["results"]) for p in pages)}, ensure_ascii=False))
        elif args.command == "fetch-companion":
            captured = fetch_companion(args.symbol, args.start, args.end, args.out,
                                       api_key=os.environ.get("SECTORS_API_KEY"))
            print(json.dumps({"archive": str(args.out), "endpoints": [row["endpoint"] for row in captured]}, ensure_ascii=False))
        elif args.command == "schedule-once":
            payload = json.loads(args.pages.read_text(encoding="utf-8"))
            interpretation = json.loads(args.interpretation.read_text(encoding="utf-8"))
            outcome = draft_schedule(payload, args.at, args.db, since=args.since,
                                     interpretation=interpretation)
            print(json.dumps(outcome, ensure_ascii=False))
        else:
            payload = json.loads(args.pages.read_text(encoding="utf-8"))
            if args.assume_timezone and args.interpretation:
                raise ValueError("mode asumsi dan sidecar tidak boleh dipakai bersamaan")
            if args.assume_timezone:
                outcome = replay_assumed(payload, args.cutoff, args.db, since=args.since,
                                         assume_timezone=args.assume_timezone)
            else:
                interpretation = json.loads(args.interpretation.read_text(encoding="utf-8")) if args.interpretation else None
                outcome = replay(payload, args.cutoff, args.db, since=args.since,
                                 interpretation=interpretation)
            print(json.dumps(outcome, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
