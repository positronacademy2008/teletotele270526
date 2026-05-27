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

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def publish_to_wp(title, content):
    if not all([WP_URL, WP_USER, WP_PASS]):
        print(f"DEBUG: Missing WP_URL={bool(WP_URL)}, WP_USER={bool(WP_USER)}, WP_PASS={bool(WP_PASS)}")
        return None
    data = {'title': title, 'content': content, 'status': 'publish'}
    response = requests.post(WP_URL, auth=(WP_USER, WP_PASS), json=data)
    if response.status_code == 201:
        return response.json().get('link')
    else:
        print(f"WP Error: {response.status_code} - {response.text}")
        return None

def rewrite_with_ai(raw_text):
    if not GEMINI_API_KEY: return "<p>AI API Key missing.</p>"
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Rewrite this news for an educational blog. Language: Hindi/Hinglish. Use HTML tags. Text: {raw_text[:4000]}"
        return model.generate_content(prompt).text.replace("```html", "").replace("```", "")
    except Exception as e:
        print(f"AI Error: {e}")
        return "<p>AI generation failed.</p>"

def process_news(url):
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        soup = BeautifulSoup(res.content, 'html.parser')
        title = soup.title.string if soup.title else "New Update"
        raw_text = " ".join([p.text for p in soup.find_all('p')])
        
        content = rewrite_with_ai(raw_text)
        return publish_to_wp(title, content)
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return None

def main():
    if not FEED_URL: return
    xml = requests.get(FEED_URL, timeout=90).text
    urls = re.findall(r'https?://[^\s<>"]+', xml)
    target_url = next((u for u in urls if "t.me" not in u and "telegram.me" not in u), None)

    if target_url:
        new_link = process_news(target_url)
        if new_link:
            msg = f"🔥 New Update\n\n🔗 Read here: {new_link}"
            for ch in DEST_CHANNEL.split(","):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
    
if __name__ == "__main__":
    main()
