"""Tests for the Vercel serverless webhook (api/webhook.py).

Mocks the Telegram HTTP calls so no network or real token is needed.
Run:  python test_webhook_api.py
"""

import os
import sys

os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))

import webhook  # noqa: E402


class _FakeResponse:
    def __init__(self, *, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


class _FakeRequests:
    """Stands in for the `requests` module inside webhook.py."""

    def __init__(self, file_bytes=b""):
        self.posts = []
        self.gets = []
        self._file_bytes = file_bytes

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return _FakeResponse(json_data={"ok": True})

    def get(self, url, **kwargs):
        self.gets.append({"url": url, **kwargs})
        if "/getFile" in url:
            return _FakeResponse(
                json_data={"ok": True, "result": {"file_path": "documents/file_1.txt"}}
            )
        # file download
        return _FakeResponse(content=self._file_bytes)


def _install(fake):
    webhook.requests = fake


def test_start_sends_welcome():
    fake = _FakeRequests()
    _install(fake)
    webhook.process_update(
        {"message": {"chat": {"id": 42, "type": "private"}, "text": "/start"}}
    )
    assert len(fake.posts) == 1
    assert fake.posts[0]["url"].endswith("/sendMessage")
    assert fake.posts[0]["json"]["chat_id"] == 42
    assert "clean .vcf" in fake.posts[0]["json"]["text"]
    print("  ok  /start -> welcome message")


def test_plain_text_hint():
    fake = _FakeRequests()
    _install(fake)
    webhook.process_update(
        {"message": {"chat": {"id": 7, "type": "private"}, "text": "hello"}}
    )
    assert len(fake.posts) == 1
    assert ".txt file" in fake.posts[0]["json"]["text"]
    print("  ok  plain text -> send-a-file hint")


def test_document_returns_vcf():
    sample = "\n".join(
        [
            "\t\tname\tnumber\tconnected-via",
            "\t\tRam\t+919322363970\tcom.android.local",
            "\t\tRam\t+919322363970\tcom.google",  # duplicate -> collapsed
            "\t\tSita\t89996 71073\tcom.google",  # messy number -> cleaned
        ]
    ).encode("utf-8")
    fake = _FakeRequests(file_bytes=sample)
    _install(fake)

    webhook.process_update(
        {
            "message": {
                "chat": {"id": 99, "type": "private"},
                "document": {
                    "file_id": "abc",
                    "file_name": "1.txt",
                    "file_size": len(sample),
                },
            }
        }
    )

    # getFile + file download
    assert any("/getFile" in g["url"] for g in fake.gets)
    assert any("file_1.txt" in g["url"] for g in fake.gets)

    # one sendDocument with the vcf
    doc_posts = [p for p in fake.posts if p["url"].endswith("/sendDocument")]
    assert len(doc_posts) == 1
    post = doc_posts[0]
    assert post["data"]["chat_id"] == 99
    assert "Kept 2 unique contacts" in post["data"]["caption"]

    out_name, vcf_bytes, mime = post["files"]["document"]
    assert out_name == "1.vcf"
    assert mime == "text/vcard"
    vcf = vcf_bytes.decode("utf-8")
    assert vcf.count("BEGIN:VCARD") == 2
    assert "TEL;TYPE=CELL:+919322363970" in vcf
    assert "TEL;TYPE=CELL:8999671073" in vcf  # space stripped
    print("  ok  document -> deduped, cleaned .vcf sent")


def test_secret_derivation_matches_botpy():
    # bot.py uses the same formula; keep them in lockstep.
    import hashlib

    expected = hashlib.sha256(("123456:TESTTOKEN" + ":webhook").encode()).hexdigest()
    assert webhook.secret_token() == expected
    print("  ok  webhook secret matches bot.py formula")


if __name__ == "__main__":
    assert webhook._CONVERTER_OK, f"converter import failed: {webhook._CONVERTER_ERR}"
    print("  ok  converter imported from repo root")
    test_start_sends_welcome()
    test_plain_text_hint()
    test_document_returns_vcf()
    test_secret_derivation_matches_botpy()
    print("\nAll webhook API tests passed.")
