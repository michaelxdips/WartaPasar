"""Offline editorial replay checks; all articles here are synthetic, not market facts."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ronce import _event, approve_packet, fetch_news, preview_packet, record_mock_attempt, replay, save_archive


def article(title, source, timestamp="2026-09-25T09:00:00", symbols=None):
    return {"title": title, "body": title, "source": source,
            "timestamp": timestamp, "symbols": ["BBCA"] if symbols is None else symbols,
            "tags": ["dividend"], "sector": "financials"}


def page(rows, fetched_at="2026-09-25T10:00:00+07:00", offset=0,
         has_next=False, next_offset=None, total_count=None):
    if total_count is None:
        total_count = (next_offset if has_next else offset + len(rows))
    return {"fetched_at": fetched_at,
            "response": {"results": rows,
                         "pagination": {"offset": offset, "showing": len(rows),
                                        "total_count": total_count,
                                        "has_next": has_next, "next_offset": next_offset}}}


CUTOFF = "2026-09-25T11:00:00+07:00"
SINCE = "2026-09-22T11:00:00+07:00"

RULES = {"source_timezone": "+07:00", "timestamp_meaning": "source_publication",
         "filter_timezone": "+07:00", "start_inclusive": True, "end_inclusive": True,
         "evidence": "https://provider.example.test/written-confirmation"}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "runs.sqlite"

    def run_replay(self, pages):
        return replay(pages, CUTOFF, self.db, since=SINCE, interpretation=dict(RULES))

    def test_conflicting_headline_numbers_abstain(self):
        rows = [article("BBCA umumkan dividen tunai 100 rupiah", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan 120 rupiah", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertIn("bertentangan", result["candidates"][0]["reason"])

    def test_conflicting_action_in_same_headline_does_not_claim_announcement(self):
        rows = [article("BBCA umumkan dan bayar dividen tunai", "https://one.test/a"),
                article("BBCA umumkan dividen tunai", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")

    def test_two_independent_reports_form_one_review_draft(self):
        rows = [article("BBCA umumkan dividen tunai 100 rupiah",
                        "https://news.example.com/first"),
                article("Dividen tunai BBCA diumumkan 100 rupiah",
                        "https://other.example.net/second")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["candidates"][0]["decision"], "review")
        self.assertEqual(result["candidates"][0]["source_count"], 2)
        self.assertIn("BBCA", result["draft"])
        self.assertIn("https://news.example.com/first", result["editorial_notes"])
        self.assertNotIn("100 rupiah", result["draft"])
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("select count(*) from runs").fetchone()[0], 1)
            self.assertEqual(con.execute("select count(*) from articles").fetchone()[0], 2)

    def test_approval_audit_package_ties_claim_quotes_to_run_and_editor(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        packet = approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(packet["run_id"], run["run_id"])
        self.assertEqual([e["page"] for e in packet["claims"][0]["evidence"]], [0, 0])
        with closing(sqlite3.connect(self.db)) as con:
            saved = con.execute("SELECT payload FROM packets WHERE run_id=?", (run["run_id"],)).fetchone()[0]
        self.assertEqual(json.loads(saved), packet)

    def test_syndication_and_subdomains_count_as_one_publisher(self):
        rows = [article("BBCA umumkan dividen tunai 100 rupiah",
                        "https://money.example.co.id/a"),
                article("Dividen tunai BBCA diumumkan 100 rupiah",
                        "https://news.example.co.id/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertEqual(result["candidates"][0]["source_count"], 1)

    def test_identical_syndicated_body_across_domains_abstains(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("BBCA umumkan dividen tunai", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertIn("Sindikasi", result["candidates"][0]["reason"])

    def test_same_ticker_different_events_do_not_merge(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("BBCA terbitkan obligasi baru", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["status"], "abstain")

    def test_late_articles_excluded_and_late_fetch_refused(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a",
                        timestamp="2026-09-25T12:00:00+07:00")]
        self.assertEqual(self.run_replay([page(rows)])["eligible_articles"], 0)
        with self.assertRaisesRegex(ValueError, "fetched_at.*cutoff"):
            self.run_replay([page(rows, fetched_at="2026-09-25T12:30:00+07:00")])

    def test_timezone_naive_articles_need_explicit_source_timezone(self):
        raw = page([article("BBCA umumkan dividen tunai", "https://one.test/a")])
        with self.assertRaisesRegex(ValueError, "source_timezone"):
            replay([raw], CUTOFF, self.db, since=SINCE)

    def test_separate_time_interpretation_keeps_archive_unchanged(self):
        raw = page([article("BBCA umumkan dividen tunai", "https://one.test/a")])
        before = json.dumps([raw], sort_keys=True)
        rules = {"source_timezone": "+07:00", "timestamp_meaning": "source_publication",
                 "filter_timezone": "+07:00", "start_inclusive": True, "end_inclusive": True,
                 "evidence": "https://provider.example.test/written-confirmation"}
        first = replay([raw], CUTOFF, self.db, since=SINCE, interpretation=rules)
        self.assertEqual(first, replay([raw], CUTOFF, self.db, since=SINCE, interpretation=rules))
        self.assertEqual(json.dumps([raw], sort_keys=True), before)
        self.assertEqual(first["eligible_articles"], 1)
        self.assertEqual(first["time_interpretation"], rules)
        with closing(sqlite3.connect(self.db)) as con:
            saved = con.execute("SELECT since, interpretation_json FROM run_context WHERE run_id=?",
                                (first["run_id"],)).fetchone()
        self.assertEqual(saved[0], "2026-09-22T11:00:00+07:00")
        self.assertEqual(json.loads(saved[1]), rules)
        with self.assertRaisesRegex(ValueError, "bukti|evidence"):
            replay([raw], CUTOFF, self.db, since=SINCE, interpretation={**rules, "evidence": ""})
        with self.assertRaisesRegex(ValueError, "inklusif|batas"):
            replay([raw], CUTOFF, self.db, since=SINCE, interpretation={**rules, "end_inclusive": None})

    def test_article_newer_than_snapshot_is_excluded(self):
        row = article("BBCA umumkan dividen tunai", "https://one.test/a",
                      timestamp="2026-09-25T10:30:00+07:00")
        result = self.run_replay([page([row], fetched_at="2026-09-25T10:00:00+07:00")])
        self.assertEqual(result["eligible_articles"], 0)
        self.assertEqual(result["status"], "abstain")

    def test_incomplete_pagination_refused_not_silent(self):
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_replay([page([article("BBCA umumkan dividen tunai", "https://one.test/a")],
                                  has_next=True, next_offset=1)])

    def test_two_pages_must_follow_pagination_chain(self):
        first = page([article("BBCA umumkan dividen tunai", "https://one.test/a")],
                     has_next=True, next_offset=1, total_count=2)
        second = page([article("Dividen tunai BBCA diumumkan", "https://two.test/b")], offset=1)
        result = self.run_replay([first, second])
        self.assertEqual(result["status"], "review")
        second["response"]["pagination"]["offset"] = 2
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_replay([first, second])

    def test_replay_rejects_offset_gap_and_incomplete_total_count(self):
        first = page([article("BBCA umumkan dividen tunai", "https://one.test/a")],
                     has_next=True, next_offset=30, total_count=31)
        second = page([article("Dividen tunai BBCA diumumkan", "https://two.test/b")], offset=30)
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_replay([first, second])

        incomplete = page([article("BBCA umumkan dividen tunai", "https://one.test/a")], total_count=2)
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_replay([incomplete])

    def test_stale_article_outside_editorial_window_is_excluded(self):
        old = article("BBCA umumkan dividen tunai", "https://one.test/a",
                      timestamp="2026-09-20T09:00:00+07:00")
        result = self.run_replay([page([old])])
        self.assertEqual(result["eligible_articles"], 0)
        self.assertEqual(result["status"], "abstain")

    def test_duplicate_url_not_two_votes(self):
        a = article("BBCA umumkan dividen tunai", "https://one.test/a")
        result = self.run_replay([page([a, dict(a)])])
        self.assertEqual(result["eligible_articles"], 1)
        self.assertEqual(result["status"], "abstain")

    def test_english_news_can_be_grouped_without_mover(self):
        rows = [article("BBCA announces cash dividend", "https://one.test/a"),
                article("Cash dividend announced by BBCA", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["candidates"][0]["topic"], "dividen")

    def test_dividend_payment_is_not_announcement(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("BBCA bayar dividen tunai", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertEqual(len(result["candidates"]), 2)

    def test_cutoff_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "cutoff.*zona waktu"):
            replay([page([])], "2026-09-25T11:00:00", self.db, since=SINCE)

    def test_replay_is_stable_and_idempotent(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        first = self.run_replay([page(rows)])
        second = self.run_replay([page(rows)])
        self.assertEqual(first, second)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("select count(*) from runs").fetchone()[0], 1)

    def test_approval_requires_source_quotes_and_distinct_report_origins(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA mengumumkan dividen tunai.", "entity": "BBCA",
                 "action": "pengumuman dividen", "event_time": "2026-09-25",
                 "value": None, "unit": None, "period": None,
                 "evidence": [{"source": rows[0]["source"], "quote": rows[0]["title"], "origin": "laporan-A"},
                              {"source": rows[1]["source"], "quote": rows[1]["title"], "origin": "laporan-B"}]}
        text = "BBCA mengumumkan dividen tunai. Sumber: https://one.test/a https://two.test/b"
        self.assertEqual(run["status"], "review")
        self.assertEqual(run["candidates"][0]["decision"], "review")
        with self.assertRaisesRegex(ValueError, "review belum"):
            approve_packet(self.db, run["run_id"], "Editor", text, [claim])
        packet = approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(packet["approval"]["editor"], "Editor")
        self.assertEqual(len(packet["claims"][0]["evidence"]), 2)
        self.assertEqual([e["page"] for e in packet["claims"][0]["evidence"]], [0, 0])
        self.assertEqual(packet["text_hash"], __import__("hashlib").sha256(text.encode("utf-8")).hexdigest())

    def test_preview_rejects_unapproved_or_changed_text(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        with self.assertRaisesRegex(ValueError, "disetujui"):
            preview_packet(self.db, run["run_id"])

        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": origin}
                              for r, origin in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        preview = preview_packet(self.db, run["run_id"])
        self.assertEqual(preview["threads"]["text"], text)
        self.assertEqual(preview["threads"]["limit_check"], "not_performed")
        self.assertEqual(preview["x"]["limit_check"], "not_performed")
        with self.assertRaisesRegex(ValueError, "disetujui"):
            preview_packet(self.db, run["run_id"], text=text + " berubah")
        with closing(sqlite3.connect(self.db)) as con, con:
            original = con.execute("SELECT payload FROM packets WHERE run_id=?", (run["run_id"],)).fetchone()[0]
            packet = json.loads(original)
            packet["claims"][0]["text"] += " tampered"
            con.execute("UPDATE packets SET payload=? WHERE run_id=?", (json.dumps(packet), run["run_id"]))
        with self.assertRaisesRegex(ValueError, "approval baru"):
            preview_packet(self.db, run["run_id"])

    def test_claims_cannot_join_distinct_events_or_override_conflict(self):
        rows = [article("BBCA umumkan dividen 100 rupiah", "https://one.test/a"),
                article("BBCA umumkan dividen 120 rupiah", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        self.assertEqual(run["status"], "abstain")
        claim = {"text": "BBCA mengumumkan dividen.", "entity": "BBCA",
                 "action": "pengumuman dividen", "event_time": "2026-09-25",
                 "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = claim["text"] + " Sumber: https://one.test/a https://two.test/b"
        with self.assertRaisesRegex(ValueError, "tidak ada kandidat review"):
            approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)

    def test_changed_approval_needs_explicit_revision(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = claim["text"] + " Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        with self.assertRaisesRegex(ValueError, "revisi"):
            approve_packet(self.db, run["run_id"], "Editor", text + " koreksi", [claim], reviewed=True)
        self.assertEqual(preview_packet(self.db, run["run_id"])["x"]["text"], text)

    def test_mock_timeout_blocks_retry_and_keeps_other_platform_separate(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = claim["text"] + " Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        ambiguous = record_mock_attempt(self.db, run["run_id"], "threads", "akun-tes", "timeout")
        self.assertEqual(ambiguous["status"], "ambiguous")
        with self.assertRaisesRegex(ValueError, "baca balik|ambigu"):
            record_mock_attempt(self.db, run["run_id"], "threads", "akun-tes", "created",
                                external_id="mock-id", readback={"id": "mock-id", "account": "akun-tes", "text": text})
        denied = record_mock_attempt(self.db, run["run_id"], "x", "akun-tes-x", "expired_token")
        self.assertEqual(denied["status"], "failed")
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(dict(con.execute("SELECT platform,status FROM mock_posts WHERE run_id=?",
                                              (run["run_id"],))), {"threads": "ambiguous", "x": "failed"})

    def test_mock_success_requires_exact_readback_account_and_text(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = claim["text"] + " Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        mismatch = record_mock_attempt(self.db, run["run_id"], "threads", "akun-tes", "created",
                                       external_id="mock-1", readback={"id": "mock-1", "account": "salah", "text": text})
        self.assertEqual(mismatch["status"], "ambiguous")
        with self.assertRaisesRegex(ValueError, "baca balik|ambigu"):
            record_mock_attempt(self.db, run["run_id"], "threads", "akun-tes", "created",
                                external_id="mock-2", readback={"id": "mock-2", "account": "akun-tes", "text": text})
        ok = record_mock_attempt(self.db, run["run_id"], "x", "akun-tes-x", "created",
                                 external_id="mock-3", readback={"id": "mock-3", "account": "akun-tes-x", "text": text})
        self.assertEqual(ok["status"], "mock_verified")

    def test_cli_replays_json_envelope(self):
        path = Path(self.temp.name) / "pages.json"
        rules = Path(self.temp.name) / "rules.json"
        path.write_text(json.dumps([page([article("BBCA umumkan dividen tunai", "https://one.test/a")])]), encoding="utf-8")
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        completed = subprocess.run([sys.executable, "ronce.py", "replay", str(path),
                                    "--cutoff", CUTOFF, "--since", SINCE, "--db", str(self.db),
                                    "--interpretation", str(rules)],
                                   text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(completed.stdout)["status"], "abstain")

    def test_percent_headline_conflict_abstains(self):
        rows = [article("BBCA umumkan dividen 5%", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan 7%", "https://two.test/b")]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertIn("bertentangan", result["candidates"][0]["reason"])

    def test_percent_headline_same_number_still_reviews(self):
        rows = [article("BBCA umumkan dividen 5%", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan 5%", "https://two.test/b")]
        self.assertEqual(self.run_replay([page(rows)])["status"], "review")

    def test_english_announce_and_pay_headline_abstains(self):
        rows = [article("BBCA announces and pays cash dividend", "https://one.test/a"),
                article("Cash dividend announced and paid by BBCA", "https://two.test/b")]
        self.assertEqual(self.run_replay([page(rows)])["status"], "abstain")

    def test_article_body_must_be_text(self):
        row = article("BBCA umumkan dividen tunai", "https://one.test/a")
        row["body"] = 123
        with self.assertRaisesRegex(ValueError, "body"):
            self.run_replay([page([row])])

    def test_pages_must_be_nonempty_list(self):
        with self.assertRaisesRegex(ValueError, "pages"):
            replay(None, CUTOFF, self.db, since=SINCE, interpretation=dict(RULES))
        with self.assertRaisesRegex(ValueError, "pages"):
            replay([], CUTOFF, self.db, since=SINCE, interpretation=dict(RULES))

    def test_cross_page_total_count_mismatch_refused(self):
        first = page([article("BBCA umumkan dividen tunai", "https://one.test/a"),
                      article("Dividen tunai BBCA diumumkan", "https://two.test/b")],
                     has_next=True, next_offset=2, total_count=5)
        second = page([article("BBCA bayar dividen tunai 10 rupiah", "https://two.test/c")],
                      offset=2, total_count=3)
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_replay([first, second])
        consistent = page([article("BBCA bayar dividen tunai 10 rupiah", "https://two.test/c")],
                          offset=2, total_count=3)
        accepted = self.run_replay([page([article("BBCA umumkan dividen tunai", "https://one.test/a"),
                                          article("Dividen tunai BBCA diumumkan", "https://two.test/b")],
                                         has_next=True, next_offset=2, total_count=3), consistent])
        self.assertEqual(accepted["status"], "review")

    def test_archive_source_timezone_is_refused(self):
        raw = page([article("BBCA umumkan dividen tunai", "https://one.test/a")])
        raw["source_timezone"] = "+07:00"
        with self.assertRaisesRegex(ValueError, "terpisah"):
            replay([raw], CUTOFF, self.db, since=SINCE)
        with self.assertRaisesRegex(ValueError, "terpisah"):
            replay([raw], CUTOFF, self.db, since=SINCE, interpretation=dict(RULES))

    def test_preview_rechecks_evidence_quotes_and_origins(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(preview_packet(self.db, run["run_id"])["x"]["text"], text)
        with closing(sqlite3.connect(self.db)) as con, con:
            payload = json.loads(con.execute("SELECT payload FROM packets WHERE run_id=?",
                                             (run["run_id"],)).fetchone()[0])
            payload["claims"][0]["evidence"][0]["quote"] = "kutipan palsu"
            con.execute("UPDATE packets SET payload=? WHERE run_id=?",
                        (json.dumps(payload, ensure_ascii=False), run["run_id"]))
        with self.assertRaisesRegex(ValueError, "kutipan|approval baru"):
            preview_packet(self.db, run["run_id"])
        with closing(sqlite3.connect(self.db)) as con, con:
            payload = json.loads(con.execute("SELECT payload FROM packets WHERE run_id=?",
                                             (run["run_id"],)).fetchone()[0])
            payload["claims"][0]["evidence"][0]["quote"] = rows[0]["title"]
            payload["claims"][0]["evidence"][1]["origin"] = "A"
            con.execute("UPDATE packets SET payload=? WHERE run_id=?",
                        (json.dumps(payload, ensure_ascii=False), run["run_id"]))
        with self.assertRaisesRegex(ValueError, "asal|approval baru"):
            preview_packet(self.db, run["run_id"])

    def test_null_body_quote_falls_back_to_title(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        rows[0]["body"] = None
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(preview_packet(self.db, run["run_id"])["threads"]["text"], text)

    def test_claim_entity_must_match_candidate_symbol(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "TLKM umumkan dividen.", "entity": "TLKM", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "TLKM umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        with self.assertRaisesRegex(ValueError, "entity"):
            approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)

    def test_claim_event_time_must_match_candidate_date(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-26", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        with self.assertRaisesRegex(ValueError, "tanggal|event_time"):
            approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)

    def test_claim_entity_is_case_and_suffix_insensitive(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "bbca.jk", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        packet = approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(packet["approval"]["editor"], "Editor")

    def test_claim_event_time_may_include_time_of_day(self):
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                 "event_time": "2026-09-25T09:00:00+07:00", "value": None, "unit": None,
                 "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "BBCA umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        packet = approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(packet["claims"][0]["event_time"], "2026-09-25T09:00:00+07:00")

    def test_claim_for_pasar_candidate_allows_non_ticker_entity(self):
        rows = [article("IDX umumkan dividen tunai", "https://one.test/a", symbols=[]),
                article("Dividen tunai diumumkan IDX", "https://two.test/b", symbols=[])]
        run = self.run_replay([page(rows)])
        claim = {"text": "IDX umumkan dividen.", "entity": "Bursa", "action": "umumkan",
                 "event_time": "2026-09-25", "value": None, "unit": None, "period": None,
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        text = "IDX umumkan dividen. Sumber: https://one.test/a https://two.test/b"
        packet = approve_packet(self.db, run["run_id"], "Editor", text, [claim], reviewed=True)
        self.assertEqual(packet["claims"][0]["entity"], "Bursa")


class EditionTests(unittest.TestCase):
    setUp = ReplayTests.setUp
    run_replay = ReplayTests.run_replay

    def test_review_render_approve_platform_specific_dry_run(self):
        import ronce
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        evidence = [{"source": r["source"], "quote": r["title"], "origin": origin}
                    for r, origin in zip(rows, ("A", "B"))]
        claims = [{"text": "BBCA mengumumkan dividen tunai.", "entity": "BBCA",
                   "action": "pengumuman", "event_time": "2026-09-25", "evidence": evidence},
                  {"text": "BBCA mengumumkan pembagian dividen.", "entity": "BBCA",
                   "action": "pengumuman", "event_time": "2026-09-25", "evidence": evidence}]
        ronce.review_claims(self.db, run["run_id"], "Editor", claims, reviewed=True)
        x_posts = ronce.render_draft(self.db, run["run_id"], "edisi-1", "x", [0])
        threads_posts = ronce.render_draft(self.db, run["run_id"], "edisi-1", "threads", [1, 0])
        self.assertNotEqual(x_posts, threads_posts)
        ronce.approve_edition(self.db, run["run_id"], "edisi-1", "x", "Editor", x_posts)
        ronce.approve_edition(self.db, run["run_id"], "edisi-1", "threads", "Editor", threads_posts)
        self.assertEqual(ronce.preview_edition(self.db, run["run_id"], "edisi-1", "x")["posts"], x_posts)
        self.assertEqual(ronce.preview_edition(self.db, run["run_id"], "edisi-1", "threads")["posts"], threads_posts)

    def test_edition_rejects_tampering_empty_claims_and_unreviewed_numbers(self):
        import ronce
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA mengumumkan dividen tunai.", "entity": "BBCA", "action": "pengumuman",
                 "event_time": "2026-09-25", "evidence": [{"source": r["source"], "quote": r["title"], "origin": origin}
                                                      for r, origin in zip(rows, ("A", "B"))]}
        with self.assertRaisesRegex(ValueError, "klaim"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [], reviewed=True)
        ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)
        posts = ronce.render_draft(self.db, run["run_id"], "edisi-1", "x", [0])
        with self.assertRaisesRegex(ValueError, "teks final"):
            ronce.approve_edition(self.db, run["run_id"], "edisi-1", "x", "Editor", [posts[0] + " 100%"])
        with self.assertRaisesRegex(ValueError, "enam"):
            ronce.render_draft(self.db, run["run_id"], "edisi-1", "x", [0, 0])
        original = ronce.approve_edition(self.db, run["run_id"], "edisi-1", "x", "Editor", posts)
        self.assertEqual(original, ronce.approve_edition(self.db, run["run_id"], "edisi-1", "x", "Editor", posts))
        with self.assertRaisesRegex(ValueError, "persetujuan baru"):
            ronce.preview_edition(self.db, run["run_id"], "edisi-1", "x", posts=[posts[0] + "!"])
        with closing(sqlite3.connect(self.db)) as con, con:
            payload = json.loads(con.execute("SELECT payload FROM reviewed_claims WHERE run_id=?", (run["run_id"],)).fetchone()[0])
            payload["claims"][0]["evidence"][0]["source"] = "https://fake.test/"
            con.execute("UPDATE reviewed_claims SET payload=? WHERE run_id=?", (json.dumps(payload), run["run_id"]))
        with self.assertRaisesRegex(ValueError, "kutipan|bukti|sumber"):
            ronce.preview_edition(self.db, run["run_id"], "edisi-1", "x")

    def test_review_rejects_abstain_and_after_cutoff(self):
        import ronce
        rows = [article("BBCA umumkan dividen 100 rupiah", "https://one.test/a"),
                article("BBCA umumkan dividen 120 rupiah", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        with self.assertRaisesRegex(ValueError, "review"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [{"text": "BBCA"}], reviewed=True)

    def test_review_rejects_unsupported_number_and_future_time(self):
        import ronce
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA mengumumkan dividen 100 rupiah.", "entity": "BBCA",
                 "action": "pengumuman", "event_time": "2026-09-25",
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": origin}
                              for r, origin in zip(rows, ("A", "B"))]}
        with self.assertRaisesRegex(ValueError, "angka"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)
        claim["text"] = "BBCA mengumumkan dividen tunai."
        claim["event_time"] = "2026-09-25T23:00:00+07:00"
        with self.assertRaisesRegex(ValueError, "cutoff"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)

    def test_review_rejects_numeric_substring_and_wrong_event_action(self):
        import ronce
        rows = [article("BBCA umumkan dividen 100 rupiah", "https://one.test/a"),
                article("Dividen BBCA diumumkan 100 rupiah", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA umumkan dividen 10 rupiah.", "entity": "BBCA", "action": "pengumuman",
                 "event_time": "2026-09-25", "value": "10", "unit": "rupiah", "period": "2026",
                 "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                              for r, o in zip(rows, ("A", "B"))]}
        with self.assertRaisesRegex(ValueError, "angka"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)
        claim["text"] = "BBCA umumkan dividen 100 rupiah."
        claim["value"] = "100"
        claim["action"] = "pembayaran"
        with self.assertRaisesRegex(ValueError, "aksi"):
            ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)

    def test_preview_rejects_edited_approval_editor(self):
        import ronce
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        run = self.run_replay([page(rows)])
        claim = {"text": "BBCA mengumumkan dividen tunai.", "entity": "BBCA", "action": "pengumuman",
                 "event_time": "2026-09-25", "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                                                      for r, o in zip(rows, ("A", "B"))]}
        ronce.review_claims(self.db, run["run_id"], "Editor", [claim], reviewed=True)
        posts = ronce.render_draft(self.db, run["run_id"], "edisi", "x", [0])
        ronce.approve_edition(self.db, run["run_id"], "edisi", "x", "Editor", posts)
        with closing(sqlite3.connect(self.db)) as con, con:
            saved = json.loads(con.execute("SELECT payload FROM editions").fetchone()[0])
            saved["approval"]["editor"] = "Penyusup"
            con.execute("UPDATE editions SET payload=?", (json.dumps(saved),))
        with self.assertRaisesRegex(ValueError, "integritas"):
            ronce.preview_edition(self.db, run["run_id"], "edisi", "x")


class ScoringTests(unittest.TestCase):
    def test_scores_only_explicit_verified_rule_inputs(self):
        from ronce import score_candidate
        base = {"reviewed": True, "endpoint_available": True, "stale_repeat": False}
        cases = [({"rule": "foreign_streak", "streak": 5}, 10),
                 ({"rule": "foreign_streak", "streak": 6}, 12),
                 ({"rule": "mover_persistent", "consecutive_days": 3}, 6),
                 ({"rule": "mover_outlier", "ratio": "2.01"}, 5),
                 ({"rule": "quarterly_new", "new_report": True}, 7),
                 ({"rule": "news_two_large", "large_tickers": 2, "has_number": True}, 4),
                 ({"rule": "news_one_ticker", "ticker_count": 1, "has_number": True}, 3)]
        for inputs, expected in cases:
            candidate = {**base, **inputs}
            original = dict(candidate)
            with self.subTest(inputs=inputs):
                self.assertEqual(score_candidate(candidate), expected)
                self.assertEqual(candidate, original)
        for inputs in ({"rule": "foreign_streak", "streak": 4},
                       {"rule": "mover_persistent", "consecutive_days": 2},
                       {"rule": "mover_outlier", "ratio": "2"},
                       {"rule": "quarterly_new", "new_report": False},
                       {"rule": "news_two_large", "large_tickers": 2, "has_number": False},
                       {"rule": "news_one_ticker", "ticker_count": 1, "has_number": False}):
            self.assertIsNone(score_candidate({**base, **inputs}))
        for gate in ({"reviewed": False}, {"endpoint_available": False}, {"stale_repeat": True}):
            self.assertIsNone(score_candidate({**base, "rule": "quarterly_new", "new_report": True, **gate}))


class DraftScheduleTests(unittest.TestCase):
    def test_schedule_cli_runs_from_local_archive_without_publishing(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            pages = Path(tmp) / "pages.json"
            sidecar = Path(tmp) / "interpretation.json"
            db = Path(tmp) / "runs.sqlite"
            rows = [article("BBCA umumkan dividen tunai", "https://one.test/a", "2026-09-25T05:00:00+07:00"),
                    article("Dividen tunai BBCA diumumkan", "https://two.test/b", "2026-09-25T05:00:00+07:00")]
            pages.write_text(json.dumps([page(rows, fetched_at="2026-09-25T05:30:00+07:00")]), encoding="utf-8")
            sidecar.write_text(json.dumps(RULES), encoding="utf-8")
            command = [sys.executable, "ronce.py", "schedule-once", str(pages), "--at", "2026-09-25T06:00:00+07:00",
                       "--since", SINCE, "--db", str(db), "--interpretation", str(sidecar)]
            first = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)["status"], "draft_only")
            second = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout), json.loads(first.stdout))

    def test_weekday_jakarta_slot_runs_once_and_does_not_publish(self):
        from ronce import draft_schedule
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            db = Path(tmp) / "runs.sqlite"
            rows = [article("BBCA umumkan dividen tunai", "https://one.test/a", "2026-09-25T05:00:00+07:00"),
                    article("Dividen tunai BBCA diumumkan", "https://two.test/b", "2026-09-25T05:00:00+07:00")]
            now = "2026-09-25T06:00:00+07:00"
            capture = [page(rows, fetched_at="2026-09-25T05:30:00+07:00")]
            first = draft_schedule(capture, now, db, since=SINCE, interpretation=dict(RULES))
            self.assertEqual(first["status"], "draft_only")
            self.assertFalse(first["api_write"])
            self.assertEqual(draft_schedule(capture, now, db, since=SINCE, interpretation=dict(RULES)), first)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM draft_schedules").fetchone()[0], 1)
            with self.assertRaisesRegex(ValueError, "jadwal"):
                draft_schedule(capture, "2026-09-25T05:59:00+07:00", db,
                               since=SINCE, interpretation=dict(RULES))

class DatabaseSafetyTests(unittest.TestCase):
    def test_connection_rejects_ghost_run_and_sets_busy_timeout(self):
        from ronce import _connect
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            db = Path(tmp) / "runs.sqlite"
            with closing(_connect(db)) as con, con:
                con.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
                con.execute("CREATE TABLE articles (run_id TEXT REFERENCES runs(id))")
                self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertGreater(con.execute("PRAGMA busy_timeout").fetchone()[0], 0)
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute("INSERT INTO articles VALUES ('ghost')")

class AssumedTimeTests(unittest.TestCase):
    def test_cli_assumed_timezone_works_only_with_explicit_flag(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            path = Path(tmp) / "pages.json"
            path.write_text(json.dumps([page([article("BBCA umumkan dividen tunai", "https://one.test/a")])]), encoding="utf-8")
            result = subprocess.run([sys.executable, "ronce.py", "replay", str(path),
                                     "--since", SINCE, "--cutoff", CUTOFF, "--db", str(Path(tmp) / "runs.sqlite"),
                                     "--assume-timezone", "+07:00"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["time_basis"], "inferred_internal")

    def test_assumed_run_cannot_be_approved_for_platform(self):
        from ronce import replay_assumed, review_claims, approve_packet
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            db = Path(tmp) / "runs.sqlite"
            rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                    article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
            run = replay_assumed([page(rows)], CUTOFF, db, since=SINCE, assume_timezone="+07:00")
            claim = {"text": "BBCA umumkan dividen.", "entity": "BBCA", "action": "umumkan",
                     "event_time": "2026-09-25", "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                                                          for r, o in zip(rows, ("A", "B"))]}
            with self.assertRaisesRegex(ValueError, "asumsi"):
                review_claims(db, run["run_id"], "Editor", [claim], reviewed=True)
            with self.assertRaisesRegex(ValueError, "asumsi"):
                approve_packet(db, run["run_id"], "Editor", claim["text"] + " Sumber: " +
                               " ".join(r["source"] for r in rows), [claim], reviewed=True)

    def test_inferred_sidecar_replay_always_watermarks_draft(self):
        from ronce import replay
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            inferred = {**RULES, "time_basis": "inferred_internal",
                        "evidence": "asumsi demo internal; bukan konfirmasi penyedia"}
            result = replay([page([article("BBCA umumkan dividen tunai", "https://one.test/a")])],
                            CUTOFF, Path(tmp) / "runs.sqlite", since=SINCE, interpretation=inferred)
            self.assertIn("ASUMSI", result["draft"])
            self.assertFalse(result["publishable"])

    def test_inferred_sidecar_rejects_offset_other_than_approved_demo_offset(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            inferred = {**RULES, "source_timezone": "+08:00", "time_basis": "inferred_internal",
                        "evidence": "asumsi demo internal; bukan konfirmasi penyedia"}
            with self.assertRaisesRegex(ValueError, "asumsi"):
                replay([page([article("BBCA umumkan dividen tunai", "https://one.test/a")])],
                       CUTOFF, Path(tmp) / "runs.sqlite", since=SINCE, interpretation=inferred)

    def test_assumed_timezone_is_watermarked_and_separate_from_archive(self):
        from ronce import replay_assumed
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            db = Path(tmp) / "runs.sqlite"
            raw = [page([article("BBCA umumkan dividen tunai", "https://one.test/a")])]
            before = json.dumps(raw, sort_keys=True)
            result = replay_assumed(raw, CUTOFF, db, since=SINCE, assume_timezone="+07:00")
            self.assertEqual(result["time_basis"], "inferred_internal")
            self.assertIn("ASUMSI", result["draft"])
            self.assertFalse(result["publishable"])
            self.assertEqual(json.dumps(raw, sort_keys=True), before)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(json.loads(con.execute("SELECT interpretation_json FROM run_context").fetchone()[0])["time_basis"],
                                 "inferred_internal")

class PlatformLimitTests(unittest.TestCase):
    def test_official_weighted_x_and_conservative_threads_limits(self):
        from ronce import check_platform_text
        x = check_platform_text("x", "Halo https://example.com/panjang/sekali 👨‍👩‍👧‍👦")
        self.assertEqual(x["status"], "documented_rules_applied")
        self.assertTrue(x["valid"])
        self.assertEqual(check_platform_text("x", "漢" * 141)["valid"], False)
        self.assertTrue(check_platform_text("threads", "a" * 500)["valid"])
        self.assertFalse(check_platform_text("threads", "🚀" * 126)["valid"])
        self.assertFalse(check_platform_text("threads", "a" * 501)["valid"])

    def test_edition_preview_blocks_oversized_post(self):
        import ronce
        rows = [article("BBCA umumkan dividen tunai", "https://one.test/a"),
                article("Dividen tunai BBCA diumumkan", "https://two.test/b")]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
            db = Path(temp) / "runs.sqlite"
            run = replay([page(rows)], CUTOFF, db, since=SINCE, interpretation=dict(RULES))
            claim = {"text": "BBCA " + "a" * 501, "entity": "BBCA", "action": "pengumuman",
                     "event_time": "2026-09-25", "evidence": [{"source": r["source"], "quote": r["title"], "origin": o}
                                                          for r, o in zip(rows, ("A", "B"))]}
            ronce.review_claims(db, run["run_id"], "Editor", [claim], reviewed=True)
            posts = ronce.render_draft(db, run["run_id"], "edisi", "threads", [0])
            with self.assertRaisesRegex(ValueError, "batas"):
                ronce.approve_edition(db, run["run_id"], "edisi", "threads", "Editor", posts)


class TopicVocabularyTests(unittest.TestCase):
    """Leksikon tema dwibahasa (P0-1): tiap pola baru punya kasusnya; veto presisi diuji terpisah."""

    def assertEvents(self, cases):
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(_event(title), expected)

    def test_english_dividend_action_classes(self):
        self.assertEvents([
            ("PT Contoh Tbk (AAAA) announces interim dividend of Rp6 per share", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) raises second interim dividend 25% to Rp25 per share", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) cuts its cash dividend to Rp10 per share", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) declares a dividend of Rp5 per share", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) increases its dividend to Rp30 per share", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) pays the cash dividend today", ("dividen", "pembayaran")),
            ("PT Contoh Tbk (AAAA) mengumumkan dividen tunai Rp6 per saham", ("dividen", "pengumuman")),
            ("PT Contoh Tbk (AAAA) membayar dividen tunai Rp6 per saham", ("dividen", "pembayaran")),
            ("PT Contoh Tbk (AAAA) membagikan dividen tunai Rp6 per saham", ("dividen", "pembayaran")),
            ("AAAA dividend outlook improves as profit surges", None),
            ("AAAA announces and pays cash dividend", None),
        ])

    def test_english_and_indonesian_earnings_vocabulary(self):
        self.assertEvents([
            ("PT Contoh Tbk (AAAA) reports US$102 million net profit for H1 2026", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) posts net loss of US$16 million in H1 2026", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) posts 23% profit rise in H1 2026", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) reports lower H1 2026 revenue and profit", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) reports strong H1 2026 earnings", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) files its interim financial report", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) mencatat laba bersih Rp50 miliar", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) membukukan rugi bersih Rp10 miliar", ("laporan keuangan", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) laporkan pendapatan naik 20%", ("laporan keuangan", "peristiwa belum dirinci")),
        ])

    def test_acquisition_vocabulary(self):
        self.assertEvents([
            ("PT Contoh Tbk (AAAA) completes acquisition of five hospitals", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) acquires 34% stake in PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) launches voluntary tender offer for PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) to merge with PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) merger dengan PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) faces a takeover bid", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) divests its fiber assets", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) increases its stake in PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) mengakuisisi 34% saham PT Contoh Dua", ("akuisisi", "peristiwa belum dirinci")),
        ])

    def test_bond_suspension_and_rate_vocabulary(self):
        self.assertEvents([
            ("PT Contoh Tbk (AAAA) defaults on Rp722 billion bond principal payment", ("obligasi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) prepays its maturing debt", ("obligasi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) terbitkan sukuk Rp500 miliar", ("obligasi", "peristiwa belum dirinci")),
            ("PT Contoh Tbk (AAAA) siapkan dana bayar obligasi jatuh tempo", ("obligasi", "peristiwa belum dirinci")),
            ("BEI suspends trading of PT Contoh Karya (AAAA)", ("suspensi", "peristiwa belum dirinci")),
            ("PT Contoh Karya (AAAA) remains under suspension", ("suspensi", "peristiwa belum dirinci")),
            ("BEI places PT Contoh (AAAA) under special monitoring", ("suspensi", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) faces delisting from the exchange", ("suspensi", "peristiwa belum dirinci")),
            ("Bank Indonesia holds BI Rate at 5.75%", ("suku bunga", "peristiwa belum dirinci")),
            ("BI cuts its interest rate by 25 bps", ("suku bunga", "peristiwa belum dirinci")),
            ("Markets await the rate decision this week", ("suku bunga", "peristiwa belum dirinci")),
        ])

    def test_rights_issue_buyback_and_ipo_vocabulary(self):
        self.assertEvents([
            ("PT Contoh (AAAA) announces up to Rp4.1 trillion rights issue", ("rights issue", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) luncurkan right issue tahap IV", ("rights issue", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) begins share buyback on the exchange", ("buyback", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) to repurchase 1 billion shares", ("buyback", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) to buy back its shares", ("buyback", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) buy\u2011back program continues", ("buyback", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) plans its IPO on the IDX", ("ipo", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) sets initial public offering price at Rp100", ("ipo", "peristiwa belum dirinci")),
        ])

    def test_foreign_flow_operations_and_exchange_policy_vocabulary(self):
        self.assertEvents([
            ("Foreign investors net sold Rp4.39 trillion this week", ("aliran asing", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) records largest foreign net buy", ("aliran asing", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) shares see net foreign sell", ("aliran asing", "peristiwa belum dirinci")),
            ("PT Contoh (AAAA) lifts force majeure at its coal mine", ("gangguan operasi", "peristiwa belum dirinci")),
            ("BEI removes Rp50 floor price for Gocap stocks", ("regulasi bursa", "peristiwa belum dirinci")),
            ("Today is the last day of the Rp50 minimum price floor", ("regulasi bursa", "peristiwa belum dirinci")),
            ("Bursa lowers the minimum stock price to Rp1", ("regulasi bursa", "peristiwa belum dirinci")),
            ("BEI reviews its price\u2011floor policy", ("regulasi bursa", "peristiwa belum dirinci")),
        ])

    def test_precision_traps_abstain(self):
        self.assertEvents([
            ("AAAA lists 2 billion shares on the exchange", None),
            ("IHSG falls amid profit-taking", None),
            ("Stocks slip on profit taking", None),
            ("AAAA stakeholders approve the restructuring plan", None),
            ("Commissioner of AAAA disposes of 3 million shares", None),
            ("Directors of AAAA increase shareholdings in September", None),
            ("Tahir sells additional 2.5 million shares of AAAA", None),
            ("AAAA and BBBB flagged as cheap stocks by a broker", None),
            ("United Tractors' long journey toward a sustainable industry", None),
        ])

    def test_digest_roundup_titles_abstain(self):
        self.assertEvents([
            ("Popular news roundup: AAAA plans IPO in October", None),
            ("Popular news roundup highlights PT Contoh (AAAA) revenue growth", None),
        ])


class EnglishFlowReplayTests(unittest.TestCase):
    """Alur arsip EN: pasangan laporan membentuk review; digest & angka bertentangan abstain."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "runs.sqlite"

    def run_replay(self, pages):
        return replay(pages, CUTOFF, self.db, since=SINCE, interpretation=dict(RULES))

    def test_english_earnings_pair_forms_review_candidate(self):
        rows = [article("PT Contoh Tbk (MDKA) reports net profit of US$102 million in H1 2026",
                        "https://one.test/a", symbols=["MDKA"]),
                article("MDKA posts H1 2026 net profit of US$102 million",
                        "https://two.test/b", symbols=["MDKA"])]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "review")
        self.assertEqual([c["topic"] for c in result["candidates"]], ["laporan keuangan"])

    def test_roundup_digest_produces_no_candidate(self):
        rows = [article("Popular news roundup: MDKA net profit surges",
                        "https://one.test/a", symbols=["MDKA"])]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertEqual(result["candidates"], [])

    def test_conflicting_english_amounts_abstain(self):
        rows = [article("PT Contoh Tbk (MDKA) reports net profit of US$102 million in H1 2026",
                        "https://one.test/a", symbols=["MDKA"]),
                article("MDKA posts H1 2026 net profit of US$54 million",
                        "https://two.test/b", symbols=["MDKA"])]
        result = self.run_replay([page(rows)])
        self.assertEqual(result["status"], "abstain")
        self.assertIn("bertentangan", result["candidates"][0]["reason"])

    def test_equivalent_currency_prefixes_and_spacing_review(self):
        rows = [article("PT Contoh (AAAA) acquires clinics for IDR 3.47 trillion", "https://one.test/a", symbols=["AAAA"]),
                article("AAAA completes acquisition for Rp3.47\u202ftriliun", "https://two.test/b", symbols=["AAAA"])]
        self.assertEqual(self.run_replay([page(rows)])["status"], "review")

    def test_same_percentage_with_extra_share_count_reviews(self):
        rows = [article("AAAA acquires 62.5 million shares for 52% stake", "https://one.test/a", symbols=["AAAA"]),
                article("AAAA buys 52% stake", "https://two.test/b", symbols=["AAAA"])]
        self.assertEqual(self.run_replay([page(rows)])["status"], "review")

    def test_matching_two_amounts_in_different_order_reviews(self):
        rows = [article("AAAA announces floor price Rp50 and new floor Rp1", "https://one.test/a", symbols=["AAAA"]),
                article("AAAA floor price moves to Rp1 from Rp50", "https://two.test/b", symbols=["AAAA"])]
        self.assertEqual(self.run_replay([page(rows)])["status"], "review")

    def test_distinct_value_in_shared_unit_abstains_despite_other_match(self):
        rows = [article("AAAA buys 52% stake for IDR 3.47 trillion", "https://one.test/a", symbols=["AAAA"]),
                article("AAAA acquires 52% stake for Rp4.3 trillion", "https://two.test/b", symbols=["AAAA"])]
        self.assertEqual(self.run_replay([page(rows)])["status"], "abstain")

    def test_currency_mismatch_and_numeric_vs_non_numeric_abstain(self):
        cases = [("AAAA buys 52% stake for US$3.47 billion", "AAAA acquires 52% stake for Rp3.47 billion"),
                 ("AAAA buys 52% stake for Rp100", "AAAA acquires 52% stake")]
        for first, second in cases:
            with self.subTest(first=first):
                rows = [article(first, "https://one.test/a", symbols=["AAAA"]),
                        article(second, "https://two.test/b", symbols=["AAAA"])]
                self.assertEqual(self.run_replay([page(rows)])["status"], "abstain")


