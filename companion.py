"""Companion adapters: independent acquisition, schema validation, normalization and status.

Every family archives atomically on its own and records its own acquisition status, retrieval
time, scope, contract version, payload hash and pagination completeness, so a denied or partial
endpoint can never erase a successful companion or the valid news archive.

Contracts are recorded with the date they were checked against official documentation
(docs.sectors.app). Values are attributed market context, never reviewed Ronce claims, and a
missing value stays missing (never zero).
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.sectors.app/v2/"

# family -> verified contract. `checked` is the date the primary documentation was re-read.
CONTRACT = {
    "movers": {"path": "companies/top-changes/", "checked": "2026-09-30",
               "params": ("classifications", "periods"), "cost": "1 per classification x period",
               "envelope": "dict(top_gainers/top_losers per period)"},
    "daily": {"path": "daily/{symbol}/", "checked": "2026-10-02", "params": ("start", "end"),
              "cost": "1", "envelope": "array[DailyDataItem] (<=90d window)"},
    "quarterly": {"path": "financials/quarterly/{symbol}/", "checked": "2026-09-30",
                  "params": ("n_quarters",), "cost": "1 per quarter", "envelope": "array[quarter]"},
    "foreign_flow": {"path": "foreign-flow/{symbol}/", "checked": "2026-09-30",
                     "params": ("start", "end"), "cost": "1", "envelope": "dict(symbol,data[])"},
    "filings": {"path": "filings/", "checked": "2026-10-02",
                "params": ("symbol", "limit"), "cost": "1", "envelope": "dict(results[],pagination)"},
    "corporate_actions": {"path": "corporate-actions/", "checked": "2026-09-30",
                          "params": ("start", "end", "type"), "cost": "1 per type",
                          "envelope": "per-type arrays"},
}

DATE_KINDS = ("announcement", "cum", "ex", "record", "payment", "meeting")
ACTION_TYPES = ("dividend", "upcoming_dividend", "stock_split", "bonus", "right_issue", "warrant", "agm")
RETRYABLE = ("timeout", "rate_limited", "server_error")
TERMINAL = ("denied", "unconfigured", "not_found")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _retry_policy():
    """Bounded retry only for transient acquisition failures; permission stays terminal."""
    return {"attempts": 2, "backoff_seconds": (0.5, 1.5), "retryable": RETRYABLE, "terminal": TERMINAL}


def migrate_companion(db):
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS companion_records (id TEXT PRIMARY KEY, family TEXT NOT NULL, "
                    "symbol TEXT, scope TEXT NOT NULL, period TEXT, value_json TEXT NOT NULL, "
                    "source_url TEXT, as_of TEXT, imported_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS companion_status (family TEXT NOT NULL, scope TEXT NOT NULL, "
                    "endpoint TEXT NOT NULL, status TEXT NOT NULL, http_status INTEGER, retrieved_at TEXT NOT NULL, "
                    "contract_checked TEXT NOT NULL, payload_sha256 TEXT, records INTEGER, "
                    "pagination_json TEXT, error TEXT, PRIMARY KEY (family, scope))")
        return {"tables": ["companion_records", "companion_status"]}


def _valid_daily(payload):
    return isinstance(payload, list)


def _valid_top_changes(payload):
    return isinstance(payload, dict) and any(isinstance(payload.get(k), dict) for k in ("top_gainers", "top_losers"))


def _valid_foreign_flow(payload):
    return isinstance(payload, dict) and isinstance(payload.get("data"), list)


def _valid_quarterly(payload):
    return isinstance(payload, list)


def _valid_filings(payload):
    return isinstance(payload, dict) and isinstance(payload.get("results"), list)


def _valid_corporate_actions(payload):
    return isinstance(payload, dict) or isinstance(payload, list)


VALIDATORS = {"movers": _valid_top_changes, "daily": _valid_daily, "quarterly": _valid_quarterly,
              "foreign_flow": _valid_foreign_flow, "filings": _valid_filings,
              "corporate_actions": _valid_corporate_actions}


def _record_id(family, *parts):
    return hashlib.sha256("|".join([family, *[str(part) for part in parts]]).encode("utf-8")).hexdigest()[:20]


def _number(value):
    """Keep documented nulls as None; never turn missing into zero."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def normalize(family, payload, *, scope):
    """Typed records with entity, value, unit, period/as-of and deterministic identity."""
    rows = []
    if family == "daily":
        for item in payload:
            if not isinstance(item, dict) or not item.get("date"):
                continue
            symbol = str(item.get("symbol") or scope.get("symbol") or "").removesuffix(".JK")
            rows.append({"id": _record_id(family, symbol, item["date"]), "family": family, "symbol": symbol,
                         "period": item["date"], "as_of": item["date"], "source_url": None,
                         "value": {"close": _number(item.get("close")), "open": _number(item.get("open")),
                                   "high": _number(item.get("high")), "low": _number(item.get("low")),
                                   "volume": _number(item.get("volume")), "market_cap": _number(item.get("market_cap")),
                                   "unit": "IDR", "kind": "daily_price"}})
    elif family == "movers":
        for classification, periods in payload.items():
            if classification not in ("top_gainers", "top_losers") or not isinstance(periods, dict):
                continue
            for period, items in periods.items():
                for item in items or []:
                    if not isinstance(item, dict) or not item.get("symbol"):
                        continue
                    symbol = str(item["symbol"]).removesuffix(".JK")
                    rows.append({"id": _record_id(family, classification, period, symbol), "family": family,
                                 "symbol": symbol, "period": period,
                                 "as_of": item.get("latest_close_date"), "source_url": None,
                                 "value": {"classification": classification, "name": item.get("name"),
                                           "price_change": _number(item.get("price_change")),
                                           "last_close_price": _number(item.get("last_close_price")),
                                           "unit": "IDR/desimal", "kind": "movers", "subset": True}})
    elif family == "foreign_flow":
        symbol = str(payload.get("symbol") or scope.get("symbol") or "").removesuffix(".JK")
        for item in payload.get("data", []):
            if not isinstance(item, dict) or not item.get("date"):
                continue
            rows.append({"id": _record_id(family, symbol, item["date"]), "family": family, "symbol": symbol,
                         "period": item["date"], "as_of": item["date"], "source_url": None,
                         "value": {"net_foreign_inflow": _number(item.get("net_foreign_inflow")),
                                   "foreign_buy_idr": _number(item.get("foreign_buy_idr")),
                                   "foreign_sell_idr": _number(item.get("foreign_sell_idr")),
                                   "foreign_share": _number(item.get("foreign_share")),
                                   "unit": "IDR", "kind": "foreign_flow",
                                   "definition": ("arus bersih investor asing menurut asal investor, bukan asal broker; "
                                                  "porsi asing setiap broker dijumlahkan lintas broker")}})
    elif family == "quarterly":
        for item in payload:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or scope.get("symbol") or "").removesuffix(".JK")
            report_date = item.get("date") or item.get("report_date")
            if not symbol or not report_date:
                continue
            rows.append({"id": _record_id(family, symbol, report_date), "family": family, "symbol": symbol,
                         "period": report_date, "as_of": None, "source_url": None,
                         "value": {"revenue": _number(item.get("revenue")), "earnings": _number(item.get("earnings")),
                                   "total_assets": _number(item.get("total_assets")),
                                   "total_equity": _number(item.get("total_equity")),
                                   "unit": "IDR", "kind": "quarterly", "period_label": report_date}})
    elif family == "filings":
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").removesuffix(".JK")
            rows.append({"id": _record_id(family, symbol, item.get("timestamp"), item.get("holder_name")),
                         "family": family, "symbol": symbol, "period": (item.get("timestamp") or "")[:10],
                         "as_of": (item.get("timestamp") or "")[:10], "source_url": item.get("source"),
                         "value": {"transaction_type": item.get("transaction_type"),
                                   "holder_type": item.get("holder_type"), "holder_name": item.get("holder_name"),
                                   "amount_transaction": _number(item.get("amount_transaction")),
                                   "price": _number(item.get("price")),
                                   "transaction_value": _number(item.get("transaction_value")),
                                   "share_percentage_before": _number(item.get("share_percentage_before")),
                                   "share_percentage_after": _number(item.get("share_percentage_after")),
                                   "unit": "IDR/saham/persen", "kind": "filing",
                                   "claim_note": "judul filing bukan klaim yang ditinjau"}})
    elif family == "corporate_actions":
        groups = payload if isinstance(payload, list) else [
            {"type": key, "rows": value} for key, value in payload.items() if isinstance(value, list)]
        for group in groups:
            if not isinstance(group, dict):
                continue
            if "rows" in group:
                action_type, group_rows = group.get("type"), group["rows"]
            else:
                action_type, group_rows = group.get("type") or group.get("action_type"), [group]
            for item in group_rows or []:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or scope.get("symbol") or "").removesuffix(".JK")
                dates = {kind: item.get(kind) if kind in item else item.get(f"{kind}_date")
                         for kind in DATE_KINDS}
                rows.append({"id": _record_id(family, symbol, action_type,
                                              item.get("announcement_date") or item.get("ex_date")
                                              or item.get("record_date") or item.get("payment_date")),
                             "family": family, "symbol": symbol,
                             "period": next((value for value in dates.values() if value), None),
                             "as_of": None, "source_url": item.get("source") or item.get("url"),
                             "value": {"action_type": action_type, "dates": dates,
                                       "status": item.get("status") or "tercatat",
                                       "unit": "tanggal", "kind": "corporate_action",
                                       "note": "tanggal peristiwa terpisah dari tanggal terbit berita"}})
    return rows


