import os
import requests
import google.generativeai as genai
import time

# --- SETUP ---
# 1. API Configuration
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# gemini-2.0-flash quota ke liye best hai
model = genai.GenerativeModel('gemini-2.0-flash')

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    # 2. Firewall Bypass: Browser jaisa Identity (User-Agent)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        # Session use kar rahe hain taaki firewall connection ko stable maane
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        
        print(f"DEBUG: Status Code: {response.status_code}")
        if response.status_code == 201:
            print("✅ SUCCESS: Post Published!")
            return True
        else:
            print(f"❌ WP ERROR: {response.text}")
            return False
    except Exception as e:
        print(f"❌ WP Exception: {e}")
        return False

if __name__ == "__main__":
    try:
        print("⏳ Generating Content...")
        ai_response = model.generate_content("Write a 100-word educational update about Science.")
        final_text = ai_response.text
        
        print("⏳ Publishing to WordPress...")
        if publish_to_wp("Science Daily Update", final_text):
            print("🚀 Bot Task Finished Successfully!")
        else:
            print("🛑 Task Failed: Hosting Firewall is still blocking the bot.")
            
    except Exception as e:
        print(f"❌ AI Quota/Error: {e}")
