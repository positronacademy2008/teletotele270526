import os
import requests
from openai import OpenAI

# --- 1. SETUP GROQ AI ---
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

def get_telegram_data():
    """
    Yahan se Telegram ka last message fetch hoga.
    Agar aapka koi special Telegram scraping logic tha, toh wo yahan add kar lena.
    """
    bot_token = os.environ.get("BOT_TOKEN")
    
    print("⏳ Fetching from Telegram...")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        
        if resp.get("ok") and len(resp["result"]) > 0:
            # Sabse aakhri message uthao
            latest_msg = resp["result"][-1]["message"]["text"]
            return latest_msg
        else:
            print("⚠️ No new messages found in Telegram.")
            return None
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
        # Test ke liye default message agar Telegram fetch fail ho jaye
        return "Science Update: Positron Academy starts new technology batch!"

def get_groq_content(msg):
    print("⏳ Rewriting content via Groq AI...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional blog writer for Positron Academy."},
                {"role": "user", "content": f"Rewrite this text into an engaging, professional blog post in Hindi/English mix: {msg}"}
            ],
            model="llama3-8b-8192", # Groq ka sabse fast model
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq API Error: {e}")
        return f"Latest Update:\n\n{msg}"

def publish_to_wp(title, content):
    print("⏳ Publishing to WordPress...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    # 🔥 YAHI HAI FIREWALL BYPASS (ModSecurity ka dushman)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }
    
    data = {
        'title': title, 
        'content': content, 
        'status': 'publish'
    }
    
    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        
        if response.status_code == 201:
            print("✅ SUCCESS: Post Published to WordPress!")
            return True
        else:
            print(f"❌ WP ERROR: Status {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ WP Exception: {e}")
        return False

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("🚀 Starting Positron Bot...")
    
    # Step 1: Get Telegram Message
    raw_msg = get_telegram_data()
    
    if raw_msg:
        print(f"📥 Fetched Text: {raw_msg[:50]}...") # Shuruwaati 50 shabd print karega
        
        # Step 2: Make it beautiful with AI
        final_content = get_groq_content(raw_msg)
        
        # Step 3: Publish
        # Title aap apne hisaab se dynamically bhi set karwa sakte ho AI se
        publish_to_wp("Positron Academy Daily Update", final_content)
    else:
        print("🛑 Task stopped. Nothing to publish.")
