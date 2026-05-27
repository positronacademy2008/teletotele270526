import os, requests
import google.generativeai as genai
from requests.adapters import HTTPAdapter

# Setup
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Model Try/Except Logic
def get_model():
    models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
    for m in models:
        try:
            return genai.GenerativeModel(m)
        except: continue
    return None

model = get_model()

def publish_to_wp(title, content):
    session = requests.Session()
    # Firewall ko bypass karne ke लिए Session Headers
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    })
    
    try:
        response = session.post(
            os.environ.get("WP_URL"), 
            auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")), 
            json={'title': title, 'content': content, 'status': 'publish'},
            timeout=90
        )
        print(f"DEBUG: Status {response.status_code}")
        return response.status_code == 201
    except Exception as e:
        print(f"WP Error: {e}")
        return False

# Execution
if model:
    try:
        print("Testing AI...")
        res = model.generate_content("Say OK")
        print("AI OK. Testing WP...")
        publish_to_wp("Bot Test", "Success")
    except Exception as e:
        print(f"Critical: {e}")
else:
    print("No valid AI model found.")
