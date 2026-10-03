"""Offline outbox checks: durable slots, no blind retries, readback-verified completion.

All stores are synthetic and temporary. No network call is made anywhere in this module; the
transport results here are values handed to `outbox_record`, not real platform responses.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import adapters
import outbox
import ronce
from test_ronce import CUTOFF, RULES, SINCE, article, page

ROWS = [("BBCA uji sintetis umumkan dividen tunai 100 juta rupiah", "https://kanal-a.test/uji/o1"),
        ("Dividen tunai uji sintetis BBCA diumumkan 100 juta rupiah", "https://kanal-b.test/uji/o2")]
ACCOUNT = "akun-uji-sintetis"


def claim():
    return {"text": "BBCA uji sintetis umumkan dividen tunai 100 juta rupiah.",
            "entity": "BBCA", "action": "umumkan", "event_time": "2026-09-25",
            "value": "100", "unit": "rupiah", "scale": "juta", "metric": "dividen", "period": "2026",
            "evidence": [{"source": url, "quote": title, "origin": f"contoh sintetis {index + 1}",
                          "origin_basis": "independent_review",
                          "origin_note": "contoh sintetis: dua judul uji terpisah"}
                         for index, (title, url) in enumerate(ROWS)]}


def approved_edition(db):
    """Replay, review, approve one post; return (run_id, edition_id, platform, post_text)."""
    rows = [article(title, url) for title, url in ROWS]
    run = ronce.replay([page(rows, fetched_at="2026-09-25T10:00:00+07:00")], CUTOFF, db,
                       since=SINCE, interpretation=dict(RULES))
    ronce.review_claims(db, run["run_id"], "Editor Uji", [claim()], reviewed=True)
    ronce.migrate(db)
    ronce.register_versioned_stories(db, run["run_id"])
    posts = ronce.render_draft(db, run["run_id"], "edisi-uji", "threads", [0])
    ronce.approve_edition(db, run["run_id"], "edisi-uji", "threads", "Editor Uji", posts)
    return run["run_id"], "edisi-uji", "threads", posts[0]


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.run_id, self.edition_id, self.platform, self.text = approved_edition(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, **overrides):
        arguments = {"account": ACCOUNT}
        arguments.update(overrides)
        return outbox.outbox_plan(self.db, self.run_id, self.edition_id, self.platform, **arguments)

    def test_plan_requires_an_approved_edition_and_pins_hashes(self):
        with self.assertRaises(ValueError):
            outbox.outbox_plan(self.db, self.run_id, "belum-ada", self.platform, account=ACCOUNT)
        planned = self.plan()
        self.assertEqual(len(planned["posts"]), 1)
        post = planned["posts"][0]
        self.assertEqual(post["state"], "planned")
        self.assertEqual(post["text"], self.text)
        self.assertEqual(post["text_hash"], outbox.outbox_text_hash(self.text))
        self.assertEqual(post["next_action"], "submit")
        self.assertFalse(planned["api_write"])
        # Idempotent re-plan returns the same row.
        again = self.plan()
        self.assertEqual(again["posts"][0]["updated_at"], post["updated_at"])
        # A different account on a planned slot is refused.
        with self.assertRaisesRegex(ValueError, "terkunci"):
            self.plan(account="akun-lain")

    def test_created_requires_external_id_and_readback_verifies(self):
        self.plan()
        with self.assertRaisesRegex(ValueError, "external_id"):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "created")
        recorded = outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1,
                                        "created", external_id="post-uji-1")
        self.assertEqual(recorded["state"], "created")
        self.assertEqual(recorded["next_action"], "readback_first")
        # A blind resubmit while created is refused.
        with self.assertRaisesRegex(ValueError, "baca balik"):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "created",
                                 external_id="post-uji-2")
        readback = {"id": "post-uji-1", "text": self.text, "username": ACCOUNT}
        verified = outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1,
                                          readback)
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(verified["next_action"], "already_done")
        # Repeating the identical readback is an idempotent no-op.
        again = outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1,
                                       readback)
        self.assertEqual(again["state"], "verified")
        status = outbox.outbox_status(self.db, self.run_id, self.edition_id, self.platform)
        self.assertEqual(status["pending"], [])

    def test_readback_mismatch_is_terminal_for_manual_review(self):
        self.plan()
        outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "created",
                             external_id="post-uji-1")
        mismatch = outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1,
                                          {"id": "post-uji-1", "text": "teks berbeda",
                                           "username": ACCOUNT})
        self.assertEqual(mismatch["state"], "mismatch")
        self.assertEqual(mismatch["next_action"], "manual_review")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "failed")

    def test_ambiguous_requires_readback_or_explicit_absence_confirmation(self):
        self.plan()
        recorded = outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1,
                                        "timeout")
        self.assertEqual(recorded["state"], "ambiguous")
        self.assertEqual(recorded["next_action"], "readback_first")
        with self.assertRaisesRegex(ValueError, "baca balik"):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "failed")
        with self.assertRaisesRegex(ValueError, "konfirmasi"):
            outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1, None)
        # Explicit operator confirmation that the post is absent resolves it to failed (retryable).
        failed = outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1, None,
                                        confirm_absent=True)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["next_action"], "retry_after_fix")
        retried = outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1,
                                       "created", external_id="post-uji-3")
        self.assertEqual(retried["state"], "created")

    def test_ambiguous_readback_that_finds_the_post_verifies(self):
        self.plan()
        outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "partial_failure")
        verified = outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 1,
                                          {"id": "post-uji-9", "text": self.text, "username": ACCOUNT})
        self.assertEqual(verified["state"], "verified")

    def test_rate_limited_and_failed_states_map_to_safe_actions(self):
        self.plan()
        limited = outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1,
                                       "rate_limited", retry_after="2026-10-02T09:00:00Z")
        self.assertEqual(limited["state"], "rate_limited")
        self.assertEqual(limited["retry_after"], "2026-10-02T09:00:00Z")
        self.assertEqual(limited["next_action"], "wait_then_retry")
        failed = outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "failed")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["next_action"], "retry_after_fix")

    def test_unknown_outcome_and_unplanned_slot_are_refused(self):
        self.plan()
        with self.assertRaises(ValueError):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 1, "published")
        with self.assertRaises(ValueError):
            outbox.outbox_record(self.db, self.run_id, self.edition_id, self.platform, 2, "failed")
        with self.assertRaises(ValueError):
            outbox.outbox_readback(self.db, self.run_id, self.edition_id, self.platform, 2, None,
                                   confirm_absent=True)

    def test_status_on_an_unplanned_edition_is_empty_not_an_error(self):
        status = outbox.outbox_status(self.db, self.run_id, "belum-ada", self.platform)
        self.assertEqual(status["posts"], [])
        self.assertEqual(status["pending"], [])

    def test_live_publishing_stays_disabled_and_adapters_refuse_blind_writes(self):
        self.assertFalse(adapters.LIVE_PUBLISHING)
        request = {"platform": "threads", "method": "POST", "url": "https://example.invalid",
                   "json": {"text": self.text}}
        with self.assertRaises(adapters.PublicationRefused):
            adapters.publication_preflight(request, None, account=ACCOUNT)

    def test_plan_refuses_when_a_newer_story_revision_exists(self):
        # A second run revises the story; the old approval must not authorize a fresh plan.
        rows = [("BBCA uji sintetis umumkan dividen tunai 120 juta rupiah", "https://kanal-a.test/uji/o3"),
                ("Dividen tunai uji sintetis BBCA diumumkan 120 juta rupiah", "https://kanal-b.test/uji/o4")]
        run_b = ronce.replay([page([article(title, url) for title, url in rows],
                                   fetched_at="2026-09-25T12:00:00+07:00")],
                             "2026-09-25T13:00:00+07:00", self.db, since=SINCE,
                             interpretation=dict(RULES))
        revised = dict(claim(), value="120",
                       text="BBCA uji sintetis umumkan dividen tunai 120 juta rupiah.",
                       evidence=[{"source": url, "quote": title, "origin": f"contoh sintetis {index + 1}",
                                  "origin_basis": "independent_review",
                                  "origin_note": "contoh sintetis: dua judul uji terpisah"}
                                 for index, (title, url) in enumerate(rows)])
        ronce.review_claims(self.db, run_b["run_id"], "Editor Uji", [revised], reviewed=True)
        ronce.register_versioned_stories(self.db, run_b["run_id"])
        with self.assertRaisesRegex(ValueError, "revisi cerita berubah"):
            self.plan()


if __name__ == "__main__":
    unittest.main()
