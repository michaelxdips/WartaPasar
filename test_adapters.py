import json
import unittest
from pathlib import Path
from unittest.mock import patch

import adapters


class RequestBuilderTests(unittest.TestCase):
    def test_x_post_shape(self):
        request = adapters.build_x_post("Halo pasar")
        self.assertEqual(request["platform"], "x")
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://api.x.com/2/tweets")
        self.assertEqual(request["json"], {"text": "Halo pasar"})

    def test_x_post_reply_shape(self):
        request = adapters.build_x_post("Lanjutan", reply_to="123")
        self.assertEqual(request["json"]["reply"]["in_reply_to_tweet_id"], "123")

    def test_x_post_validation(self):
        with self.assertRaisesRegex(ValueError, "teks"):
            adapters.build_x_post("   ")
        with self.assertRaisesRegex(ValueError, "reply_to"):
            adapters.build_x_post("Halo", reply_to="")

    def test_x_readback_uses_post_fields(self):
        request = adapters.build_x_readback("999")
        self.assertEqual(request["method"], "GET")
        self.assertTrue(request["url"].endswith("/2/tweets/999"))
        self.assertEqual(request["params"]["post.fields"], "author_id,created_at,text")

    def test_threads_create_shape(self):
        request = adapters.build_threads_create("Halo threads", user_id="u1")
        self.assertEqual(request["url"], "https://graph.threads.com/v1.0/u1/threads")
        self.assertEqual(request["json"], {"media_type": "TEXT", "text": "Halo threads"})

    def test_threads_publish_shape(self):
        request = adapters.build_threads_publish("creation-1", user_id="u1")
        self.assertTrue(request["url"].endswith("/u1/threads_publish"))
        self.assertEqual(request["json"], {"creation_id": "creation-1"})

    def test_threads_readback_shape(self):
        request = adapters.build_threads_readback("media-1")
        self.assertTrue(request["url"].endswith("/media-1"))
        for field in ("text", "username", "permalink", "link_attachment_url"):
            self.assertIn(field, request["params"]["fields"])

    def test_threads_create_requires_user_id(self):
        with self.assertRaisesRegex(ValueError, "user_id"):
            adapters.build_threads_create("Halo", user_id="")

    def test_graph_host_is_configurable(self):
        request = adapters.build_threads_readback("media-1", graph="https://graph.threads.net/v1.0")
        self.assertTrue(request["url"].startswith("https://graph.threads.net/v1.0/"))

    def test_request_description_has_no_secret(self):
        request = adapters.build_x_post("Halo")
        dumped = json.dumps(request)
        self.assertNotIn("Bearer", dumped)
        self.assertNotIn("token", dumped.lower())

    def test_auth_headers_rejects_empty_token(self):
        with self.assertRaisesRegex(ValueError, "token"):
            adapters.auth_headers("  ")
        self.assertEqual(adapters.auth_headers("tok")["Authorization"], "Bearer tok")