def _pagination(family, payload, scope):
    if family == "filings" and isinstance(payload, dict):
        page = payload.get("pagination") or {}
        total = page.get("total_count")
        showing = page.get("showing")
        complete = not page.get("has_next") if page.get("has_next") is not None else None
        return {"total": total, "showing": showing, "complete": complete, "next_offset": page.get("next_offset")}
    if family == "daily":
        return {"total": len(payload), "showing": len(payload), "complete": True, "next_offset": None}
    if family == "foreign_flow":
        dates = {item.get("date") for item in payload.get("data", []) if isinstance(item, dict)}
        expected = scope.get("expect_days")
        complete = None if not expected else len(dates) >= int(expected)
        return {"total": len(dates), "showing": len(dates), "complete": complete,
                "expected_days": expected, "next_offset": None}
    return {"total": None, "showing": None, "complete": None, "next_offset": None}


def import_family(db, family, payload, *, scope, http_status=200, retrieved_at=None):
    """Validate, normalize and persist one family's response with its own status. Idempotent."""
    if family not in CONTRACT:
        raise ValueError("keluarga companion tidak dikenal")
    retrieved = retrieved_at or _now()
    contract = CONTRACT[family]
    endpoint = contract["path"].format(symbol=scope.get("symbol", ""))
    status = {"family": family, "scope": scope, "endpoint": endpoint, "http_status": http_status,
              "retrieved_at": retrieved, "contract_checked": contract["checked"],
              "payload_sha256": _hash(payload), "records": 0, "error": None}
    migrate_companion(db)
    if not VALIDATORS[family](payload):
        status.update({"status": "malformed", "error": "respons tidak sesuai kontrak terdokumentasi"})
        _write_status(db, status)
        return {"status": status, "records": []}
    records = normalize(family, payload, scope=scope)
    page = _pagination(family, payload, scope)
    status["pagination"] = page
    if not records:
        status["status"] = "empty"
    elif page.get("complete") is False:
        status["status"] = "incomplete"
    else:
        status["status"] = "success"
    with closing(sqlite3.connect(db)) as con, con:
        for record in records:
            con.execute("INSERT OR IGNORE INTO companion_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (record["id"], record["family"], record["symbol"], json.dumps(scope, sort_keys=True),
                         record["period"], json.dumps(record["value"], sort_keys=True), record["source_url"],
                         record["as_of"], retrieved))
    status["records"] = len(records)
    _write_status(db, status)
    return {"status": status, "records": records}


