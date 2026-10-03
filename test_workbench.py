"""Workbench checks over real local HTTP requests and temporary databases.

Every refusal is paired with a positive control that must be accepted. Nothing here proves
provider truth or legal identity: the operator is a configured local principal and the
synthetic store is visibly fake. Each test gets its own store and server, so tests cannot
borrow state from each other.
"""
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import ronce
import workbench
from test_ronce import CUTOFF, RULES, SINCE, article, page

SECRET = "rahasia-uji-sintetis"
SECRET_HASH = workbench.hash_secret(SECRET)  # One derivation; reused by every fixture.
OPERATOR = "Operator Uji"
_UNSET = object()

ROWS_A = [("BBCA uji sintetis umumkan dividen tunai 100 juta rupiah", "https://kanal-a.test/uji/a1"),
          ("Dividen tunai uji sintetis BBCA diumumkan 100 juta rupiah", "https://kanal-b.test/uji/a2")]
ROWS_B = [("BBCA uji sintetis umumkan dividen tunai 120 juta rupiah", "https://kanal-a.test/uji/b1"),
          ("Dividen tunai uji sintetis BBCA diumumkan 120 juta rupiah", "https://kanal-b.test/uji/b2"),
          ("Koreksi uji sintetis: dividen tunai BBCA 120 juta rupiah diumumkan ulang", "https://kanal-c.test/uji/b3")]
STORY_KEY = ronce.story_identity(symbol="BBCA", topic="dividen", action="pengumuman", date="2026-09-25")


def articles(rows):
    return [article(title, url) for title, url in rows]


def claim_for(rows, value="100"):
    return {"text": f"BBCA uji sintetis umumkan dividen tunai {value} juta rupiah.",
            "entity": "BBCA", "action": "umumkan", "event_time": "2026-09-25",
            "value": value, "unit": "rupiah", "scale": "juta", "metric": "dividen", "period": "2026",
            "evidence": [{"source": url, "quote": title, "origin": f"contoh sintetis {index + 1}",
                          "origin_basis": "independent_review",
                          "origin_note": "contoh sintetis: dua judul uji terpisah"}
                         for index, (title, url) in enumerate(rows)]}


def build_run(db, rows, fetched_at="2026-09-25T10:00:00+07:00", cutoff=CUTOFF):
    return ronce.replay([page(articles(rows), fetched_at=fetched_at)], cutoff, db,
                        since=SINCE, interpretation=dict(RULES))


class Client:
    """Minimal HTTP client with explicit cookie/header control over a real socket."""

    def __init__(self, port, host="127.0.0.1"):
        self.port, self.host = port, host
        self.cookie = None
        self.csrf = None

    def request(self, method, path, body=None, *, headers=None, origin=None, host=None,
                cookie=_UNSET, csrf=_UNSET):
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        connection = http.client.HTTPConnection(self.host, self.port, timeout=15)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host or f"127.0.0.1:{self.port}")
        if payload is not None:
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(payload)))
        if origin is not None:
            connection.putheader("Origin", origin)
        cookie_value = self.cookie if cookie is _UNSET else cookie
        if cookie_value:
            connection.putheader("Cookie", cookie_value)
        csrf_value = self.csrf if csrf is _UNSET else csrf
        if csrf_value:
            connection.putheader(workbench.CSRF_HEADER, csrf_value)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(payload)
        response = connection.getresponse()
        raw = response.read()
        set_cookie = response.getheader("Set-Cookie")
        connection.close()
        if set_cookie and set_cookie.startswith(workbench.SESSION_COOKIE + "="):
            value = set_cookie.split(";", 1)[0].split("=", 1)[1]
            self.cookie = f"{workbench.SESSION_COOKIE}={value}" if value else None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except ValueError:
            parsed = None
        return response.status, parsed, set_cookie

    def login(self, secret=SECRET):
        status, payload, _ = self.request("POST", "/api/login", {"secret": secret})
        if status == 200:
            self.csrf = payload["csrf"]
        return status, payload


