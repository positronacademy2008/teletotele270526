import os, requests
import google.generativeai as genai

# --- CONFIGURATION (GitHub Secrets se utha raha hai) ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-3.1-pro-preview')

def get_latest_tg_message():
    # Aapka Telegram Bot logic (yahan apna original code use karein)
    # Filhal testing ke liye dummy message
    return "Science News: Positron Academy successfully launched new AI batch!"

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    password = os.environ.get("WP_PASS")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        response = requests.post(url, auth=(user, password), json=data, headers=headers, timeout=120)
        return response.status_code == 201
    except Exception as e:
        print(f"WP Error: {e}")
        return False

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    msg = get_latest_tg_message()
    print(f"Fetched: {msg}")
    
    # AI se content rewrite karwa rahe hain
    ai_response = model.generate_content(f"Rewrite this for a Science Blog: {msg}")
    final_content = ai_response.text
    
    # WordPress par publish
    if publish_to_wp("Latest Science Update", final_content):
        print("✅ SUCCESS: Published to WordPress!")
    else:
        print("❌ FAILED: Still blocked by Hosting Firewall. Contact Support!")