def _write_status(db, status):
    with closing(sqlite3.connect(db)) as con, con:
        con.execute("INSERT OR REPLACE INTO companion_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (status["family"], json.dumps(status["scope"], sort_keys=True), status["endpoint"],
                     status["status"], status.get("http_status"), status["retrieved_at"],
                     status["contract_checked"], status["payload_sha256"], status.get("records", 0),
                     json.dumps(status.get("pagination"), sort_keys=True), status.get("error")))


def classify_failure(exc):
    """Distinguish a retryable transient failure from a terminal permission decision."""
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return {"status": "denied", "retryable": False, "http_status": exc.code}
        if exc.code == 404:
            return {"status": "not_found", "retryable": False, "http_status": exc.code}
        if exc.code == 429:
            return {"status": "rate_limited", "retryable": True, "http_status": exc.code}
        if 500 <= exc.code < 600:
            return {"status": "server_error", "retryable": True, "http_status": exc.code}
        return {"status": "failed", "retryable": False, "http_status": exc.code}
    if isinstance(exc, (URLError, TimeoutError)):
        return {"status": "timeout", "retryable": True, "http_status": None}
    return {"status": "failed", "retryable": False, "http_status": None}


def fetch_family(db, family, *, scope, api_key, transport=None, max_attempts=None):
    """Acquire one family through the caller-supplied transport (or urlopen) and import it.

    The transport is injectable so every documented state can be exercised offline; no key is
    ever logged and no other family's data is touched on failure.
    """
    if family not in CONTRACT:
        raise ValueError("keluarga companion tidak dikenal")
    policy = _retry_policy()
    attempts = max_attempts or policy["attempts"]
    contract = CONTRACT[family]
    params = {key: scope[key] for key in contract["params"] if key in scope}
    url = BASE + contract["path"].format(symbol=scope.get("symbol", "")) + ("?" + urlencode(params) if params else "")
    opener = transport or (lambda request, timeout: urlopen(request, timeout=timeout))
    last = None
    for attempt in range(1, attempts + 1):
        request = Request(url, headers={"Authorization": api_key or "", "Accept": "application/json",
                                        "User-Agent": "Ronce-MVP/0.1"})
        try:
            payload = opener(request, 25)
            if hasattr(payload, "read") and not isinstance(payload, (dict, list)):
                payload = json.load(payload)
        except Exception as exc:  # noqa: BLE001 - classified below, never re-raised blind
            last = classify_failure(exc)
            if not last["retryable"] or attempt == attempts:
                migrate_companion(db)
                status = {"family": family, "scope": scope, "endpoint": contract["path"].format(symbol=scope.get("symbol", "")),
                          "status": last["status"], "http_status": last["http_status"], "retrieved_at": _now(),
                          "contract_checked": contract["checked"], "payload_sha256": None, "records": 0,
                          "pagination": {"total": None, "showing": None, "complete": None, "next_offset": None},
                          "error": f"{type(exc).__name__}: {last['status']}"}
                _write_status(db, status)
                return {"status": status, "records": [], "attempts": attempt}
            continue
        return import_family(db, family, payload, scope=scope)
    return {"status": last, "records": [], "attempts": attempts}


