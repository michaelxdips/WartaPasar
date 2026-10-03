"""Private local editorial workbench: one operator, loopback only, engine-gated actions.

This is a local runtime, not a deployment. It binds to 127.0.0.1, authenticates one configured
operator against a salted hash supplied by environment, and routes every editorial mutation
through the existing ronce engine gates. The public static export stays read-only and is never
served from here; live publishing stays off and there is no external-release action.

Security posture (stated, not implied):
- the secret is compared in constant time against `RONCE_WORKBENCH_SECRET_HASH`
  (`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`); an unset or malformed hash fails startup
  closed, and a bare unsalted digest is refused, not accepted as "close enough";
- sessions are 32 random bytes in an HttpOnly, SameSite=Strict cookie, persisted server-side with
  an explicit expiry; logout and expiry invalidate immediately;
- mutations are POST-only, require the session-bound CSRF header, and require a loopback Host and
  a same-origin Origin; reads never mutate;
- the request body cannot establish identity: reviewer names come from the configured principal,
  never from JSON;
- every decision carries `expected_revision_id`, checked inside the engine's write transaction,
  so a stale tab is refused with 409 conflict feedback rather than silently overwriting;
- audit rows record principal, action, target, expected/actual revision, outcome and time; error
  responses and stderr output are redacted of the secret and cookie values.

Evidence-interpretation limits stay visible in the page: numeric validation is token/scale
matching, not semantic understanding, and an ambiguous source blocks the candidate instead of
being guessed.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import traceback
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import export as export_module
import ronce

SESSION_COOKIE = "ronce_workbench_session"
CSRF_HEADER = "X-Ronce-CSRF"
SESSION_TTL_SECONDS = 8 * 3600
HASH_PREFIX = "pbkdf2_sha256"
MIN_ITERATIONS = 100_000
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
LIVE_PUBLISHING = False  # A constant, not a flag: this module has no external-release action.
MAX_BODY_BYTES = 2_000_000
_OPERATOR_ENV = "RONCE_WORKBENCH_OPERATOR"
_SECRET_ENV = "RONCE_WORKBENCH_SECRET_HASH"
_DB_ENV = "RONCE_WORKBENCH_DB"
_EXPORT_DIR_ENV = "RONCE_WORKBENCH_EXPORT_DIR"


class ConfigError(ValueError):
    """Startup configuration is missing or invalid; the server must not start."""


class Conflict(ValueError):
    """The request conflicts with current server state (HTTP 409)."""


def _parse_hash(stored):
    """Parse the verification format; None when malformed or weaker than the floor."""
    if not isinstance(stored, str):
        return None
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != HASH_PREFIX:
        return None
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
    except ValueError:
        return None
    if iterations < MIN_ITERATIONS or len(salt) < 16 or len(expected) != 32:
        return None
    return iterations, salt, expected


def hash_secret(secret, *, salt=None, iterations=MIN_ITERATIONS):
    """Produce the storable verification format for one secret. Never log the input."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret wajib teks tidak kosong")
    if type(iterations) is not int or iterations < MIN_ITERATIONS:
        raise ValueError(f"iterasi minimal {MIN_ITERATIONS}")
    salt = secrets.token_bytes(16) if salt is None else salt
    if not isinstance(salt, bytes) or len(salt) < 16:
        raise ValueError("salt minimal 16 byte")
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
    return f"{HASH_PREFIX}${iterations}${salt.hex()}${digest.hex()}"


def verify_secret(secret, stored):
    """Constant-time verification against the stored format; unknown formats are refused."""
    if not isinstance(secret, str) or not secret:
        return False
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    iterations, salt, expected = parsed
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def redact(text, secrets_to_hide):
    """Remove secret material from any outbound text; used for errors and logs."""
    result = str(text)
    for secret in secrets_to_hide:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def _now():
    return datetime.now(timezone.utc)


def _iso(moment):
    return moment.isoformat()


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _safe_segment(label, value):
    """One path segment from user input: no separators, no dot-only names, bounded length."""
    if not isinstance(value, str) or not _SAFE_SEGMENT.match(value) or value in (".", ".."):
        raise ValueError(f"{label} hanya huruf, angka, titik, garis bawah, dan strip (maks 64)")
    return value


def _action_label(path, payload):
    """Audit action name that matches the success-path label for the same operation."""
    if path == "/api/decision":
        action = payload.get("action")
        return f"decision:{action}" if isinstance(action, str) and action else "decision"
    return {"/api/origin-review": "origin-review", "/api/export": "export"}.get(path, path)


