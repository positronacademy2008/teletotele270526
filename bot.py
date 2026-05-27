import os, requests, time
import google.generativeai as genai

# API key configure
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    auth = (os.environ.get("WP_USER"), os.environ.get("WP_PASS"))
    # Firewall ko bypass karne ke liye headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        # Request bhejte waqt delay taaki firewall ko lage ki ye human traffic hai
        time.sleep(10) 
        response = requests.post(url, auth=auth, data=data, headers=headers, timeout=120)
        return response.status_code == 201
    except Exception as e:
        print(f"WP Error: {e}")
        return False

# Main
if __name__ == "__main__":
    try:
        print("⏳ Waiting for API cooldown...")
        time.sleep(60) # 1 minute ka cooldown
        ai_response = model.generate_content("Science Update: Artificial Intelligence is evolving fast.")
        
        if publish_to_wp("AI Science Update", ai_response.text):
            print("🚀 SUCCESS!")
        else:
            print("🛑 FAILED: Please check Hosting Support response.")
    except Exception as e:
        print(f"❌ Quota Issue (Wait 24hrs): {e}")