class ValidateThreadsTextTests(unittest.TestCase):
    """Unit tests untuk validasi UTF-8 Threads (500 byte limit)."""

    def test_valid_short_text_returns_text(self):
        valid, result = adapters.validate_threads_text("Halo pasar")
        self.assertTrue(valid)
        self.assertEqual(result, "Halo pasar")

    def test_valid_exactly_500_bytes(self):
        text = "a" * 500  # ASCII 'a' = 1 byte per char
        valid, result = adapters.validate_threads_text(text)
        self.assertTrue(valid)
        self.assertEqual(result, text)

    def test_invalid_empty_string(self):
        valid, reason = adapters.validate_threads_text("")
        self.assertFalse(valid)
        self.assertEqual(reason, "teks kosong")

    def test_invalid_whitespace_only(self):
        valid, reason = adapters.validate_threads_text("   ")
        self.assertFalse(valid)
        self.assertEqual(reason, "teks kosong")

    def test_invalid_non_string(self):
        valid, reason = adapters.validate_threads_text(12345)
        self.assertFalse(valid)
        self.assertEqual(reason, "text harus string")

    def test_invalid_501_bytes_fails(self):
        text = "a" * 501
        valid, reason = adapters.validate_threads_text(text)
        self.assertFalse(valid)
        self.assertTrue("exceeds" in reason and "UTF-8 bytes" in reason)

    def test_utf8_multiple_byte_characters_counted_correctly(self):
        # Emoji dan karakter non-ASCII menggunakan >1 byte UTF-8
        # 😊 = 4 bytes UTF-8
        text = "😊" * 125  # 125 × 4 = 500 bytes exactly
        valid, result = adapters.validate_threads_text(text)
        self.assertTrue(valid)
        self.assertEqual(result, text)

    def test_utf8_exceeds_500_with_emoji(self):
        # 126 emojis = 504 bytes → invalid
        text = "😊" * 126
        valid, reason = adapters.validate_threads_text(text)
        self.assertFalse(valid)
        self.assertTrue("exceeds" in reason and "504" in reason)

    def test_build_threads_create_rejects_overlimit(self):
        text = "a" * 501
        with self.assertRaisesRegex(ValueError, "exceeds.*UTF-8 bytes"):
            adapters.build_threads_create(text, user_id="u1")

    def test_build_threads_create_accepts_valid(self):
        # Valid dengan emoji: 250 chars + 1 URL ≈ ~254 bytes
        text = "Update terbaru! " + "😊" * 10 + " https://example.com"
        request = adapters.build_threads_create(text, user_id="u1")
        self.assertEqual(request["json"]["text"], text)


class ReplyBuilderTests(unittest.TestCase):
    """Builder kontrak offline balasan berantai Threads (reply_to_id)."""

    def test_threads_reply_shape(self):
        request = adapters.build_threads_reply("Lanjutan", user_id="u1", reply_to_id="parent-1")
        self.assertEqual(request["platform"], "threads")
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://graph.threads.com/v1.0/u1/threads")
        self.assertEqual(request["json"],
                         {"media_type": "TEXT", "text": "Lanjutan", "reply_to_id": "parent-1"})

    def test_threads_reply_requires_reply_to_id(self):
        for bad in ("", "   "):
            with self.assertRaisesRegex(ValueError, "reply_to_id"):
                adapters.build_threads_reply("Lanjutan", user_id="u1", reply_to_id=bad)

    def test_threads_reply_validates_text_limits(self):
        with self.assertRaisesRegex(ValueError, "teks"):
            adapters.build_threads_reply("   ", user_id="u1", reply_to_id="parent-1")
        with self.assertRaisesRegex(ValueError, "exceeds.*UTF-8 bytes"):
            adapters.build_threads_reply("a" * 501, user_id="u1", reply_to_id="parent-1")

    def test_threads_reply_graph_host_configurable(self):
        request = adapters.build_threads_reply("Lanjutan", user_id="u1", reply_to_id="parent-1",
                                               graph="https://graph.threads.net/v1.0")
        self.assertTrue(request["url"].startswith("https://graph.threads.net/v1.0/"))


class ClassifyTests(unittest.TestCase):
    def test_success_with_id_is_created(self):
        result = adapters.classify_response(201, {"id": "55"})
        self.assertEqual(result, {"outcome": "created", "external_id": "55"})

    def test_success_without_id_is_ambiguous(self):
        result = adapters.classify_response(200, {})
        self.assertEqual(result["outcome"], "ambiguous")

    def test_rate_limited_keeps_reset_header(self):
        result = adapters.classify_response(429, {"error": "slow down"},
                                            headers={"x-rate-limit-reset": "1700000000"})
        self.assertEqual(result["outcome"], "rate_limited")
        self.assertEqual(result["retry_after"], "1700000000")

    def test_auth_states(self):
        self.assertEqual(adapters.classify_response(401, {})["outcome"], "auth_expired")
        self.assertEqual(adapters.classify_response(403, {})["outcome"], "failed")

    def test_client_error_is_failed(self):
        self.assertEqual(adapters.classify_response(422, {})["outcome"], "failed")

    def test_server_error_is_ambiguous(self):
        self.assertEqual(adapters.classify_response(503, {})["outcome"], "ambiguous")


