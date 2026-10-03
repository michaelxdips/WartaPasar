"""Build the visibly synthetic workbench demo store and print how to start the runtime.

Everything here is fake ("uji sintetis" titles). The script creates two runs over one story so
the browser journey can show: inspection -> mapping -> origin review -> hold/review -> approve ->
export -> a revision arriving -> the stale approval being refused -> the new revision reviewed.
It never touches real archives and never enables publishing.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ronce  # noqa: E402

RULES = {"source_timezone": "+07:00", "timestamp_meaning": "source_publication",
         "filter_timezone": "+07:00", "start_inclusive": True, "end_inclusive": True,
         "evidence": "fixture sintetis; bukan konfirmasi penyedia"}

ROWS_A = [("BBCA uji sintetis umumkan dividen tunai 100 juta rupiah", "https://kanal-a.test/uji/a1"),
          ("Dividen tunai uji sintetis BBCA diumumkan 100 juta rupiah", "https://kanal-b.test/uji/a2")]
ROWS_B = [("BBCA uji sintetis umumkan dividen tunai 120 juta rupiah", "https://kanal-a.test/uji/b1"),
          ("Dividen tunai uji sintetis BBCA diumumkan 120 juta rupiah", "https://kanal-b.test/uji/b2"),
          ("Koreksi uji sintetis: dividen tunai BBCA 120 juta rupiah diumumkan ulang", "https://kanal-c.test/uji/b3")]


def article(title, url):
    return {"title": title, "body": title, "source": url, "timestamp": "2026-09-25T09:00:00",
            "symbols": ["BBCA"], "tags": ["uji-sintetis"], "sector": "financials"}


def page(rows, fetched_at):
    return {"fetched_at": fetched_at,
            "response": {"results": rows,
                         "pagination": {"offset": 0, "showing": len(rows), "total_count": len(rows),
                                        "has_next": False, "next_offset": None}}}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "advance":
        # Second run: revises the story while the old approval stays bound to the old revision.
        # Deliberately leaves the review to the browser journey, so the editor performs it live.
        if len(sys.argv) < 3:
            raise SystemExit("pakai: build_workbench_demo.py advance <db>")
        db = Path(sys.argv[2])
        run_b = ronce.replay([page([article(*row) for row in ROWS_B], "2026-09-25T12:00:00+07:00")],
                             "2026-09-25T13:00:00+07:00", db, since="2026-09-22T00:00:00+07:00",
                             interpretation=dict(RULES))
        ronce.migrate(db)
        ronce.register_versioned_stories(db, run_b["run_id"])
        print(json.dumps({"run_b": run_b["run_id"],
                          "story_key": ronce.story_identity(symbol="BBCA", topic="dividen",
                                                            action="pengumuman", date="2026-09-25")},
                         ensure_ascii=False))
        return
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ronce-wb-demo-"))
    target.mkdir(parents=True, exist_ok=True)
    db = target / "demo.sqlite"
    if db.exists():
        db.unlink()
    run_a = ronce.replay([page([article(*row) for row in ROWS_A], "2026-09-25T10:00:00+07:00")],
                         "2026-09-25T11:00:00+07:00", db, since="2026-09-22T00:00:00+07:00",
                         interpretation=dict(RULES))
    print(json.dumps({"demo_db": str(db), "demo_export_dir": str(target / "export"),
                      "run_a": run_a["run_id"],
                      "story_key": ronce.story_identity(symbol="BBCA", topic="dividen",
                                                        action="pengumuman", date="2026-09-25"),
                      "advance": f"python scripts/build_workbench_demo.py advance {db}"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
