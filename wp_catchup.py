"""Publish missing WordPress posts and send Full Post link to Telegram."""
from __future__ import annotations

import os
import sys

from env_loader import load_dotenv

if not load_dotenv():
    print("ERROR: .env file missing.")
    print("Copy .env.example to .env and fill BOT_TOKEN, WP_USER, WP_PASS, GROQ_API_KEY from GitHub secrets.")
    print("Or run:  gh workflow run \"WordPress Catch-up\" --repo positronacademy2008/teletotele270526")
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