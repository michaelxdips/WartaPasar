"""Antarmuka web Ronce — lihat Warta langsung di browser.

Jalankan:
    python app.py
Lalu buka: http://127.0.0.1:8765

Hanya memakai pustaka bawaan Python. Tidak ada dependensi.

Ini alat pratinjau lokal, bukan layanan publik:
- hanya menerima koneksi dari 127.0.0.1
- tidak pernah memposting ke platform mana pun
"""
from __future__ import annotations

import html
import json
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
PORT = 8765


# ------------------------------------------------------------------ data

def daftar_warta() -> list[dict]:
    """Semua Warta yang ada di folder output."""
    hasil = []
    for f in sorted(OUT.glob("warta-*.json"), reverse=True):
        try:
            w = json.loads(f.read_text(encoding="utf-8"))
            hasil.append({
                "file": f.name,
                "tanggal": w.get("tanggal", ""),
                "judul": w.get("judul", ""),
                "ringkasan": w.get("ringkasan", ""),
                "jumlah_post": w.get("jumlah_post", 0),
                "sumber": w.get("sumber", []),
                "data": w,
            })
        except (OSError, json.JSONDecodeError):
            continue
    return hasil


def muat(tanggal: str) -> dict | None:
    f = OUT / f"warta-{tanggal}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ------------------------------------------------------------------ tampilan

CSS = """
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #1c2430;
  --text: #e6edf3; --muted: #8b949e; --border: #30363d;
  --green: #3fb950; --amber: #d29922; --blue: #58a6ff; --red: #f85149;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.6; font-size: 15px;
}
.wrap { max-width: 900px; margin: 0 auto; padding: 24px 20px 60px; }
header {
  border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 28px;
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
}
h1 { font-size: 22px; margin: 0; letter-spacing: -0.3px; }
h1 span { color: var(--green); }
.sub { color: var(--muted); font-size: 13px; }
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px; margin-bottom: 18px;
}
.card h2 { font-size: 17px; margin: 0 0 6px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 12px; }

.badge {
  display: inline-block; padding: 2px 9px; border-radius: 20px;
  font-size: 12px; margin-right: 6px; margin-bottom: 4px;
  background: var(--surface2); color: var(--muted);
  border: 1px solid var(--border);
}
.badge.ok { color: var(--green); border-color: #238636; }
.badge.warn { color: var(--amber); border-color: #9e6a03; }
.badge.no { color: var(--red); border-color: #da3633; }
.badge.info { color: var(--blue); border-color: #1f6feb; }

.ringkasan {
  background: var(--surface2); border-left: 3px solid var(--green);
  padding: 12px 16px; border-radius: 6px; font-size: 14px;
  color: var(--muted); margin: 12px 0 18px;
}

.post {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; margin-bottom: 14px;
}
.post-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 10px; font-size: 12px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.post-body {
  white-space: pre-wrap; font-size: 14.5px; line-height: 1.65;
  word-wrap: break-word;
}
.post-body .bagian { color: var(--green); font-weight: 600; }
.post-body .judul-b { color: var(--text); font-weight: 600; }
.post-body .narasi { color: var(--muted); }

.bar {
  height: 4px; background: var(--surface2); border-radius: 4px;
  margin-top: 10px; overflow: hidden;
}
.bar div { height: 100%; background: var(--green); }
.bar div.warn { background: var(--amber); }
.bar div.no { background: var(--red); }

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 13px; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }

.aksi { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
button, .tombol {
  background: var(--surface2); color: var(--text);
  border: 1px solid var(--border); border-radius: 7px;
  padding: 8px 16px; font-size: 14px; cursor: pointer;
  font-family: inherit;
}
button:hover, .tombol:hover { border-color: var(--green); color: var(--green); }
button:disabled { opacity: .5; cursor: wait; }

.nota {
  background: #1c2128; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; font-size: 13px; color: var(--muted); margin-bottom: 20px;
}
.nota b { color: var(--amber); }
"""


def halaman_daftar() -> str:
    daftar = daftar_warta()
    baris = []
    for w in daftar:
        post = w["data"].get("posts", [])
        lewat = sum(1 for p in post if len(p.encode("utf-8")) > 500)
        badge = (f'<span class="badge ok">{w["jumlah_post"]} post</span>'
                 if not lewat else
                 f'<span class="badge no">{lewat} post lewat batas</span>')
        baris.append(f"""
        <div class="card">
          <h2><a href="/?t={html.escape(w['tanggal'])}">{html.escape(w['judul'])}</a></h2>
          <div class="meta">
            {badge}
            <span class="badge info">{html.escape(', '.join(w['sumber']))}</span>
          </div>
          <div class="ringkasan">{html.escape(w['ringkasan'][:220])}</div>
          <div class="aksi">
            <a class="tombol" href="/?t={html.escape(w['tanggal'])}">Lihat Warta</a>
            <a class="tombol" href="/raw?t={html.escape(w['tanggal'])}">Teks siap posting</a>
            <a class="tombol" href="/json?t={html.escape(w['tanggal'])}">Data JSON</a>
          </div>
        </div>""")

    kosong = '<div class="card"><p>Belum ada Warta. Jalankan <code>python ronce.py make</code> dulu.</p></div>'

    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ronce — Pratinjau</title><style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>Ronce<span>.</span></h1>
  <span class="sub">Pratinjau Warta — lokal, tidak memposting ke mana pun</span>
