import json, os, sys
sys.path.insert(0, os.getcwd())
from adapters import validate_threads_text

# Load fetched articles
with open("draft/news-2026-09-28-direct.json", "r", encoding="utf-8") as f:
    pages = json.load(f)

articles = [a for p in pages for a in p["response"]["results"]]

# Draft posting untuk 3 topik utama hari ini
drafts = []

# 1. GOCAP IDX rule (topik paling hot)
gocap_article = articles[0]
gocap_post = (
    f"📊 BEI turunkan gocap ke Rp1:\n\n"
    f"- Minimum saham turun dari Rp50 ke Rp1 mulai hari ini\n"
    f"- {len(gocap_article['symbols'])} saham anjlok ke level baru termasuk GoTo (GOTO.JK)\n\n"
    f"{gocap_article['source']}"
)
valid, result = validate_threads_text(gocap_post)
drafts.append({
    "platform": "threads",
    "content": result if isinstance(result, str) else gocap_post,
    "topic": "gocap_idx",
    "symbols": gocap_article["symbols"],
    "hash": hash(gocap_post)
})

# 2. Bayan Resources stake acquisition
byan = next((a for a in articles if "BYAN" in a.get("symbols", "")), None)
if byan:
    byan_post = (
        f"💼 Akuisisi 30% saham Bayan Resources:\n\n"
        f"- PT Jhonlin Baratama caplok 10 miliar saham BYAN\n"
        f"- Low Tuck Kwong tetap controlling shareholder\n"
        f"- Transaksi terkait approval RKAB Tambang Tiwa Abadi, Tanur Jaya & Fajar Sakti\n\n"
        f"{byan['source']}"
    )
    valid, result = validate_threads_text(byan_post)
    drafts.append({
        "platform": "threads",
        "content": result if isinstance(result, str) else byan_post,
        "topic": "bayan_stake_transfer",
        "symbols": ["BYAN.JK"],
        "hash": hash(byan_post)
    })

# 3. Kalbe Farma recovery projection
kalbe = next((a for a in articles if "KLBF" in a.get("symbols", "")), None)
if kalbe:
    kalbe_post = (
        f"🏥 Kalbe Farma margin tertekan, proyeksi pulih 2027:\n\n"
        f"- H1-2026 revenue +14% jadi Rp19.48T tapi laba neto turun 2.74%\n"
        f"- Gross profit margin drop 37.56% dari 41.14% karena biaya bahan baku impor\n"
        f"- BRI Danareksa target Rp1,000; Phintraco Rp1,500 per share\n\n"
        f"{kalbe['source']}"
    )
    valid, result = validate_threads_text(kalbe_post)
    drafts.append({
        "platform": "threads",
        "content": result if isinstance(result, str) else kalbe_post,
        "topic": "kalbe_earnings",
        "symbols": ["KLBF.JK"],
        "hash": hash(kalbe_post)
    })

# Write to file directly
with open("draft/posts-draft.json", "w", encoding="utf-8") as f:
    json.dump(drafts, f, ensure_ascii=False, indent=2)

print("DRAFTS_WRITTEN_TO=draft/posts-draft.json")
print("TOTAL_DRAFTS=" + str(len(drafts)))
