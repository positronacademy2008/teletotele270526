def get_telegram_data():
    bot_token = os.environ.get("BOT_TOKEN")
    print("⏳ Fetching from Telegram...")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        
        if resp.get("ok") and len(resp["result"]) > 0:
            # Piche se (latest se) messages check karna shuru karega
            for update in reversed(resp["result"]):
                # Agar normal group/private message hai
                if "message" in update and "text" in update["message"]:
                    return update["message"]["text"]
                # Agar CHANNEL ka post hai (Zaruri)
                elif "channel_post" in update and "text" in update["channel_post"]:
                    return update["channel_post"]["text"]
            
            print("⚠️ Messages found, but no text in them (maybe images/stickers).")
            return None
        else:
            print("⚠️ Telegram API returned 0 new messages.")
            return None
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return None
