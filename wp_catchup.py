"""Publish missing WordPress posts and send Full Post link to Telegram."""
from __future__ import annotations

import os
import sys

from env_loader import load_dotenv

load_dotenv()
if not os.environ.get("BOT_TOKEN"):
    print("ERROR: BOT_TOKEN missing.")
    print("Local PC: copy .env.example to .env and fill secrets from GitHub.")
    print("GitHub: use the \"WordPress Catch-up\" workflow.")
    sys.exit(1)

os.environ.setdefault("WP_CATCHUP_ONLY", "true")
os.environ.setdefault("SKIP_WORDPRESS", "false")
os.environ.setdefault("WP_CATCHUP", "true")
os.environ.setdefault("FEED_URL", "https://tg.i-c-a.su/rss/ShikshaVibhag")
os.environ.setdefault("WP_URL", "https://positronacademy.in")

import run_bot  # noqa: F401 — apply runtime patches

import bot

if __name__ == "__main__":
    bot.main()