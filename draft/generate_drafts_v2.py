"""CONTOH SAJA (v2) -- bukan jalur produksi dan tidak dapat dipublikasikan.

Versi ini mencari artikel berdasarkan kata kunci judul sebelum menyusun contoh
post. Output selalu `"publishable": false` tanpa blok `review`, memakai hash
kanonik (SHA256), dan menolak menulis apa pun bila validasi platform gagal.
Untuk publikasi, gunakan ronce.review_claims -> ronce.render_draft -> ronce.approve_edition.

Jalankan: python draft/generate_drafts_v2.py --sample
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import adapters  # noqa: E402
import ronce  # noqa: E402

ARCHIVE = ROOT / "draft/news-2026-09-28-direct.json"
DEFAULT_OUT = ROOT / "draft/samples/posts-sample-v2.json"


def post(text, *, topic, symbols, claim_type="reported_fact", attribution=None, source_title=None):
    valid, result = adapters.validate_threads_text(text)
    if not valid:
        raise SystemExit(f"post '{topic}' ditolak validasi platform: {result}")
    return {"platform": "threads", "content": result, "topic": topic, "symbols": symbols,
            "claim_type": claim_type, "attribution": attribution,
            "text_hash": ronce.artifact_hash(result), "source_title": source_title}


def build(articles):
    drafts = []
    gocap_articles = [a for a in articles
                      if "minimum" in a.get("title", "").lower() or "gocap" in a.get("title", "").lower()]
    if gocap_articles:
        gocap_article = gocap_articles[0]
        drafts.append(post(
            f"📊 BEI turunkan gocap ke Rp1\n\n"
            f"- Minimum saham turun dari Rp50 ke Rp1 mulai 28/9/2026\n"
            f"- {len(gocap_article['symbols'])} saham anjlok ke level baru termasuk GoTo (GOTO.JK)\n\n"
            f"Source: {gocap_article['source']}",
            topic="gocap_idx",
            symbols=list({sym.replace(".jk", ".JK").replace(".Jk", ".JK") for sym in gocap_article.get("symbols", [])}),
            source_title=gocap_article.get("title")))
    byan_articles = [a for a in articles if "bayan" in a.get("title", "").lower()]
    if byan_articles:
        byan = byan_articles[0]
        drafts.append(post(
            f"💼 Akuisisi 30% saham Bayan Resources (BYAN)\n\n"
            f"- PT Jhonlin Baratama caplok 10 miliar saham (~30%) dari Low Tuck Kwong\n"
            f"- Low Tuck tetap controlling shareholder setelah transaksi\n"
            f"- RKAB Tambang Tiwa Abadi, Tanur Jaya & Fajar Sakti sudah approved 23/9\n\n"
            f"Source: {byan['source']}",
            topic="bayan_stake_transfer", symbols=["BYAN.JK"], source_title=byan.get("title")))
    kalbe_articles = [a for a in articles
                      if "kalbe" in a.get("title", "").lower() or "klbf" in a.get("title", "").lower()]
    if kalbe_articles:
        kalbe = kalbe_articles[0]
        drafts.append(post(
            f"🏥 Kalbe Farma (KLBF): margin tertekan, proyeksi pulih 2027\n\n"
            f"- H1-2026 revenue +14.05% jadi Rp19.48T\n"
            f"- Laba neto turun 2.74% jadi Rp1.97T; gross margin drop ke 37.56%\n"
            f"- BRI Danareksa target Rp1,000 | Phintraco Rp1,500 | Sinarmas Rp900\n\n"
            f"Source: {kalbe['source']}",
            topic="kalbe_earnings_recovery", symbols=["KLBF.JK"], claim_type="analyst_opinion",
            attribution="BRI Danareksa Sekuritas; Phintraco Sekuritas; Sinarmas Sekuritas",
            source_title=kalbe.get("title")))
    return drafts


def main():
    parser = argparse.ArgumentParser(description="Contoh penyusunan post v2 (tidak dapat dipublikasikan)")
    parser.add_argument("--sample", action="store_true", required=True,
                        help="konfirmasi bahwa output adalah contoh, bukan bahan publikasi")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    pages = json.loads(args.archive.read_text(encoding="utf-8"))
    articles = [a for page in pages for a in page["response"]["results"]]
    drafts = build(articles)
    artifact = {"publishable": False, "review": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generator": "draft/generate_drafts_v2.py", "sample_only": True,
                "input_archive": args.archive.name,
                "input_sha256": ronce.artifact_hash(pages),
                "posts": drafts}
    ronce.save_archive(args.out, artifact)
    print(json.dumps({"out": str(args.out), "posts": len(drafts), "publishable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
