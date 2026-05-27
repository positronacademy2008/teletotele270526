import os, requests
import google.generativeai as genai

# Setup
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

def check_models():
    print("--- CHECKING AVAILABLE MODELS ---")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"AVAILABLE: {m.name}")
    except Exception as e:
        print(f"❌ AI List Error: {e}")

def test_wp():
    print("--- TESTING WP CONNECTION ---")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    }
    
    try:
        # GET request se check karte hain agar server allow kar raha hai
        response = requests.get(url.replace('/posts', ''), headers=headers, timeout=30)
        print(f"WP Root Status: {response.status_code}")
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    check_models()
    test_wp()
