"""CONTOH SAJA -- bukan jalur produksi dan tidak dapat dipublikasikan.

Skrip ini menyusun contoh post dari arsip mentah. Outputnya selalu
`"publishable": false` tanpa blok `review`, memakai hash kanonik (SHA256) dan
menolak menulis apa pun bila validasi platform gagal. Untuk publikasi, gunakan
alur ronce.review_claims -> ronce.render_draft -> ronce.approve_edition.

Jalankan: python draft/generate_drafts.py --sample
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
DEFAULT_OUT = ROOT / "draft/samples/posts-sample.json"


def post(text, *, topic, symbols, claim_type="reported_fact", attribution=None, source_title=None):
    valid, result = adapters.validate_threads_text(text)
    if not valid:
        raise SystemExit(f"post '{topic}' ditolak validasi platform: {result}")
    entry = {"platform": "threads", "content": result, "topic": topic, "symbols": symbols,
             "claim_type": claim_type, "attribution": attribution,
             "text_hash": ronce.artifact_hash(result), "source_title": source_title}
    return entry


def build(articles):
    drafts = []
    gocap_article = articles[0]
    drafts.append(post(
        f"📊 BEI turunkan gocap ke Rp1:\n\n"
        f"- Minimum saham turun dari Rp50 ke Rp1 mulai hari ini\n"
        f"- {len(gocap_article['symbols'])} saham anjlok ke level baru termasuk GoTo (GOTO.JK)\n\n"
        f"{gocap_article['source']}",
        topic="gocap_idx", symbols=gocap_article["symbols"],
        source_title=gocap_article.get("title")))
    byan = next((a for a in articles if "bayan" in a.get("title", "").lower()), None)
    if byan:
        drafts.append(post(
            f"💼 Akuisisi 30% saham Bayan Resources:\n\n"
            f"- PT Jhonlin Baratama caplok 10 miliar saham BYAN\n"
            f"- Low Tuck Kwong tetap controlling shareholder\n"
            f"- Transaksi terkait approval RKAB Tambang Tiwa Abadi, Tanur Jaya & Fajar Sakti\n\n"
            f"{byan['source']}",
            topic="bayan_stake_transfer", symbols=["BYAN.JK"], source_title=byan.get("title")))
    kalbe = next((a for a in articles if "kalbe" in a.get("title", "").lower()
                  or "klbf" in a.get("title", "").lower()), None)
    if kalbe:
        drafts.append(post(
            f"🏥 Kalbe Farma margin tertekan, proyeksi pulih 2027:\n\n"
            f"- H1-2026 revenue +14% jadi Rp19.48T tapi laba neto turun 2.74%\n"
            f"- Gross profit margin drop 37.56% dari 41.14% karena biaya bahan baku impor\n"
            f"- BRI Danareksa target Rp1,000; Phintraco Rp1,500 per share\n\n"
            f"{kalbe['source']}",
            topic="kalbe_earnings", symbols=["KLBF.JK"], claim_type="analyst_opinion",
            attribution="BRI Danareksa Sekuritas; Phintraco Sekuritas",
            source_title=kalbe.get("title")))
    return drafts


def main():
    parser = argparse.ArgumentParser(description="Contoh penyusunan post (tidak dapat dipublikasikan)")
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
                "generator": "draft/generate_drafts.py", "sample_only": True,
                "input_archive": args.archive.name,
                "input_sha256": ronce.artifact_hash(pages),
                "posts": drafts}
    ronce.save_archive(args.out, artifact)
    print(json.dumps({"out": str(args.out), "posts": len(drafts), "publishable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
