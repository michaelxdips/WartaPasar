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
    if utf8_bytes > 500:
        return False, f"text exceeds {utf8_bytes} UTF-8 bytes (limit 500)"
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


def classify_response(status, payload, *, headers=None):
    """Peta status HTTP ke status publikasi.

    `created` berarti id diterima; untuk langkah container Threads, id itu
    adalah creation_id (belum terbit), bukan media id final.
    """
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


def submit(transport, request, *, token):
    """Jalankan satu request lewat transport milik pemanggil.

    transport: callable(request, headers) -> (status, payload, headers).
    Modul ini tidak menyediakan transport jaringan; kegagalan transport tidak
    pernah di-retry otomatis dan selalu dipetakan ke `ambiguous`.
    """
    headers = auth_headers(token)
    try:
        status, payload, extra = transport(request, headers)
    except TimeoutError:
        return {"outcome": "ambiguous", "reason": "timeout"}
    except Exception as exc:  # transport rusak/tak terduga tidak boleh mengirim ulang buta
        return {"outcome": "ambiguous", "reason": f"transport error: {type(exc).__name__}"}
    return classify_response(status, payload, headers=extra or {})


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