class FetchTests(unittest.TestCase):
    def test_companion_cli_refuses_missing_key_without_archive(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            target = Path(tmp) / "capture.json"
            env = dict(os.environ)
            env.pop("SECTORS_API_KEY", None)
            result = subprocess.run([sys.executable, "ronce.py", "fetch-companion", "--symbol", "BBCA",
                                     "--start", "2026-09-24", "--end", "2026-09-25", "--out", str(target)],
                                    text=True, capture_output=True, env=env)
            self.assertIn("SECTORS_API_KEY", result.stderr)
            self.assertFalse(target.exists())

    def test_companion_endpoints_archive_synthetic_payloads_without_overwrite(self):
        from ronce import fetch_companion
        from urllib.parse import urlsplit
        fixtures = {"top_changes": {"top_gainers": {"1d": [{"symbol": "BBCA.JK", "price_change": 0.02}]}, "top_losers": {}},
                    "foreign_flow": {"symbol": "BBCA.JK", "data": [{"date": "2026-09-25", "net_foreign_inflow": None}]},
                    "quarterly": [{"symbol": "BBCA.JK", "date": "2026-06-30", "revenue": None}]}
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return json.dumps(self.payload).encode()
        requests = []
        def fake_open(request, timeout):
            requests.append(request)
            self.assertEqual(request.get_header("Authorization"), "secret")
            self.assertNotIn("secret", request.full_url)
            kind = ("top_changes" if "top-changes" in request.full_url else
                    "foreign_flow" if "foreign-flow" in request.full_url else "quarterly")
            return Response(fixtures[kind])
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            target = Path(tmp) / "capture.json"
            with patch("ronce.urlopen", side_effect=fake_open):
                saved = fetch_companion("BBCA", "2026-09-24", "2026-09-25", target, api_key="secret")
                self.assertEqual([x["endpoint"] for x in saved], ["top_changes", "foreign_flow", "quarterly"])
                self.assertEqual([x["response"] for x in saved], list(fixtures.values()))
                self.assertTrue(all(x["fetched_at"].endswith("+00:00") for x in saved))
                with self.assertRaises(FileExistsError):
                    fetch_companion("BBCA", "2026-09-24", "2026-09-25", target, api_key="secret")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), saved)
            self.assertEqual(len(requests), 3)
            self.assertEqual([urlsplit(r.full_url).path for r in requests],
                             ["/v2/companies/top-changes/", "/v2/foreign-flow/BBCA/", "/v2/financials/quarterly/BBCA/"])

    def test_companion_partial_error_leaves_no_archive(self):
        from ronce import fetch_companion
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return json.dumps(self.payload).encode()
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
            target = Path(tmp) / "capture.json"
            with patch("ronce.urlopen", side_effect=[Response({"top_gainers": {}}), Response({"bad": 1})]):
                with self.assertRaisesRegex(ValueError, "foreign_flow"):
                    fetch_companion("BBCA", "2026-09-24", "2026-09-25", target, api_key="secret")
            self.assertFalse(target.exists())
            with patch("ronce.urlopen") as opened:
                with self.assertRaisesRegex(ValueError, "90"):
                    fetch_companion("BBCA", "2026-01-01", "2026-09-25", target, api_key="secret")
                opened.assert_not_called()

    def test_archive_is_atomic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            target = Path(directory) / "pages.json"
            save_archive(target, [{"response": {"results": []}}])
            self.assertEqual(len(json.loads(target.read_text(encoding="utf-8"))), 1)
            with self.assertRaisesRegex(FileExistsError, "arsip"):
                save_archive(target, [{"response": {"results": [1]}}])
            self.assertEqual(len(json.loads(target.read_text(encoding="utf-8"))[0]["response"]["results"]), 0)

    def test_cli_refuses_existing_archive_before_key_or_network(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            target = Path(directory) / "pages.json"
            target.write_text("original", encoding="utf-8")
            env = dict(os.environ)
            env.pop("SECTORS_API_KEY", None)
            result = subprocess.run([sys.executable, "ronce.py", "fetch", "--start", "2026-09-24",
                                     "--end", "2026-09-25", "--out", str(target)],
                                    text=True, capture_output=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("arsip sudah ada", result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_fetch_preserves_pages_and_utc_fetch_time_without_guessing_source_timezone(self):
        responses = [
            {"results": [article("BBCA umumkan dividen tunai", "https://one.test/a")],
             "pagination": {"offset": 0, "showing": 1, "total_count": 2,
                            "has_next": True, "next_offset": 1}},
            {"results": [article("BBCA umumkan dividen tunai", "https://two.test/b")],
             "pagination": {"offset": 1, "showing": 1, "total_count": 2,
                            "has_next": False, "next_offset": None}},
        ]
        urls = []

        class Response:
            status = 200

            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                return json.dumps(self.value).encode()

        def fake_open(request, timeout):
            urls.append(request.full_url)
            self.assertEqual(request.get_header("Authorization"), "secret")
            self.assertEqual(request.get_header("User-agent"), "Ronce-MVP/0.1")
            return Response(responses[len(urls) - 1])

        with patch("ronce.urlopen", side_effect=fake_open):
            pages = fetch_news("2026-09-24", "2026-09-25", api_key="secret", max_pages=2)
        self.assertEqual(len(pages), 2)
        self.assertEqual([p["request"]["offset"] for p in pages], [0, 1])
        self.assertEqual([p["response"] for p in pages], responses)
        self.assertTrue(all("source_timezone" not in p for p in pages))
        self.assertTrue(all(p["fetched_at"].endswith("+00:00") for p in pages))
        self.assertTrue(all("secret" not in u for u in urls))
        with self.assertRaisesRegex(ValueError, "source_timezone"):
            replay(pages, datetime.now(timezone.utc).isoformat(), ":memory:", since=SINCE)

    def test_invalid_date_or_missing_key_fails_before_network(self):
        with patch("ronce.urlopen") as open_url:
            for start, end, key in [("2026-09-25", "2026-09-24", "secret"),
                                     ("2026-09-24", "2026-09-25", ""),
                                     ("2026-09-24x", "2026-09-25", "secret")]:
                with self.assertRaises(ValueError):
                    fetch_news(start, end, api_key=key)
            open_url.assert_not_called()

    def test_last_page_total_count_mismatch_fails_closed(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return json.dumps({"results": [article("BBCA umumkan dividen tunai", "https://one.test/a")],
                    "pagination": {"offset": 0, "showing": 1, "total_count": 2,
                                   "has_next": False, "next_offset": None}}).encode()
        with patch("ronce.urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "pagination"):
                fetch_news("2026-09-24", "2026-09-25", api_key="secret")

    def test_bad_pagination_refuses_partial_archive(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self):
                return json.dumps({"results": [], "pagination": {"offset": 0,
                    "showing": 0, "total_count": 1000, "has_next": True,
                    "next_offset": 30}}).encode()

        with patch("ronce.urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "pagination|batas"):
                fetch_news("2026-09-24", "2026-09-25", api_key="secret", max_pages=1)


if __name__ == "__main__":
    unittest.main()
