import os, requests, time, random
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
        
        # Scenario A: Agar Telegram par NAYA message mil jata hai
        if resp.get("ok") and len(resp["result"]) > 0:
            latest_update = resp["result"][-1]
            update_id = str(latest_update["update_id"])
            
            text = None
            if "message" in latest_update and "text" in latest_update["message"]:
                text = latest_update["message"]["text"]
            elif "channel_post" in latest_update and "text" in latest_update["channel_post"]:
                text = latest_update["channel_post"]["text"]
                
            if text:
                # Check if already processed
                if os.path.exists("last.txt"):
                    with open("last.txt", "r") as f:
                        last_id = f.read().strip()
                    if last_id == update_id:
                        print("⚠️ Telegram message is old. Switching to Test Mode Messages...")
                        return get_testing_fallback_message()
                return text, update_id

        # Scenario B: Telegram khali hai, toh TESTING MODE chalega
        print("⚠️ Telegram API returned 0 new messages.")
        return get_testing_fallback_message()

    except Exception as e:
        print(f"❌ Telegram Error: {e}. Switching to Test Mode...")
        return get_testing_fallback_message()

def get_testing_fallback_message():
    """
    🔥 TESTING MODE: Yahan aap apne purane bheje gaye messages daal do.
    Bot har baar inmein se ek message random utha kar test karega.
    """
    print("🧪 TESTING MODE ACTIVE: Using old messages database...")
    
    old_messages_pool = [
        "Science News: Positron Academy successfully launched new AI batch for students!",
        "Chemistry Class Update: Important formulas and notes for Class IX chemical bonding are now available.",
        "Admissions Open: New batches starting soon for professional courses session 2025-2027."
    ]
    
    # Har baar random message uthayega taaki WordPress par alag content jaye
    selected_msg = random.choice(old_messages_pool)
    
    # Fake dynamic update_id bana rahe hain timestamp se, taaki last.txt ise kabhi block na kare
    fake_update_id = "test_" + str(int(time.time()))
    
    return selected_msg, fake_update_id

def save_last_id(update_id):
    with open("last.txt", "w") as f:
        f.write(update_id)

def get_groq_content(msg):
    print("⏳ Rewriting content via Groq AI (Llama 3)...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional blog writer for Positron Academy. Write an engaging, professional update in a mix of Hindi and English (Hinglish)."},
                {"role": "user", "content": f"Rewrite this text into a small professional blog post: {msg}"}
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
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=60)
        return response.status_code == 201
    except Exception as e:
        print(f"❌ WP Exception: {e}")
        return False

# --- MAIN LOGIC ---
if __name__ == "__main__":
    print("🚀 Starting Positron Bot Testing...")
    
    msg, update_id = get_telegram_data()
    
    if msg and update_id:
        print(f"📥 Processing Text: {msg}")
        
        final_content = get_groq_content(msg)
        
        if publish_to_wp("Positron Academy Live Update", final_content):
            save_last_id(update_id)
            print("🚀 SUCCESS: Posted to WordPress!")
        else:
            print("❌ WP Publish Failed.")
    else:
        print("🛑 Task stopped.")
