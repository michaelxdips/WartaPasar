"""Web edition contract (schema v1).

Deterministic, public, non-sensitive export of one approved edition. Reader-facing
fields only: article bodies are never exported, credentials never appear, and the
approval record travels with the content so the reader surface can show what was
approved, by whom and when. Stable IDs are content addressed, so a rebuild of the
same edition produces the same identifiers.
"""
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import companion
import ronce

SCHEMA_VERSION = 2
SCHEMA_VERSION_COMPANION = 3
CONTENT_FILES = ("edition.json", "stories.json", "claims.json", "model.json")


def stable_id(*parts):
    """Content-addressed identifier, stable across runs and rebuilds."""
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def story_id(key):
    """One logical story, one id: symbol, topic, action and date — not the run it appeared in."""
    return ronce.story_identity(symbol=key["symbol"], topic=key["topic"],
                                action=key["action"], date=key["date"])


def build_export(db, run_id, edition_id, platform, *, dataset="archive", companion_db=None):
    """Pure payload for one approved edition; fails closed when the edition is not approved.

    `companion_db` adds the normalized market-context section (schema v3). Companion values are
    attributed context, never reviewed claims, and they never inherit editorial approval.
    """
    if dataset not in ("archive", "fixture"):
        raise ValueError("dataset harus arsip atau fixture")
    preview = ronce.preview_edition(db, run_id, edition_id, platform)
    with closing(ronce._connect(db)) as con:
        run_row = con.execute("SELECT decision_json FROM runs WHERE id=?", (run_id,)).fetchone()
        if run_row is None:
            raise ValueError("run tidak dikenal")
        context = con.execute("SELECT since, interpretation_json FROM run_context WHERE run_id=?",
                              (run_id,)).fetchone()
        review = ronce._read_review(con, run_id)
        archives = [json.loads(payload) for _, payload in
                    con.execute("SELECT source, payload FROM articles WHERE run_id=?", (run_id,))]
    decisions = json.loads(run_row[0])
    if not isinstance(decisions, list):
        raise ValueError("decision_json bukan daftar kandidat")
    model = ronce.story_model(db)
    revision_by_story = {}
    for revision in model["revisions"]:
        revision_by_story.setdefault(revision["story_key"], revision)
    index = {item["source"]: item for item in archives}
    stories = []
    for candidate in decisions:
        key = story_id(candidate)
        revision = revision_by_story.get(key)
        status = model["status"].get(key)
        stories.append({
            "id": key, "symbol": candidate["symbol"], "topic": candidate["topic"],
            "action": candidate["action"], "date": candidate["date"],
            "decision": candidate["decision"], "reason": candidate.get("reason"),
            "revision": None if revision is None else {"revision_id": revision["revision_id"],
                                                       "content_hash": revision["content_hash"],
                                                       "created_at": revision["created_at"]},
            "status": status["status"] if status else "active",
            "relations": sorted(relation["relation_id"] for relation in model["relations"]
                                if key in (relation["from_story"], relation["to_story"])),
            "counts": {"articles": candidate.get("article_count"),
                       "publishers": candidate.get("publisher_count"),
                       "sources": candidate.get("source_count")},
            "score": candidate.get("score", 0), "score_detail": candidate.get("score_detail", []),
            "sources": sorted(({"url": url, "title": index[url].get("title"),
                                "timestamp": index[url].get("timestamp"),
                                "symbols": index[url].get("symbols"), "tags": index[url].get("tags")}
                               for url in candidate["sources"] if url in index),
                              key=lambda row: row["url"])})
    claims = []
    for claim in review["claims"]:
        key = claim.get("story_key")
        linked = story_id(key) if key else None
        claims.append({
            "id": stable_id(linked, claim["text"]), "story_id": linked, "text": claim["text"],
            "entity": claim["entity"], "action": claim["action"], "event_time": claim["event_time"],
            "value": claim.get("value"), "unit": claim.get("unit"), "scale": claim.get("scale"),
            "metric": claim.get("metric"), "period": claim.get("period"),
            "claim_type": claim.get("claim_type"), "attribution": claim.get("attribution"),
            "source_counts": claim.get("source_counts"),
            "evidence": [{"url": item["source"], "quote": item["quote"], "origin": item["origin"],
                          "origin_basis": item.get("origin_basis", "unknown")}
                         for item in claim["evidence"]]})
    by_index = {position: claim for position, claim in enumerate(claims)}
    posts = []
    for ordinal, (text, claim_index) in enumerate(zip(preview["posts"], preview["indexes"]), start=1):
        posts.append({"ordinal": ordinal, "text": text,
                      "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                      "claim_id": by_index.get(claim_index, {}).get("id")})
    payload = {
        "schema_version": SCHEMA_VERSION_COMPANION if companion_db else SCHEMA_VERSION,
        "companion": companion.companion_state(companion_db) if companion_db else None,
        "edition": {"uid": stable_id(run_id, edition_id, platform), "run_id": run_id,
                    "edition_id": edition_id, "platform": platform, "hash": preview["hash"],
                    "approval": preview["approval"], "posts": posts},
        "stories": stories,
        "claims": claims,
        "model": {"topics": model["topics"],
                  "identities": [{"story_key": row["story_key"], "symbol": row["symbol"],
                                  "topic_id": row["topic_id"], "action": row["action"], "date": row["date"]}
                                 for row in model["identities"]],
                  "revisions": model["revisions"],
                  "relations": model["relations"],
                  "comparisons": model["comparisons"],
                  "status": [{"story_key": key, **value} for key, value in sorted(model["status"].items())]},
        "coverage": {"articles": len(archives), "eligible": len(archives),
                     "candidates": len(stories),
                     "reviewable": sum(1 for story in stories if story["decision"] == "review"),
                     "since": context[0] if context else None,
                     "policy_version": ronce.POLICY_VERSION,
                     "dataset": dataset,
                     "interpretation": json.loads(context[1]) if context else None,
                     "policy": {"public_fields_only": True, "bodies_exported": False,
                                "live_publishing": False}},
    }
    if payload["companion"] is not None:
        payload["companion"]["applies_to"] = "dataset=" + dataset
        payload["companion"]["note"] = ("nilai companion adalah konteks pasar teratribusi, bukan klaim "
                                        "yang ditinjau editor, dan tidak mewarisi persetujuan")
    return payload


def export_edition(db, run_id, edition_id, platform, target, *, dataset="archive", companion_db=None):
    """Write the public export atomically: staging directory, then one rename.

    Refuses an existing target and any edition that is not approved (the build
    raises before the filesystem is touched). Content files are canonical, so two
    rebuilds of the same edition are byte-identical; only the manifest carries
    `generated_at`.
    """
    payload = build_export(db, run_id, edition_id, platform, dataset=dataset, companion_db=companion_db)
    schema_version = SCHEMA_VERSION_COMPANION if companion_db else SCHEMA_VERSION
    target = Path(target)
    if target.exists():
        raise FileExistsError(f"ekspor sudah ada: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(target.parent)))
    try:
        files = {"edition.json": {"schema_version": schema_version, "edition": payload["edition"]},
                 "stories.json": {"schema_version": schema_version, "stories": payload["stories"],
                                  "coverage": payload["coverage"]},
                 "claims.json": {"schema_version": schema_version, "claims": payload["claims"]},
                 "model.json": {"schema_version": schema_version, "model": payload["model"]}}
        if payload["companion"] is not None:
            files["companion.json"] = {"schema_version": schema_version, "companion": payload["companion"]}
        written = {}
        for name, body in files.items():
            text = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            (staging / name).write_text(text, encoding="utf-8", newline="")
            written[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest = {"schema_version": schema_version,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "edition_uid": payload["edition"]["uid"], "run_id": run_id,
                    "edition_id": edition_id, "platform": platform, "files": written,
                    "counts": {"stories": len(payload["stories"]), "claims": len(payload["claims"]),
                               "posts": len(payload["edition"]["posts"]),
                               "topics": len(payload["model"]["topics"]),
                               "relations": len(payload["model"]["relations"]),
                               "revisions": len(payload["model"]["revisions"]),
                               "companion_records": len((payload["companion"] or {}).get("records", [])),
                               "companion_families": len((payload["companion"] or {}).get("status", []))},
                    "policy": {"reader_surface": "approved editions only", "bodies_exported": False,
                               "live_publishing": False},
                    "dataset": dataset}
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="")
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest
