import os, requests
import google.generativeai as genai

# Setup
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# Aapka model jo quota mein best chal raha hai
model = genai.GenerativeModel('gemini-2.0-flash')

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    auth = (os.environ.get("WP_USER"), os.environ.get("WP_PASS"))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}
    
    response = requests.post(url, auth=auth, data=data, headers=headers, timeout=90)
    return response.status_code == 201

if __name__ == "__main__":
    try:
        # Telegram message ki jagah apna content yahan fetch karein
        msg = "Science News: AI is transforming education at Positron Academy."
        
        # AI se content banwayein
        ai_response = model.generate_content(f"Create a short blog post: {msg}")
        
        # WordPress par bhejein
        if publish_to_wp("Latest Science Update", ai_response.text):
            print("🚀 SUCCESS: Bot is fully operational!")
        else:
            print("❌ WP Publish Failed.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
