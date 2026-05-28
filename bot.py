import os, requests, time
import google.generativeai as genai

# Setup
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash-lite')

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    auth = (os.environ.get("WP_USER"), os.environ.get("WP_PASS"))
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = {'title': title, 'content': content, 'status': 'publish'}
    return requests.post(url, auth=auth, data=data, headers=headers, timeout=60).status_code == 201

if __name__ == "__main__":
    msg = "Science News: AI batch launched." # Simple rakhna hai
    
    try:
        # Prompt ko chhota rakho taaki tokens kam use hon
        prompt = f"Summarize this in 30 words: {msg}"
        response = model.generate_content(prompt)
        
        if publish_to_wp("Update", response.text):
            print("🚀 SUCCESS!")
        else:
            print("❌ WP Failed.")
    except Exception as e:
        print(f"❌ Quota Error: {e}")
