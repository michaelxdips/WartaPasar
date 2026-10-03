"""Kontrak adapter offline untuk publikasi X dan Threads.

Tidak ada kode jaringan di modul ini: setiap fungsi hanya membangun deskripsi
request atau mengklasifikasi respons yang disediakan pemanggil lewat transport
buatan sendiri. Tidak ada transport nyata, tidak ada panggilan API, dan tidak
ada rahasia di dalam deskripsi request. Publikasi live tetap OFF secara desain
sampai ada persetujuan eksplisit, akun sasaran, kredensial, dan anggaran.

Dokumen resmi diperiksa 2026-09-27:
- X create post: POST https://api.x.com/2/tweets `{"text": ...}`; thread =
  balasan via `reply.in_reply_to_tweet_id`; auth OAuth 1.0a User Context atau
  OAuth 2.0 user context (scope tweet.read, tweet.write, users.read).
  https://docs.x.com/x-api/posts/manage-tweets/integrate.md
- X readback: GET /2/tweets/{id}; parameter field resmi `post.fields` (contoh
  dokumentasi lama memakai `tweet.fields`); auth OAuth2 user (tweet.read,
  users.read), OAuth 1.0a, atau BearerToken.
  https://docs.x.com/x-api/posts/get-post-by-id.md
- X rate limit: POST /2/tweets 10.000/24 jam per app dan 100/15 menit per user;
  DELETE /2/tweets/:id 50/15 menit per user; GET /2/tweets/:id 450/15 menit per
  app dan 900/15 menit per user.
  https://docs.x.com/x-api/fundamentals/rate-limits.md
- X biaya pay-per-usage: Post: Create $0,015; Post: Create (with URL) $0,200;
  Owned Reads $0,001/resource.
  https://docs.x.com/x-api/getting-started/pricing.md
- Threads create container: POST graph/{threads-user-id}/threads
  (media_type=TEXT, text), lalu publish POST .../threads_publish (creation_id);
  dokumentasi menyarankan jeda rata-rata ±30 detik. Contoh di dokumen sebagian
  memakai host graph.threads.net; host di modul ini dapat dikonfigurasi.
  https://developers.facebook.com/documentation/threads/posts
- Threads readback: GET /{threads-media-id}?fields=id,text,username,permalink,
  link_attachment_url,timestamp.
  https://developers.facebook.com/docs/threads/retrieve-and-discover-posts/retrieve-posts
  https://developers.facebook.com/docs/threads/threads-media

Catatan batas: replika balasan berantai (thread) Threads memakai parameter
`reply_to_id` pada container POST .../threads; diverifikasi di dokumen resmi
2026-09-28 (syarat: pemilik thread root atau scope threads_keyword_search/
threads_manage_mentions). Builder `build_threads_reply` menyediakan kontrak
offline balasan; orkestrasi rantai dan uji akun nyata belum ada. Quota
publikasi 250 post/24 jam per profil (carousel
dihitung satu post); cek kuota via GET /{threads-user-id}/threads_publishing_limit.
https://developers.facebook.com/documentation/threads/retrieve-and-manage-replies/create-replies
https://developers.facebook.com/documentation/threads/overview
Label: documented_rules_applied, bukan platform_verified.
"""

LIVE_PUBLISHING = False
THREADS_MAX_BYTES = 500

X_API = "https://api.x.com/2"
X_READBACK_FIELDS = "author_id,created_at,text"
THREADS_GRAPH = "https://graph.threads.com/v1.0"
THREADS_READBACK_FIELDS = "id,text,username,permalink,link_attachment_url,timestamp"

DONE_STATES = ("created", "verified", "mock_verified")
AMBIGUOUS_STATES = ("ambiguous", "timeout", "partial_failure")
RETRY_STATES = ("failed", "auth_expired", "expired_token")
WAIT_STATES = ("rate_limited",)


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} tidak boleh kosong")
    return value


def validate_threads_text(text):
    """Validasi teks Threads: max 500 byte UTF-8, non-kosong.

    Return (valid=True/False, reason_or_id). Valid selalu True kecuali ada alasan rejection.
    Label: documented_rules_applied, bukan platform_verified.
    """
    if not isinstance(text, str):
        return False, "text harus string"
    stripped = text.strip()
    if not stripped:
        return False, "teks kosong"
    utf8_bytes = len(stripped.encode('utf-8'))
    if utf8_bytes == 0:
        return False, "teks kosong"
    if utf8_bytes > THREADS_MAX_BYTES:
        return False, f"text exceeds {utf8_bytes} UTF-8 bytes (limit {THREADS_MAX_BYTES})"
    return True, stripped


def auth_headers(token):
    """Header otorisasi; rahasia tidak pernah masuk ke deskripsi request."""
    return {"Authorization": f"Bearer {_nonempty(token, 'token')}", "Accept": "application/json"}


