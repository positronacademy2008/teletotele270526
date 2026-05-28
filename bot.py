import os, requests, time
import google.generativeai as genai

# Setup Nayi API Key (GitHub Secrets mein update kar dena)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# Quota-friendly aur fast model
model = genai.GenerativeModel('gemini-2.0-flash-lite')

def get_telegram_data():
    # Yahan apna Telegram fetch logic daalo
    return "Science News: Positron Academy successfully launched new AI batch!"

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    auth = (os.environ.get("WP_USER"), os.environ.get("WP_PASS"))
    # Yahi headers ne aapka Firewall bypass kiya tha
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        response = requests.post(url, auth=auth, data=data, headers=headers, timeout=90)
        return response.status_code == 201
    except Exception as e:
        print(f"WP Error: {e}")
        return False

# --- MAIN LOGIC ---
if __name__ == "__main__":
    msg = get_telegram_data()
    print(f"Fetched Message: {msg}")
    
    try:
        # AI se content rewrite
        ai_response = model.generate_content(f"Rewrite this as an engaging Science update: {msg}")
        final_post = ai_response.text
        
        # WP Publish
        if publish_to_wp("Latest Science Update", final_post):
            print("🚀 SUCCESS: Bot live hai!")
        else:
            print("❌ FAILED: Check connection.")
            
    except Exception as e:
        print(f"❌ AI Quota/Error: {e}")
