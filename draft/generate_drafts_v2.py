import json, os, sys
sys.path.insert(0, os.getcwd())
from adapters import validate_threads_text

# Load fetched articles
with open("draft/news-2026-09-28-direct.json", "r", encoding="utf-8") as f:
    pages = json.load(f)

articles = [a for p in pages for a in p["response"]["results"]]
print(f"Loaded {len(articles)} articles")

# Debug: print symbols of each article
for i, a in enumerate(articles[:3]):
    print(f"{i}: {a.get('symbols', [])}")

# Draft posting untuk TOPIC HARI INI
drafts = []

# 1. GOCAP IDX rule (topik paling hot - artikel #0 and #4)
gocap_articles = [a for a in articles if "minimum" in a.get("title", "").lower() or "gocap" in a.get("title", "").lower()]
if gocap_articles:
    gocap_article = gocap_articles[0]
    gocap_post = (
        f"📊 BEI turunkan gocap ke Rp1\n\n"
        f"- Minimum saham turun dari Rp50 ke Rp1 mulai 28/9/2026\n"
        f"- {len(gocap_article['symbols'])} saham anjlok ke level baru termasuk GoTo (GOTO.JK)\n\n"
        f"Source: {gocap_article['source']}"
    )
    valid, result = validate_threads_text(gocap_post)
    drafts.append({
        "platform": "threads",
        "content": result if isinstance(result, str) else gocap_post,
        "topic": "gocap_idx",
        "symbols": list(set([sym.replace(".jk", ".JK").replace(".Jk", ".JK") for sym in gocap_article.get("symbols", [])])),
        "hash": hash(gocap_post),
        "source_title": gocap_article.get("title")
    })

# 2. Bayan Resources stake acquisition
byan_articles = [a for a in articles if "bayan" in a.get("title", "").lower()]
if byan_articles:
    byan = byan_articles[0]
    byan_post = (
        f"💼 Akuisisi 30% saham Bayan Resources (BYAN)\n\n"
        f"- PT Jhonlin Baratama caplok 10 miliar saham (~30%) dari Low Tuck Kwong\n"
        f"- Low Tuck tetap controlling shareholder setelah transaksi\n"
        f"- RKAB Tambang Tiwa Abadi, Tanur Jaya & Fajar Sakti sudah approved 23/9\n\n"
        f"Source: {byan['source']}"
    )
    valid, result = validate_threads_text(byan_post)
    drafts.append({
        "platform": "threads",
        "content": result if isinstance(result, str) else byan_post,
        "topic": "bayan_stake_transfer",
        "symbols": ["BYAN.JK"],
        "hash": hash(byan_post),
        "source_title": byan.get("title")
    })

# 3. Kalbe Farma recovery projection
kalbe_articles = [a for a in articles if "kalbe" in a.get("title", "").lower() or "klbf" in a.get("title", "").lower()]
if kalbe_articles:
    kalbe = kalbe_articles[0]
    kalbe_post = (
        f"🏥 Kalbe Farma (KLBF): margin tertekan, proyeksi pulih 2027\n\n"
        f"- H1-2026 revenue +14.05% jadi Rp19.48T\n"
        f"- Laba neto turun 2.74% jadi Rp1.97T; gross margin drop ke 37.56%\n"
        f"- BRI Danareksa target Rp1,000 | Phintraco Rp1,500 | Sinarmas Rp900\n\n"
        f"Source: {kalbe['source']}"
    )
    valid, result = validate_threads_text(kalbe_post)
    drafts.append({
        "platform": "threads",
        "content": result if isinstance(result, str) else kalbe_post,
        "topic": "kalbe_earnings_recovery",
        "symbols": ["KLBF.JK"],
        "hash": hash(kalbe_post),
        "source_title": kalbe.get("title")
    })

# Write to file directly
with open("draft/posts-draft-v2.json", "w", encoding="utf-8") as f:
    json.dump(drafts, f, ensure_ascii=False, indent=2)

print("\nDRAFTS_WRITTEN_TO=draft/posts-draft-v2.json")
print(f"TOTAL_DRAFTS={len(drafts)}")
for i, d in enumerate(drafts, 1):
    print(f"Draft {i}: {d['topic']} ({len(d.get('symbols', []))} symbols)")