def _candidate_key(candidate):
    """Stable story key for one stored candidate row, or None when a required field is absent.

    Stored `decision_json` may predate this reader; a missing field must become a clear refusal,
    never an unhandled KeyError that drops the connection.
    """
    if not isinstance(candidate, dict):
        return None
    fields = (candidate.get("symbol"), candidate.get("topic"),
              candidate.get("action"), candidate.get("date"))
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        return None
    return ronce.story_identity(symbol=fields[0], topic=fields[1], action=fields[2], date=fields[3])


def _one_revision(expected):
    if isinstance(expected, dict) and len(expected) == 1:
        value = next(iter(expected.values()))
        return value if isinstance(value, str) else None
    return None


class Workbench:
    """Owns configuration, the session table and the engine calls. One instance per server."""

    def __init__(self, *, db, operator, secret_hash, export_dir, session_ttl=SESSION_TTL_SECONDS):
        if not isinstance(operator, str) or not operator.strip():
            raise ConfigError(f"{_OPERATOR_ENV} wajib diisi (nama operator lokal)")
        if not isinstance(secret_hash, str) or not secret_hash.strip():
            raise ConfigError(f"{_SECRET_ENV} wajib diisi (format {HASH_PREFIX}$<iterasi>$<salt>$<hash>)")
        if _parse_hash(secret_hash) is None:
            raise ConfigError(f"{_SECRET_ENV} tidak valid: hash tidak dapat diverifikasi pada format "
                              f"{HASH_PREFIX}$<iterasi>$<salt>$<hash>; hash polos tanpa salt ditolak")
        if type(session_ttl) is not int or session_ttl < 1:
            raise ConfigError("session_ttl harus detik positif")
        self.db = Path(db)
        self.operator = operator.strip()
        self.secret_hash = secret_hash
        self.export_dir = Path(export_dir)
        self.session_ttl = session_ttl
        self._lock = threading.Lock()
        self._sessions = {}  # token -> {"csrf", "expires_at"}
        self._export_lock = threading.Lock()
        self._init_store()

    # -- store -----------------------------------------------------------------
    def _init_store(self):
        self.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(ronce._connect(self.db)) as con, con:
            con.execute("CREATE TABLE IF NOT EXISTS workbench_audit ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, principal TEXT NOT NULL, "
                        "action TEXT NOT NULL, target TEXT NOT NULL, "
                        "expected_revision TEXT, actual_revision TEXT, result TEXT NOT NULL, "
                        "at TEXT NOT NULL)")

    def audit(self, principal, action, target, result, *, expected_revision=None, actual_revision=None):
        with closing(ronce._connect(self.db)) as con, con:
            con.execute("INSERT INTO workbench_audit (principal, action, target, expected_revision, "
                        "actual_revision, result, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (principal, action, str(target), expected_revision, actual_revision, result,
                         _iso(_now())))

    def audit_tail(self, limit=50):
        with closing(ronce._connect(self.db)) as con:
            try:
                rows = con.execute("SELECT principal, action, target, expected_revision, actual_revision, "
                                   "result, at FROM workbench_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(zip(("principal", "action", "target", "expected_revision", "actual_revision",
                          "result", "at"), row)) for row in rows]

    # -- sessions --------------------------------------------------------------
    def login(self, secret):
        """Verify one secret; on success mint a session. Never distinguishes failure causes."""
        if not verify_secret(secret, self.secret_hash):
            return None
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = {"csrf": csrf, "expires_at": _now() + timedelta(seconds=self.session_ttl)}
        return token, csrf

    def session_for(self, token):
        """Return the live session view, expiring it on read when past its deadline."""
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            entry = self._sessions.get(token)
            if entry is None:
                return None
            if entry["expires_at"] <= _now():
                del self._sessions[token]
                return None
            return {"csrf": entry["csrf"], "expires_at": entry["expires_at"]}

    def logout(self, token):
        with self._lock:
            return self._sessions.pop(token, None) is not None

    # -- reads -----------------------------------------------------------------
    def runs(self):
        with closing(ronce._connect(self.db)) as con:
            try:
                rows = con.execute("SELECT id, cutoff, saved_at FROM runs ORDER BY saved_at DESC, id").fetchall()
            except sqlite3.OperationalError:
                return []
        return [{"run_id": row[0], "cutoff": row[1], "saved_at": row[2]} for row in rows]

    def _revision_index(self, con):
        try:
            rows = con.execute("SELECT story_key, revision_id, decision, content_hash, created_at "
                               "FROM story_revisions ORDER BY created_at, rowid").fetchall()
        except sqlite3.OperationalError:
            return {}, {}
        current, history = {}, {}
        for story_key, revision_id, decision, content_hash, created_at in rows:
            current[story_key] = revision_id
            history.setdefault(story_key, []).append(
                {"revision_id": revision_id, "decision": decision, "content_hash": content_hash,
                 "created_at": created_at})
        return current, history

    def candidates(self, run_id):
        """One run's candidates, each with its stable story key and current revision."""
        with closing(ronce._connect(self.db)) as con:
            row = con.execute("SELECT cutoff, decision_json FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("run tidak dikenal")
            try:
                candidates = json.loads(row[1])
            except ValueError as exc:
                raise ValueError("decision_json bukan JSON") from exc
            if not isinstance(candidates, list):
                raise ValueError("decision_json bukan daftar kandidat")
            current, _ = self._revision_index(con)
            registered = set()
            try:
                registered = {r[0] for r in con.execute("SELECT story_key FROM story_identities")}
            except sqlite3.OperationalError:
                pass
        enriched = []
        for candidate in candidates:
            key = _candidate_key(candidate)
            if key is None:
                raise ValueError("baris kandidat tidak lengkap: perlu symbol, topic, action, dan date")
            enriched.append({**candidate, "story_key": key,
                             "current_revision_id": current.get(key),
                             "registered": key in registered})
        return {"run_id": run_id, "cutoff": row[0], "candidates": enriched}

    def _find_candidate(self, con, story_key):
        try:
            rows = con.execute("SELECT id, decision_json FROM runs ORDER BY saved_at DESC, id").fetchall()
        except sqlite3.OperationalError:
            return None, None
        for run_id, decision_json in rows:
            try:
                candidates = json.loads(decision_json)
            except ValueError:
                continue
            for candidate in candidates if isinstance(candidates, list) else []:
                if _candidate_key(candidate) == story_key:
                    return candidate, run_id
        return None, None

    def candidate_detail(self, story_key):
        """One story's context: decision, counts, evidence spans, current revision, history.

        Works before the version migration (registry rows absent) and after it.
        """
        with closing(ronce._connect(self.db)) as con:
            try:
                identity = con.execute("SELECT symbol, topic_id, action, date FROM story_identities "
                                       "WHERE story_key=?", (story_key,)).fetchone()
            except sqlite3.OperationalError:
                identity = None
            try:
                status = con.execute("SELECT status, reason, evidence FROM story_status WHERE story_key=?",
                                     (story_key,)).fetchone()
                revision_rows = con.execute(
                    "SELECT revision_id, run_id, content_hash, decision, payload, created_at FROM story_revisions "
                    "WHERE story_key=? ORDER BY created_at, rowid", (story_key,)).fetchall()
                relations = con.execute(
                    "SELECT relation_id, kind, from_story, to_story, from_revision, to_revision, reason, evidence "
                    "FROM story_relations WHERE from_story=? OR to_story=? ORDER BY created_at, relation_id",
                    (story_key, story_key)).fetchall()
            except sqlite3.OperationalError:
                status, revision_rows, relations = None, [], []
            candidate, run_id = self._find_candidate(con, story_key)
            review_row = None
            review_run_id = None
            for revision in reversed(revision_rows):
                if revision[1]:
                    review_row = con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?",
                                             (revision[1],)).fetchone()
                    if review_row:
                        review_run_id = revision[1]
                        break
            current, _ = self._revision_index(con)
        if identity is None and candidate is None:
            raise ValueError("story_key tidak dikenal")
        revisions = [{"revision_id": row[0], "run_id": row[1], "content_hash": row[2], "decision": row[3],
                      "payload": json.loads(row[4]), "created_at": row[5]} for row in revision_rows]
        relation_rows = [{"relation_id": row[0], "kind": row[1], "from_story": row[2], "to_story": row[3],
                          "from_revision": row[4], "to_revision": row[5], "reason": row[6], "evidence": row[7]}
                         for row in relations]
        try:
            with closing(ronce._connect(self.db)) as con:
                comparisons = ronce.story_comparisons(con, story_key, relation_rows)
        except sqlite3.OperationalError:
            comparisons = []
        claims = []
        if review_row:
            for claim in json.loads(review_row[0])["claims"]:
                if claim.get("story_key") and ronce.story_identity(**claim["story_key"]) == story_key:
                    claims.append(claim)
        return {
            "story_key": story_key,
            "symbol": identity[0] if identity else candidate["symbol"],
            "topic_id": identity[1] if identity else ronce.topic_id(candidate["topic"]),
            "action": identity[2] if identity else candidate["action"],
            "date": identity[3] if identity else candidate["date"],
            "status": {"status": status[0], "reason": status[1], "evidence": status[2]} if status
            else {"status": "active", "reason": None, "evidence": None},
            "candidate": candidate,
            "source_run_id": run_id,
            "review_run_id": review_run_id,
            "claims": claims,
            "revisions": revisions,
            "current_revision_id": current.get(story_key),
            "relations": relation_rows,
            "comparisons": comparisons,
        }

    # -- mutations (each engine-gated; expected revision checked inside the transaction) -----
    def record_origin(self, run_id, source, entity, rationale, *, expected_revisions):
        """Write one origin decision for the configured principal, bound to the source content hash."""
        if not isinstance(source, str) or not source.strip() or not isinstance(entity, str) or not entity.strip():
            raise ValueError("sumber dan entitas wajib diisi")
        if not isinstance(rationale, str) or len(rationale.strip()) < 12:
            raise ValueError("alasan tinjauan asal minimal 12 karakter")
        with closing(ronce._connect(self.db)) as con, con:
            ronce._require_expected_revisions(con, expected_revisions)
            payload = ronce._article_payload(con, run_id, source)
            if payload is None:
                raise ValueError("sumber tinjauan asal tidak ada pada arsip")
            content_hash = ronce._article_content_hash(payload)
            con.execute("CREATE TABLE IF NOT EXISTS origin_reviews (run_id TEXT NOT NULL, source TEXT NOT NULL, "
                        "entity TEXT NOT NULL, reviewer TEXT NOT NULL, rationale TEXT NOT NULL, "
                        "content_hash TEXT NOT NULL, decided_at TEXT NOT NULL, "
                        "PRIMARY KEY (run_id, source, entity))")
            previous = con.execute("SELECT content_hash FROM origin_reviews WHERE run_id=? AND source=? AND entity=?",
                                   (run_id, source, entity)).fetchone()
            if previous and previous[0] != content_hash:
                raise ValueError("konten sumber berubah sejak tinjauan asal; tinjauan perlu diulang")
            con.execute("INSERT OR REPLACE INTO origin_reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (run_id, source, entity, self.operator, rationale.strip(), content_hash, _iso(_now())))
        return {"run_id": run_id, "source": source, "entity": entity, "reviewer": self.operator,
                "content_hash": content_hash}

    def review(self, run_id, claims, *, expected_revisions):
        """Record reviewed claims for the configured principal; the engine re-validates everything.

        After a successful review the version model is migrated and the run's stories are
        registered idempotently, so the new immutable revision is what later decisions bind to.
        """
        record = ronce.review_claims(self.db, run_id, self.operator, claims, reviewed=True,
                                     expected_revisions=expected_revisions)
        ronce.migrate(self.db)
        ronce.register_versioned_stories(self.db, run_id)
        return {"run_id": run_id, "editor": record["editor"], "claims": len(record["claims"]),
                "reviewed_at": record["reviewed_at"]}

    def current_revision(self, story_key):
        with closing(ronce._connect(self.db)) as con:
            return ronce.current_revision_id(con, story_key)

    def approve(self, run_id, edition_id, platform, indexes, *, expected_revisions):
        """Render and approve exact posts; the revision precondition runs in the approval transaction."""
        posts = ronce.render_draft(self.db, run_id, edition_id, platform, indexes)
        saved = ronce.approve_edition(self.db, run_id, edition_id, platform, self.operator, posts,
                                      expected_revisions=expected_revisions)
        return {"run_id": run_id, "edition_id": edition_id, "platform": platform,
                "posts": saved["bound"]["posts"], "hash": saved["hash"],
                "approved_at": saved["approval"]["approved_at"]}

    def correct(self, story_key, *, reason, evidence, relation_kind, from_revision, to_revision,
                expected_revisions):
        """Record a typed correction relation; both endpoints must match the caller's expectation."""
        if relation_kind not in ("corrects", "supersedes"):
            raise ValueError("koreksi memakai jenis corrects atau supersedes")
        return ronce.add_relation(self.db, relation_kind, story_key, story_key, reason=reason,
                                  evidence=evidence, from_revision=from_revision, to_revision=to_revision,
                                  expected_revisions=expected_revisions)

    def withdraw(self, story_key, *, reason, evidence, expected_revisions):
        return ronce.withdraw_story(self.db, story_key, reason=reason, evidence=evidence,
                                    expected_revisions=expected_revisions)

    def hold(self, story_key, *, note, expected_revisions):
        """Explicit hold: the story must be known, the precondition checked, then audit records it."""
        if not isinstance(note, str) or not note.strip():
            raise ValueError("alasan tahan wajib diisi")
        with closing(ronce._connect(self.db)) as con, con:
            if not self._story_known(con, story_key):
                raise ValueError("story_key tidak ada pada registri identitas")
            ronce._require_expected_revisions(con, expected_revisions, require_keys={story_key})
        return {"story_key": story_key, "status": "held", "note": note.strip()}

    def _story_known(self, con, story_key):
        """A story exists once registered, or as a candidate in some run before registration."""
        try:
            if con.execute("SELECT 1 FROM story_identities WHERE story_key=?", (story_key,)).fetchone():
                return True
        except sqlite3.OperationalError:
            pass
        return self._find_candidate(con, story_key)[0] is not None

    def export(self, run_id, edition_id, platform, dataset, *, expected_revisions):
        """Export one approved edition atomically; the edition's own story revisions must be current.

        The revision check and the exclusive write run under one lock, so concurrent export
        requests cannot both pass the precondition and race the filesystem. Path segments are
        validated so an edition id can never traverse outside the export directory.
        """
        _safe_segment("edition_id", edition_id)
        _safe_segment("platform", platform)
        if dataset not in ("fixture", "archive"):
            raise ValueError("dataset harus fixture atau archive")
        with closing(ronce._connect(self.db)) as con:
            row = con.execute("SELECT payload FROM editions WHERE run_id=? AND edition_id=? AND platform=?",
                              (run_id, edition_id, platform)).fetchone()
            if row is None:
                raise ValueError("edisi belum disetujui")
            try:
                bound = json.loads(row[0]).get("bound") or {}
            except ValueError as exc:
                raise ValueError("integritas persetujuan rusak") from exc
            ronce._require_expected_revisions(con, expected_revisions,
                                              require_keys=set((bound.get("revisions") or {}).keys()))
        with self._export_lock:
            target = self.export_dir / edition_id / platform
            if target.exists():
                raise FileExistsError(f"ekspor sudah ada: {target}")
            manifest = export_module.export_edition(self.db, run_id, edition_id, platform, target,
                                                    dataset=dataset)
        return {"target": str(target), "edition_uid": manifest["edition_uid"],
                "counts": manifest["counts"], "dataset": manifest["dataset"],
                "live_publishing": False}

    def export_manifest(self, edition_id, platform):
        """Read-only summary of the produced private/public contract copy, for inspection."""
        _safe_segment("edition_id", edition_id)
        _safe_segment("platform", platform)
        manifest_path = self.export_dir / edition_id / platform / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("ekspor belum ada")
        return json.loads(manifest_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# HTTP boundary
# --------------------------------------------------------------------------- #

class WorkbenchHandler(BaseHTTPRequestHandler):
    """Request handler. Configuration lives on `self.server.workbench` (see `serve`)."""

    server_version = "RonceWorkbench/0.1"
    sys_version = ""
    timeout = 30

    def log_message(self, fmt, *args):  # Redacted, minimal, no request bodies.
        message = redact(fmt % args, self._secrets())
        sys.stderr.write(f"workbench {self.log_date_time_string()} {message}\n")

    def _secrets(self):
        return getattr(self.server, "redaction_secrets", ())

    @property
    def workbench(self):
        return self.server.workbench

    # -- request helpers -------------------------------------------------------
    def _host_ok(self):
        host = self.headers.get("Host") or ""
        if host.startswith("["):
            hostname = host.split("]")[0] + "]"
        else:
            hostname = host.rsplit(":", 1)[0]
        return hostname.lower() in ALLOWED_HOSTS

    def _origin_ok(self):
        """Same-origin only: the Origin's host *and* port must match this server.

        Any other loopback port is a different origin (a different local page), so it must not
        be able to write. A request without Origin is allowed because the Host check still
        applies and browsers send Origin on cross-origin writes.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
            return False
        return parsed.port == self.server.server_address[1]

    def _session(self):
        cookie = SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None, None
        token = morsel.value
        return token, self.workbench.session_for(token)

    def _read_json_body(self):
        length = self.headers.get("Content-Length")
        try:
            size = int(length) if length is not None else 0
        except ValueError as exc:
            raise ValueError("Content-Length tidak valid") from exc
        if size < 0 or size > MAX_BODY_BYTES:
            raise ValueError("ukuran badan permintaan di luar batas")
        raw = self.rfile.read(size) if size else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("badan permintaan bukan JSON valid") from exc
        if not isinstance(payload, dict):
            raise ValueError("badan permintaan harus objek JSON")
        return payload

    def _send(self, status, body, content_type, *, extra_headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _respond(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _fail(self, status, message):
        self._respond(status, {"error": redact(message, self._secrets())})

    # -- routing ---------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._fail(HTTPStatus.FORBIDDEN, "Host tidak diizinkan")
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query)
        _, session = self._session()
        if path in ("/", "/index.html"):
            try:
                page = _page_html(_PAGE_PATH()).replace(
                    "__BOOTSTRAP__", _safe_json(_bootstrap(self.workbench, session)))
            except OSError:
                return self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, "halaman workbench tidak terbaca")
            return self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8",
                              extra_headers=(("Content-Security-Policy",
                                              "default-src 'none'; style-src 'unsafe-inline'; "
                                              "script-src 'unsafe-inline'; connect-src 'self'; "
                                              "base-uri 'none'; form-action 'none'"),))
        if path == "/api/session":
            if session is None:
                return self._respond(HTTPStatus.OK, {"authenticated": False,
                                                     "live_publishing": LIVE_PUBLISHING})
            return self._respond(HTTPStatus.OK, {"authenticated": True, "operator": self.workbench.operator,
                                                 "csrf": session["csrf"],
                                                 "expires_at": _iso(session["expires_at"]),
                                                 "live_publishing": LIVE_PUBLISHING})
        if session is None:
            return self._fail(HTTPStatus.UNAUTHORIZED, "sesi tidak ada atau kedaluwarsa")
        try:
            return self._read_route(path, query)
        except Conflict as exc:
            return self._fail(HTTPStatus.CONFLICT, str(exc))
        except ValueError as exc:
            return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        except (OSError, sqlite3.Error):
            return self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, "operasi baca gagal")
        except Exception:
            # No unexpected exception may drop the connection without a response.
            self.log_error("unhandled read error: %s", traceback.format_exc())
            return self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, "kesalahan tak terduga pada pembacaan")

    def _read_route(self, path, query):
        if path == "/api/runs":
            return self._respond(HTTPStatus.OK, {"runs": self.workbench.runs()})
        if path == "/api/candidates":
            run_id = (query.get("run") or [""])[0]
            if not run_id:
                raise ValueError("parameter run wajib ada")
            return self._respond(HTTPStatus.OK, self.workbench.candidates(run_id))
        if path == "/api/audit":
            return self._respond(HTTPStatus.OK, {"audit": self.workbench.audit_tail()})
        if path == "/api/export":
            edition_id = (query.get("edition_id") or [""])[0]
            platform = (query.get("platform") or [""])[0]
            if not edition_id or not platform:
                raise ValueError("parameter edition_id dan platform wajib ada")
            return self._respond(HTTPStatus.OK, self.workbench.export_manifest(edition_id, platform))
        match = re.fullmatch(r"/api/candidate/([0-9a-f]{16})", path)
        if match:
            return self._respond(HTTPStatus.OK, self.workbench.candidate_detail(match.group(1)))
        return self._fail(HTTPStatus.NOT_FOUND, "rute tidak dikenal")

    def do_POST(self):
        if not self._host_ok():
            return self._fail(HTTPStatus.FORBIDDEN, "Host tidak diizinkan")
        if not self._origin_ok():
            return self._fail(HTTPStatus.FORBIDDEN, "Origin di luar lingkup lokal")
        path = urlsplit(self.path).path
        token, session = self._session()
        if path == "/api/login":
            return self._login()
        if session is None:
            return self._fail(HTTPStatus.UNAUTHORIZED, "sesi tidak ada atau kedaluwarsa")
        if not hmac.compare_digest(self.headers.get(CSRF_HEADER) or "", session["csrf"]):
            return self._fail(HTTPStatus.FORBIDDEN, "token CSRF tidak cocok")
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        try:
            return self._mutation_route(path, payload)
        except (Conflict, ronce.RevisionConflict) as exc:
            self.workbench.audit(self.workbench.operator, _action_label(path, payload),
                                 payload.get("story_key") or payload.get("run_id") or "-", "conflict",
                                 expected_revision=_one_revision(payload.get("expected_revisions")))
            return self._fail(HTTPStatus.CONFLICT, str(exc))
        except sqlite3.IntegrityError as exc:
            # A concurrent writer won the same unique row (e.g. two approvals of one edition).
            self.workbench.audit(self.workbench.operator, _action_label(path, payload),
                                 payload.get("story_key") or payload.get("run_id") or "-", "conflict",
                                 expected_revision=_one_revision(payload.get("expected_revisions")))
            return self._fail(HTTPStatus.CONFLICT, f"penulisan bersamaan ditolak: {exc}")
        except FileExistsError as exc:
            return self._fail(HTTPStatus.CONFLICT, str(exc))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.workbench.audit(self.workbench.operator, _action_label(path, payload),
                                 payload.get("story_key") or payload.get("run_id") or "-", "refused",
                                 expected_revision=_one_revision(payload.get("expected_revisions")))
            return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            # No unexpected exception may drop the connection without a response.
            self.log_error("unhandled mutation error: %s", traceback.format_exc())
            self.workbench.audit(self.workbench.operator, _action_label(path, payload),
                                 payload.get("story_key") or payload.get("run_id") or "-", "error",
                                 expected_revision=_one_revision(payload.get("expected_revisions")))
            return self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, "kesalahan tak terduga pada penulisan")

    def _login(self):
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
        secret = payload.get("secret")
        outcome = self.workbench.login(secret if isinstance(secret, str) else "")
        if outcome is None:
            self.workbench.audit(self.workbench.operator, "login", "local", "refused")
            return self._fail(HTTPStatus.UNAUTHORIZED, "kredensial tidak diterima")
        token, csrf = outcome
        self.workbench.audit(self.workbench.operator, "login", "local", "ok")
        self._send(HTTPStatus.OK,
                   json.dumps({"authenticated": True, "operator": self.workbench.operator,
                               "csrf": csrf, "live_publishing": LIVE_PUBLISHING}).encode("utf-8"),
                   "application/json; charset=utf-8",
                   extra_headers=(("Set-Cookie",
                                   f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"),))

    def _mutation_route(self, path, payload):
        workbench = self.workbench
        if path == "/api/logout":
            workbench.logout(self._session()[0])
            workbench.audit(workbench.operator, "logout", "local", "ok")
            return self._send(HTTPStatus.OK, json.dumps({"authenticated": False}).encode("utf-8"),
                              "application/json; charset=utf-8",
                              extra_headers=(("Set-Cookie",
                                              f"{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"),))
        if path not in ("/api/origin-review", "/api/decision", "/api/export"):
            return self._fail(HTTPStatus.NOT_FOUND, "rute tidak dikenal")
        expected = payload.get("expected_revisions")
        if not isinstance(expected, dict) or not expected:
            raise ValueError("expected_revisions wajib diisi: setiap keputusan terikat revisi yang dilihat")
        if path == "/api/origin-review":
            outcome = workbench.record_origin(str(payload.get("run_id") or ""),
                                              str(payload.get("source") or ""),
                                              str(payload.get("entity") or ""),
                                              payload.get("rationale"), expected_revisions=expected)
            workbench.audit(workbench.operator, "origin-review",
                            f"{payload.get('run_id')}|{payload.get('source')}|{payload.get('entity')}", "ok",
                            expected_revision=_one_revision(expected))
            return self._respond(HTTPStatus.OK, outcome)
        if path == "/api/decision":
            action = payload.get("action")
            story_key = str(payload.get("story_key") or "")
            if action == "hold":
                outcome = workbench.hold(story_key, note=payload.get("note"), expected_revisions=expected)
            elif action == "review":
                outcome = workbench.review(str(payload.get("run_id") or ""), payload.get("claims") or [],
                                           expected_revisions=expected)
            elif action == "approve":
                indexes = payload.get("indexes")
                if not isinstance(indexes, list):
                    raise ValueError("indexes harus daftar")
                outcome = workbench.approve(str(payload.get("run_id") or ""),
                                            str(payload.get("edition_id") or ""),
                                            str(payload.get("platform") or ""), indexes,
                                            expected_revisions=expected)
            elif action == "correct":
                outcome = workbench.correct(story_key, reason=payload.get("reason"), evidence=payload.get("evidence"),
                                            relation_kind=str(payload.get("relation_kind") or "corrects"),
                                            from_revision=payload.get("from_revision"),
                                            to_revision=payload.get("to_revision"),
                                            expected_revisions=expected)
            elif action == "withdraw":
                outcome = workbench.withdraw(story_key, reason=payload.get("reason"), evidence=payload.get("evidence"),
                                             expected_revisions=expected)
            else:
                raise ValueError("aksi keputusan tidak dikenal")
            actual = workbench.current_revision(story_key) if story_key else None
            workbench.audit(workbench.operator, f"decision:{action}",
                            story_key or str(payload.get("run_id") or "-"), "ok",
                            expected_revision=_one_revision(expected), actual_revision=actual)
            return self._respond(HTTPStatus.OK, outcome)
        if path == "/api/export":
            outcome = workbench.export(str(payload.get("run_id") or ""), str(payload.get("edition_id") or ""),
                                       str(payload.get("platform") or ""),
                                       str(payload.get("dataset") or "fixture"),
                                       expected_revisions=expected)
            workbench.audit(workbench.operator, "export",
                            str(payload.get("story_key") or payload.get("edition_id") or "-"), "ok",
                            expected_revision=_one_revision(expected))
            return self._respond(HTTPStatus.OK, outcome)
        return self._fail(HTTPStatus.NOT_FOUND, "rute tidak dikenal")

    # Unsupported methods on this boundary are refused, not silently handled.
    def do_PUT(self):
        self._fail(HTTPStatus.METHOD_NOT_ALLOWED, "metode tidak didukung")

    do_PATCH = do_PUT
    do_DELETE = do_PUT


def _bootstrap(workbench, session):
    return {"authenticated": session is not None, "operator": workbench.operator,
            "csrf": session["csrf"] if session else None,
            "live_publishing": LIVE_PUBLISHING,
            "boundary": {"bind": "127.0.0.1 (loopback)", "session_cookie": SESSION_COOKIE,
                         "session_ttl_seconds": workbench.session_ttl,
                         "external_release": "tidak ada tindakan publikasi eksternal"},
            "limits": ["Validasi angka adalah pencocokan token/unit/skala, bukan pemahaman semantik.",
                       "Sumber dengan angka ambigu menahan kandidat, tidak ditebak.",
                       "Keputusan asal adalah asersi editor, bukan verifikasi identitas penerbit."]}


def _safe_json(payload):
    """Serialize for embedding in a <script> block: no raw `</` sequence can escape it."""
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _PAGE_PATH():
    return Path(__file__).with_name("workbench_page.html")


def _page_html(path):
    return path.read_text(encoding="utf-8")


def serve(*, db, operator, secret_hash, export_dir, port=0, session_ttl=SESSION_TTL_SECONDS):
    """Start the loopback server and return (server, thread). Tests use port=0."""
    workbench = Workbench(db=db, operator=operator, secret_hash=secret_hash, export_dir=export_dir,
                          session_ttl=session_ttl)
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkbenchHandler)
    server.daemon_threads = True
    server.workbench = workbench
    server.redaction_secrets = (secret_hash,)
    thread = threading.Thread(target=server.serve_forever, name="ronce-workbench", daemon=True)
    thread.start()
    return server, thread


def config_from_env(env=None):
    """Read the four required settings; missing or invalid values raise ConfigError."""
    env = os.environ if env is None else env
    missing = [name for name in (_OPERATOR_ENV, _SECRET_ENV, _DB_ENV, _EXPORT_DIR_ENV) if not env.get(name)]
    if missing:
        raise ConfigError("konfigurasi workbench tidak lengkap: " + ", ".join(missing))
    return {"operator": env[_OPERATOR_ENV], "secret_hash": env[_SECRET_ENV],
            "db": Path(env[_DB_ENV]), "export_dir": Path(env[_EXPORT_DIR_ENV])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787, help="loopback port (default 8787)")
    parser.add_argument("--print-hash", metavar="SECRET",
                        help="print the verification hash for a secret (prefer the environment for real use)")
    args = parser.parse_args()
    if args.print_hash is not None:
        print(hash_secret(args.print_hash))
        return
    try:
        config = config_from_env()
        server, thread = serve(db=config["db"], operator=config["operator"],
                               secret_hash=config["secret_hash"], export_dir=config["export_dir"],
                               port=args.port)
    except ConfigError as exc:
        parser.error(str(exc))
    print(json.dumps({"listening": f"http://127.0.0.1:{server.server_address[1]}/",
                      "operator": server.workbench.operator, "live_publishing": LIVE_PUBLISHING,
                      "db": str(server.workbench.db), "export_dir": str(server.workbench.export_dir),
                      "session_ttl_seconds": server.workbench.session_ttl}, ensure_ascii=False))
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
