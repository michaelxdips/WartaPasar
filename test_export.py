"""Web edition contract v1: determinism, atomicity, and the public-field policy."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import export
import ronce
from test_ronce import CUTOFF, RULES, SINCE, article, page

CLAIM = {"text": "BBCA mengumumkan dividen tunai 100 rupiah.", "entity": "BBCA",
         "action": "umumkan", "event_time": "2026-09-25", "value": "100", "unit": "rupiah",
         "scale": "unit", "metric": "dividen tunai", "period": "2026"}


def rows():
    first = article("BBCA umumkan dividen tunai 100 rupiah", "https://one.test/a")
    second = article("Dividen tunai BBCA diumumkan 100 rupiah", "https://two.test/b")
    first["body"] = "RAHASIA-BODY satu.test"
    second["body"] = "RAHASIA-BODY dua.test"
    return first, second


def approved(db):
    first, second = rows()
    run = ronce.replay([page([first, second])], CUTOFF, db, since=SINCE, interpretation=dict(RULES))
    claim = dict(CLAIM, evidence=[
        {"source": first["source"], "quote": first["title"], "origin": "A", "origin_basis": "independent_review", "origin_note": "Tinjauan editorial: asal terpisah dari rilis atau laporan lain."},
        {"source": second["source"], "quote": second["title"], "origin": "B", "origin_basis": "independent_review", "origin_note": "Tinjauan editorial: asal terpisah dari rilis atau laporan lain."}])
    ronce.review_claims(db, run["run_id"], "Editor", [claim], reviewed=True)
    ronce.migrate(db)
    ronce.register_versioned_stories(db, run["run_id"])
    posts = ronce.render_draft(db, run["run_id"], "edisi-pagi", "threads", [0])
    ronce.approve_edition(db, run["run_id"], "edisi-pagi", "threads", "Editor", posts)
    return run["run_id"]


class ExportContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.run_id = approved(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_export_writes_the_contract_and_never_bodies(self):
        target = self.tmp / "public"
        manifest = export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", target)
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ["claims.json", "edition.json", "manifest.json", "model.json", "stories.json"])
        text = "\n".join((target / name).read_text(encoding="utf-8")
                         for name in export.CONTENT_FILES)
        self.assertNotIn("RAHASIA-BODY", text)
        self.assertIn("BBCA umumkan dividen tunai 100 rupiah", text)
        self.assertEqual(manifest["counts"]["stories"], 1)
        self.assertEqual(manifest["counts"]["claims"], 1)
        self.assertEqual(manifest["counts"]["posts"], 1)
        self.assertEqual(manifest["counts"]["revisions"], 1)
        self.assertEqual(manifest["counts"]["topics"], 1)
        self.assertFalse(manifest["policy"]["bodies_exported"])
        self.assertFalse(manifest["policy"]["live_publishing"])

    def test_content_is_deterministic_and_manifest_hashes_match(self):
        first = self.tmp / "export-a"
        second = self.tmp / "export-b"
        manifest_a = export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", first)
        manifest_b = export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", second)
        for name in export.CONTENT_FILES:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
            digest = __import__("hashlib").sha256((first / name).read_bytes()).hexdigest()
            self.assertEqual(manifest_a["files"][name], digest, name)
        self.assertEqual({k: v for k, v in manifest_a.items() if k != "generated_at"},
                         {k: v for k, v in manifest_b.items() if k != "generated_at"})

    def test_export_is_exclusive_and_leaves_no_staging_behind(self):
        target = self.tmp / "public"
        export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", target)
        with self.assertRaises(FileExistsError):
            export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", target)
        with self.assertRaisesRegex(ValueError, "disetujui"):
            export.export_edition(self.db, self.run_id, "edisi-hantu", "threads", self.tmp / "ghost")
        self.assertFalse((self.tmp / "ghost").exists())
        leftovers = [p.name for p in self.tmp.iterdir() if p.name.startswith(".public-")]
        self.assertEqual(leftovers, [])

    def test_ids_are_content_addressed_and_linked(self):
        payload = export.build_export(self.db, self.run_id, "edisi-pagi", "threads")
        rebuilt = export.build_export(self.db, self.run_id, "edisi-pagi", "threads")
        story = payload["stories"][0]
        claim = payload["claims"][0]
        self.assertEqual(story["id"], rebuilt["stories"][0]["id"], "id stabil antar rebuild")
        self.assertRegex(story["id"], r"^[0-9a-f]{16}$")
        self.assertEqual(claim["id"], export.stable_id(story["id"], claim["text"]))
        self.assertEqual(claim["story_id"], story["id"])
        self.assertEqual(payload["edition"]["posts"][0]["claim_id"], claim["id"])
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["model"]["topics"][0]["id"], "dividen")
        self.assertEqual(payload["model"]["identities"][0]["story_key"], story["id"])
        self.assertEqual(payload["model"]["revisions"][0]["story_key"], story["id"])
        self.assertEqual(story["revision"]["revision_id"], payload["model"]["revisions"][0]["revision_id"])
        self.assertEqual(story["status"], "active")
        self.assertEqual(story["relations"], [])
        self.assertEqual(payload["coverage"]["policy_version"], ronce.POLICY_VERSION)
        self.assertEqual({item["origin_basis"] for item in claim["evidence"]}, {"independent_review"})
        self.assertEqual(story["counts"], {"articles": 2, "publishers": 2, "sources": 2})
        moved = export.story_id({"symbol": story["symbol"], "topic": story["topic"],
                                 "action": story["action"], "date": "2026-09-26"})
        self.assertNotEqual(moved, story["id"], "tanggal adalah bagian dari identitas")

    def test_export_cli_runs_end_to_end(self):
        target = self.tmp / "cli-export"
        result = subprocess.run(
            [sys.executable, "ronce.py", "export-edition", "--db", str(self.db), "--run-id",
             self.run_id, "--edition-id", "edisi-pagi", "--platform", "threads",
             "--out-dir", str(target)], capture_output=True, text=True, cwd=Path(__file__).parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["edition_uid"], export.stable_id(self.run_id, "edisi-pagi", "threads"))
        self.assertTrue((target / "manifest.json").exists())


class VersionModelTests(unittest.TestCase):
    """Persisted model: migrations, stable identity, immutable revisions, relations, withdrawal."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.first, self.second = rows()
        self.run = self.seed_run()

    def tearDown(self):
        self._tmp.cleanup()

    def seed_run(self):
        return ronce.replay([page([self.first, self.second])], CUTOFF, self.db, since=SINCE,
                            interpretation=dict(RULES))

    def test_migration_is_idempotent_and_preserves_approved_records(self):
        run_id = approved(self.db)
        before = ronce.preview_edition(self.db, run_id, "edisi-pagi", "threads")
        ronce.migrate(self.db)
        ronce.migrate(self.db)
        model = ronce.story_model(self.db)
        self.assertEqual(len(model["identities"]), 1)
        self.assertEqual(len(model["revisions"]), 1)
        after = ronce.preview_edition(self.db, run_id, "edisi-pagi", "threads")
        self.assertEqual(before["hash"], after["hash"])

    def test_repeat_ingestion_creates_no_duplicate_identity_or_revision(self):
        ronce.migrate(self.db)
        first = ronce.register_versioned_stories(self.db, self.run["run_id"])
        second = ronce.register_versioned_stories(self.db, self.run["run_id"])
        self.assertEqual(first["written"]["revisions"], 1)
        self.assertEqual(second["written"]["revisions"], 0)
        self.assertEqual(second["written"]["identities"], 0)
        self.assertEqual(second["written"]["topics"], 0)
        self.assertEqual(second["written"]["unchanged"], 1)
        model = ronce.story_model(self.db)
        self.assertEqual((len(model["identities"]), len(model["revisions"])), (1, 1))

    def test_changed_content_adds_an_immutable_revision_under_the_same_identity(self):
        ronce.migrate(self.db)
        ronce.register_versioned_stories(self.db, self.run["run_id"])
        with closing(sqlite3.connect(self.db)) as con, con:
            payload = json.loads(con.execute("SELECT payload FROM articles WHERE run_id=? AND source=?",
                                            (self.run["run_id"], self.first["source"])).fetchone()[0])
            payload["title"] = payload["title"] + " (koreksi)"
            con.execute("UPDATE articles SET payload=? WHERE run_id=? AND source=?",
                        (json.dumps(payload), self.run["run_id"], self.first["source"]))
        again = ronce.register_versioned_stories(self.db, self.run["run_id"])
        self.assertEqual(again["written"]["revisions"], 1)
        self.assertEqual(again["written"]["identities"], 0)
        model = ronce.story_model(self.db)
        self.assertEqual(len(model["identities"]), 1, "identitas stabil tidak boleh bercabang")
        self.assertEqual(len(model["revisions"]), 2, "konten berbeda harus menjadi revisi baru")
        self.assertEqual(len({row["revision_id"] for row in model["revisions"]}), 2)
        self.assertEqual({row["story_key"] for row in model["revisions"]}, {model["identities"][0]["story_key"]})

    def test_relations_require_valid_endpoints_and_provenance(self):
        run_id = approved(self.db)
        model = ronce.story_model(self.db)
        key = model["identities"][0]["story_key"]
        with self.assertRaisesRegex(ValueError, "tidak ada pada registri"):
            ronce.add_relation(self.db, "supports", key, "0" * 16, reason="alasan cukup", evidence="uji")
        with self.assertRaisesRegex(ValueError, "alasan"):
            ronce.add_relation(self.db, "supports", key, key, reason="x", evidence="uji")
        with self.assertRaisesRegex(ValueError, "bukti"):
            ronce.add_relation(self.db, "supports", key, key, reason="alasan cukup", evidence=" ")
        first = ronce.add_relation(self.db, "contradicts", key, key, reason="dua sumber berbeda angka",
                                   evidence="uji sintetis: dua judul bentrok", from_revision=model["revisions"][0]["revision_id"])
        second = ronce.add_relation(self.db, "contradicts", key, key, reason="dua sumber berbeda angka",
                                    evidence="uji sintetis: dua judul bentrok", from_revision=model["revisions"][0]["revision_id"])
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["relation_id"], second["relation_id"])
        payload = export.build_export(self.db, run_id, "edisi-pagi", "threads")
        self.assertEqual(payload["stories"][0]["relations"], [first["relation_id"]])
        self.assertEqual(payload["model"]["relations"][0]["reason"], "dua sumber berbeda angka")

    def test_withdrawal_requires_reason_and_evidence_and_is_exported(self):
        run_id = approved(self.db)
        model = ronce.story_model(self.db)
        key = model["identities"][0]["story_key"]
        with self.assertRaisesRegex(ValueError, "bukti"):
            ronce.withdraw_story(self.db, key, reason="salah kutip", evidence=" ")
        ronce.withdraw_story(self.db, key, reason="salah kutip angka", evidence="uji sintetis: koreksi redaksi")
        payload = export.build_export(self.db, run_id, "edisi-pagi", "threads")
        self.assertEqual(payload["stories"][0]["status"], "withdrawn")
        self.assertEqual(payload["model"]["status"][0]["story_key"], key)

    def test_export_requires_the_migrated_model(self):
        run_id = approved(self.db)
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("DROP TABLE story_revisions")
        with self.assertRaisesRegex(ValueError, "belum dimigrasi|revisi cerita tidak terbaca"):
            export.build_export(self.db, run_id, "edisi-pagi", "threads")


