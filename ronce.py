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
POLICY_VERSION = "numeric-v2"
_UNSET = object()


class RevisionConflict(ValueError):
    """A caller's expected story revision is no longer the current one.

    Subclasses ValueError so every existing `except ValueError` contract holds; the private
    workbench maps it to an HTTP conflict so a stale tab gets conflict feedback, not a silent
    overwrite.
    """


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


def _companion_specs(symbol, start, end):
    return [("top_changes", "companies/top-changes/", {"classifications": "top_gainers,top_losers", "periods": "1d,7d"}),
            ("foreign_flow", f"foreign-flow/{symbol.upper()}/", {"start": start, "end": end}),
            ("quarterly", f"financials/quarterly/{symbol.upper()}/", {"n_quarters": 1})]


def _companion_shape_ok(kind, payload):
    if kind == "top_changes":
        return isinstance(payload, dict) and any(isinstance(payload.get(k), dict) for k in ("top_gainers", "top_losers"))
    if kind == "foreign_flow":
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)
    if kind == "quarterly":
        return isinstance(payload, list)
    return False


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
    specs = _companion_specs(symbol, start, end)
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
        if not _companion_shape_ok(kind, payload):
            raise ValueError(f"respons {kind} tidak sesuai bentuk dokumentasi; arsip tidak disimpan")
        captured.append({"endpoint": kind, "request": params, "fetched_at": fetched_at, "response": payload})
    save_archive(target, captured)
    return captured


def fetch_companion_independent(symbol, start, end, out_dir, *, api_key):
    """Archive each companion endpoint separately; an unavailable endpoint never hides the others.

    Every endpoint keeps its own atomic archive and the status file records, per endpoint,
    whether the response was archived, unavailable (HTTP/network) or rejected for shape.
    """
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("SECTORS_API_KEY wajib tersedia di lingkungan proses")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z]{4}(?:\.[Jj][Kk])?", symbol):
        raise ValueError("symbol IDX harus empat huruf, opsional .JK")
    if (not isinstance(start, str) or not isinstance(end, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)
            or not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 90):
        raise ValueError("rentang foreign-flow wajib tanggal valid 0-90 hari")
    specs = _companion_specs(symbol, start, end)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    targets = {kind: directory / f"{kind}.json" for kind, _, _ in specs}
    for kind, path in targets.items():
        if path.exists():
            raise FileExistsError(f"arsip sudah ada: {path}")
    status = []
    for kind, path, params in specs:
        entry = {"endpoint": kind, "request": params, "fetched_at": datetime.now(timezone.utc).isoformat()}
        request = Request("https://api.sectors.app/v2/" + path + "?" + urlencode(params),
                          headers={"Authorization": api_key, "Accept": "application/json", "User-Agent": "Ronce-MVP/0.1"})
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.load(response)
        except HTTPError as exc:
            entry.update({"status": "unavailable", "error": f"HTTP {exc.code}"})
            status.append(entry)
            continue
        except (URLError, TimeoutError):
            entry.update({"status": "unavailable", "error": "jaringan tidak tersedia"})
            status.append(entry)
            continue
        if not _companion_shape_ok(kind, payload):
            entry.update({"status": "invalid_shape", "error": "bentuk respons tidak sesuai dokumentasi"})
            status.append(entry)
            continue
        save_archive(targets[kind], [{"endpoint": kind, "request": params,
                                      "fetched_at": entry["fetched_at"], "response": payload}])
        entry.update({"status": "archived", "path": targets[kind].name})
        status.append(entry)
    report = {"symbol": symbol.upper().removesuffix(".JK"), "start": start, "end": end,
              "status": status, "api_write": False}
    save_archive(directory / "status.json", report)
    return report

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


def _ingest(pages, cutoff, since, interpretation=None, *, snapshot_cutoff=None):
    """`cutoff` filters article publication time; `snapshot_cutoff` (default: cutoff)
    bounds how late the completed snapshot may be for a live edition."""
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages harus daftar halaman tidak kosong")
    availability = cutoff if snapshot_cutoff is None else snapshot_cutoff
    seen = set()
    rows = []
    expected_offset = 0
    total_seen = None
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or "fetched_at" not in page:
            raise ValueError("halaman harus memuat fetched_at")
        source_timezone = interpretation["source_timezone"] if interpretation else None
        fetched_at = _time(page["fetched_at"], source_timezone)
        if fetched_at > availability:
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

_SCALE_WORDS = {"unit": 1, "": 1, "ribu": 1000, "thousand": 1000, "juta": 1000000,
                "million": 1000000, "miliar": 1000000000, "billion": 1000000000,
                "triliun": 1000000000000, "trillion": 1000000000000}
_CURRENCIES = {"rp": "IDR", "idr": "IDR", "rupiah": "IDR", "us$": "USD", "usd": "USD",
               "dolar": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
               "sgd": "SGD", "jpy": "JPY", "yen": "JPY", "eur": "EUR", "euro": "EUR"}
_FACT = re.compile(
    r"(?<![\w.])(?:(?P<currency>US\$|USD|IDR|Rp|SGD|JPY|EUR|\$)\s*)?(?P<sign>[-+]\s*)?"
    r"(?P<number>\d+(?:[.,\u202f ]\d+)*)\s*"
    r"(?P<scale>triliun|trillion|miliar|billion|juta|million|ribu|thousand)?\s*"
    r"(?P<unit>poin persentase|percentage points?|(?:rupiah|dolar|dollars?|yen|euro|usd|idr)\s+per\s+(?:saham|share)|per saham|per share|persen|saham|shares?|rupiah|dolar|dollars?|yen|euro|%)?"
    r"(?!\w)", re.I)
_OPINION_MARKERS = re.compile(
    r"\b(target(?: harga)?|menargetkan|proyeksi|diproyeksikan|rekomendasi|rating|estimasi|"
    r"diperkirakan|perkiraan|perkirakan|outlook|analis|analyst|menurut analis)\b", re.I)


def _number(raw):
    raw = raw.replace("\u202f", "").replace(" ", "")
    if "." in raw and "," in raw:
        sep = "." if raw.rfind(".") > raw.rfind(",") else ","
        raw = raw.replace("," if sep == "." else ".", "").replace(sep, ".")
    elif raw.count(".") + raw.count(",") == 1:
        sep = "." if "." in raw else ","
        if len(raw.split(sep)[1]) == 3:
            raise ValueError("angka ambigu tanpa metadata lokal")
        raw = raw.replace(",", ".")
    elif "." in raw or "," in raw:
        sep = "." if "." in raw else ","
        parts = raw.split(sep)
        if not all(len(part) == 3 for part in parts[1:]):
            raise ValueError("angka ambigu tanpa metadata lokal")
        raw = "".join(parts)
    return Decimal(raw)


