# Contacts Filter Bot (.txt → .vcf)

A Telegram bot: send it a contacts **.txt** export and it replies with a clean
**.vcf** file that keeps **only the name and phone number** — duplicates and all
the extra columns are stripped out.

## What it does

Your `.txt` looks like this (tab-separated, and every contact is repeated once
per source account):

```
	name	number	connected-via
	नारयण तुपे	8010716376	com.android.local
	नारयण तुपे	8010716376	com.google
	माहाराज	+919730740310	com.android.local
	माहाराज	+919730740310	com.google
```

The bot turns that into a standard vCard file:

```
BEGIN:VCARD
VERSION:3.0
N:नारयण तुपे;;;;
FN:नारयण तुपे
TEL;TYPE=CELL:8010716376
END:VCARD
...
```

Along the way it:

- keeps **only the name + phone**, drops the `connected-via` column and header;
- **removes duplicates** — the same contact repeated per source becomes one entry
  (a name with two *different* numbers stays as two entries);
- **cleans phone numbers** — strips spaces and stray junk like a trailing `p` or
  `;` (e.g. `+91 87660 66168` → `+918766066168`, `7387381517;` → `7387381517`);
- keeps names in any language (Marathi/Hindi/Devanagari, etc.) via UTF-8.

On the included sample of 2,227 rows this produces **771 unique contacts**.

## Setup

### 1. Get a bot token

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts (choose a name and a username).
3. BotFather gives you a token that looks like `123456789:ABCdef...`.

### 2. Add the token

Create a file called **`token.txt`** in this folder and paste the token into it
(nothing else). *(Alternatively, set an environment variable `BOT_TOKEN`.)*

`token.txt` is already git-ignored so you won't accidentally share it.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the bot

```bash
python bot.py
```

Leave this running. Stop it any time with `Ctrl+C`.

## Using it

1. Open your bot in Telegram (the link BotFather gave you).
2. Send `/start`.
3. Tap the 📎 attach button and upload your `.txt` file.
4. The bot replies with a `.vcf` file — open it on your phone to import the
   contacts.

## Notes

- **File size:** Telegram lets bots download files up to **20 MB**. Larger files
  need to be split.
- **Number format:** numbers are kept exactly as they appear (just cleaned),
  including short codes like `100`/`112`. The bot does **not** auto-add a `+91`
  country code, because the list also contains landlines and helplines where that
  would be wrong.
- **Encodings:** the bot auto-detects UTF-8 / UTF-16 / Windows-1252 text.

## Deploy on Render (24/7 hosting)

This repo is ready to run as a **web service** on [Render](https://render.com).
The bot detects Render automatically (via `RENDER_EXTERNAL_URL` + `PORT`) and
switches from polling to **webhook** mode, binding to the port Render provides.

Quickest way (Blueprint):

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, pick the repo (it reads `render.yaml`).
3. When prompted, set the `BOT_TOKEN` environment variable to your BotFather
   token. **Never commit the token** — it lives only in Render.
4. Deploy. The bot registers its webhook on startup and is live.

Or **New → Web Service** with these settings:

| Setting | Value |
| --- | --- |
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `python bot.py` |
| Environment variable | `BOT_TOKEN` = your token |

**Free plan note:** free web services sleep after ~15 min of inactivity. The
first message after a nap wakes the service (a ~30–60 s cold start) and Telegram
retries delivery, so it still gets through — just with a short delay. Keep it
awake with an uptime monitor (below), or upgrade to a paid instance.

## Keep it awake with UptimeRobot

The bot exposes a health endpoint that returns `200 OK`:

```
https://<your-service>.onrender.com/healthz
```

Ping it every few minutes so the free instance never idles out:

1. Sign in at [uptimerobot.com](https://uptimerobot.com).
2. **+ New monitor** →
   - **Type:** HTTP(s)
   - **URL:** `https://<your-service>.onrender.com/healthz`
   - **Monitoring interval:** 5 minutes
3. Save. The monitor should show **Up** (green) — the endpoint returns 200.

> Render free instances only sleep after ~15 min of *no* traffic, so a 5-minute
> ping keeps it continuously awake. (Free-tier instance hours are limited per
> month; a single always-on service fits within the monthly allowance.)

## Project files

| File | Purpose |
| --- | --- |
| `bot.py` | The Telegram bot (download file → convert → reply with `.vcf`). |
| `converter.py` | Pure parsing + vCard logic (no Telegram code). |
| `test_converter.py` | Tests for the logic — run `python test_converter.py`. |
| `test_webserver.py` | Tests for the webhook/health server — run `python test_webserver.py`. |
| `requirements.txt` | Python dependencies. |