def build_x_post(text, *, reply_to=None):
    body = {"text": _nonempty(text, "teks")}
    if reply_to is not None:
        body["reply"] = {"in_reply_to_tweet_id": _nonempty(reply_to, "reply_to")}
    return {"platform": "x", "method": "POST", "url": f"{X_API}/tweets",
            "params": None, "json": body}


def build_x_readback(post_id):
    post_id = _nonempty(post_id, "post_id")
    return {"platform": "x", "method": "GET", "url": f"{X_API}/tweets/{post_id}",
            "params": {"post.fields": X_READBACK_FIELDS}, "json": None}


def build_threads_create(text, *, user_id, graph=THREADS_GRAPH):
    """Build Threads container request with UTF-8 validation (500 byte limit)."""
    valid, result = validate_threads_text(text)
    if not valid:
        raise ValueError(result)
    text = result
    body = {"media_type": "TEXT", "text": _nonempty(text, "teks")}
    return {"platform": "threads", "method": "POST",
            "url": f"{graph}/{_nonempty(user_id, 'user_id')}/threads",
            "params": None, "json": body}


def build_threads_reply(text, *, user_id, reply_to_id, graph=THREADS_GRAPH):
    """Kontrak offline balasan berantai Threads: container dengan `reply_to_id`.

    Penerbitan memakai alur threads_publish yang sama; uji pada akun nyata dan
    orkestrasi rantai belum dilakukan.
    https://developers.facebook.com/documentation/threads/retrieve-and-manage-replies/create-replies
    """
    valid, result = validate_threads_text(text)
    if not valid:
        raise ValueError(result)
    body = {"media_type": "TEXT", "text": result,
            "reply_to_id": _nonempty(reply_to_id, "reply_to_id")}
    return {"platform": "threads", "method": "POST",
            "url": f"{graph}/{_nonempty(user_id, 'user_id')}/threads",
            "params": None, "json": body}


def build_threads_publish(creation_id, *, user_id, graph=THREADS_GRAPH):
    body = {"creation_id": _nonempty(creation_id, "creation_id")}
    return {"platform": "threads", "method": "POST",
            "url": f"{graph}/{_nonempty(user_id, 'user_id')}/threads_publish",
            "params": None, "json": body}


def build_threads_readback(media_id, *, graph=THREADS_GRAPH):
    media_id = _nonempty(media_id, "media_id")
    return {"platform": "threads", "method": "GET", "url": f"{graph}/{media_id}",
            "params": {"fields": THREADS_READBACK_FIELDS}, "json": None}


def _http_state(status):
    if status == 429:
        return {"state": "rate_limited", "reason": "HTTP 429"}
    if status == 401:
        return {"state": "auth_expired", "reason": "HTTP 401"}
    if 400 <= status < 500:
        return {"state": "failed", "reason": f"HTTP {status}"}
    return {"state": "ambiguous", "reason": f"HTTP {status}"}


def parse_x_create(status, payload):
    """Envelope resmi X create-post: id post berada di `data.id`."""
    if status in (200, 201):
        data = payload.get("data") if isinstance(payload, dict) else None
        post_id = data.get("id") if isinstance(data, dict) else None
        if isinstance(post_id, str) and post_id:
            return {"state": "created", "external_id": post_id, "envelope": "data.id"}
        return {"state": "ambiguous", "reason": "sukses tanpa data.id"}
    return _http_state(status)


def parse_threads_container(status, payload):
    """Container Threads: id top-level adalah creation_id, belum terbit."""
    if status in (200, 201):
        creation_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(creation_id, str) and creation_id:
            return {"state": "container_created", "external_id": creation_id, "envelope": "id"}
        return {"state": "ambiguous", "reason": "sukses tanpa id container"}
    return _http_state(status)


def parse_threads_publish(status, payload):
    """Publikasi Threads: id top-level adalah media id yang sudah terbit."""
    if status in (200, 201):
        media_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(media_id, str) and media_id:
            return {"state": "published", "external_id": media_id, "envelope": "id"}
        return {"state": "ambiguous", "reason": "sukses tanpa id media"}
    return _http_state(status)