def _facts(text):
    """Extract comparable numeric facts; a bare number is not a fact."""
    facts = []
    for match in _FACT.finditer(text):
        currency = (match["currency"] or "").casefold()
        scale_word = (match["scale"] or "").casefold()
        unit_word = (match["unit"] or "").casefold()
        if not (currency or scale_word or unit_word):
            continue
        code = _CURRENCIES.get(currency) or _CURRENCIES.get(unit_word, "")
        if "poin persentase" in unit_word or "percentage point" in unit_word:
            kind, code = "percent_point", ""
        elif unit_word in ("%", "persen"):
            kind, code = "percent", ""
        elif "per saham" in unit_word or "per share" in unit_word or unit_word in ("saham", "share", "shares"):
            kind = "shares"
            code = code or next((mapped for token, mapped in _CURRENCIES.items() if token in unit_word), "")
        elif code:
            kind = "money"
        else:
            kind = "scaled"
        try:
            amount = _number(match["number"])
        except (ValueError, ArithmeticError) as exc:
            raise ValueError("angka kutipan ambigu tanpa metadata lokal") from exc
        if match["sign"] and "-" in match["sign"]:
            amount = -amount
        facts.append({"amount": amount, "currency": code, "kind": kind,
                      "scale": _SCALE_WORDS.get(scale_word, 1), "raw": match.group(0).strip()})
    return facts


def _claim_fact(claim):
    """Normalize one reviewed numeric claim into a comparable fact."""
    fields = {k: claim.get(k) for k in ("value", "unit", "scale", "metric")}
    if any(not isinstance(fields[k], str) or not fields[k].strip() for k in fields):
        raise ValueError("angka pada teks perlu nilai, satuan, skala, dan metrik yang ditinjau")
    try:
        amount = _number(fields["value"])
    except (ValueError, ArithmeticError) as exc:
        raise ValueError("angka pada teks tidak dapat dibaca sebagai nilai") from exc
    unit = fields["unit"].casefold()
    code = next((mapped for token, mapped in _CURRENCIES.items() if token in unit), "")
    if "poin persentase" in unit or "percentage point" in unit or unit.strip() == "pp":
        kind, code = "percent_point", ""
    elif "%" in unit or "persen" in unit:
        kind, code = "percent", ""
    elif "per saham" in unit or "saham" in unit or "share" in unit:
        kind = "shares"
    elif code:
        kind = "money"
    else:
        kind = "scaled"
    scale_word = fields["scale"].casefold()
    if scale_word not in _SCALE_WORDS:
        raise ValueError("skala angka tidak dikenal: " + scale_word)
    return {"amount": amount, "currency": code, "kind": kind, "scale": _SCALE_WORDS[scale_word]}


def _quote_supports_fact(fact, quote):
    """A claim's number must exist in the quote with the same unit and scale."""
    return any(candidate["amount"] == fact["amount"] and candidate["kind"] == fact["kind"]
               and candidate["currency"] == fact["currency"] and candidate["scale"] == fact["scale"]
               for candidate in _facts(quote))


def artifact_hash(value):
    """Stable content identity; independent of the interpreter hash seed."""
    return _edition_hash(value)


def assert_publishable(artifact):
    """Only an approved edition record may enter any publishing path."""
    review = artifact.get("review") if isinstance(artifact, dict) else None
    if (not isinstance(artifact, dict) or artifact.get("publishable") is not True
            or not isinstance(review, dict) or not str(review.get("editor") or "").strip()):
        raise ValueError("artefak bukan edisi disetujui; publikasi ditolak")
    return artifact


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
                           "source_count": len(publishers), "publisher_count": len(publishers),
                           "article_count": len(independent_articles),
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

def rank_candidates(candidates, *, signals=None, diversify=True):
    """Deterministic editorial ranking; rule detail comes only from explicit signals."""
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError("kandidat harus daftar objek")

    def detail_for(candidate):
        entry = None
        if isinstance(signals, dict):
            entry = signals.get((candidate.get("symbol"), candidate.get("topic")))
            if entry is None:
                entry = signals.get(candidate.get("symbol"))
        if not isinstance(entry, dict):
            return 0, []
        detail, total = [], 0
        for rule in entry.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            points = score_candidate({"reviewed": True, "endpoint_available": True,
                                      "stale_repeat": False, **rule})
            if points is None:
                continue
            observed = {k: rule[k] for k in ("streak", "consecutive_days", "ratio", "new_report",
                                             "has_number", "large_tickers", "ticker_count") if k in rule}
            detail.append({"rule": rule.get("rule"), "points": points, "observed": observed})
            total += points
        return total, detail

    ranked = []
    for candidate in candidates:
        total, detail = detail_for(candidate)
        ranked.append({**candidate, "score": total, "score_detail": detail})
    ranked.sort(key=lambda c: (-c["score"], -c["source_count"], -c["article_count"],
                               c["topic"], c["symbol"], c["date"]))
    if diversify:
        for index in range(len(ranked) - 1):
            if ranked[index + 1]["score"] != ranked[index]["score"] or ranked[index + 1]["topic"] != ranked[index]["topic"]:
                continue
            swap = next((j for j in range(index + 2, len(ranked))
                         if ranked[j]["score"] == ranked[index]["score"]
                         and ranked[j]["topic"] != ranked[index]["topic"]), None)
            if swap is not None:
                ranked[index + 1], ranked[swap] = ranked[swap], ranked[index + 1]
    return ranked

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
            claim_kind = claim.get("claim_type") or (
                "analyst_opinion" if _OPINION_MARKERS.search(claim["text"]) else "reported_fact")
            if claim_kind not in ("reported_fact", "analyst_opinion"):
                raise ValueError("claim_type tidak dikenal")
            if strict and claim_kind == "analyst_opinion":
                if claim.get("claim_type") != "analyst_opinion":
                    raise ValueError("teks opini perlu claim_type=analyst_opinion eksplisit")
                if not str(claim.get("attribution") or "").strip():
                    raise ValueError("klaim opini perlu atribusi analis atau lembaga")
            if claim.get("value") is not None and any(not isinstance(claim.get(k), str) or not claim[k].strip()
                                                       for k in ("value", "unit", "period")):
                raise ValueError("angka perlu nilai, satuan, dan periode")
            fact = None
            if strict:
                numeric = re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", claim["text"])
                if numeric and any(not isinstance(claim.get(k), str) or not claim[k].strip()
                                   for k in ("value", "unit", "period")):
                    raise ValueError("angka pada teks perlu nilai, satuan, dan periode yang ditinjau")
                if numeric and any(number not in claim["value"] for number in numeric):
                    raise ValueError("angka pada teks tidak cocok dengan nilai yang ditinjau")
                if numeric and any(any(number not in re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", item.get("quote", ""))
                                       for number in numeric) for item in claim.get("evidence", [])):
                    raise ValueError("angka pada teks tidak ada pada setiap kutipan sumber")
                if numeric:
                    fact = _claim_fact(claim)
                    moment_text = claim["event_time"].strip()
                    if claim["period"].strip() != moment_text[:4] and not moment_text.startswith(claim["period"].strip()):
                        raise ValueError("periode angka tidak cocok dengan waktu klaim")
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
            reviewed_origins = set()
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
                if strict:
                    entity_token = claim["entity"].strip().upper().removesuffix(".JK")
                    row_symbols = {str(symbol).upper().removesuffix(".JK") for symbol in (row.get("symbols") or [])}
                    if entity_token != "PASAR" and entity_token not in row_symbols:
                        raise ValueError("entitas klaim tidak didukung metadata simbol artikel sumber")
                    metric_tokens = [token for token in re.split(r"[^0-9A-Za-z]+", str(claim.get("metric") or "").casefold())
                                     if len(token) >= 4]
                    if metric_tokens and not any(token in item["quote"].casefold() for token in metric_tokens):
                        raise ValueError("metrik klaim tidak didukung teks kutipan sumber")
                origin = item["origin"].strip().casefold()
                origins.add(origin)
                basis = item.get("origin_basis") or "unknown"
                if basis not in ("independent_review", "unknown"):
                    raise ValueError("origin_basis tidak dikenal")
                note = item.get("origin_note")
                if strict and basis == "independent_review" and (not isinstance(note, str) or len(note.strip()) < 12):
                    raise ValueError("asal berdiri sendiri perlu alasan tinjauan (origin_note minimal 12 karakter)")
                if basis == "independent_review":
                    reviewed_origins.add(origin)
                if fact is not None and not _quote_supports_fact(fact, item["quote"]):
                    raise ValueError("angka, satuan, atau skala klaim tidak cocok dengan kutipan sumber")
                verified.append({**item, "origin_basis": basis, "page": _source_page(con, run_id, item["source"])})
            if len(origins) < 2:
                raise ValueError("asal laporan tidak independen")
            if strict and len(reviewed_origins) < 2:
                raise ValueError("asal tinjauan independen belum dinyatakan untuk dua sumber; tandai origin_basis=independent_review hanya bila asal berdiri sendiri")
            if len({item["source"] for item in verified}) != len(verified):
                raise ValueError("dua label asal tidak boleh menunjuk satu sumber yang sama")
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
            first = matched[0]
            checked.append({**claim, "claim_type": claim_kind,
                            "story_key": {"symbol": first["symbol"], "topic": first["topic"],
                                          "action": first["action"], "date": first["date"]},
                            "source_counts": {"articles": max(c["article_count"] for c in matched),
                                              "publishers": max(c["source_count"] for c in matched),
                                              "reviewed_origins": len(reviewed_origins) if strict else len(origins)},
                            "evidence": verified})
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
        import adapters
        valid, _ = adapters.validate_threads_text(text)
        return {"valid": valid, "length": len(text.strip().encode("utf-8")),
                "status": "documented_rules_applied"}
    if platform != "x":
        raise ValueError("platform tidak dikenal")
    try:
        import os
        env = os.environ.copy()
        # Force UTF-8 on Windows by avoiding text=True (which uses cp1252)
        result = subprocess.run(["node", str(Path(__file__).with_name("x_length.mjs"))],
                                input=text.encode('utf-8'), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=10, cwd=Path(__file__).parent,
                                env=env)
        if result.returncode != 0:
            raise ValueError(f"twitter-text gagal: {result.stderr.decode('utf-8')}")
        parsed = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("twitter-text gagal: validasi X ditahan") from exc
    if type(parsed.get("weighted_length")) is not int or type(parsed.get("valid")) is not bool:
        raise ValueError("twitter-text mengembalikan hitungan tidak valid")
    return {"valid": parsed["valid"] and parsed["weighted_length"] <= 280,
            "length": parsed["weighted_length"], "status": "documented_rules_applied"}

