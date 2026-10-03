"""Durable offline outbox for approved X/Threads editions.

The outbox is a local queue of exact approved posts. It contains no network transport and no
credentials: rows advance only when the caller reports a transport result or a readback through
`outbox_record` / `outbox_readback`, and the state machine refuses blind retries of ambiguous
writes — an ambiguous slot must be resolved by readback (or an explicit operator `confirm_absent`)
before it can be submitted again. Live publishing stays off; planning requires an approved edition
whose bound story revisions are still current (enforced by `ronce.publication_manifest`).

States and transitions:
    planned     -> created | ambiguous | failed | rate_limited | auth_expired
    created     -> verified (readback matches) | mismatch (readback differs)
    ambiguous   -> verified | mismatch | failed (only with confirm_absent=True)
    failed / auth_expired / rate_limited -> created | ambiguous | ... (retry after the caller's fix/wait)
    verified    -> terminal (an identical readback repeat is an idempotent no-op)
    mismatch    -> manual review only; no automatic action

`outbox_status` reports each slot's state and the next safe action. The action mapping extends
`adapters.plan_next_action` with the outbox's readback-to-verify step: `created` still needs a
readback before it counts as verified, so its next action is `readback_first`, not `already_done`.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import adapters
import ronce

OUTCOMES = ("created", "ambiguous", "timeout", "partial_failure", "failed", "auth_expired", "rate_limited")
TERMINAL = ("verified", "mismatch")
ACTIONS = {"planned": "submit", "created": "readback_first", "ambiguous": "readback_first",
           "failed": "retry_after_fix", "auth_expired": "retry_after_fix",
           "rate_limited": "wait_then_retry", "verified": "already_done", "mismatch": "manual_review"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS outbox_posts ("
                "run_id TEXT NOT NULL, edition_id TEXT NOT NULL, platform TEXT NOT NULL, "
                "ordinal INTEGER NOT NULL, account TEXT NOT NULL, text TEXT NOT NULL, "
                "text_hash TEXT NOT NULL, edition_hash TEXT NOT NULL, state TEXT NOT NULL, "
                "external_id TEXT, retry_after TEXT, readback_json TEXT, reason TEXT, "
                "updated_at TEXT NOT NULL, "
                "PRIMARY KEY (run_id, edition_id, platform, ordinal))")


def _row_view(row):
    return {"run_id": row[0], "edition_id": row[1], "platform": row[2], "ordinal": row[3],
            "account": row[4], "text": row[5], "text_hash": row[6], "edition_hash": row[7],
            "state": row[8], "external_id": row[9], "retry_after": row[10],
            "readback": json.loads(row[11]) if row[11] else None, "reason": row[12],
            "updated_at": row[13], "next_action": ACTIONS.get(row[8], "manual_review")}


def _fetch(con, run_id, edition_id, platform, ordinal):
    return con.execute("SELECT run_id, edition_id, platform, ordinal, account, text, text_hash, "
                       "edition_hash, state, external_id, retry_after, readback_json, reason, updated_at "
                       "FROM outbox_posts WHERE run_id=? AND edition_id=? AND platform=? AND ordinal=?",
                       (run_id, edition_id, platform, ordinal)).fetchone()


def _keyed(con, run_id, edition_id, platform):
    return con.execute("SELECT run_id, edition_id, platform, ordinal, account, text, text_hash, "
                       "edition_hash, state, external_id, retry_after, readback_json, reason, updated_at "
                       "FROM outbox_posts WHERE run_id=? AND edition_id=? AND platform=? ORDER BY ordinal",
                       (run_id, edition_id, platform)).fetchall()


def outbox_plan(db, run_id, edition_id, platform, *, account):
    """Materialize one durable row per approved post; idempotent, pinned to the approval hashes.

    Refuses an unapproved edition (via the engine manifest), a differing account on a re-plan, or a
    differing text/edition hash for an existing slot.
    """
    manifest = ronce.publication_manifest(db, run_id, edition_id, platform, account=account)
    with closing(ronce._connect(db)) as con, con:
        _ensure_table(con)
        for post in manifest["posts"]:
            ordinal = post["ordinal"]
            existing = _fetch(con, run_id, edition_id, platform, ordinal)
            if existing:
                row = _row_view(existing)
                if (row["text_hash"] != post["text_hash"] or row["account"] != account
                        or row["edition_hash"] != manifest["edition_hash"]):
                    raise ValueError("slot outbox terkunci; teks/akun/edisi berbeda dari rencana awal")
                continue
            con.execute("INSERT INTO outbox_posts VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', NULL, NULL, NULL, NULL, ?)",
                        (run_id, edition_id, platform, ordinal, account, post["text"], post["text_hash"],
                         manifest["edition_hash"], _now()))
        rows = [_row_view(row) for row in _keyed(con, run_id, edition_id, platform)]
    return {"run_id": run_id, "edition_id": edition_id, "platform": platform,
            "edition_hash": manifest["edition_hash"], "account": account, "posts": rows,
            "api_write": False}


def outbox_record(db, run_id, edition_id, platform, ordinal, outcome, *,
                  external_id=None, retry_after=None):
    """Record one classified transport result for one slot.

    Refuses: unknown outcomes, `created` without an external id, any advance on a terminal slot,
    and a re-submit while the slot is `ambiguous` or `created` (readback must resolve those first).
    """
    if outcome not in OUTCOMES:
        raise ValueError("hasil transport tidak dikenal")
    if outcome == "created" and (not isinstance(external_id, str) or not external_id.strip()):
        raise ValueError("created tanpa external_id tidak boleh dicatat")
    with closing(ronce._connect(db)) as con, con:
        _ensure_table(con)
        row = _fetch(con, run_id, edition_id, platform, ordinal)
        if row is None:
            raise ValueError("slot outbox belum direncanakan")
        view = _row_view(row)
        if view["state"] == "mismatch":
            raise ValueError("slot mismatch; perlu tinjauan manual")
        if view["state"] in TERMINAL:
            raise ValueError("slot selesai; tidak ada tindakan otomatis")
        if view["state"] in ("ambiguous", "created"):
            raise ValueError("slot menunggu baca balik; kirim ulang buta ditolak")
        new_state = "created" if outcome == "created" else (
            "rate_limited" if outcome == "rate_limited" else (
                "auth_expired" if outcome == "auth_expired" else (
                    "ambiguous" if outcome in ("ambiguous", "timeout", "partial_failure") else "failed")))
        con.execute("UPDATE outbox_posts SET state=?, external_id=?, retry_after=?, reason=?, updated_at=? "
                    "WHERE run_id=? AND edition_id=? AND platform=? AND ordinal=?",
                    (new_state, external_id if new_state == "created" else None,
                     retry_after if new_state == "rate_limited" else None,
                     None if new_state == "created" else f"transport: {outcome}",
                     _now(), run_id, edition_id, platform, ordinal))
        return _row_view(_fetch(con, run_id, edition_id, platform, ordinal))


def outbox_readback(db, run_id, edition_id, platform, ordinal, payload, *, confirm_absent=False):
    """Record a readback result. `payload=None` means "not found"; absence only becomes `failed`
    with an explicit operator confirmation, never by inference."""
    with closing(ronce._connect(db)) as con, con:
        _ensure_table(con)
        row = _fetch(con, run_id, edition_id, platform, ordinal)
        if row is None:
            raise ValueError("slot outbox belum direncanakan")
        view = _row_view(row)
        if view["state"] == "mismatch":
            raise ValueError("slot ditandai mismatch; perlu tinjauan manual")
        if view["state"] == "verified":
            if payload is not None:
                matched, _ = adapters.verify_readback(platform, payload,
                                                      expected_account=view["account"],
                                                      expected_text=view["text"])
                if matched:
                    return view  # Idempotent repeat of the verifying readback.
            raise ValueError("slot sudah terverifikasi; hasil baca balik berbeda ditolak")
        if view["state"] not in ("created", "ambiguous"):
            raise ValueError("baca balik hanya berlaku setelah kirim")
        if payload is None:
            if not confirm_absent:
                raise ValueError("absen tanpa konfirmasi operator bukan bukti; slot tetap menunggu")
            con.execute("UPDATE outbox_posts SET state='failed', reason=?, updated_at=? "
                        "WHERE run_id=? AND edition_id=? AND platform=? AND ordinal=?",
                        ("dikonfirmasi absen oleh operator", _now(), run_id, edition_id, platform, ordinal))
            return _row_view(_fetch(con, run_id, edition_id, platform, ordinal))
        matched, reason = adapters.verify_readback(platform, payload, expected_account=view["account"],
                                                   expected_text=view["text"])
        new_state = "verified" if matched else "mismatch"
        con.execute("UPDATE outbox_posts SET state=?, readback_json=?, reason=?, updated_at=? "
                    "WHERE run_id=? AND edition_id=? AND platform=? AND ordinal=?",
                    (new_state, json.dumps(payload, ensure_ascii=False), None if matched else reason,
                     _now(), run_id, edition_id, platform, ordinal))
        return _row_view(_fetch(con, run_id, edition_id, platform, ordinal))


def outbox_status(db, run_id, edition_id, platform):
    """Read model: every slot with its state and next safe action."""
    with closing(ronce._connect(db)) as con:
        try:
            rows = _keyed(con, run_id, edition_id, platform)
        except sqlite3.OperationalError:
            rows = []
    posts = [_row_view(row) for row in rows]
    return {"run_id": run_id, "edition_id": edition_id, "platform": platform,
            "posts": posts, "api_write": False,
            "pending": [post["ordinal"] for post in posts if post["state"] != "verified"]}


def outbox_text_hash(text):
    """The hash pinned per slot; exposed so callers can compare without importing hashlib."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
