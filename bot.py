"""Telegram bot: send it a contacts .txt export and get back a clean .vcf.

Usage:
    1. Get a bot token from @BotFather on Telegram.
    2. Put the token in a file named ``token.txt`` next to this script,
       OR set the environment variable ``BOT_TOKEN``.
    3. Run:  python bot.py
    4. In Telegram, open your bot, send /start, then upload the .txt file.

The bot filters out every column except the name and phone number, removes
the duplicate rows (same contact repeated per source account), and replies
with a ready-to-import .vcf contacts file.
"""

from __future__ import annotations

import hashlib
import logging
import os
from io import BytesIO
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from converter import convert_text_to_vcf

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Telegram's getFile download limit for bots is 20 MB.
MAX_FILE_BYTES = 20 * 1024 * 1024


def load_token() -> str:
    """Read the bot token from token.txt (preferred) or the BOT_TOKEN env var."""
    token_file = Path(__file__).with_name("token.txt")
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token
    raise SystemExit(
        "No bot token found.\n"
        "Create a file called 'token.txt' next to bot.py containing your\n"
        "token from @BotFather, or set the BOT_TOKEN environment variable."
    )


def decode_bytes(data: bytes) -> str:
    """Decode uploaded file bytes as text, trying the common encodings."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # latin-1 never fails, but keep a safe fallback just in case.
    return data.decode("utf-8", errors="replace")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi! I turn a contacts .txt file into a clean .vcf file.\n\n"
        "Just send me the .txt file (like your exported contacts list) and "
        "I'll:\n"
        "• keep only the name and phone number\n"
        "• remove duplicate rows and the extra columns\n"
        "• send you back a .vcf file you can import into your phone.\n\n"
        "Go ahead — upload your .txt file now."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me a .txt file where each line has a name and a phone number "
        "(tab-separated). I'll filter out everything else and reply with a "
        ".vcf contacts file.\n\nCommands:\n/start – how it works\n/help – this message"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    filename = document.file_name or "contacts.txt"

    if document.file_size and document.file_size > MAX_FILE_BYTES:
        await update.message.reply_text(
            "That file is larger than 20 MB, which is the most I can download. "
            "Please split it into smaller files."
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT
    )

    try:
        tg_file = await document.get_file()
        data = bytes(await tg_file.download_as_bytearray())
    except Exception:
        logger.exception("Failed to download document")
        await update.message.reply_text(
            "Sorry, I couldn't download that file. Please try again."
        )
        return

    text = decode_bytes(data)

    try:
        vcf, count = convert_text_to_vcf(text)
    except Exception:
        logger.exception("Failed to convert file")
        await update.message.reply_text(
            "Something went wrong while reading that file. Make sure it's the "
            "contacts .txt export and try again."
        )
        return

    if count == 0:
        await update.message.reply_text(
            "I couldn't find any name + phone number rows in that file. 🤔\n"
            "Make sure each line has a name and a number separated by a tab, "
            "then send it again."
        )
        return

    out_name = (Path(filename).stem or "contacts") + ".vcf"
    bio = BytesIO(vcf.encode("utf-8"))
    bio.name = out_name

    await update.message.reply_document(
        document=bio,
        filename=out_name,
        caption=(
            f"✅ Done! Kept {count} unique contact"
            f"{'s' if count != 1 else ''} (name + phone).\n"
            "Open this .vcf file on your phone to import them."
        ),
    )


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Please send me your contacts as a .txt *file* (not text in a message). "
        "Tap the 📎 attach button and choose the .txt document."
    )


def main() -> None:
    token = load_token()
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other)
    )

    # On a host that gives us a public URL + port (e.g. Render) run in webhook
    # mode and bind to that port so the platform's health checks pass. Locally,
    # where there's no such URL, fall back to long polling.
    external_url = (
        os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    )
    port = int(os.environ.get("PORT", "0"))

    if external_url and port:
        external_url = external_url.rstrip("/")
        # Stable, non-guessable values derived from the token — we never put the
        # raw token in the URL path. secret_token lets Telegram-signed requests
        # be verified via the X-Telegram-Bot-Api-Secret-Token header.
        url_path = hashlib.sha256(token.encode()).hexdigest()[:32]
        secret = hashlib.sha256((token + ":webhook").encode()).hexdigest()
        logger.info("Starting in webhook mode, binding 0.0.0.0:%s", port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=f"{external_url}/{url_path}",
            secret_token=secret,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Starting in polling mode. Press Ctrl+C to stop.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