def _article_payload(con, run_id, source):
    row = con.execute("SELECT payload FROM articles WHERE run_id=? AND source=?", (run_id, source)).fetchone()
    return json.loads(row[0]) if row else None


def _article_content_hash(payload):
    """Identity of the reviewed content version (title + body as archived)."""
    return _edition_hash({"title": payload.get("title"), "body": payload.get("body")})


def _require_origin_decisions(con, run_id, claims):
    """Approval gate: every independent origin needs a persisted, content-bound editorial decision."""
    try:
        for claim in claims:
            for item in claim["evidence"]:
                if item.get("origin_basis") != "independent_review":
                    continue
                row = con.execute("SELECT content_hash, rationale, reviewer FROM origin_reviews "
                                  "WHERE run_id=? AND source=? AND entity=?",
                                  (run_id, item["source"], claim["entity"])).fetchone()
                if row is None or not row[1].strip() or not row[2].strip():
                    raise ValueError("keputusan asal berdiri sendiri belum tercatat; review perlu dijalankan di jalur editorial")
                payload = _article_payload(con, run_id, item["source"])
                if payload is None or row[0] != _article_content_hash(payload):
                    raise ValueError("konten sumber berubah sejak tinjauan asal; persetujuan baru diperlukan")
    except sqlite3.OperationalError as exc:
        raise ValueError("keputusan asal berdiri sendiri belum tercatat; review perlu dijalankan di jalur editorial") from exc


def record_origin_decisions(con, run_id, claims, editor, decided_at):
    """Persist the editorial decision behind each independent origin, bound to the content version.

    Only this trusted local path writes the table; the review flags alone never reach the approval
    gate, which re-reads the record and re-checks the archived content hash.
    """
    con.execute("CREATE TABLE IF NOT EXISTS origin_reviews (run_id TEXT NOT NULL, source TEXT NOT NULL, "
                "entity TEXT NOT NULL, reviewer TEXT NOT NULL, rationale TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, decided_at TEXT NOT NULL, "
                "PRIMARY KEY (run_id, source, entity))")
    written = 0
    for claim in claims:
        for item in claim["evidence"]:
            if item.get("origin_basis") != "independent_review":
                continue
            payload = _article_payload(con, run_id, item["source"])
            if payload is None:
                raise ValueError("sumber tinjauan asal tidak ada pada arsip")
            content_hash = _article_content_hash(payload)
            previous = con.execute("SELECT content_hash FROM origin_reviews WHERE run_id=? AND source=? AND entity=?",
                                   (run_id, item["source"], claim["entity"])).fetchone()
            if previous and previous[0] != content_hash:
                raise ValueError("konten sumber berubah sejak tinjauan asal; tinjauan perlu diulang")
            con.execute("INSERT OR REPLACE INTO origin_reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (run_id, item["source"], claim["entity"], editor, item["origin_note"].strip(),
                         content_hash, decided_at))
            written += 1
    return written


def review_claims(db, run_id, editor, claims, *, reviewed=False, expected_revisions=None):
    """Record editor's assertions, not verification of economic truth or identity.

    `expected_revisions` is the workbench precondition: for every story in this review the
    caller's seen revision must still be the current one, checked inside this write transaction.
    """
    if not isinstance(editor, str) or not editor.strip() or not reviewed:
        raise ValueError("review editor eksplisit wajib ada")
    with closing(_connect(db)) as con, con:
        _require_confirmed_time(con, run_id)
        con.execute("CREATE TABLE IF NOT EXISTS reviewed_claims (run_id TEXT PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL)")
        checked = _validate_claims(con, run_id, claims, strict=True)
        previous = con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?", (run_id,)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if old["editor"] == editor and old["claims"] == checked:
                return old  # Idempotent repeat: no write, so no revision precondition applies.
            raise ValueError("revisi klaim perlu run baru dan review ulang")
        _require_expected_revisions(con, expected_revisions,
                                    require_keys={story_identity(**claim["story_key"]) for claim in checked})
        reviewed_at = datetime.now(timezone.utc).isoformat()
        record_origin_decisions(con, run_id, checked, editor, reviewed_at)
        record = {"run_id": run_id, "editor": editor, "claims": checked,
                  "reviewed_at": reviewed_at}
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

