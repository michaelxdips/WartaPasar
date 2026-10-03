"""Companion adapter contract tests: acquisition states, normalization and failure isolation.

All payloads here are synthetic contract fixtures shaped like the documented envelopes
(checked 2026-09-30 / 2026-10-02); nothing is a live provider response.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion  # noqa: E402
import ronce  # noqa: E402


def movers_fixture():
    return {"top_gainers": {"1d": [{"symbol": "BBCA.JK", "name": "Bank Central Asia", "price_change": 0.021,
                                    "last_close_price": 8975, "latest_close_date": "2026-09-25"}],
                            "7d": []},
            "top_losers": {"1d": [{"symbol": "GOTO.JK", "name": "GoTo Gojek Tokopedia", "price_change": -0.031,
                                   "last_close_price": 62, "latest_close_date": "2026-09-25"}], "7d": []}}


def daily_fixture():
    return [{"symbol": "BBCA.JK", "date": "2026-09-25", "close": 8975, "open": None, "high": 9000,
             "low": 8850, "volume": 92219000, "market_cap": 1095329638012500}]


def flow_fixture(days=3):
    return {"symbol": "BBCA.JK", "start": "2026-09-22", "end": "2026-09-25",
            "data": [{"date": f"2026-09-{22 + index}", "net_foreign_inflow": 1000 * index,
                      "foreign_buy_idr": 5000, "foreign_sell_idr": 4000, "foreign_share": 0.12}
                     for index in range(days)]}


def actions_fixture():
    return [{"symbol": "BBCA.JK", "type": "dividend", "announcement_date": "2026-09-20",
             "cum_date": "2026-09-24", "ex_date": "2026-09-25", "record_date": None,
             "payment_date": "2026-10-10", "status": "tercatat", "source": "https://www.idx.co.id/announcement"}]


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.db = Path(self._tmp.name) / "companion.sqlite"
        companion.migrate_companion(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_integration_denied_quarterly_and_partial_flow_do_not_hide_successes(self):
        runs_db = Path(self._tmp.name) / "runs.sqlite"
        news = ronce.replay(
            [{"fetched_at": "2026-09-25T10:00:00+07:00",
              "response": {"results": [
                  {"title": "BBCA umumkan dividen tunai 100 juta rupiah", "body": "BBCA umumkan dividen tunai 100 juta rupiah",
                   "source": "https://kanal-a.test/1", "timestamp": "2026-09-25T09:00:00", "symbols": ["BBCA"],
                   "tags": ["dividend"], "sector": "financials"},
                  {"title": "Dividen tunai BBCA diumumkan 100 juta rupiah", "body": "Dividen tunai BBCA diumumkan 100 juta rupiah",
                   "source": "https://kanal-b.test/2", "timestamp": "2026-09-25T09:00:00", "symbols": ["BBCA"],
                   "tags": ["dividend"], "sector": "financials"}],
                  "pagination": {"offset": 0, "showing": 2, "total_count": 2, "has_next": False, "next_offset": None}}},
            ], "2026-09-25T11:00:00+07:00", runs_db,
            since="2026-09-22T00:00:00+07:00",
            interpretation={"source_timezone": "+07:00", "timestamp_meaning": "source_publication",
                            "filter_timezone": "+07:00", "start_inclusive": True, "end_inclusive": True,
                            "evidence": "fixture uji"})
        self.assertEqual(news["status"], "review")

        movers = companion.import_family(self.db, "movers", movers_fixture(), scope={"classifications": "top_gainers,top_losers", "periods": "1d,7d"})
        self.assertEqual(movers["status"]["status"], "success")

        def denied(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)
        quarterly = companion.fetch_family(self.db, "quarterly", scope={"symbol": "BBCA", "n_quarters": 1},
                                           api_key="secret-key", transport=denied)
        self.assertEqual(quarterly["status"]["status"], "denied")
        self.assertEqual(quarterly["attempts"], 1, "denial tidak boleh diulang")

        partial = companion.import_family(self.db, "foreign_flow", flow_fixture(days=2),
                                          scope={"symbol": "BBCA", "start": "2026-09-22", "end": "2026-09-25",
                                                 "expect_days": 4})
        self.assertEqual(partial["status"]["status"], "incomplete")
        self.assertFalse(partial["status"]["pagination"]["complete"])

        state = companion.companion_state(self.db)
        statuses = {row["family"]: row["status"] for row in state["status"]}
        self.assertEqual(statuses["movers"], "success")
        self.assertEqual(statuses["quarterly"], "denied")
        self.assertEqual(statuses["foreign_flow"], "incomplete")
        self.assertTrue(any(record["family"] == "movers" for record in state["records"]))
        text = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("secret-key", text, "kunci tidak boleh masuk status atau record")
        with closing(sqlite3.connect(runs_db)) as con:
            archived = con.execute("SELECT COUNT(*) FROM articles WHERE run_id=?", (news["run_id"],)).fetchone()[0]
        self.assertEqual(archived, 2, "berita valid tetap utuh saat companion gagal")

    def test_empty_is_not_denied(self):
        empty = companion.import_family(self.db, "filings", {"results": [], "pagination": {"total_count": 0, "showing": 0, "has_next": False}}, scope={"symbol": "ZZZZ"})
        self.assertEqual(empty["status"]["status"], "empty")
        self.assertEqual(empty["records"], [])
        self.assertNotEqual(empty["status"]["status"], "denied")

    def test_rate_limited_retries_then_succeeds(self):
        calls = {"count": 0}

        def flaky(request, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
            return daily_fixture()
        result = companion.fetch_family(self.db, "daily", scope={"symbol": "BBCA", "start": "2026-09-25", "end": "2026-09-25"},
                                        api_key="k", transport=flaky)
        self.assertEqual(result["status"]["status"], "success")
        self.assertEqual(calls["count"], 2)

    def test_malformed_payload_is_recorded_and_yields_no_records(self):
        result = companion.import_family(self.db, "filings", {"unexpected": True}, scope={"symbol": "BBCA"})
        self.assertEqual(result["status"]["status"], "malformed")
        self.assertEqual(result["records"], [])
        state = companion.companion_state(self.db)
        self.assertEqual(state["status"][0]["status"], "malformed")

    def test_quarterly_success_path_records_typed_rows(self):
        """The quarterly family is otherwise only exercised through a denial; cover its success path."""
        payload = [{"symbol": "BBCA.JK", "date": "2026-06-30", "revenue": 25000000000000,
                    "earnings": 9000000000000, "total_assets": None, "total_equity": 90000000000000}]
        result = companion.import_family(self.db, "quarterly", payload,
                                         scope={"symbol": "BBCA", "n_quarters": 1})
        self.assertEqual(result["status"]["status"], "success")
        self.assertEqual(result["status"]["records"], 1)
        record = result["records"][0]
        self.assertEqual(record["family"], "quarterly")
        self.assertEqual(record["symbol"], "BBCA")
        self.assertEqual(record["period"], "2026-06-30")
        self.assertEqual(record["value"]["revenue"], 25000000000000)
        self.assertIsNone(record["value"]["total_assets"], "null tetap null, bukan nol")
        # A malformed quarterly payload (not a list) is refused, not silently accepted.
        refused = companion.import_family(self.db, "quarterly", {"symbol": "BBCA"},
                                          scope={"symbol": "BBCA", "n_quarters": 1})
        self.assertEqual(refused["status"]["status"], "malformed")
        self.assertEqual(refused["records"], [])

    def test_null_stays_null_and_is_not_zero(self):
        companion.import_family(self.db, "daily", daily_fixture(), scope={"symbol": "BBCA"})
        record = companion.companion_state(self.db)["records"][0]
        self.assertIsNone(record["value"]["open"], "null tidak boleh menjadi 0")
        self.assertEqual(record["value"]["close"], 8975)

    def test_repeat_import_is_idempotent(self):
        first = companion.import_family(self.db, "daily", daily_fixture(), scope={"symbol": "BBCA"})
        second = companion.import_family(self.db, "daily", daily_fixture(), scope={"symbol": "BBCA"})
        self.assertEqual(first["status"]["payload_sha256"], second["status"]["payload_sha256"])
        with closing(sqlite3.connect(self.db)) as con:
            count = con.execute("SELECT COUNT(*) FROM companion_records").fetchone()[0]
        self.assertEqual(count, 1)

    def test_foreign_flow_keeps_its_documented_investor_origin_definition(self):
        """Documented 2026-10-02: flow is attributed by investor origin, not by broker ownership."""
        companion.import_family(self.db, "foreign_flow", flow_fixture(), scope={"symbol": "BBCA"})
        rows = companion.companion_state(self.db)["records"]
        record = next(row for row in rows if row["period"] == "2026-09-24")
        definition = record["value"]["definition"]
        self.assertIn("investor asing", definition)
        self.assertIn("bukan asal broker", definition)
        self.assertNotIn("broker asing", definition)
        # The documented fields survive verbatim and are not recomputed from the definition.
        self.assertEqual(record["value"]["net_foreign_inflow"], 2000)
        self.assertEqual(record["value"]["foreign_buy_idr"], 5000)
        self.assertEqual(record["value"]["foreign_sell_idr"], 4000)
        self.assertEqual(record["value"]["foreign_share"], 0.12)
        # A day without a foreign split keeps its documented null instead of becoming zero.
        payload = {"symbol": "BBCA.JK", "data": [{"date": "2026-09-29", "net_foreign_inflow": None,
                                                  "foreign_buy_idr": None, "foreign_sell_idr": None,
                                                  "foreign_share": None}]}
        companion.import_family(self.db, "foreign_flow", payload, scope={"symbol": "BBCA", "expect_days": 1})
        null_rows = [row for row in companion.companion_state(self.db)["records"] if row["period"] == "2026-09-29"]
        self.assertIsNone(null_rows[0]["value"]["net_foreign_inflow"], "null bukan nol")

    def test_calendar_date_kinds_stay_separate(self):
        companion.import_family(self.db, "corporate_actions", actions_fixture(), scope={"symbol": "BBCA"})
        record = companion.companion_state(self.db)["records"][0]
        dates = record["value"]["dates"]
        self.assertEqual(dates["ex"], "2026-09-25")
        self.assertEqual(dates["payment"], "2026-10-10")
        self.assertIsNone(dates["record"], "tanggal yang tidak ada tetap kosong, bukan tengah malam")
        self.assertNotIn("T00:00:00", json.dumps(dates))

    def test_unsupported_family_is_refused(self):
        with self.assertRaisesRegex(ValueError, "tidak dikenal"):
            companion.import_family(self.db, "hantu", {}, scope={})


if __name__ == "__main__":
    unittest.main()
