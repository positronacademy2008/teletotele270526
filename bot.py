import os, requests
import google.generativeai as genai

# Setup
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-pro') # Change kiya

def publish_to_wp(title, content):
    # Firewall ko dhokha dene ke liye Real Browser ki tarah headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://google.com/'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        # Authentication aur data bhej rahe hain
        response = requests.post(
            os.environ.get("WP_URL"), 
            auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")), 
            json=data, 
            headers=headers, 
            timeout=90
        )
        print(f"DEBUG: Response {response.status_code} - {response.text}")
        return response.status_code == 201
    except Exception as e:
        print(f"WP Publish Exception: {e}")
        return False

# AI aur WP Test
try:
    print("Testing AI...")
    model.generate_content("Hi")
    print("AI OK. Testing WP...")
    if publish_to_wp("Test", "Bot is active"):
        print("✅ SUCCESS: WordPress Connected!")
    else:
        print("❌ WP Publish Failed.")
except Exception as e:
    print(f"❌ Critical Error: {e}")