def approve_edition(db, run_id, edition_id, platform, editor, posts, *, expected_revisions=None):
    """Bind one platform's exact posts and reviewed sources to one edition."""
    if (platform not in ("x", "threads") or not isinstance(edition_id, str) or not edition_id.strip()
            or not isinstance(editor, str) or not editor.strip()):
        raise ValueError("edisi, platform, dan editor wajib valid")
    with closing(_connect(db)) as con, con:
        review = _read_review(con, run_id)
        _require_origin_decisions(con, run_id, review["claims"])
        _require_expected_revisions(con, expected_revisions,
                                    require_keys={story_identity(**claim["story_key"]) for claim in review["claims"]
                                                  if claim.get("story_key")})
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
                 "posts": posts, "indexes": matches, "review_hash": _edition_hash(review),
                 "revisions": _current_revisions(con, review)}
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

def preview_edition(db, run_id, edition_id, platform, *, posts=None, stale_ok=False):
    """Fail closed on text, order, provenance, or approval changes; no API write.

    `stale_ok=True` keeps a historical edition readable (integrity still checked) without letting a
    stale approval authorize anything: export and publication always use the default.
    """
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
        _require_origin_decisions(con, run_id, review["claims"])
        if not stale_ok:
            _require_current_revisions(con, bound)
        if (bound["review_hash"] != _edition_hash(review)
                or _edition_posts(review["claims"], bound["indexes"]) != bound["posts"]
                or (posts is not None and posts != bound["posts"])):
            raise ValueError("teks, urutan, atau sumber berubah; persetujuan baru diperlukan")
        checks = [check_platform_text(platform, post) for post in bound["posts"]]
        if any(not check["valid"] for check in checks):
            raise ValueError("post melewati batas konservatif platform")
        return {"run_id": run_id, "edition_id": edition_id, "platform": platform,
                "posts": bound["posts"], "indexes": bound["indexes"], "approval": saved["approval"],
                "hash": saved["hash"], "limit_check": "documented_rules_applied",
                "lengths": [check["length"] for check in checks], "api_write": False}

