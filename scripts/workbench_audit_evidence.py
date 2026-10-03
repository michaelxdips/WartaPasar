"""Produce the audit-trail evidence file with synthetic principals (no real identities).

Runs the workbench against a temporary synthetic store over real HTTP, performs a login, an
origin review, a hold, a stale-revision conflict and a refused login, then dumps the audit rows.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
import http.cookiejar  # noqa: E402

import subprocess  # noqa: E402

import workbench  # noqa: E402


def call(opener, base, path, method="GET", body=None, csrf=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if csrf:
        request.add_header("X-Ronce-CSRF", csrf)
    try:
        with opener.open(request) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ronce-audit-evidence-"))
    built = subprocess.run([sys.executable, "scripts/build_workbench_demo.py", str(tmp)],
                           capture_output=True, text=True, cwd=ROOT)
    demo = json.loads(built.stdout.strip().split("\n")[-1])
    operator = "Editor Contoh (sintetis)"
    secret = "rahasia-contoh-sintetis"
    server, _ = workbench.serve(db=Path(demo["demo_db"]), operator=operator,
                                secret_hash=workbench.hash_secret(secret),
                                export_dir=tmp / "export", port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    lines = [f"operator: {operator}", f"secret: [REDACTED] ({len(secret)} karakter, tidak dicetak)"]
    try:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        # 1. Refused login (wrong secret).
        status, _ = call(opener, base, "/api/login", "POST", {"secret": "salah"})
        lines.append(f"1. login salah -> {status} (ditolak, tercatat)")
        # 2. Successful login.
        status, payload = call(opener, base, "/api/login", "POST", {"secret": secret})
        csrf = payload["csrf"]
        lines.append(f"2. login benar -> {status}")
        # 3. Origin review on the candidate's first source.
        status, candidates = call(opener, base, "/api/candidates?run=" + demo["run_a"])
        source = candidates["candidates"][0]["sources"][0]
        status, _ = call(opener, base, "/api/origin-review", "POST",
                         {"run_id": demo["run_a"], "source": source, "entity": "BBCA",
                          "rationale": "contoh sintetis: sumber uji berdiri sendiri",
                          "expected_revisions": {demo["story_key"]: None}}, csrf)
        lines.append(f"3. keputusan asal -> {status}")
        # 4. Hold on the (still unregistered) revision None.
        status, _ = call(opener, base, "/api/decision", "POST",
                         {"action": "hold", "story_key": demo["story_key"],
                          "note": "menunggu konfirmasi tambahan",
                          "expected_revisions": {demo["story_key"]: None}}, csrf)
        lines.append(f"4. tahan -> {status}")
        # 5. Stale revision conflict (wrong revision id).
        status, conflict = call(opener, base, "/api/decision", "POST",
                                {"action": "hold", "story_key": demo["story_key"],
                                 "note": "dari tampilan lama",
                                 "expected_revisions": {demo["story_key"]: "revisi-palsu"}}, csrf)
        lines.append(f"5. revisi usang -> {status} ({conflict.get('error', '')})")
        # 6. Dump the audit trail.
        status, audit = call(opener, base, "/api/audit")
        lines.append("")
        lines.append("audit (terbaru dulu):")
        for row in audit["audit"]:
            lines.append("  {at} | {principal} | {action} | {target} | expected={expected_revision} | {result}"
                         .format(**{key: (value if value is not None else "-") for key, value in row.items()}))
    finally:
        server.shutdown()
        server.server_close()
    output = "\n".join(lines) + "\n"
    target = ROOT / ".internal/phase7/evidence_workbench_audit.txt"
    target.write_text(output, encoding="utf-8")
    print(output)
    print("written:", target)


if __name__ == "__main__":
    main()
