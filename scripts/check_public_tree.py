"""Check that the tracked tree matches the declared public allowlist.

Tracked files must be allowlisted here (mirroring .gitignore), fall under an
allowed prefix, or be a documented exception with a reason. Anything else is
drift and fails the check. Files that are allowlisted but not yet tracked are
printed as `missing` (pre-commit state, not a failure).

Jalankan: python scripts/check_public_tree.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ALLOWLIST = (".gitignore", "README.md", "ronce.py", "adapters.py", "companion.py", "export.py",
             "outbox.py", "workbench.py", "workbench_page.html", "test_ronce.py",
             "test_adapters.py", "test_companion.py", "test_export.py", "test_outbox.py",
             "test_workbench.py", "package.json", "package-lock.json", "x_length.mjs")
ALLOW_PREFIXES = ("scripts/", "web/")
EXCEPTIONS = {
    "draft/generate_drafts.py": "legacy sample script tracked before the allowlist policy; owner decision Q1 pending",
    "draft/generate_drafts_v2.py": "legacy sample script tracked before the allowlist policy; owner decision Q1 pending",
    "draft/news-2026-09-28-direct.json": "provider capture tracked before the policy; owner decision Q1 pending",
    "draft/posts-draft.json": "generated sample tracked before the policy; owner decision Q1 pending",
    "draft/posts-draft-v2.json": "generated sample tracked before the policy; owner decision Q1 pending",
}
FORBIDDEN = re.compile(r"(^|/)\.env|(^|/)\.mcp\.json$|\.pem$|\.key$|\.p12$|(^|/)id_rsa[^/]*$", re.I)


def check(tracked):
    """Pure check: returns the drift/forbidden/missing report for a tracked list."""
    forbidden = [path for path in tracked if FORBIDDEN.search(path)]
    drift = [path for path in tracked
             if path not in ALLOWLIST and not path.startswith(ALLOW_PREFIXES) and path not in EXCEPTIONS
             and path not in forbidden]
    missing = [path for path in ALLOWLIST if path not in tracked]
    return {"ok": not drift and not forbidden, "drift": sorted(drift),
            "forbidden": sorted(forbidden), "missing": sorted(missing),
            "exceptions": sorted(EXCEPTIONS)}


def main():
    repo = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, check=True).stdout.split()
    report = check(tracked)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