class ServerFixture(unittest.TestCase):
    """Fresh loopback server and temporary store for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.export_dir = self.tmp / "export"
        self.server, self.thread = workbench.serve(db=self.db, operator=OPERATOR,
                                                   secret_hash=SECRET_HASH,
                                                   export_dir=self.export_dir, port=0)
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def client(self, login=True):
        client = Client(self.port)
        if login:
            status, payload = client.login()
            self.assertEqual(status, 200, payload)
        return client

    def audit_rows(self):
        return self.server.workbench.audit_tail(limit=1000)

    def expected_for(self, story_key=STORY_KEY):
        return {story_key: self.server.workbench.current_revision(story_key)}

    def review_claim(self, client, run_id, claim, story_key=STORY_KEY):
        return client.request("POST", "/api/decision",
                              {"action": "review", "run_id": run_id, "claims": [claim],
                               "expected_revisions": self.expected_for(story_key)})

    def approve(self, client, run_id, edition_id, indexes=(0,), story_key=STORY_KEY):
        return client.request("POST", "/api/decision",
                              {"action": "approve", "run_id": run_id, "edition_id": edition_id,
                               "platform": "threads", "indexes": list(indexes),
                               "expected_revisions": self.expected_for(story_key)})

    def export(self, client, run_id, edition_id, story_key=STORY_KEY, dataset="fixture"):
        return client.request("POST", "/api/export",
                              {"run_id": run_id, "edition_id": edition_id, "platform": "threads",
                               "dataset": dataset, "story_key": story_key,
                               "expected_revisions": self.expected_for(story_key)})


class ConfigAndSecretTests(unittest.TestCase):
    """Startup fails closed; the secret format is explicit and salted."""

    def test_secret_format_round_trip_and_plain_digest_refused(self):
        stored = workbench.hash_secret(SECRET)
        self.assertTrue(workbench.verify_secret(SECRET, stored))
        self.assertFalse(workbench.verify_secret("salah", stored))
        import hashlib
        plain = hashlib.sha256(SECRET.encode()).hexdigest()
        self.assertFalse(workbench.verify_secret(SECRET, plain), "hash polos tanpa salt ditolak")
        self.assertFalse(workbench.verify_secret(SECRET, "pbkdf2_sha256$1000$ab$cd"))
        self.assertFalse(workbench.verify_secret(SECRET, ""))

    def test_workbench_refuses_missing_operator_and_bad_hash(self):
        good = workbench.hash_secret(SECRET)
        with self.assertRaises(workbench.ConfigError):
            workbench.Workbench(db="x.sqlite", operator="", secret_hash=good, export_dir="out")
        with self.assertRaises(workbench.ConfigError):
            workbench.Workbench(db="x.sqlite", operator=OPERATOR, secret_hash="", export_dir="out")
        with self.assertRaises(workbench.ConfigError):
            workbench.Workbench(db="x.sqlite", operator=OPERATOR, secret_hash="sha256$abc",
                                export_dir="out")

    def test_config_from_env_reports_every_missing_name(self):
        with self.assertRaisesRegex(workbench.ConfigError, "RONCE_WORKBENCH_OPERATOR"):
            workbench.config_from_env({})
        complete = {workbench._OPERATOR_ENV: OPERATOR, workbench._SECRET_ENV: workbench.hash_secret(SECRET),
                    workbench._DB_ENV: "db.sqlite", workbench._EXPORT_DIR_ENV: "out"}
        self.assertEqual(workbench.config_from_env(complete)["operator"], OPERATOR)

    def test_print_hash_cli_emits_a_verifiable_hash(self):
        result = subprocess.run([sys.executable, "workbench.py", "--print-hash", SECRET],
                                capture_output=True, text=True, cwd=Path(__file__).parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(workbench.verify_secret(SECRET, result.stdout.strip()))

    def test_redact_removes_secret_material(self):
        self.assertEqual(workbench.redact(f"error dengan {SECRET} di dalamnya", [SECRET]),
                         "error dengan [REDACTED] di dalamnya")
        self.assertEqual(workbench.redact("tanpa rahasia", [SECRET]), "tanpa rahasia")


class BoundaryTests(ServerFixture):
    """Authentication, CSRF, Host/Origin, method and session lifecycle over real HTTP."""

    def test_reads_require_a_session_and_login_is_the_positive_control(self):
        anonymous = Client(self.port)
        status, payload, _ = anonymous.request("GET", "/api/runs")
        self.assertEqual(status, 401, payload)
        status, payload, _ = anonymous.request("GET", "/api/session")
        self.assertEqual((status, payload["authenticated"]), (200, False))
        client = self.client()
        status, payload, _ = client.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["operator"], OPERATOR)
        self.assertFalse(payload["live_publishing"])
        self.assertTrue(payload["csrf"])

    def test_login_refusals_are_audited_and_never_echo_secrets(self):
        client = Client(self.port)
        stored = self.server.workbench.secret_hash
        status, payload, set_cookie = client.request("POST", "/api/login", {"secret": "salah"})
        self.assertEqual(status, 401)
        self.assertNotIn(SECRET, json.dumps(payload))
        self.assertNotIn(stored, json.dumps(payload))
        self.assertIsNone(set_cookie)
        self.assertEqual(self.audit_rows()[0]["result"], "refused")
        status, payload = client.login()
        self.assertEqual(status, 200)
        self.assertNotIn(SECRET, json.dumps(payload))
        self.assertNotIn(stored, json.dumps(payload))

    def test_session_cookie_is_http_only_strict_and_absent_from_bodies(self):
        client = Client(self.port)
        status, payload, set_cookie = client.request("POST", "/api/login", {"secret": SECRET})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/", set_cookie)
        token = set_cookie.split(";", 1)[0].split("=", 1)[1]
        self.assertNotIn(token, json.dumps(payload))
        self.assertNotIn(token, json.dumps(client.request("GET", "/api/session")[1]))

    def test_expiry_is_deterministic_and_logout_invalidates(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 2, tzinfo=timezone.utc)
        server, _ = workbench.serve(db=self.tmp / "expiry.sqlite", operator=OPERATOR,
                                    secret_hash=SECRET_HASH, export_dir=self.tmp / "expiry-export",
                                    port=0, session_ttl=60)
        try:
            client = Client(server.server_address[1])
            with patch.object(workbench, "_now", return_value=start):
                self.assertEqual(client.login()[0], 200)
                self.assertTrue(client.request("GET", "/api/session")[1]["authenticated"])
            with patch.object(workbench, "_now", return_value=start + timedelta(seconds=61)):
                status, payload, _ = client.request("GET", "/api/session")
                self.assertEqual((status, payload["authenticated"]), (200, False))
                self.assertEqual(client.request("GET", "/api/runs")[0], 401)
            self.assertEqual(client.login()[0], 200)
            self.assertEqual(client.request("POST", "/api/logout", {})[0], 200)
            self.assertEqual(client.request("GET", "/api/runs")[0], 401)
        finally:
            server.shutdown()
            server.server_close()

    def test_csrf_required_for_every_mutation(self):
        client = self.client()
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "hold", "story_key": STORY_KEY,
                                             "note": "x", "expected_revisions": {STORY_KEY: None}},
                                            csrf="token-palsu")
        self.assertEqual(status, 403, payload)
        status, _, _ = client.request("POST", "/api/decision",
                                      {"action": "hold", "story_key": STORY_KEY,
                                       "note": "x", "expected_revisions": {STORY_KEY: None}},
                                      csrf=None)
        self.assertEqual(status, 403, "permintaan tanpa header CSRF ditolak")
        # Positive control: the real CSRF token reaches the engine; refusal is about content.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "hold", "story_key": "0" * 16,
                                             "note": "x", "expected_revisions": {"0" * 16: None}})
        self.assertEqual(status, 400, payload)
        self.assertIn("story_key", payload["error"])

    def test_foreign_origin_and_host_are_refused_with_local_controls(self):
        client = self.client()
        body = {"action": "hold", "story_key": STORY_KEY, "note": "x",
                "expected_revisions": {STORY_KEY: None}}
        status, _, _ = client.request("POST", "/api/decision", body, origin="http://evil.test")
        self.assertEqual(status, 403)
        status, _, _ = client.request("POST", "/api/decision", body,
                                      origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 400, "origin lokal yang benar harus lolos ke mesin")
        status, _, _ = client.request("GET", "/api/session", host="evil.test")
        self.assertEqual(status, 403)
        status, _, _ = client.request("GET", "/api/session", host="localhost")
        self.assertEqual(status, 200)

    def test_unsupported_methods_and_unknown_routes(self):
        client = self.client()
        for method in ("PUT", "PATCH", "DELETE"):
            status, _, _ = client.request(method, "/api/runs")
            self.assertEqual(status, 405, method)
        self.assertEqual(client.request("GET", "/api/tidak-ada")[0], 404)
        self.assertEqual(client.request("POST", "/api/tidak-ada", {})[0], 404)

    def test_reads_never_write_audit_rows(self):
        client = self.client()
        before = len(self.audit_rows())
        self.assertEqual(client.request("GET", "/api/runs")[0], 200)
        self.assertEqual(client.request("GET", "/api/session")[0], 200)
        self.assertEqual(len(self.audit_rows()), before, "GET tidak boleh menulis audit")


class ReadModelTests(ServerFixture):
    """Candidate inspection over HTTP against the synthetic store, before any review."""

    def setUp(self):
        super().setUp()
        self.run_a = build_run(self.db, ROWS_A)

    def test_candidates_include_story_key_and_revision_state(self):
        client = self.client()
        status, payload, _ = client.request("GET", f"/api/candidates?run={self.run_a['run_id']}")
        self.assertEqual(status, 200, payload)
        rows = {row["story_key"]: row for row in payload["candidates"]}
        self.assertIn(STORY_KEY, rows)
        self.assertEqual(rows[STORY_KEY]["decision"], "review")
        self.assertIsNone(rows[STORY_KEY]["current_revision_id"])
        self.assertFalse(rows[STORY_KEY]["registered"])
        self.assertEqual(client.request("GET", "/api/candidates?run=tidak-ada")[0], 400)
        self.assertEqual(client.request("GET", "/api/candidates")[0], 400)

    def test_candidate_detail_is_read_only_and_reports_registry_state(self):
        client = self.client()
        before = len(self.audit_rows())
        status, payload, _ = client.request("GET", f"/api/candidate/{STORY_KEY}")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["symbol"], "BBCA")
        self.assertEqual(payload["candidate"]["decision"], "review")
        self.assertEqual(payload["claims"], [])
        self.assertIsNone(payload["current_revision_id"])
        self.assertEqual(len(self.audit_rows()), before, "detail tidak menulis apa pun")
        self.assertEqual(client.request("GET", "/api/candidate/" + "0" * 16)[0], 400)
        self.assertEqual(client.request("GET", "/api/candidate/BBCA")[0], 404)


class EditorialFlowTests(ServerFixture):
    """Engine-backed mapping, origin review, hold/review/approve/export with stale controls."""

    def setUp(self):
        super().setUp()
        self.run_a = build_run(self.db, ROWS_A)

    def test_mapping_review_records_principal_not_body_names_and_is_idempotent(self):
        client = self.client()
        claim = claim_for(ROWS_A)
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "review", "run_id": self.run_a["run_id"],
                                             "claims": [claim], "editor": "Penyusup", "reviewed": True,
                                             "expected_revisions": self.expected_for()})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["editor"], OPERATOR, "identitas dari principal, bukan badan permintaan")
        with closing(ronce._connect(self.db)) as con:
            stored = json.loads(con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?",
                                            (self.run_a["run_id"],)).fetchone()[0])
            revision = con.execute("SELECT revision_id FROM story_revisions WHERE story_key=?",
                                   (STORY_KEY,)).fetchone()
        self.assertEqual(stored["editor"], OPERATOR)
        self.assertIsNotNone(revision, "review mendaftarkan revisi imutabel")
        status, again, _ = self.review_claim(client, self.run_a["run_id"], claim)
        self.assertEqual(status, 200)
        self.assertEqual(again["reviewed_at"], payload["reviewed_at"], "ulangan idempoten")

    def test_origin_review_requires_rationale_and_persists_with_content_hash(self):
        client = self.client()
        _, url = ROWS_A[0]
        status, payload, _ = client.request("POST", "/api/origin-review",
                                            {"run_id": self.run_a["run_id"], "source": url,
                                             "entity": "BBCA", "rationale": "pendek",
                                             "expected_revisions": {STORY_KEY: None}})
        self.assertEqual(status, 400)
        status, payload, _ = client.request("POST", "/api/origin-review",
                                            {"run_id": self.run_a["run_id"], "source": url,
                                             "entity": "BBCA",
                                             "rationale": "contoh sintetis: judul uji berdiri sendiri",
                                             "expected_revisions": {STORY_KEY: None}})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["reviewer"], OPERATOR)
        with closing(ronce._connect(self.db)) as con:
            row = con.execute("SELECT reviewer, rationale, content_hash FROM origin_reviews "
                              "WHERE run_id=? AND source=? AND entity=?",
                              (self.run_a["run_id"], url, "BBCA")).fetchone()
        self.assertEqual(row[0], OPERATOR)
        self.assertRegex(row[2], r"^[0-9a-f]{64}$")

    def test_hold_approve_export_then_stale_revision_conflicts(self):
        client = self.client()
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        revision_r1 = self.server.workbench.current_revision(STORY_KEY)
        self.assertIsNotNone(revision_r1)
        # Hold on the seen revision succeeds.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "hold", "story_key": STORY_KEY,
                                             "note": "menunggu konfirmasi tambahan",
                                             "expected_revisions": {STORY_KEY: revision_r1}})
        self.assertEqual(status, 200, payload)
        # Approve edition uji-a bound to R1.
        status, payload, _ = self.approve(client, self.run_a["run_id"], "uji-a")
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["posts"]), 1)
        self.assertIn("Sumber:", payload["posts"][0])
        # A new run revises the story while uji-a stays approved on R1.
        run_b = build_run(self.db, ROWS_B, fetched_at="2026-09-25T12:00:00+07:00",
                          cutoff="2026-09-25T13:00:00+07:00")
        ronce.review_claims(self.db, run_b["run_id"], OPERATOR, [claim_for(ROWS_B, value="120")],
                            reviewed=True)
        ronce.register_versioned_stories(self.db, run_b["run_id"])
        revision_r2 = self.server.workbench.current_revision(STORY_KEY)
        self.assertNotEqual(revision_r2, revision_r1)
        # A stale approve (client saw R1) is refused with conflict feedback and audited.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "approve", "run_id": self.run_a["run_id"],
                                             "edition_id": "uji-a2", "platform": "threads", "indexes": [0],
                                             "expected_revisions": {STORY_KEY: revision_r1}})
        self.assertEqual(status, 409, payload)
        self.assertEqual(self.audit_rows()[0]["result"], "conflict")
        # Export of the R1-bound edition cannot inherit the newer revision: refused.
        status, payload, _ = self.export(client, self.run_a["run_id"], "uji-a")
        self.assertEqual(status, 409, payload)
        self.assertFalse((self.export_dir / "uji-a").exists(), "tidak ada ekspor parsial")
        # Export with a stale client view is refused before the engine runs.
        status, payload, _ = client.request("POST", "/api/export",
                                            {"run_id": self.run_a["run_id"], "edition_id": "uji-a",
                                             "platform": "threads", "dataset": "fixture",
                                             "expected_revisions": {STORY_KEY: revision_r1}})
        self.assertEqual(status, 409, payload)
        # Positive control on the fresh revision: approve and export uji-b.
        status, payload, _ = self.approve(client, run_b["run_id"], "uji-b")
        self.assertEqual(status, 200, payload)
        status, payload, _ = self.export(client, run_b["run_id"], "uji-b")
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["live_publishing"])
        manifest = json.loads((self.export_dir / "uji-b" / "threads" / "manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["posts"], 1)
        self.assertFalse(manifest["policy"]["live_publishing"])
        text = "\n".join((self.export_dir / "uji-b" / "threads" / name).read_text(encoding="utf-8")
                         for name in ("edition.json", "stories.json", "claims.json"))
        self.assertIn("uji sintetis", text)

    def test_correction_and_withdrawal_over_http_with_preconditions(self):
        """The two remaining decision actions must be exercised over HTTP, not only via the engine."""
        client = self.client()
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        revision = self.server.workbench.current_revision(STORY_KEY)
        self.assertIsNotNone(revision)
        # Correction with a stale revision is refused.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "correct", "story_key": STORY_KEY,
                                             "reason": "koreksi uji sintetis", "evidence": "bukti uji",
                                             "relation_kind": "corrects",
                                             "from_revision": "revisi-palsu", "to_revision": revision,
                                             "expected_revisions": {STORY_KEY: revision}})
        self.assertEqual(status, 400, payload)
        # Correction with a valid endpoint pair succeeds.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "correct", "story_key": STORY_KEY,
                                             "reason": "koreksi uji sintetis", "evidence": "bukti uji",
                                             "relation_kind": "corrects",
                                             "from_revision": revision, "to_revision": revision,
                                             "expected_revisions": {STORY_KEY: revision}})
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["idempotent"])
        # The same correction repeated is idempotent, not a second row.
        status, again, _ = client.request("POST", "/api/decision",
                                          {"action": "correct", "story_key": STORY_KEY,
                                           "reason": "koreksi uji sintetis", "evidence": "bukti uji",
                                           "relation_kind": "corrects",
                                           "from_revision": revision, "to_revision": revision,
                                           "expected_revisions": {STORY_KEY: revision}})
        self.assertEqual(status, 200, again)
        self.assertTrue(again["idempotent"])
        # Withdrawal requires reason and evidence, then records the status.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "withdraw", "story_key": STORY_KEY,
                                             "reason": "pendek", "evidence": "bukti uji",
                                             "expected_revisions": {STORY_KEY: revision}})
        self.assertEqual(status, 400, payload)
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "withdraw", "story_key": STORY_KEY,
                                             "reason": "penarikan uji sintetis", "evidence": "bukti uji",
                                             "expected_revisions": {STORY_KEY: revision}})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["status"], "withdrawn")
        # The withdrawal is visible in the detail read model.
        status, detail, _ = client.request("GET", f"/api/candidate/{STORY_KEY}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["status"]["status"], "withdrawn")
        self.assertEqual(len(detail["relations"]), 1, "koreksi tercatat sekali")
        # A stale withdrawal (old revision) is refused with conflict feedback.
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "withdraw", "story_key": STORY_KEY,
                                             "reason": "penarikan dari tampilan lama", "evidence": "bukti",
                                             "expected_revisions": {STORY_KEY: "revisi-lama"}})
        self.assertEqual(status, 409, payload)

    def test_export_manifest_read_route(self):
        """The manifest read endpoint reports the produced export, and refuses before one exists."""
        client = self.client()
        status, payload, _ = client.request("GET", "/api/export?edition_id=none&platform=threads")
        self.assertEqual(status, 400, payload)
        self.assertEqual(client.request("GET", "/api/export?edition_id=none")[0], 400)
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        self.assertEqual(self.approve(client, self.run_a["run_id"], "manifest-uji")[0], 200)
        self.assertEqual(self.export(client, self.run_a["run_id"], "manifest-uji")[0], 200)
        status, manifest, _ = client.request("GET", "/api/export?edition_id=manifest-uji&platform=threads")
        self.assertEqual(status, 200, manifest)
        self.assertEqual(manifest["edition_id"], "manifest-uji")
        self.assertFalse(manifest["policy"]["live_publishing"])
        # Path traversal through the read route is refused too.
        status, payload, _ = client.request("GET", "/api/export?edition_id=..&platform=threads")
        self.assertEqual(status, 400, payload)

    def test_malformed_candidate_row_is_refused_not_a_dropped_connection(self):
        """Stored decision_json may predate this reader; a missing field must not crash the server."""
        import ronce as engine
        with closing(engine._connect(self.db)) as con, con:
            stored = json.loads(con.execute("SELECT decision_json FROM runs WHERE id=?",
                                            (self.run_a["run_id"],)).fetchone()[0])
            stored[0].pop("symbol", None)
            con.execute("UPDATE runs SET decision_json=? WHERE id=?",
                        (json.dumps(stored), self.run_a["run_id"]))
        client = self.client()
        status, payload, _ = client.request("GET", f"/api/candidates?run={self.run_a['run_id']}")
        self.assertEqual(status, 400, payload)
        self.assertIn("kandidat", payload["error"])
        # The same malformed row must not crash detail reads or decisions either.
        status, payload, _ = client.request("GET", "/api/candidate/" + "0" * 16)
        self.assertEqual(status, 400, payload)
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "hold", "story_key": "0" * 16, "note": "x",
                                             "expected_revisions": {"0" * 16: None}})
        self.assertEqual(status, 400, payload)
        # Positive control: the server is still healthy and answers reads.
        self.assertEqual(client.request("GET", "/api/runs")[0], 200)

    def test_origin_from_a_foreign_loopback_port_is_refused(self):
        """A page served from another local port is a different origin and must not write."""
        client = self.client()
        body = {"action": "hold", "story_key": "0" * 16, "note": "x",
                "expected_revisions": {"0" * 16: None}}
        status, payload, _ = client.request("POST", "/api/decision", body,
                                            origin="http://127.0.0.1:9999")
        self.assertEqual(status, 403, payload)
        # Positive control: the workbench's own origin is accepted.
        status, payload, _ = client.request("POST", "/api/decision", body,
                                            origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 400, payload)

    def test_export_refused_without_approval_and_repeat_export_is_a_conflict(self):
        client = self.client()
        status, payload, _ = client.request("POST", "/api/export",
                                            {"run_id": self.run_a["run_id"], "edition_id": "belum-ada",
                                             "platform": "threads", "dataset": "fixture",
                                             "expected_revisions": {STORY_KEY: None}})
        self.assertEqual(status, 400, payload)
        self.assertFalse((self.export_dir / "belum-ada").exists())
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        self.assertEqual(self.approve(client, self.run_a["run_id"], "uji-ulang")[0], 200)
        status, payload, _ = self.export(client, self.run_a["run_id"], "uji-ulang")
        self.assertEqual(status, 200, payload)
        status, payload, _ = self.export(client, self.run_a["run_id"], "uji-ulang")
        self.assertEqual(status, 409, f"ekspor ulang ditolak, bukan ditimpa: {payload}")

    def test_origin_gate_is_rechecked_at_approval_not_trusted_from_the_body(self):
        client = self.client()
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        with closing(ronce._connect(self.db)) as con, con:
            con.execute("DELETE FROM origin_reviews WHERE run_id=?", (self.run_a["run_id"],))
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "approve", "run_id": self.run_a["run_id"],
                                             "edition_id": "uji-gate", "platform": "threads", "indexes": [0],
                                             "reviewed": True, "approved": True,
                                             "expected_revisions": self.expected_for()})
        self.assertEqual(status, 400, payload)
        self.assertIn("asal", payload["error"])
        for _, url in ROWS_A:
            status, payload, _ = client.request("POST", "/api/origin-review",
                                                {"run_id": self.run_a["run_id"], "source": url,
                                                 "entity": "BBCA",
                                                 "rationale": "contoh sintetis: tinjauan asal dipulihkan",
                                                 "expected_revisions": self.expected_for()})
            self.assertEqual(status, 200, payload)
        status, payload, _ = client.request("POST", "/api/decision",
                                            {"action": "approve", "run_id": self.run_a["run_id"],
                                             "edition_id": "uji-gate", "platform": "threads", "indexes": [0],
                                             "expected_revisions": self.expected_for()})
        self.assertEqual(status, 200, payload)

    def test_missing_expected_revisions_is_refused_before_any_write(self):
        client = self.client()
        ronce.migrate(self.db)
        before = len(ronce.story_model(self.db)["revisions"])
        for path, body in (("/api/decision", {"action": "hold", "story_key": STORY_KEY, "note": "x"}),
                           ("/api/decision", {"action": "review", "run_id": self.run_a["run_id"],
                                              "claims": [claim_for(ROWS_A)]}),
                           ("/api/origin-review", {"run_id": self.run_a["run_id"],
                                                   "source": ROWS_A[0][1], "entity": "BBCA",
                                                   "rationale": "contoh sintetis tanpa revisi"}),
                           ("/api/export", {"run_id": self.run_a["run_id"], "edition_id": "x",
                                            "platform": "threads", "dataset": "fixture"})):
            status, payload, _ = client.request("POST", path, body)
            self.assertEqual(status, 400, (path, payload))
        after = len(ronce.story_model(self.db)["revisions"])
        self.assertEqual(after, before, "tidak ada tulisan tanpa revisi")

    def test_export_path_segments_cannot_traverse(self):
        client = self.client()
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        self.assertEqual(self.approve(client, self.run_a["run_id"], "aman")[0], 200)
        for edition_id, platform in (("..", "threads"), ("../../evil", "threads"),
                                     ("aman", ".."), ("aman", "a/b")):
            status, payload, _ = client.request("POST", "/api/export",
                                                {"run_id": self.run_a["run_id"], "edition_id": edition_id,
                                                 "platform": platform, "dataset": "fixture",
                                                 "expected_revisions": self.expected_for()})
            self.assertEqual(status, 400, (edition_id, platform, payload))
        self.assertFalse((self.tmp / "evil").exists())
        # Positive control: a safe pair still exports.
        self.assertEqual(self.export(client, self.run_a["run_id"], "aman")[0], 200)

    def test_bootstrap_embedding_cannot_escape_the_script_block(self):
        # The operator name is configuration, but a hostile value must not break the page.
        stored = workbench.hash_secret(SECRET)
        nasty = "Operator </script><script>window.pwned=1</script>"
        server, _ = workbench.serve(db=self.tmp / "nasty.sqlite", operator=nasty,
                                    secret_hash=stored, export_dir=self.tmp / "nasty-export", port=0)
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=15)
            connection.request("GET", "/")
            response = connection.getresponse()
            page = response.read().decode("utf-8")
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertNotIn("</script><script>", page, "urutan penutup skrip tidak boleh mentah")
            bootstrap = page.split('type="application/json">', 1)[1].split("</script>", 1)[0]
            self.assertIn("window.pwned", bootstrap, "nilai tetap terbaca sebagai data")
            self.assertNotIn("</script", bootstrap, "penutup skrip mentah tidak boleh ada di dalam data")
            self.assertIn("<\\/script", bootstrap, "penutup skrip di-escape")
        finally:
            server.shutdown()
            server.server_close()

    def test_failed_validation_leaves_no_partial_rows(self):
        client = self.client()

        def count(table):
            with closing(ronce._connect(self.db)) as con:
                try:
                    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.OperationalError:
                    return 0

        before = count("reviewed_claims")
        broken = dict(claim_for(ROWS_A),
                      evidence=[dict(item, quote="kutipan palsu tidak ada")
                                for item in claim_for(ROWS_A)["evidence"]])
        status, payload, _ = self.review_claim(client, self.run_a["run_id"], broken)
        self.assertEqual(status, 400, payload)
        self.assertEqual(count("reviewed_claims"), before, "validasi gagal tidak menulis review")
        self.assertEqual(count("origin_reviews"), 0, "validasi gagal tidak menulis keputusan asal")

    def test_two_tabs_second_write_is_refused_not_silently_merged(self):
        client_one = self.client()
        client_two = self.client()
        self.assertEqual(self.review_claim(client_one, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        revision = self.server.workbench.current_revision(STORY_KEY)
        self.assertEqual(client_one.request("POST", "/api/decision",
                                            {"action": "hold", "story_key": STORY_KEY,
                                             "note": "tab satu menahan",
                                             "expected_revisions": {STORY_KEY: revision}})[0], 200)
        status, payload, _ = client_two.request("POST", "/api/decision",
                                                {"action": "hold", "story_key": STORY_KEY,
                                                 "note": "tab dua dari tampilan lama",
                                                 "expected_revisions": {STORY_KEY: None}})
        self.assertEqual(status, 409, payload)
        self.assertEqual(self.audit_rows()[0]["result"], "conflict")

    def test_concurrent_exports_produce_exactly_one_winner(self):
        client = self.client()
        self.assertEqual(self.review_claim(client, self.run_a["run_id"], claim_for(ROWS_A))[0], 200)
        revision = self.server.workbench.current_revision(STORY_KEY)
        status, payload, _ = self.approve(client, self.run_a["run_id"], "uji-race")
        self.assertEqual(status, 200, payload)
        results = []
        lock = threading.Lock()

        def export():
            worker = self.client()
            status, payload, _ = worker.request("POST", "/api/export",
                                                {"run_id": self.run_a["run_id"], "edition_id": "uji-race",
                                                 "platform": "threads", "dataset": "fixture",
                                                 "expected_revisions": {STORY_KEY: revision}})
            with lock:
                results.append(status)

        threads = [threading.Thread(target=export) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(200), 1, results)
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.assertTrue((self.export_dir / "uji-race" / "threads" / "manifest.json").exists())


class RestartTests(unittest.TestCase):
    """Restart: the store persists, sessions do not, and audit history survives."""

    def test_restart_requires_login_and_keeps_the_store(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            tmp = Path(tmp)
            db, export_dir = tmp / "runs.sqlite", tmp / "export"
            build_run(db, ROWS_A)
            server, _ = workbench.serve(db=db, operator=OPERATOR, secret_hash=SECRET_HASH,
                                        export_dir=export_dir, port=0)
            client = Client(server.server_address[1])
            self.assertEqual(client.login()[0], 200)
            self.assertEqual(client.request("GET", "/api/runs")[0], 200)
            cookie = client.cookie
            server.shutdown()
            server.server_close()
            server_two, _ = workbench.serve(db=db, operator=OPERATOR, secret_hash=SECRET_HASH,
                                            export_dir=export_dir, port=0)
            try:
                stale = Client(server_two.server_address[1])
                stale.cookie = cookie
                status, payload, _ = stale.request("GET", "/api/runs")
                self.assertEqual(status, 401, payload)
                self.assertEqual(stale.login()[0], 200)
                status, payload, _ = stale.request("GET", "/api/runs")
                self.assertEqual(status, 200)
                self.assertEqual(len(payload["runs"]), 1)
                self.assertGreaterEqual(len(server_two.workbench.audit_tail()), 1)
            finally:
                server_two.shutdown()
                server_two.server_close()


class EnginePreconditionTests(unittest.TestCase):
    """The in-transaction guard is part of the engine, so every caller inherits it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.run = build_run(self.db, ROWS_A)

    def tearDown(self):
        self._tmp.cleanup()

    def test_revision_conflict_is_a_value_error_subclass(self):
        self.assertTrue(issubclass(ronce.RevisionConflict, ValueError))

    def test_expected_revision_none_mismatch_and_missing_key(self):
        with closing(ronce._connect(self.db)) as con:
            ronce._require_expected_revisions(con, {STORY_KEY: None})  # No revision yet: ok.
        ronce.migrate(self.db)
        ronce.review_claims(self.db, self.run["run_id"], OPERATOR, [claim_for(ROWS_A)], reviewed=True)
        ronce.register_versioned_stories(self.db, self.run["run_id"])
        with closing(ronce._connect(self.db)) as con:
            revision = ronce.current_revision_id(con, STORY_KEY)
            self.assertIsNotNone(revision)
            with self.assertRaises(ronce.RevisionConflict):
                ronce._require_expected_revisions(con, {STORY_KEY: None})
            with self.assertRaises(ronce.RevisionConflict):
                ronce._require_expected_revisions(con, {STORY_KEY: "revisi-palsu"})
            with self.assertRaises(ronce.RevisionConflict):
                ronce._require_expected_revisions(con, {}, require_keys={STORY_KEY})
            ronce._require_expected_revisions(con, {STORY_KEY: revision})  # Positive control.

    def test_review_approve_withdraw_relation_accept_the_precondition(self):
        claim = claim_for(ROWS_A)
        with self.assertRaises(ronce.RevisionConflict):
            ronce.review_claims(self.db, self.run["run_id"], OPERATOR, [claim], reviewed=True,
                                expected_revisions={STORY_KEY: "revisi-lama"})
        record = ronce.review_claims(self.db, self.run["run_id"], OPERATOR, [claim], reviewed=True,
                                     expected_revisions={STORY_KEY: None})
        self.assertEqual(record["editor"], OPERATOR)
        ronce.migrate(self.db)
        ronce.register_versioned_stories(self.db, self.run["run_id"])
        with closing(ronce._connect(self.db)) as con:
            revision = ronce.current_revision_id(con, STORY_KEY)
        posts = ronce.render_draft(self.db, self.run["run_id"], "edisi", "threads", [0])
        with self.assertRaises(ronce.RevisionConflict):
            ronce.approve_edition(self.db, self.run["run_id"], "edisi", "threads", OPERATOR, posts,
                                  expected_revisions={STORY_KEY: "revisi-lama"})
        saved = ronce.approve_edition(self.db, self.run["run_id"], "edisi", "threads", OPERATOR, posts,
                                      expected_revisions={STORY_KEY: revision})
        self.assertIn("hash", saved)
        with self.assertRaises(ronce.RevisionConflict):
            ronce.withdraw_story(self.db, STORY_KEY, reason="alasan cukup panjang",
                                 evidence="bukti uji", expected_revisions={STORY_KEY: "lama"})
        ronce.withdraw_story(self.db, STORY_KEY, reason="alasan cukup panjang",
                             evidence="bukti uji", expected_revisions={STORY_KEY: revision})
        with self.assertRaises(ronce.RevisionConflict):
            ronce.add_relation(self.db, "corrects", STORY_KEY, STORY_KEY,
                               reason="alasan koreksi uji", evidence="bukti koreksi",
                               expected_revisions={STORY_KEY: "lama"})
        outcome = ronce.add_relation(self.db, "corrects", STORY_KEY, STORY_KEY,
                                     reason="alasan koreksi uji", evidence="bukti koreksi",
                                     expected_revisions={STORY_KEY: revision})
        self.assertFalse(outcome["idempotent"])

    def test_approve_refuses_when_a_newer_revision_exists(self):
        ronce.review_claims(self.db, self.run["run_id"], OPERATOR, [claim_for(ROWS_A)], reviewed=True)
        ronce.migrate(self.db)
        ronce.register_versioned_stories(self.db, self.run["run_id"])
        with closing(ronce._connect(self.db)) as con:
            revision_r1 = ronce.current_revision_id(con, STORY_KEY)
        posts = ronce.render_draft(self.db, self.run["run_id"], "edisi", "threads", [0])
        ronce.approve_edition(self.db, self.run["run_id"], "edisi", "threads", OPERATOR, posts,
                              expected_revisions={STORY_KEY: revision_r1})
        run_b = build_run(self.db, ROWS_B, fetched_at="2026-09-25T12:00:00+07:00",
                          cutoff="2026-09-25T13:00:00+07:00")
        ronce.review_claims(self.db, run_b["run_id"], OPERATOR, [claim_for(ROWS_B, value="120")],
                            reviewed=True)
        ronce.register_versioned_stories(self.db, run_b["run_id"])
        with self.assertRaisesRegex(ValueError, "revisi cerita berubah"):
            ronce.preview_edition(self.db, self.run["run_id"], "edisi", "threads")
        stale_ok = ronce.preview_edition(self.db, self.run["run_id"], "edisi", "threads", stale_ok=True)
        self.assertEqual(stale_ok["posts"], posts, "riwayat tetap terbaca tanpa mengotorisasi")


if __name__ == "__main__":
    unittest.main()