</header>

<div class="nota">
  <b>Catatan:</b> semua Warta berstatus <code>publishable: false</code>.
  Ronce tidak pernah memposting sendiri — kamu yang memutuskan.
</div>

{''.join(baris) if baris else kosong}
</div></body></html>"""


def halaman_warta(w: dict) -> str:
    posts = w.get("posts", [])
    tanggal = html.escape(w.get("tanggal", ""))

    kartu = []
    for i, p in enumerate(posts, 1):
        ukuran = len(p.encode("utf-8"))
        persen = min(100, ukuran / 500 * 100)
        kelas = "ok" if ukuran <= 500 else ("warn" if ukuran <= 520 else "no")
        label = "OK" if ukuran <= 500 else "LEWAT BATAS"

        # Warnai baris: judul bagian hijau, judul berita putih
        isi = html.escape(p)
        isi = isi.replace("── ", '<span class="bagian">── ')
        isi = isi.replace(" ──", ' ──</span>')

        kartu.append(f"""
        <div class="post">
          <div class="post-head">
            <span>Post {i} dari {len(posts)}</span>
            <span class="badge {kelas}">{ukuran} / 500 byte — {label}</span>
          </div>
          <div class="post-body">{isi}</div>
          <div class="bar"><div class="{kelas}" style="width:{persen:.0f}%"></div></div>
        </div>""")

    # tabel bagian
    bagian = w.get("bagian", {})
    baris_bagian = "".join(
        f'<tr><td>{html.escape(n)}</td><td class="num">{len(e)}</td></tr>'
        for n, e in bagian.items())

    sumber = "".join(f'<span class="badge info">{html.escape(s)}</span>'
                     for s in w.get("sumber", []))

    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(w.get('judul', 'Warta'))}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1><a href="/" style="color:inherit">Ronce<span>.</span></a></h1>
  <span class="sub">{tanggal}</span>
</header>

<div class="card">
  <h2>{html.escape(w.get('judul', ''))}</h2>
  <div class="meta">
    <span class="badge warn">belum boleh dipublikasikan</span>
    <span class="badge">{len(posts)} post</span>
    <span class="badge">{html.escape(w.get('sumber_data', '-'))}</span>
  </div>
  <div class="ringkasan">{html.escape(w.get('ringkasan', ''))}</div>
  <div class="aksi">
    <a class="tombol" href="/">&larr; Semua Warta</a>
    <a class="tombol" href="/raw?t={tanggal}">Teks siap posting</a>
    <a class="tombol" href="/json?t={tanggal}">Data JSON</a>
  </div>
</div>

<h2 style="font-size:16px;color:var(--muted);margin:24px 0 12px">
  Isi Warta — {len(posts)} post
</h2>
{''.join(kartu)}

<div class="card">
  <h2>Bagian yang terisi</h2>
  <table>
    <tr><th>Bagian</th><th style="text-align:right">Entri</th></tr>
    {baris_bagian}
  </table>
  <p style="margin-top:16px"><b>Sumber:</b><br>{sumber or '-'}</p>
  <p class="meta" style="margin-top:12px">
    Jendela data: {html.escape(str(w.get('jendela', ['-','-'])[0]))} →
    {html.escape(str(w.get('jendela', ['-','-'])[1]))}
  </p>
</div>
</div></body></html>"""


def halaman_raw(tanggal: str) -> str:
    f = OUT / f"warta-{tanggal}.txt"
    if not f.exists():
        return "Tidak ada."
    return f.read_text(encoding="utf-8")


def halaman_json(tanggal: str) -> str:
    w = muat(tanggal)
    return json.dumps(w, indent=2, ensure_ascii=False) if w else "{}"


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):        # senyap
        pass

    def kirim(self, isi: str, tipe: str = "text/html; charset=utf-8", kode: int = 200):
        data = isi.encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", tipe)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):                     # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/raw":
            t = q.get("t", [""])[0]
            self.kirim(halaman_raw(t), "text/plain; charset=utf-8")
            return
        if u.path == "/json":
            t = q.get("t", [""])[0]
            self.kirim(halaman_json(t), "application/json; charset=utf-8")
            return

        t = q.get("t", [""])[0]
        if t:
            w = muat(t)
            if w:
                self.kirim(halaman_warta(w))
                return
        self.kirim(halaman_daftar())


def main():
    skor = daftar_warta()
    print("=" * 58)
    print(" RONCE — PRATINJAU LOKAL")
    print("=" * 58)
    print(f"  Warta tersedia : {len(skor)}")
    print(f"  Alamat         : http://127.0.0.1:{PORT}")
    print()
    print("  Buka alamat itu di browser.")
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 58)

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
        srv.shutdown()


if __name__ == "__main__":
    main()