def companion_state(db):
    """Read model for export: per-family status plus normalized records, newest status wins."""
    migrate_companion(db)
    with closing(sqlite3.connect(db)) as con:
        statuses = [dict(zip(("family", "scope", "endpoint", "status", "http_status", "retrieved_at",
                              "contract_checked", "payload_sha256", "records", "pagination", "error"), row))
                    for row in con.execute("SELECT family, scope, endpoint, status, http_status, retrieved_at, "
                                           "contract_checked, payload_sha256, records, pagination_json, error "
                                           "FROM companion_status ORDER BY family")]
        records = [dict(zip(("id", "family", "symbol", "scope", "period", "value", "source_url", "as_of", "imported_at"), row))
                   for row in con.execute("SELECT id, family, symbol, scope, period, value_json, source_url, "
                                          "as_of, imported_at FROM companion_records ORDER BY family, symbol, period")]
    for row in statuses:
        row["scope"] = json.loads(row["scope"])
        row["pagination"] = json.loads(row["pagination"]) if row["pagination"] else None
    for row in records:
        row["value"] = json.loads(row["value"])
    return {"contract": {family: {"path": spec["path"], "checked": spec["checked"], "cost": spec["cost"],
                                  "envelope": spec["envelope"]} for family, spec in CONTRACT.items()},
            "date_kinds": list(DATE_KINDS), "action_types": list(ACTION_TYPES),
            "status": statuses, "records": records}
