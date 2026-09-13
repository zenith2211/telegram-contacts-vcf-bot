"""Tests for the aiohttp webhook/health server. Run:  python test_webserver.py

Uses a dummy token and aiohttp's in-process test server, so no network or real
Telegram token is required.
"""

import asyncio

from aiohttp.test_utils import TestClient, TestServer
from telegram.ext import Application

from bot import build_web_app, webhook_secrets

URL_PATH = "testpath"
SECRET = "s3cr3t"

VALID_UPDATE = {
    "update_id": 10001,
    "message": {
        "message_id": 5,
        "date": 1600000000,
        "chat": {"id": 123, "type": "private"},
        "from": {"id": 123, "is_bot": False, "first_name": "Test"},
        "text": "hello",
    },
}


async def _run() -> None:
    application = Application.builder().token("123456:dummy").build()
    app = build_web_app(application, URL_PATH, SECRET)

    async with TestClient(TestServer(app)) as client:
        # Health endpoints return 200.
        for path in ("/", "/healthz"):
            resp = await client.get(path)
            assert resp.status == 200, f"GET {path} -> {resp.status}"
            assert (await resp.text()) == "OK"

        # HEAD on "/" (what some uptime monitors use) is allowed via GET route.
        resp = await client.head("/")
        assert resp.status == 200, f"HEAD / -> {resp.status}"

        # Valid webhook POST (correct secret header) enqueues one Update.
        resp = await client.post(
            f"/{URL_PATH}",
            json=VALID_UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status == 200, f"valid POST -> {resp.status}"
        assert application.update_queue.qsize() == 1
        queued = application.update_queue.get_nowait()
        assert queued.update_id == 10001

        # Wrong secret is rejected and does NOT enqueue anything.
        resp = await client.post(
            f"/{URL_PATH}",
            json=VALID_UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert resp.status == 403, f"bad-secret POST -> {resp.status}"
        assert application.update_queue.qsize() == 0

        # Missing secret header is rejected.
        resp = await client.post(f"/{URL_PATH}", json=VALID_UPDATE)
        assert resp.status == 403, f"no-secret POST -> {resp.status}"

        # Malformed body -> 400.
        resp = await client.post(
            f"/{URL_PATH}",
            data="not json",
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        assert resp.status == 400, f"bad-json POST -> {resp.status}"

    print("  ok  health endpoints return 200 (GET + HEAD)")
    print("  ok  valid webhook POST enqueues update")
    print("  ok  wrong/missing secret rejected (403)")
    print("  ok  malformed body rejected (400)")


def test_webhook_secrets_are_stable_and_hide_token():
    token = "123456:ABCdefTOKEN"
    path1, sec1 = webhook_secrets(token)
    path2, sec2 = webhook_secrets(token)
    assert (path1, sec1) == (path2, sec2)  # stable
    assert token not in path1 and token not in sec1  # never leak the raw token
    assert len(path1) == 32
    print("  ok  webhook_secrets stable and token-free")


if __name__ == "__main__":
    test_webhook_secrets_are_stable_and_hide_token()
    asyncio.run(_run())
    print("\nAll webserver tests passed.")