class PlatformParserTests(unittest.TestCase):
    """F9: each platform's documented success envelope is parsed explicitly."""

    def test_x_live_envelope_is_created(self):
        payload = {"data": {"id": "55", "text": "Halo"}}
        parsed = adapters.parse_x_create(201, payload)
        self.assertEqual((parsed["state"], parsed["external_id"], parsed["envelope"]),
                         ("created", "55", "data.id"))
        classified = adapters.classify_response(201, payload, platform="x")
        self.assertEqual(classified["outcome"], "created")
        self.assertEqual(classified["state"], "created")
        self.assertEqual(classified["external_id"], "55")

    def test_x_success_without_id_is_ambiguous(self):
        parsed = adapters.parse_x_create(200, {"data": {}})
        self.assertEqual(parsed["state"], "ambiguous")
        self.assertIn("data.id", parsed["reason"])
        classified = adapters.classify_response(200, {"data": {}}, platform="x")
        self.assertEqual(classified["outcome"], "ambiguous")

    def test_x_rate_limit_keeps_reset_header(self):
        classified = adapters.classify_response(429, {}, headers={"x-rate-limit-reset": "99"},
                                                platform="x")
        self.assertEqual(classified["outcome"], "rate_limited")
        self.assertEqual(classified["retry_after"], "99")

    def test_x_client_error_is_failed(self):
        self.assertEqual(adapters.parse_x_create(403, {"errors": []})["state"], "failed")

    def test_threads_container_and_publish_are_separate_states(self):
        container = adapters.parse_threads_container(200, {"id": "creation-1"})
        published = adapters.parse_threads_publish(200, {"id": "media-1"})
        self.assertEqual(container["state"], "container_created")
        self.assertEqual(published["state"], "published")
        classified = adapters.classify_response(200, {"id": "creation-1"},
                                                platform="threads-container")
        self.assertEqual(classified["state"], "container_created")
        self.assertEqual(classified["outcome"], "created")

    def test_legacy_envelope_stays_compatible(self):
        self.assertEqual(adapters.classify_response(201, {"id": "55"}),
                         {"outcome": "created", "external_id": "55"})


class SubmitTests(unittest.TestCase):
    @staticmethod
    def approval(text):
        return {"platform": "x", "account": "akun-x",
                "posts": [{"ordinal": 1, "text": text}]}

    def test_submit_refuses_while_live_publishing_is_off(self):
        def transport(request, headers):
            raise AssertionError("transport tidak boleh dipanggil")

        with self.assertRaisesRegex(adapters.PublicationRefused, "LIVE_PUBLISHING"):
            adapters.submit(transport, adapters.build_x_post("Halo"), token="tok", account="akun-x")

    def test_submit_requires_approved_edition_and_matching_account(self):
        def transport(request, headers):
            raise AssertionError("transport tidak boleh dipanggil")

        with patch.object(adapters, "LIVE_PUBLISHING", True):
            with self.assertRaisesRegex(adapters.PublicationRefused, "disetujui"):
                adapters.submit(transport, adapters.build_x_post("Halo"), token="tok", account="akun-x")
            wrong_platform = {"platform": "threads", "account": "akun-x", "posts": [{"text": "Halo"}]}
            with self.assertRaisesRegex(adapters.PublicationRefused, "platform"):
                adapters.submit(transport, adapters.build_x_post("Halo"), token="tok",
                                approval=wrong_platform, account="akun-x")
            with self.assertRaisesRegex(adapters.PublicationRefused, "akun approval"):
                adapters.submit(transport, adapters.build_x_post("Halo"), token="tok",
                                approval=self.approval("Halo"), account="akun-lain")
            with self.assertRaisesRegex(adapters.PublicationRefused, "bukan bagian"):
                adapters.submit(transport, adapters.build_x_post("Teks lain"), token="tok",
                                approval=self.approval("Halo"), account="akun-x")

    def test_submit_success_through_fake_transport(self):
        seen = {}

        def transport(request, headers):
            seen["auth"] = headers["Authorization"]
            return 201, {"data": {"id": "77"}}, {}

        with patch.object(adapters, "LIVE_PUBLISHING", True):
            result = adapters.submit(transport, adapters.build_x_post("Halo"), token="tok",
                                     approval=self.approval("Halo"), account="akun-x")
        self.assertEqual(result["outcome"], "created")
        self.assertEqual(result["external_id"], "77")
        self.assertEqual(seen["auth"], "Bearer tok")

    def test_submit_timeout_is_ambiguous(self):
        def transport(request, headers):
            raise TimeoutError()

        with patch.object(adapters, "LIVE_PUBLISHING", True):
            result = adapters.submit(transport, adapters.build_x_post("Halo"), token="tok",
                                     approval=self.approval("Halo"), account="akun-x")
        self.assertEqual(result, {"outcome": "ambiguous", "reason": "timeout"})

    def test_submit_transport_error_never_raises(self):
        def transport(request, headers):
            raise ConnectionResetError("boom")

        with patch.object(adapters, "LIVE_PUBLISHING", True):
            result = adapters.submit(transport, adapters.build_x_post("Halo"), token="tok",
                                     approval=self.approval("Halo"), account="akun-x")
        self.assertEqual(result["outcome"], "ambiguous")
        self.assertIn("ConnectionResetError", result["reason"])


