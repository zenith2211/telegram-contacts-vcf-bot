"""Vercel serverless function: Telegram webhook for the contacts .txt -> .vcf bot.

Vercel is serverless, so unlike the Render deployment (a long-running aiohttp
server in ../bot.py) there is no persistent process here. Telegram POSTs each
update to this function; we process that one update and return.

Endpoint: POST /api/webhook  (set as the bot's webhook URL)
          GET  /api/webhook  -> small JSON status (handy for verifying a deploy)

Requires the BOT_TOKEN environment variable (set in the Vercel project, not
committed). The parsing/vCard logic is reused from the repo-root converter.py.
"""

import hashlib
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler

import requests

# Reuse the tested pure-logic module from the repository root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from converter import convert_text_to_vcf

    _CONVERTER_OK = True
    _CONVERTER_ERR = ""
except Exception as exc:  # pragma: no cover - surfaced via GET status
    convert_text_to_vcf = None
    _CONVERTER_OK = False
    _CONVERTER_ERR = repr(exc)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{TOKEN}"
MAX_FILE_BYTES = 20 * 1024 * 1024

WELCOME = (
    "👋 Hi! I turn a contacts .txt file into a clean .vcf file.\n\n"
    "Just send me the .txt file (like your exported contacts list) and I'll:\n"
    "• keep only the name and phone number\n"
    "• remove duplicate rows and the extra columns\n"
    "• send you back a .vcf file you can import into your phone.\n\n"
    "Go ahead — upload your .txt file now."
)
HELP = (
    "Send me a .txt file where each line has a name and a phone number "
    "(tab-separated). I'll filter out everything else and reply with a .vcf "
    "contacts file.\n\nCommands:\n/start – how it works\n/help – this message"
)
SEND_FILE_HINT = (
    "Please send me your contacts as a .txt file (not text in a message). "
    "Tap the 📎 attach button and choose the .txt document."
)


def secret_token() -> str:
    """Same derivation as bot.py so the webhook secret matches across hosts."""
    return hashlib.sha256((TOKEN + ":webhook").encode()).hexdigest()


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _safe_vcf_name(filename: str) -> str:
    stem = os.path.splitext(filename or "")[0]
    # Keep the multipart filename header ASCII-safe.
    stem = re.sub(r"[^A-Za-z0-9._-]", "", stem)
    return (stem or "contacts") + ".vcf"


def send_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=20,
    )


def handle_document(chat_id: int, document: dict) -> None:
    filename = document.get("file_name") or "contacts.txt"
    size = document.get("file_size") or 0
    if size and size > MAX_FILE_BYTES:
        send_message(
            chat_id,
            "That file is larger than 20 MB, which is the most I can download. "
            "Please split it into smaller files.",
        )
        return

    info = requests.get(
        f"{API}/getFile", params={"file_id": document["file_id"]}, timeout=20
    ).json()
    if not info.get("ok"):
        send_message(chat_id, "Sorry, I couldn't download that file. Please try again.")
        return

    file_path = info["result"]["file_path"]
    data = requests.get(f"{FILE_API}/{file_path}", timeout=45).content
    text = decode_bytes(data)

    vcf, count = convert_text_to_vcf(text)
    if count == 0:
        send_message(
            chat_id,
            "I couldn't find any name + phone number rows in that file. 🤔\n"
            "Make sure each line has a name and a number separated by a tab, "
            "then send it again.",
        )
        return

    caption = (
        f"✅ Done! Kept {count} unique contact{'s' if count != 1 else ''} "
        "(name + phone).\nOpen this .vcf file on your phone to import them."
    )
    requests.post(
        f"{API}/sendDocument",
        data={"chat_id": chat_id, "caption": caption},
        files={"document": (_safe_vcf_name(filename), vcf.encode("utf-8"), "text/vcard")},
        timeout=45,
    )


def process_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return

    if "document" in message:
        handle_document(chat_id, message["document"])
        return

    text = message.get("text", "") or ""
    if text.startswith("/start"):
        send_message(chat_id, WELCOME)
    elif text.startswith("/help"):
        send_message(chat_id, HELP)
    else:
        send_message(chat_id, SEND_FILE_HINT)


class handler(BaseHTTPRequestHandler):
    def _respond(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (tornado/http.server naming)
        status = {
            "ok": True,
            "service": "telegram-contacts-vcf-bot",
            "converter_loaded": _CONVERTER_OK,
            "token_set": bool(TOKEN),
        }
        if not _CONVERTER_OK:
            status["converter_error"] = _CONVERTER_ERR
        self._respond(200, json.dumps(status).encode("utf-8"), "application/json")

    def do_POST(self) -> None:  # noqa: N802
        if not TOKEN:
            # Not configured yet; ack so Telegram doesn't retry-storm.
            self._respond(200, b"no token")
            return

        # Verify the request really comes from Telegram.
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret_token():
            self._respond(403, b"forbidden")
            return

        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            update = json.loads(raw.decode("utf-8"))
        except Exception:
            self._respond(400, b"bad request")
            return

        if not _CONVERTER_OK:
            # Should never happen once deployed correctly; report instead of crash.
            print(f"converter failed to load: {_CONVERTER_ERR}", file=sys.stderr)
        else:
            try:
                process_update(update)
            except Exception:
                # Log for Vercel runtime logs, but still 200 to avoid retries.
                traceback.print_exc()

        self._respond(200, b"ok")