class SchemaCompatibilityTests(unittest.TestCase):
    """Schema-v1 artifacts stay readable through the web preparation boundary."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.run_id = approved(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def prepare(self, export_dir):
        return subprocess.run(["node", "scripts/prepare-data.mjs"], cwd=Path(__file__).parent / "web",
                              env=dict(os.environ, RONCE_EXPORT_DIR=str(export_dir)),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_v2_export_passes_and_v1_shaped_artifact_still_reads(self):
        v2 = self.tmp / "v2"
        export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", v2)
        result = self.prepare(v2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skema v2", result.stdout)

        # A v1 artifact is the same content without the model file and without the v2 fields.
        v1 = self.tmp / "v1"
        v1.mkdir()
        for name in ("manifest.json", "edition.json", "stories.json", "claims.json"):
            payload = json.loads((v2 / name).read_text(encoding="utf-8"))
            payload["schema_version"] = 1
            if name == "stories.json":
                for story in payload["stories"]:
                    for field in ("revision", "status", "relations"):
                        story.pop(field, None)
            (v1 / name).write_text(json.dumps(payload), encoding="utf-8")
        result = self.prepare(v1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skema v1", result.stdout)

    def test_v2_export_with_a_broken_relation_is_refused(self):
        v2 = self.tmp / "v2-broken"
        export.export_edition(self.db, self.run_id, "edisi-pagi", "threads", v2)
        model = json.loads((v2 / "model.json").read_text(encoding="utf-8"))
        model["model"]["relations"] = [{"relation_id": "0" * 16, "kind": "supports", "from_story": "0" * 16,
                                        "to_story": "0" * 16, "from_revision": None, "to_revision": None,
                                        "reason": "alasan", "evidence": "bukti"}]
        (v2 / "model.json").write_text(json.dumps(model), encoding="utf-8")
        result = self.prepare(v2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identitas tak dikenal", result.stdout + result.stderr)


class ComparisonAndBindingTests(unittest.TestCase):
    """Revision readability, revision-bound approval, comparison categories, citation fields."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "runs.sqlite"
        self.first, self.second = rows()
        self.run_id = approved(self.db)
        self.model = ronce.story_model(self.db)
        self.key = self.model["identities"][0]["story_key"]

    def tearDown(self):
        self._tmp.cleanup()

    def touch_article(self, source, suffix):
        with closing(sqlite3.connect(self.db)) as con, con:
            payload = json.loads(con.execute("SELECT payload FROM articles WHERE run_id=? AND source=?",
                                            (self.run_id, source)).fetchone()[0])
            payload["title"] = payload["title"] + suffix
            con.execute("UPDATE articles SET payload=? WHERE run_id=? AND source=?",
                        (json.dumps(payload), self.run_id, source))

    def test_exported_revisions_carry_their_own_immutable_content(self):
        payload = export.build_export(self.db, self.run_id, "edisi-pagi", "threads")
        revision = payload["model"]["revisions"][0]
        self.assertEqual(revision["story_key"], self.key)
        self.assertEqual(revision["payload"]["status_at"], "active")
        self.assertTrue(revision["payload"]["claims"][0]["evidence"][0]["quote"])
        self.assertEqual(revision["payload"]["claims"][0]["value"], "100")
        text = json.dumps(payload["model"], ensure_ascii=False)
        self.assertNotIn("Tinjauan editorial", text, "alasan internal tidak boleh diekspor")
        self.assertNotIn("RAHASIA-BODY", text)

    def test_new_revision_invalidates_the_old_approval_and_a_fresh_approval_works(self):
        with closing(sqlite3.connect(self.db)) as con:
            edition = json.loads(con.execute(
                "SELECT payload FROM editions WHERE run_id=? AND edition_id='edisi-pagi'",
                (self.run_id,)).fetchone()[0])
        self.assertEqual(list(edition["bound"]["revisions"].values()),
                         [self.model["revisions"][0]["revision_id"]],
                         "persetujuan harus menyebut revisi yang diizinkan")
        self.touch_article(self.first["source"], " (koreksi)")
        ronce.register_versioned_stories(self.db, self.run_id)
        self.assertEqual(len(ronce.story_model(self.db)["revisions"]), 2)
        with self.assertRaisesRegex(ValueError, "berubah"):
            ronce.preview_edition(self.db, self.run_id, "edisi-pagi", "threads")
        with self.assertRaisesRegex(ValueError, "berubah"):
            export.build_export(self.db, self.run_id, "edisi-pagi", "threads")

    def test_comparison_reports_a_source_title_update(self):
        self.touch_article(self.first["source"], " (judul diperbarui)")
        ronce.register_versioned_stories(self.db, self.run_id)
        pairs = ronce.story_model(self.db)["comparisons"]
        self.assertEqual(len(pairs), 1)
        kinds = {change["kind"] for change in pairs[0]["changes"]}
        self.assertIn("source_updated", kinds)
        self.assertNotIn("claim_corrected", kinds, "judul sumber saja bukan koreksi angka")

    def test_change_categories_from_typed_records_and_field_diffs(self):
        import ronce as engine
        base = {"story_key": self.key, "decision": "review", "reason": "dua penerbit", "status_at": "active",
                "policy_version": engine.POLICY_VERSION,
                "sources": [{"url": "https://a.test/1", "title": "Judul A", "timestamp": "2026-09-25T09:00:00"},
                            {"url": "https://b.test/2", "title": "Judul B", "timestamp": "2026-09-25T09:00:00"}],
                "claims": [{"text": "Nilai 100 juta rupiah.", "entity": "BBCA", "action": "umumkan",
                            "value": "100", "unit": "rupiah", "scale": "juta", "metric": "dividen",
                            "period": "2026", "claim_type": "reported_fact",
                            "evidence": [{"url": "https://a.test/1", "quote": "q1", "origin": "A", "origin_basis": "independent_review"},
                                         {"url": "https://b.test/2", "quote": "q2", "origin": "B", "origin_basis": "independent_review"}]}]}
        changed = json.loads(json.dumps(base))
        changed["claims"][0]["value"] = "120"
        kinds = {change["kind"] for change in engine.compare_revisions(base, changed, [], story_key=self.key)}
        self.assertEqual(kinds, {"claim_corrected"})
        edited = json.loads(json.dumps(base))
        edited["claims"][0]["text"] = "Nilai 100 juta rupiah (disunting)."
        self.assertEqual({change["kind"] for change in engine.compare_revisions(base, edited, [], story_key=self.key)},
                         {"text_only"})
        withdrawn = json.loads(json.dumps(base))
        withdrawn["status_at"] = "withdrawn"
        self.assertEqual({change["kind"] for change in engine.compare_revisions(base, withdrawn, [], story_key=self.key)},
                         {"withdrawal"})
        relation = [{"kind": "corrects", "from_story": self.key, "to_story": self.key}]
        labelled = engine.compare_revisions(base, changed, relation, story_key=self.key)
        self.assertEqual(labelled[0]["basis"], "relasi koreksi")
        without_evidence = json.loads(json.dumps(base))
        without_evidence["claims"][0]["evidence"] = without_evidence["claims"][0]["evidence"][:1]
        kinds = {change["kind"] for change in engine.compare_revisions(base, without_evidence, [], story_key=self.key)}
        self.assertEqual(kinds, {"evidence_removed"})
        policy = json.loads(json.dumps(base))
        policy["policy_version"] = "numeric-v3"
        self.assertEqual({change["kind"] for change in engine.compare_revisions(base, policy, [], story_key=self.key)},
                         {"other"}, "perubahan kebijakan bukan suntingan teks")

    def test_comparison_categories_come_from_records_and_diffs(self):
        self.touch_article(self.first["source"], " (judul sumber berubah)")
        ronce.register_versioned_stories(self.db, self.run_id)
        pairs = ronce.story_model(self.db)["comparisons"]
        self.assertEqual(len(pairs), 1)
        kinds = {change["kind"] for change in pairs[0]["changes"]}
        self.assertIn("source_updated", kinds)
        self.assertNotIn("claim_corrected", kinds, "judul sumber saja bukan koreksi angka")

    def test_text_only_change_is_not_reported_as_a_correction(self):
        self.touch_article(self.second["source"], " (sunting judul)")
        ronce.register_versioned_stories(self.db, self.run_id)
        pairs = ronce.story_model(self.db)["comparisons"]
        self.assertTrue(pairs, "perubahan judul harus menghasilkan revisi baru")
        kinds = {change["kind"] for change in pairs[0]["changes"]}
        self.assertNotIn("claim_corrected", kinds)
        self.assertIn("source_updated", kinds)

    def test_withdrawal_is_visible_without_rewriting_the_old_revision(self):
        ronce.withdraw_story(self.db, self.key, reason="angka salah kutip", evidence="uji sintetis")
        ronce.register_versioned_stories(self.db, self.run_id)
        # Status changed, so the previous approval no longer covers the new revision: re-approve.
        posts = ronce.render_draft(self.db, self.run_id, "edisi-tarik", "threads", [0])
        ronce.approve_edition(self.db, self.run_id, "edisi-tarik", "threads", "Editor", posts)
        payload = export.build_export(self.db, self.run_id, "edisi-tarik", "threads")
        statuses = payload["model"]["status"]
        self.assertEqual(statuses[0]["status"], "withdrawn")
        revisions = [row for row in payload["model"]["revisions"] if row["story_key"] == self.key]
        self.assertEqual(revisions[0]["payload"]["status_at"], "active",
                         "revisi lama menyimpan status saat itu, bukan status sekarang")
        self.assertTrue(any(change["kind"] == "withdrawal"
                            for pair in ronce.story_model(self.db)["comparisons"]
                            for change in pair["changes"]))
        old = ronce.preview_edition(self.db, self.run_id, "edisi-pagi", "threads", stale_ok=True)
        self.assertEqual(old["posts"], posts, "edisi lama tetap terbaca sebagai catatan sejarah")
        with self.assertRaisesRegex(ValueError, "revisi cerita berubah"):
            ronce.preview_edition(self.db, self.run_id, "edisi-pagi", "threads")

    def test_citation_fields_and_fixture_label_are_exported(self):
        payload = export.build_export(self.db, self.run_id, "edisi-pagi", "threads", dataset="fixture")
        self.assertEqual(payload["coverage"]["dataset"], "fixture")
        claim = payload["claims"][0]
        for field in ("metric", "value", "unit", "scale", "period", "claim_type", "attribution"):
            self.assertIn(field, claim)
        self.assertEqual(claim["claim_type"], "reported_fact")
        manifest = export.export_edition(self.db, self.run_id, "edisi-pagi", "threads",
                                         self.tmp / "fixture-export", dataset="fixture")
        self.assertEqual(manifest["dataset"], "fixture")
        with self.assertRaisesRegex(ValueError, "dataset"):
            export.build_export(self.db, self.run_id, "edisi-pagi", "threads", dataset="produksi")


if __name__ == "__main__":
    unittest.main()
