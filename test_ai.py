import os, requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# Configuration
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

def test_everything():
    print("--- STARTING BOT TEST ---")
    
    # 1. AI Connection Test
    try:
        response = model.generate_content("Hello! Give a short 'Yes' if you are active.")
        print(f"✅ AI Working: {response.text}")
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return

    # 2. WordPress Connection Test
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    password = os.environ.get("WP_PASS")

    if not all([url, user, password]):
        print("❌ ERROR: Secrets missing in GitHub Actions!")
        return

    headers = {'User-Agent': 'Mozilla/5.0'}
    data = {'title': 'Bot Live Test', 'content': 'Bot successfully connected!', 'status': 'publish'}
    
    try:
        response = requests.post(url, auth=HTTPBasicAuth(user, password), json=data, headers=headers, timeout=60)
        if response.status_code == 201:
            print(f"✅ SUCCESS: Post published! Link: {response.json().get('link')}")
        else:
            print(f"❌ WP AUTH FAILED! Status: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ WP Connection Exception: {e}")

if __name__ == "__main__":
    test_everything()
