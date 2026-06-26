"""Publish missing WordPress posts and send Full Post link to Telegram."""
from __future__ import annotations

import os

os.environ.setdefault("WP_CATCHUP_ONLY", "true")
os.environ.setdefault("SKIP_WORDPRESS", "false")
os.environ.setdefault("WP_CATCHUP", "true")
os.environ.setdefault("FEED_URL", "https://tg.i-c-a.su/rss/ShikshaVibhag")
os.environ.setdefault("WP_URL", "https://positronacademy.in")

import run_bot  # noqa: F401 — apply runtime patches

import bot

if __name__ == "__main__":
    bot.main()