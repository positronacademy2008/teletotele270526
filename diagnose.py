"""Startup diagnostics for Telegram feed + channels + WordPress."""
from __future__ import annotations

import os
import sys

import requests

import bot


def main() -> int:
    bot.setup_logging()
    missing = [name for name in ("BOT_TOKEN", "DEST_CHANNEL", "FEED_URL") if not os.environ.get(name)]
    if missing:
        print(f"Missing env: {', '.join(missing)}")
        return 1

    config = bot.Config.from_env()
    session = requests.Session()
    ok = True

    print(f"Source RSS: {config.feed_url}")
    print(f"Destination: {', '.join(config.dest_channels)}")
    print(f"WordPress: {config.wp_url or '(not set)'} | skip={config.skip_wordpress}")

    try:
        me = session.get(
            f"https://api.telegram.org/bot{config.bot_token}/getMe",
            timeout=20,
        ).json()
        if me.get("ok"):
            print(f"Bot OK: @{me['result'].get('username', '?')}")
        else:
            print(f"Bot FAIL: {me.get('description')}")
            ok = False
    except Exception as exc:
        print(f"Bot FAIL: {exc}")
        ok = False

    for channel in config.dest_channels:
        try:
            payload = session.get(
                f"https://api.telegram.org/bot{config.bot_token}/getChat",
                params={"chat_id": channel},
                timeout=20,
            ).json()
            if payload.get("ok"):
                chat = payload["result"]
                print(f"Dest OK: {channel} -> {chat.get('title', chat.get('username', channel))}")
            else:
                print(f"Dest FAIL: {channel} -> {payload.get('description')}")
                ok = False
        except Exception as exc:
            print(f"Dest FAIL: {channel} -> {exc}")
            ok = False

    try:
        response = session.get(
            config.feed_url,
            headers=bot.default_headers(),
            timeout=30,
            verify=config.verify_ssl,
        )
        response.raise_for_status()
        items = bot.parse_feed(response.text, config.feed_url)
        print(f"Feed OK: {len(items)} item(s)")
        if items:
            sample = items[0]
            media = sample.enclosure_url or "(text only)"
            print(f"Latest: {sample.title[:90]}")
            print(f"  guid={sample.guid}")
            print(f"  media={media}")
    except Exception as exc:
        print(f"Feed FAIL: {exc}")
        ok = False

    if config.wordpress_ready and not config.skip_wordpress:
        try:
            root = bot.WordPressClient(config, session).api_root()
            response = session.get(f"{root}/posts?per_page=1", timeout=30, verify=config.verify_ssl)
            print(f"WordPress API: HTTP {response.status_code}")
            if response.status_code != 200:
                ok = False
        except Exception as exc:
            print(f"WordPress FAIL: {exc}")
            ok = False

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())