class PlanTests(unittest.TestCase):
    def test_plan_next_action_mapping(self):
        cases = {None: "submit", "created": "already_done", "mock_verified": "already_done",
                 "timeout": "readback_first", "ambiguous": "readback_first",
                 "partial_failure": "readback_first", "failed": "retry_after_fix",
                 "expired_token": "retry_after_fix", "rate_limited": "wait_then_retry",
                 "sesuatu-yang-tak-dikenal": "readback_first"}
        for previous, expected in cases.items():
            with self.subTest(previous=previous):
                self.assertEqual(adapters.plan_next_action(previous), expected)


class ReadbackTests(unittest.TestCase):
    def test_x_readback_match(self):
        payload = {"data": {"text": "Halo", "author_id": "42"}}
        ok, reason = adapters.verify_readback("x", payload, expected_account="42", expected_text="Halo")
        self.assertTrue(ok)
        self.assertEqual(reason, "cocok")

    def test_x_readback_text_mismatch(self):
        payload = {"data": {"text": "Halo!", "author_id": "42"}}
        ok, reason = adapters.verify_readback("x", payload, expected_account="42", expected_text="Halo")
        self.assertFalse(ok)
        self.assertEqual(reason, "teks tidak cocok")

    def test_x_readback_account_mismatch(self):
        payload = {"data": {"text": "Halo", "author_id": "43"}}
        ok, reason = adapters.verify_readback("x", payload, expected_account="42", expected_text="Halo")
        self.assertFalse(ok)
        self.assertEqual(reason, "akun tidak cocok")

    def test_threads_readback_link_mismatch(self):
        payload = {"text": "Halo", "username": "akun", "link_attachment_url": "https://x.test/1"}
        ok, reason = adapters.verify_readback("threads", payload, expected_account="akun",
                                              expected_text="Halo", expected_link="https://x.test/2")
        self.assertFalse(ok)
        self.assertEqual(reason, "tautan tidak cocok")

    def test_unknown_platform_rejected(self):
        with self.assertRaisesRegex(ValueError, "platform"):
            adapters.verify_readback("mastodon", {}, expected_account="a", expected_text="b")


class ModuleGuardTests(unittest.TestCase):
    def test_module_contains_no_network_code(self):
        source = Path(adapters.__file__).read_text(encoding="utf-8").lower()
        for needle in ("urllib", "requests", "http.client", "socket", "httpx"):
            self.assertNotIn(needle, source, f"kode jaringan ditemukan: {needle}")

    def test_live_publishing_is_off_by_default(self):
        self.assertFalse(adapters.LIVE_PUBLISHING)


if __name__ == "__main__":
    unittest.main()