def classify_response(status, payload, *, headers=None, platform=None):
    """Peta status HTTP ke status publikasi.

    `created` berarti id diterima; untuk langkah container Threads, id itu
    adalah creation_id (belum terbit), bukan media id final. Parser platform
    (`parse_x_create`, `parse_threads_container`, `parse_threads_publish`) adalah
    acuan envelope resmi; parameter `platform` memilihnya untuk response tulisan.
    """
    if platform in ("x", "threads", "threads-container", "threads-publish"):
        parsed = {"x": parse_x_create, "threads": parse_threads_publish,
                  "threads-container": parse_threads_container,
                  "threads-publish": parse_threads_publish}[platform](status, payload)
        outcome = {"created": "created", "container_created": "created",
                   "published": "created"}.get(parsed["state"], parsed["state"])
        result = {"outcome": outcome, "state": parsed["state"]}
        if parsed.get("external_id"):
            result["external_id"] = parsed["external_id"]
        if parsed.get("reason"):
            result["reason"] = parsed["reason"]
        if outcome == "rate_limited":
            result["retry_after"] = (headers or {}).get("x-rate-limit-reset")
        return result
    headers = headers or {}
    if status in (200, 201):
        external_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(external_id, str) and external_id:
            return {"outcome": "created", "external_id": external_id}
        return {"outcome": "ambiguous", "reason": "sukses tanpa id"}
    if status == 429:
        return {"outcome": "rate_limited", "retry_after": headers.get("x-rate-limit-reset")}
    if status == 401:
        return {"outcome": "auth_expired", "reason": "HTTP 401"}
    if 400 <= status < 500:
        return {"outcome": "failed", "reason": f"HTTP {status}"}
    return {"outcome": "ambiguous", "reason": f"HTTP {status}"}


class PublicationRefused(ValueError):
    """Tulisan eksternal ditolak sebelum transport dipanggil."""


def publication_preflight(request, approval, *, account, live=None):
    """Batas tulisan eksternal: edisi disetujui, akun eksplisit, dan live=True."""
    live = LIVE_PUBLISHING if live is None else live
    if not isinstance(request, dict) or request.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
        return {"ok": True, "reason": "read_only"}
    if live is not True:
        raise PublicationRefused("publikasi live dimatikan (LIVE_PUBLISHING=False)")
    if not isinstance(account, str) or not account.strip():
        raise PublicationRefused("akun publikasi wajib eksplisit")
    if not isinstance(approval, dict):
        raise PublicationRefused("edisi disetujui wajib ada sebelum menulis")
    if approval.get("platform") != request.get("platform"):
        raise PublicationRefused("platform approval tidak cocok dengan request")
    if str(approval.get("account")) != account:
        raise PublicationRefused("akun approval tidak cocok dengan akun publikasi")
    text = (request.get("json") or {}).get("text")
    posts = approval.get("posts")
    if not isinstance(posts, list) or not any(
            isinstance(item, dict) and item.get("text") == text for item in posts):
        raise PublicationRefused("teks request bukan bagian dari edisi disetujui")
    return {"ok": True, "reason": "approved_edition"}


def submit(transport, request, *, token, approval=None, account=None, live=None):
    """Jalankan satu request lewat transport milik pemanggil setelah batas publikasi lulus.

    Tulisan (POST/PUT/PATCH/DELETE) wajib punya approval edisi disetujui, akun
    eksplisit, dan LIVE_PUBLISHING=True; permintaan baca lolos tanpa itu.
    transport: callable(request, headers) -> (status, payload, headers).
    Modul ini tidak menyediakan transport jaringan; kegagalan transport tidak
    pernah di-retry otomatis dan selalu dipetakan ke `ambiguous`.
    """
    publication_preflight(request, approval, account=account, live=live)
    headers = auth_headers(token)
    write = isinstance(request, dict) and request.get("method") in ("POST", "PUT", "PATCH", "DELETE")
    try:
        status, payload, extra = transport(request, headers)
    except TimeoutError:
        return {"outcome": "ambiguous", "reason": "timeout"}
    except Exception as exc:  # transport rusak/tak terduga tidak boleh mengirim ulang buta
        return {"outcome": "ambiguous", "reason": f"transport error: {type(exc).__name__}"}
    return classify_response(status, payload, headers=extra or {},
                             platform=request.get("platform") if write else None)


def plan_next_action(previous_outcome):
    """Aksi aman berikutnya untuk satu posisi (platform, ordinal)."""
    if previous_outcome in (None, ""):
        return "submit"
    if previous_outcome in DONE_STATES:
        return "already_done"
    if previous_outcome in AMBIGUOUS_STATES:
        return "readback_first"
    if previous_outcome in RETRY_STATES:
        return "retry_after_fix"
    if previous_outcome in WAIT_STATES:
        return "wait_then_retry"
    return "readback_first"


def verify_readback(platform, payload, *, expected_account, expected_text, expected_link=None):
    """Cocokkan hasil baca balik dengan yang diharapkan (False, alasan) bila beda."""
    if platform == "x":
        data = (payload or {}).get("data") or {}
        got_text = data.get("text")
        got_account = data.get("author_id")
    elif platform == "threads":
        data = payload or {}
        got_text = data.get("text")
        got_account = data.get("username")
    else:
        raise ValueError("platform tidak dikenal")
    if got_text != expected_text:
        return False, "teks tidak cocok"
    if str(got_account) != str(expected_account):
        return False, "akun tidak cocok"
    if expected_link is not None and data.get("link_attachment_url") != expected_link:
        return False, "tautan tidak cocok"
    return True, "cocok"
