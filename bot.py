import os, requests, json
from openai import OpenAI

# --- 1. GROQ SETUP ---
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

def get_telegram_data():
    bot_token = os.environ.get("BOT_TOKEN")
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    
    print("⏳ Fetching from Telegram...")
    try:
        resp = requests.get(url, timeout=30).json()
        if resp.get("ok") and len(resp["result"]) > 0:
            # Sabse latest message uthao (list ka aakhri item)
            latest_update = resp["result"][-1]
            update_id = str(latest_update["update_id"])
            
            # Channel aur Normal Message dono handle karega
            text = None
            if "message" in latest_update and "text" in latest_update["message"]:
                text = latest_update["message"]["text"]
            elif "channel_post" in latest_update and "text" in latest_update["channel_post"]:
                text = latest_update["channel_post"]["text"]
                
            if not text:
                print("⚠️ Message found, but it has no text (might be an image or sticker).")
                return None, None
                
            # Check if this message was already processed
            if os.path.exists("last.txt"):
                with open("last.txt", "r") as f:
                    last_id = f.read().strip()
                if last_id == update_id:
                    print("⚠️ No new message found. Already processed this one.")
                    return None, None
            
            return text, update_id
        else:
            print("⚠️ Telegram API returned 0 messages.")
            return None, None
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        return None, None

def save_last_id(update_id):
    # Process hone ke baad ID save kar do
    with open("last.txt", "w") as f:
        f.write(update_id)

def get_groq_content(msg):
    print("⏳ Rewriting content via Groq AI (Llama 3)...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional blog writer for Positron Academy. Write an engaging, professional update in a mix of Hindi and English."},
                {"role": "user", "content": f"Rewrite this as an engaging post: {msg}"}
            ],
            model="llama3-8b-8192", 
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq Error: {e}")
        return f"Latest Update:\n\n{msg}"

def publish_to_wp(title, content):
    print("⏳ Publishing to WordPress...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    # Firewall Bypass Headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=60)
        
        if response.status_code == 201:
            print("✅ SUCCESS: Post Published to WordPress!")
            return True
        else:
            print(f"❌ WP ERROR: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ WP Exception: {e}")
        return False

# --- MAIN LOGIC ---
if __name__ == "__main__":
    msg, update_id = get_telegram_data()
    
    if msg and update_id:
        print(f"📥 Fetched Text: {msg[:50]}...")
        
        final_content = get_groq_content(msg)
        
        if publish_to_wp("Positron Academy Daily Update", final_content):
            save_last_id(update_id) # Tabi save hoga jab WP par post ho jayega
    else:
        print("🛑 Task stopped. Waiting for new messages.")
