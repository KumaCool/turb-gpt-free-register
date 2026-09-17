# -*- coding: utf-8 -*-
import json
import unittest
from unittest.mock import patch

from core.generic_api_mail_client import (
    GenericApiEmailAccount,
    _is_loopback_url,
    _parse_pickup_page_url,
    fetch_latest_otp,
)


PICKUP_URL = "http://127.0.0.1:5050/pickup/AI243NQ3xppUGwsieBoe3hD4vZklTFyooh8No754uII"
EMAIL = "28.harmony.titled@icloud.com"


class _Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload


class _Session:
    def __init__(self, responses):
        self.urls = []
        self.proxies = {}
        self.trust_env = True
        self._responses = list(responses)

    def get(self, url, **_kwargs):
        self.urls.append(url.split("?", 1)[0])
        if not self._responses:
            raise AssertionError("unexpected request: %s" % url)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class GenericApiPickupPageTests(unittest.TestCase):
    def test_parse_pickup_page_url(self):
        self.assertEqual(
            _parse_pickup_page_url(PICKUP_URL),
            ("http://127.0.0.1:5050", "AI243NQ3xppUGwsieBoe3hD4vZklTFyooh8No754uII"),
        )
        self.assertEqual(
            _parse_pickup_page_url(PICKUP_URL + "/messages"),
            ("http://127.0.0.1:5050", "AI243NQ3xppUGwsieBoe3hD4vZklTFyooh8No754uII"),
        )
        self.assertIsNone(_parse_pickup_page_url("https://remail.aishop6.com/v1/pickup"))
        self.assertTrue(_is_loopback_url(PICKUP_URL))

    def test_fetch_latest_otp_uses_async_message_api(self):
        account = GenericApiEmailAccount(email=EMAIL, code_url=PICKUP_URL)
        session = _Session([
            _Response({
                "emails": [
                    {"id": "6", "subject": "old", "date": "2026-09-14T10:00:00+08:00"},
                    {"id": "7", "subject": "Your ChatGPT code", "date": "2026-09-15T03:15:00+08:00"},
                ],
                "refreshing": False,
            }),
            _Response({"ready": True, "message": {
                "subject": "Your ChatGPT code",
                "body": "Your code is 246813",
                "html": "<p>Your code is 246813</p>",
                "verification_code": "246813",
            }}),
        ])
        with patch("core.generic_api_mail_client.get_account_context", return_value=account), \
             patch("core.generic_api_mail_client._proxy_cfg.pick_proxy", return_value="http://user:pass@100.102.89.105:55223"), \
             patch("core.generic_api_mail_client.requests.Session", return_value=session):
            code = fetch_latest_otp(EMAIL, max_wait=2, poll_interval=0.01, settle_seconds=0)
        self.assertEqual(code, "246813")
        self.assertEqual(session.proxies, {})
        self.assertEqual(session.urls, [
            "http://127.0.0.1:5050/pickup/AI243NQ3xppUGwsieBoe3hD4vZklTFyooh8No754uII/messages",
            "http://127.0.0.1:5050/pickup/AI243NQ3xppUGwsieBoe3hD4vZklTFyooh8No754uII/message/7",
        ])
        self.assertNotIn(PICKUP_URL, session.urls)

    def test_waits_when_message_body_is_still_loading(self):
        account = GenericApiEmailAccount(email=EMAIL, code_url=PICKUP_URL)
        session = _Session([
            _Response({"emails": [{"id": "7", "subject": "ChatGPT", "date": "2026-09-15T03:15:00+08:00"}]}),
            _Response({"ready": False, "refreshing": True}, status_code=202),
            _Response({"emails": [{"id": "7", "subject": "ChatGPT", "date": "2026-09-15T03:15:00+08:00"}]}),
            _Response({"ready": True, "message": {
                "subject": "ChatGPT",
                "body": "verification code 135790",
                "verification_code": "135790",
            }}),
        ])
        with patch("core.generic_api_mail_client.get_account_context", return_value=account), \
             patch("core.generic_api_mail_client._proxy_cfg.pick_proxy", return_value=""), \
             patch("core.generic_api_mail_client.requests.Session", return_value=session):
            code = fetch_latest_otp(EMAIL, max_wait=2, poll_interval=0.01, settle_seconds=0)
        self.assertEqual(code, "135790")
        self.assertEqual(len(session.urls), 4)


if __name__ == "__main__":
    unittest.main()