def publication_manifest(db, run_id, edition_id, platform, *, account):
    """Exact approved posts and hashes for the transport boundary; fails closed."""
    if not isinstance(account, str) or not account.strip():
        raise ValueError("akun publikasi wajib eksplisit")
    preview = preview_edition(db, run_id, edition_id, platform)
    return {"platform": platform, "run_id": run_id, "edition_id": edition_id,
            "account": account, "approval": preview["approval"],
            "edition_hash": preview["hash"], "api_write": False,
            "posts": [{"ordinal": index + 1, "text": text,
                       "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                      for index, text in enumerate(preview["posts"])]}


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
        sources = set()
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
            sources.add(item["source"])
        if len(origins) < 2:
            raise ValueError("integritas asal bukti berubah; approval baru diperlukan")
        if len(sources) != len(evidence):
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

def replay(pages, cutoff, db, *, since, interpretation=None, snapshot_cutoff=None):
    """Return draft and decision trail; never assert causality or numeric claims.

    `cutoff` bounds eligible article publication time (see `_ingest`); the optional
    `snapshot_cutoff` is the completion moment of the snapshot a live edition may use.
    """
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages harus daftar halaman tidak kosong")
    if not isinstance(cutoff, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", cutoff):
        raise ValueError("cutoff harus menyertakan zona waktu")
    if not isinstance(since, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", since):
        raise ValueError("since harus menyertakan zona waktu")
    if snapshot_cutoff is not None and (not isinstance(snapshot_cutoff, str)
                                        or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", snapshot_cutoff)):
        raise ValueError("snapshot_cutoff harus menyertakan zona waktu")
    moment, beginning = _time(cutoff), _time(since)
    if beginning > moment:
        raise ValueError("since setelah cutoff")
    availability = moment if snapshot_cutoff is None else _time(snapshot_cutoff)
    if availability < moment:
        raise ValueError("snapshot_cutoff tidak boleh mendahului cutoff edisi")
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
    rows = _ingest(pages, moment, beginning, interpretation,
                   snapshot_cutoff=None if snapshot_cutoff is None else availability)
    candidates = rank_candidates(_candidates(rows))
    selected = next((c for c in candidates if c["decision"] == "review"), None)
    digest = hashlib.sha256(json.dumps({"policy": POLICY_VERSION, "cutoff": moment.isoformat(), "since": beginning.isoformat(),
                                        "snapshot_cutoff": snapshot_cutoff,
                                        "pages": pages,
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


def replay_edition(pages, db, *, window_start, window_end, snapshot_cutoff, interpretation=None):
    """Live edition: the news window, the completed snapshot and the replay cutoff differ.

    Articles are eligible up to `window_end` while the snapshot itself may have finished
    later (`snapshot_cutoff`); historical `replay()` keeps its strict no-lookahead rule.
    """
    start, end, done = _time(window_start), _time(window_end), _time(snapshot_cutoff)
    if start > end or end > done:
        raise ValueError("urutan waktu edisi tidak valid: window_start <= window_end <= snapshot_cutoff")
    return replay(pages, window_end, db, since=window_start, interpretation=interpretation,
                  snapshot_cutoff=snapshot_cutoff)


def editorial_window(slot, *, lookback_hours=24):
    """Editorial news window ending at the slot; Monday reaches back across the weekend.

    No holiday calendar is assumed: pass explicit window_start for holidays or catch-up.
    """
    if not isinstance(slot, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", slot):
        raise ValueError("slot harus menyertakan zona waktu")
    if type(lookback_hours) is not int or not 1 <= lookback_hours <= 168:
        raise ValueError("lookback_hours harus 1..168")
    end = _time(slot).astimezone(JAKARTA)
    if end.weekday() >= 5:
        raise ValueError("slot editorial hanya hari kerja")
    hours = 72 if end.weekday() == 0 else lookback_hours
    start = end - timedelta(hours=hours)
    return {"scheduled_for": end.isoformat(), "window_start": start.isoformat(),
            "window_end": end.isoformat(), "coverage_hours": hours}


def draft_schedule(pages, scheduled_for, db, *, since=None, interpretation=None,
                   window_start=None, window_end=None, processed_at=None, lookback_hours=None):
    """Explicit offline business slot; caller owns invocation, not an unattended daemon.

    `scheduled_for` is the editorial slot, the window bounds article publication time and
    `processed_at` is the moment the snapshot finished (a fetch starting at the slot
    normally completes after it; that completion must not hide the new pages).
    """
    moment = _time(scheduled_for)
    local = moment.astimezone(JAKARTA)
    if local.weekday() >= 5 or (local.hour, local.minute, local.second, local.microsecond) != (6, 0, 0, 0):
        raise ValueError("jadwal draft hanya hari kerja 06:00 WIB")
    if (not isinstance(interpretation, dict)
            or interpretation.get("time_basis") == "inferred_internal"
            or not isinstance(interpretation.get("evidence"), str)
            or not interpretation["evidence"].strip()):
        raise ValueError("interpretasi waktu belum dikonfirmasi; jadwal ditahan")
    if window_start is not None:
        start = window_start
    elif lookback_hours is not None:
        start = editorial_window(scheduled_for, lookback_hours=lookback_hours)["window_start"]
    elif since is not None:
        start = since
    else:
        raise ValueError("since, window_start, atau lookback_hours wajib ada")
    end = window_end or scheduled_for
    done = processed_at or scheduled_for
    result = replay_edition(pages, db, window_start=start, window_end=end,
                            snapshot_cutoff=done, interpretation=interpretation)
    slot = local.date().isoformat()
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS draft_schedules (slot TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL)")
        previous = con.execute("SELECT run_id, payload FROM draft_schedules WHERE slot=?", (slot,)).fetchone()
        if previous:
            if previous[0] != result["run_id"]:
                raise ValueError("slot jadwal sudah memiliki run berbeda; tahan edisi")
            return json.loads(previous[1])
        output = {"slot": slot, "run_id": result["run_id"], "status": "draft_only",
                  "review_status": result["status"], "api_write": False,
                  "scheduled_for": moment.isoformat(), "window_start": start,
                  "window_end": end, "processed_at": done}
        con.execute("INSERT INTO draft_schedules VALUES (?, ?, ?)",
                    (slot, result["run_id"], _edition_json(output)))
        return output

# --------------------------------------------------------------------------- #
# Persisted version model: topic registry, stable story identities, immutable
# revisions, typed relations and withdrawal status. Migrations are additive and
# idempotent; approved editions and old links are never rewritten.
# --------------------------------------------------------------------------- #

TOPIC_SLUG = re.compile(r"[^a-z0-9]+")
RELATION_KINDS = ("supersedes", "corrects", "supports", "contradicts", "withdraws")


def topic_id(label):
    """Stable topic identity derived from the editorial label, not from a run."""
    slug = TOPIC_SLUG.sub("-", str(label).strip().casefold()).strip("-")
    if not slug:
        raise ValueError("label topik kosong")
    return slug


def story_identity(*, symbol, topic, action, date):
    """Stable logical identity: one story keeps it while its content revision changes."""
    return hashlib.sha256("|".join(str(part) for part in (symbol, topic, action, date))
                          .encode("utf-8")).hexdigest()[:16]


def migrate(db):
    """Additive, idempotent migration; every existing table and approval is preserved."""
    with closing(_connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS story_identities (story_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
                    "topic_id TEXT NOT NULL, action TEXT NOT NULL, date TEXT NOT NULL, created_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS story_revisions (revision_id TEXT PRIMARY KEY, story_key TEXT NOT NULL, "
                    "run_id TEXT, content_hash TEXT NOT NULL, decision TEXT NOT NULL, payload TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, UNIQUE (story_key, content_hash))")
        con.execute("CREATE TABLE IF NOT EXISTS story_relations (relation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                    "from_story TEXT NOT NULL, to_story TEXT NOT NULL, from_revision TEXT, to_revision TEXT, "
                    "reason TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS story_status (story_key TEXT PRIMARY KEY, status TEXT NOT NULL, "
                    "reason TEXT, evidence TEXT, updated_at TEXT NOT NULL)")
        return {"tables": ["topics", "story_identities", "story_revisions", "story_relations", "story_status"]}


def _story_revision_payload(con, run_id, candidate, review, *, status_at):
    """Complete safe canonical view of one story in one run: decision, sources, claims, evidence.

    Immutable by construction: comparison reads this payload, never today's mutable rows. The
    capture time lives in the revision row, not in the payload, so identical content hashes equal.
    """
    articles = {url: json.loads(payload) for url, payload in
                con.execute("SELECT source, payload FROM articles WHERE run_id=?", (run_id,))}
    key = story_identity(symbol=candidate["symbol"], topic=candidate["topic"],
                         action=candidate["action"], date=candidate["date"])
    claims = [{"text": claim["text"], "entity": claim["entity"], "action": claim["action"],
               "value": claim.get("value"), "unit": claim.get("unit"),
               "scale": claim.get("scale"), "metric": claim.get("metric"), "period": claim.get("period"),
               "claim_type": claim.get("claim_type"), "attribution": claim.get("attribution"),
               "source_counts": claim.get("source_counts"),
               "evidence": [{"url": item["source"], "quote": item["quote"], "origin": item["origin"],
                             "origin_basis": item.get("origin_basis", "unknown")}
                            for item in claim["evidence"]]}
              for claim in (review or {}).get("claims", [])
              if story_identity(**claim["story_key"]) == key]
    return {"story_key": key, "decision": candidate["decision"], "reason": candidate.get("reason"),
            "counts": {"articles": candidate.get("article_count"), "publishers": candidate.get("publisher_count")},
            "policy_version": POLICY_VERSION, "status_at": status_at,
            "sources": sorted(({"url": url, "title": articles.get(url, {}).get("title"),
                                "timestamp": articles.get(url, {}).get("timestamp")}
                               for url in candidate["sources"] if url in articles),
                              key=lambda row: row["url"]),
            "claims": sorted(claims, key=lambda row: row["text"])}


def register_versioned_stories(db, run_id):
    """Idempotently register topics, stable identities and immutable story revisions for one run."""
    with closing(_connect(db)) as con, con:
        _require_confirmed_time(con, run_id)
        row = con.execute("SELECT decision_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("run tidak dikenal")
        candidates = json.loads(row[0])
        if not isinstance(candidates, list):
            raise ValueError("decision_json bukan daftar kandidat")
        try:
            review = _read_review(con, run_id)
        except (ValueError, sqlite3.OperationalError):
            review = {"claims": []}
        now = datetime.now(timezone.utc).isoformat()
        written = {"topics": 0, "identities": 0, "revisions": 0, "unchanged": 0}
        for candidate in candidates:
            tid = topic_id(candidate["topic"])
            if con.execute("SELECT 1 FROM topics WHERE id=?", (tid,)).fetchone() is None:
                con.execute("INSERT INTO topics VALUES (?, ?, ?)", (tid, candidate["topic"], now))
                written["topics"] += 1
            key = story_identity(symbol=candidate["symbol"], topic=candidate["topic"],
                                 action=candidate["action"], date=candidate["date"])
            if con.execute("SELECT 1 FROM story_identities WHERE story_key=?", (key,)).fetchone() is None:
                con.execute("INSERT INTO story_identities VALUES (?, ?, ?, ?, ?, ?)",
                            (key, candidate["symbol"], tid, candidate["action"], candidate["date"], now))
                written["identities"] += 1
            payload = _story_revision_payload(con, run_id, candidate, review,
                                              status_at=_story_status(con, key))
            content_hash = _edition_hash(payload)
            if con.execute("SELECT 1 FROM story_revisions WHERE story_key=? AND content_hash=?",
                           (key, content_hash)).fetchone() is not None:
                written["unchanged"] += 1
                continue
            revision_id = hashlib.sha256((key + "|" + content_hash).encode("utf-8")).hexdigest()[:16]
            con.execute("INSERT INTO story_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (revision_id, key, run_id, content_hash, candidate["decision"], _edition_json(payload), now))
            written["revisions"] += 1
        return {"run_id": run_id, "written": written}


def add_relation(db, kind, from_story, to_story, *, reason, evidence, from_revision=None, to_revision=None,
                 expected_revisions=None):
    """Typed relation between two stable identities, with provenance and valid endpoints only."""
    if kind not in RELATION_KINDS:
        raise ValueError("jenis relasi tidak dikenal")
    if not isinstance(reason, str) or len(reason.strip()) < 8:
        raise ValueError("relasi perlu alasan yang jelas")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("relasi perlu rujukan bukti")
    with closing(_connect(db)) as con, con:
        for label, key in (("from_story", from_story), ("to_story", to_story)):
            if con.execute("SELECT 1 FROM story_identities WHERE story_key=?", (key,)).fetchone() is None:
                raise ValueError(f"{label} tidak ada pada registri identitas")
        _require_expected_revisions(con, expected_revisions, require_keys={from_story, to_story})
        for label, revision, key in (("from_revision", from_revision, from_story),
                                     ("to_revision", to_revision, to_story)):
            if revision is None:
                continue
            row = con.execute("SELECT story_key FROM story_revisions WHERE revision_id=?", (revision,)).fetchone()
            if row is None or row[0] != key:
                raise ValueError(f"{label} tidak cocok dengan ujung relasi")
        relation_id = hashlib.sha256(_edition_json([kind, from_story, to_story, from_revision, to_revision,
                                                    reason.strip()]).encode("utf-8")).hexdigest()[:16]
        existing = con.execute("SELECT 1 FROM story_relations WHERE relation_id=?", (relation_id,)).fetchone()
        if existing is not None:
            return {"relation_id": relation_id, "kind": kind, "from_story": from_story,
                    "to_story": to_story, "idempotent": True}
        con.execute("INSERT INTO story_relations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (relation_id, kind, from_story, to_story, from_revision, to_revision,
                     reason.strip(), evidence.strip(), datetime.now(timezone.utc).isoformat()))
        return {"relation_id": relation_id, "kind": kind, "from_story": from_story,
                "to_story": to_story, "idempotent": False}


def withdraw_story(db, story_key, *, reason, evidence, expected_revisions=None):
    """Record a withdrawal with its reason and evidence; the revision history stays readable."""
    if not isinstance(reason, str) or len(reason.strip()) < 8:
        raise ValueError("penarikan perlu alasan yang jelas")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("penarikan perlu rujukan bukti")
    with closing(_connect(db)) as con, con:
        if con.execute("SELECT 1 FROM story_identities WHERE story_key=?", (story_key,)).fetchone() is None:
            raise ValueError("story_key tidak ada pada registri identitas")
        _require_expected_revisions(con, expected_revisions, require_keys={story_key})
        con.execute("INSERT OR REPLACE INTO story_status VALUES (?, ?, ?, ?, ?)",
                    (story_key, "withdrawn", reason.strip(), evidence.strip(),
                     datetime.now(timezone.utc).isoformat()))
        return {"story_key": story_key, "status": "withdrawn"}


def _current_revisions(con, review):
    """story_key -> current revision id for every story this approval touches ({} without a model)."""
    try:
        rows = {row[0]: row[1] for row in
                con.execute("SELECT story_key, revision_id FROM story_revisions ORDER BY created_at, rowid")}
    except sqlite3.OperationalError:
        return {}
    keys = sorted({story_identity(**claim["story_key"]) for claim in review["claims"] if claim.get("story_key")})
    return {key: rows[key] for key in keys if key in rows}


def _require_current_revisions(con, bound):
    """A newer revision must never inherit an older approval."""
    for key, revision_id in (bound.get("revisions") or {}).items():
        try:
            row = con.execute("SELECT revision_id FROM story_revisions WHERE story_key=? "
                              "ORDER BY created_at DESC, rowid DESC LIMIT 1", (key,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise RevisionConflict("revisi cerita tidak terbaca; persetujuan baru diperlukan") from exc
        if row is None or row[0] != revision_id:
            raise RevisionConflict("revisi cerita berubah sejak persetujuan; persetujuan baru diperlukan")


def current_revision_id(con, story_key):
    """Latest revision id for one story, or None when the story has no revision yet."""
    try:
        row = con.execute("SELECT revision_id FROM story_revisions WHERE story_key=? "
                          "ORDER BY created_at DESC, rowid DESC LIMIT 1", (story_key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row else None


def _require_expected_revisions(con, expected_revisions, *, require_keys=None):
    """Workbench precondition, checked inside the caller's write transaction.

    `expected_revisions` maps story_key -> the revision id the caller saw, or None when the
    caller saw "no revision yet". A mismatch raises RevisionConflict. When `require_keys` is
    given, every listed story must be covered by the caller's map, so a decision cannot omit
    the revision it is actually about.
    """
    if expected_revisions is None:
        return
    if not isinstance(expected_revisions, dict) or any(
            not isinstance(key, str) or (value is not None and not isinstance(value, str))
            for key, value in expected_revisions.items()):
        raise ValueError("expected_revision_id harus peta story_key ke revisi atau null")
    for key in sorted(require_keys or ()):
        if key not in expected_revisions:
            raise RevisionConflict("revisi yang diharapkan belum disertakan untuk cerita ini")
    for key, expected in sorted(expected_revisions.items()):
        actual = current_revision_id(con, key)
        if actual != expected:
            raise RevisionConflict("revisi cerita berubah sejak dibaca; muat ulang sebelum memutuskan")


CHANGE_KINDS = ("new_evidence", "evidence_removed", "source_updated", "claim_added", "claim_withdrawn",
                "claim_corrected", "text_only", "withdrawal", "decision_changed", "other")
_NUMBER_FIELDS = ("value", "unit", "scale", "metric", "period")


def _claim_key(claim):
    return (claim.get("entity"), claim.get("metric"), claim.get("period"))


def compare_revisions(old, new, relations, *, story_key):
    """Typed list of changes between two immutable payloads.

    Categories come from typed records (relations, withdrawal status) and field diffs, never from
    a prose interpretation: adding a source is `new_evidence`, a number change is `claim_corrected`
    (labelled `corrects` only when a typed correction relation exists), and policy/review changes
    are `other`, not a text-only edit.
    """
    changes = []
    old_sources = {source["url"] for source in old.get("sources", [])}
    new_sources = {source["url"] for source in new.get("sources", [])}
    for url in sorted(new_sources - old_sources):
        changes.append({"kind": "new_evidence", "detail": url, "evidence": url})
    for url in sorted(old_sources - new_sources):
        changes.append({"kind": "evidence_removed", "detail": url, "evidence": url})
    old_index = {source["url"]: source for source in old.get("sources", [])}
    new_index = {source["url"]: source for source in new.get("sources", [])}
    for url in sorted(old_sources & new_sources):
        if (old_index[url].get("title"), old_index[url].get("timestamp")) != \
                (new_index[url].get("title"), new_index[url].get("timestamp")):
            changes.append({"kind": "source_updated", "detail": new_index[url].get("title") or url,
                            "evidence": url, "basis": "judul atau waktu sumber berubah"})
    correcting = any(relation["kind"] in ("corrects", "supersedes") and
                     story_key in (relation["from_story"], relation["to_story"]) for relation in relations)
    withdrawn = (new.get("status_at") == "withdrawn"
                 or any(relation["kind"] == "withdraws" and story_key in (relation["from_story"], relation["to_story"])
                        for relation in relations))
    old_claims = {_claim_key(claim): claim for claim in old.get("claims", [])}
    new_claims = {_claim_key(claim): claim for claim in new.get("claims", [])}
    for key in sorted(new_claims.keys() - old_claims.keys(), key=str):
        changes.append({"kind": "claim_added", "detail": new_claims[key]["text"]})
    for key in sorted(old_claims.keys() - new_claims.keys(), key=str):
        changes.append({"kind": "claim_withdrawn", "detail": old_claims[key]["text"]})
    for key in sorted(old_claims.keys() & new_claims.keys(), key=str):
        before, after = old_claims[key], new_claims[key]
        if any(before.get(field) != after.get(field) for field in _NUMBER_FIELDS):
            changes.append({"kind": "claim_corrected", "detail": after["text"],
                            "before": {field: before.get(field) for field in _NUMBER_FIELDS},
                            "after": {field: after.get(field) for field in _NUMBER_FIELDS},
                            "basis": "relasi koreksi" if correcting else "angka berubah"})
        elif before["text"] != after["text"]:
            changes.append({"kind": "text_only", "detail": after["text"],
                            "before": before["text"], "basis": "angka dan bukti sama"})
        before_evidence = sorted(item["url"] for item in before.get("evidence", []))
        after_evidence = sorted(item["url"] for item in after.get("evidence", []))
        if before_evidence != after_evidence:
            changes.append({"kind": "new_evidence" if len(after_evidence) > len(before_evidence) else "evidence_removed",
                            "detail": after["text"], "evidence": sorted(set(after_evidence) - set(before_evidence)) or
                            sorted(set(before_evidence) - set(after_evidence))})
    if old.get("decision") != new.get("decision"):
        changes.append({"kind": "decision_changed", "detail": f"{old.get('decision')} -> {new.get('decision')}"})
    if old.get("status_at") != new.get("status_at") or withdrawn:
        changes.append({"kind": "withdrawal", "detail": f"status {new.get('status_at', 'withdrawn')}",
                        "basis": "status atau relasi tercatat"})
    if old.get("policy_version") != new.get("policy_version"):
        changes.append({"kind": "other", "detail": f"kebijakan {old.get('policy_version')} -> {new.get('policy_version')}"})
    if old.get("reason") != new.get("reason") and (old.get("reason") or new.get("reason")):
        changes.append({"kind": "other", "detail": "alasan mesin berubah"})
    return changes


def story_comparisons(con, story_key, relations):
    """Consecutive immutable revision pairs for one story, with their typed change list."""
    rows = con.execute("SELECT revision_id, payload, created_at FROM story_revisions WHERE story_key=? "
                       "ORDER BY created_at, rowid", (story_key,)).fetchall()
    pairs = []
    for older, newer in zip(rows, rows[1:]):
        older_id, older_json, older_at = older
        newer_id, newer_json, newer_at = newer
        pairs.append({"story_key": story_key, "from_revision": older_id, "to_revision": newer_id,
                      "from_captured_at": older_at, "to_captured_at": newer_at,
                      "changes": compare_revisions(json.loads(older_json), json.loads(newer_json),
                                                   relations, story_key=story_key)})
    return pairs


def _story_status(con, story_key):
    row = con.execute("SELECT status FROM story_status WHERE story_key=?", (story_key,)).fetchone()
    return row[0] if row else "active"


def story_model(db):
    """Read model: registry, revisions, relations and status for export."""
    with closing(_connect(db)) as con:
        try:
            topics = [{"id": row[0], "label": row[1]} for row in con.execute("SELECT id, label FROM topics ORDER BY label")]
            identities = [dict(zip(("story_key", "symbol", "topic_id", "action", "date"),
                                   row)) for row in con.execute(
                "SELECT story_key, symbol, topic_id, action, date FROM story_identities ORDER BY story_key")]
            revisions = [{"revision_id": row[0], "story_key": row[1], "run_id": row[2], "content_hash": row[3],
                          "decision": row[4], "created_at": row[6], "payload": json.loads(row[5])}
                         for row in con.execute("SELECT revision_id, story_key, run_id, content_hash, decision, payload, created_at "
                                                "FROM story_revisions ORDER BY created_at, revision_id")]
            relations = [{"relation_id": row[0], "kind": row[1], "from_story": row[2], "to_story": row[3],
                          "from_revision": row[4], "to_revision": row[5], "reason": row[6], "evidence": row[7]}
                         for row in con.execute("SELECT relation_id, kind, from_story, to_story, from_revision, "
                                                "to_revision, reason, evidence FROM story_relations ORDER BY created_at, relation_id")]
            statuses = {row[0]: {"status": row[1], "reason": row[2], "evidence": row[3]}
                        for row in con.execute("SELECT story_key, status, reason, evidence FROM story_status")}
            comparisons = [pair for identity in identities
                           for pair in story_comparisons(con, identity["story_key"], relations)]
        except sqlite3.OperationalError as exc:
            raise ValueError("model versi belum dimigrasi; jalankan migrate") from exc
    return {"topics": topics, "identities": identities, "revisions": revisions,
            "relations": relations, "status": statuses, "comparisons": comparisons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="archive all Sectors IDX news pages for date range")
    fetch.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    fetch.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    fetch.add_argument("--out", type=Path, required=True, help="archive path")
    companion = sub.add_parser("fetch-companion", help="archive three companion endpoint responses atomically")
    companion.add_argument("--symbol", required=True)
    companion.add_argument("--start", required=True)
    companion.add_argument("--end", required=True)
    companion.add_argument("--out", type=Path, required=True)
    split = sub.add_parser("fetch-companion-independent",
                           help="archive each companion endpoint separately; failures do not hide the others")
    split.add_argument("--symbol", required=True)
    split.add_argument("--start", required=True)
    split.add_argument("--end", required=True)
    split.add_argument("--out-dir", type=Path, required=True)
    scheduled = sub.add_parser("schedule-once", help="offline draft-only invocation at explicit WIB business slot")
    scheduled.add_argument("pages", type=Path)
    scheduled.add_argument("--at", required=True, help="explicit ISO 8601 instant")
    scheduled.add_argument("--since", help="ISO 8601 earliest editorial timestamp; used when no window/lookback is given")
    scheduled.add_argument("--db", type=Path, required=True)
    scheduled.add_argument("--interpretation", type=Path, required=True)
    scheduled.add_argument("--processed-at", help="moment the snapshot finished; defaults to --at")
    scheduled.add_argument("--window-start", help="explicit editorial window start")
    scheduled.add_argument("--window-end", help="explicit editorial window end; defaults to --at")
    scheduled.add_argument("--lookback-hours", type=int, help="window start = slot - N hours (Monday: 72)")
    reviewed = sub.add_parser("review-claims", help="record editor-reviewed claims for one run")
    reviewed.add_argument("--db", type=Path, required=True)
    reviewed.add_argument("--run-id", required=True)
    reviewed.add_argument("--editor", required=True)
    reviewed.add_argument("--claims", type=Path, required=True, help="JSON list of claim objects")
    reviewed.add_argument("--reviewed", action="store_true", help="explicit editor review assertion")
    render = sub.add_parser("render-draft", help="render one post per selected reviewed claim")
    render.add_argument("--db", type=Path, required=True)
    render.add_argument("--run-id", required=True)
    render.add_argument("--edition-id", required=True)
    render.add_argument("--platform", required=True, choices=["x", "threads"])
    render.add_argument("--indexes", required=True, help="comma-separated reviewed-claim indexes, e.g. 0,1")
    render.add_argument("--out", type=Path, help="write the JSON list here instead of stdout")
    edition_approve = sub.add_parser("approve-edition", help="bind exact posts to one edition and platform")
    edition_approve.add_argument("--db", type=Path, required=True)
    edition_approve.add_argument("--run-id", required=True)
    edition_approve.add_argument("--edition-id", required=True)
    edition_approve.add_argument("--platform", required=True, choices=["x", "threads"])
    edition_approve.add_argument("--editor", required=True)
    edition_approve.add_argument("--posts", type=Path, help="JSON list of exact post texts")
    edition_approve.add_argument("--indexes", help="build posts from these reviewed-claim indexes instead")
    edition_preview = sub.add_parser("preview-edition", help="fail-closed check of one approved edition; no API write")
    edition_preview.add_argument("--db", type=Path, required=True)
    edition_preview.add_argument("--run-id", required=True)
    edition_preview.add_argument("--edition-id", required=True)
    edition_preview.add_argument("--platform", required=True, choices=["x", "threads"])
    edition_preview.add_argument("--posts", type=Path, help="optional JSON list to compare against the approval")
    exporter = sub.add_parser("export-edition",
                              help="atomic public export of one approved edition (web contract v1)")
    exporter.add_argument("--db", type=Path, required=True)
    exporter.add_argument("--run-id", required=True)
    exporter.add_argument("--edition-id", required=True)
    exporter.add_argument("--platform", required=True, choices=["x", "threads"])
    exporter.add_argument("--out-dir", type=Path, required=True)
    exporter.add_argument("--dataset", choices=["archive", "fixture"], default="archive",
                          help="label the export origin; fixtures stay visibly synthetic")
    migration = sub.add_parser("migrate", help="additive, idempotent schema migration for the version model")
    migration.add_argument("--db", type=Path, required=True)
    versions = sub.add_parser("register-versions",
                              help="register topics, stable story identities and immutable revisions for a run")
    versions.add_argument("--db", type=Path, required=True)
    versions.add_argument("--run-id", required=True)
    command = sub.add_parser("replay", help="replay archived Sectors /v2/news/ JSON pages")
    command.add_argument("pages", type=Path, help="JSON list of {fetched_at, request, response} pages")
    command.add_argument("--cutoff", required=True, help="ISO 8601 timestamp; include timezone")
    command.add_argument("--since", required=True, help="ISO 8601 earliest editorial timestamp; include timezone")
    command.add_argument("--db", type=Path, default=Path("ronce.sqlite"))
    command.add_argument("--interpretation", type=Path, help="separate JSON sidecar, only after authoritative written provider confirmation")
    command.add_argument("--assume-timezone", choices=["+07:00"], help="internal demo only; blocks approval and publication")
    args = parser.parse_args()

    def read_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

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
        elif args.command == "fetch-companion-independent":
            report = fetch_companion_independent(args.symbol, args.start, args.end, args.out_dir,
                                                 api_key=os.environ.get("SECTORS_API_KEY"))
            print(json.dumps(report, ensure_ascii=False))
        elif args.command == "schedule-once":
            payload = read_json(args.pages)
            interpretation = read_json(args.interpretation)
            outcome = draft_schedule(payload, args.at, args.db, since=args.since,
                                     interpretation=interpretation, window_start=args.window_start,
                                     window_end=args.window_end, processed_at=args.processed_at,
                                     lookback_hours=args.lookback_hours)
            print(json.dumps(outcome, ensure_ascii=False))
        elif args.command == "review-claims":
            record = review_claims(args.db, args.run_id, args.editor, read_json(args.claims),
                                   reviewed=args.reviewed)
            print(json.dumps(record, ensure_ascii=False))
        elif args.command == "render-draft":
            indexes = [int(part) for part in args.indexes.split(",") if part.strip()]
            posts = render_draft(args.db, args.run_id, args.edition_id, args.platform, indexes)
            if args.out:
                args.out.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"edition_id": args.edition_id, "platform": args.platform,
                                  "posts": len(posts), "out": str(args.out)}, ensure_ascii=False))
            else:
                print(json.dumps(posts, ensure_ascii=False, indent=2))
        elif args.command == "approve-edition":
            if args.posts and args.indexes:
                raise ValueError("pakai --posts atau --indexes, bukan keduanya")
            if args.posts:
                posts = read_json(args.posts)
            elif args.indexes:
                indexes = [int(part) for part in args.indexes.split(",") if part.strip()]
                posts = render_draft(args.db, args.run_id, args.edition_id, args.platform, indexes)
            else:
                raise ValueError("--posts atau --indexes wajib ada")
            saved = approve_edition(args.db, args.run_id, args.edition_id, args.platform, args.editor, posts)
            print(json.dumps(saved, ensure_ascii=False, indent=2))
        elif args.command == "preview-edition":
            outcome = preview_edition(args.db, args.run_id, args.edition_id, args.platform,
                                      posts=read_json(args.posts) if args.posts else None)
            print(json.dumps(outcome, ensure_ascii=False, indent=2))
        elif args.command == "export-edition":
            import export as export_module
            manifest = export_module.export_edition(args.db, args.run_id, args.edition_id,
                                                    args.platform, args.out_dir, dataset=args.dataset)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        elif args.command == "migrate":
            print(json.dumps(migrate(args.db), ensure_ascii=False))
        elif args.command == "register-versions":
            print(json.dumps(register_versioned_stories(args.db, args.run_id), ensure_ascii=False))
        else:
            payload = read_json(args.pages)
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
