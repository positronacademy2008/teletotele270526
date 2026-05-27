import os, re, time, requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# Load Secrets
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DEST_CHANNELS = os.environ.get("DEST_CHANNEL", "")
FEED_URL = os.environ.get("FEED_URL")
WP_URL = os.environ.get("WP_URL") 
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def publish_to_wp(title, content):
    if not all([WP_URL, WP_USER, WP_PASS]):
        return None
    data = {'title': title, 'content': content, 'status': 'publish'}
    # WP API request with higher timeout
    response = requests.post(WP_URL, auth=(WP_USER, WP_PASS), json=data, timeout=90)
    return response.json().get('link') if response.status_code == 201 else None

def rewrite_with_ai(raw_text):
    # Text ko chhota kiya taaki AI jaldi respond kare
    chunk = raw_text[:3000]
    try:
        response = model.generate_content(f"Rewrite this for an educational blog in Hindi/Hinglish. Use simple HTML. Content: {chunk}")
        return response.text.replace("```html", "").replace("```", "")
    except Exception as e:
        print(f"AI Exception: {e}")
        return "<p>Content generation failed locally.</p>"

def main():
    if not FEED_URL: return
    try:
        xml = requests.get(FEED_URL, timeout=120).text
        urls = re.findall(r'https?://[^\s<>"]+', xml)
        target_url = next((u for u in urls if "t.me" not in u and "telegram.me" not in u), None)

        if target_url:
            # Website content fetch
            res = requests.get(target_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
            soup = BeautifulSoup(res.content, 'html.parser')
            title = soup.title.string if soup.title else "New Educational Post"
            
            # Content cleaning
            paragraphs = [p.text for p in soup.find_all('p') if len(p.text) > 20]
            raw_text = " ".join(paragraphs)
            
            # AI Rewrite
            final_content = rewrite_with_ai(raw_text)
            
            # WP Publish
            new_link = publish_to_wp(title, final_content)
            
            if new_link:
                msg = f"🔥 New Update\n\n🔗 Pura padhein: {new_link}"
                for ch in DEST_CHANNELS.split(","):
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
    except Exception as e:
        print(f"Main Error: {e}")

if __name__ == "__main__":
    main()
