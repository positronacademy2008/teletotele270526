import os, re, time, hashlib, requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# --- CONFIGURATION (GitHub Secrets se uthayega) ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow us")
WP_URL = os.environ["WP_URL"]  # https://positronacademy.in/wp-json/wp/v2/posts
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)

def publish_to_wp(title, content):
    data = {'title': title, 'content': content, 'status': 'publish'}
    response = requests.post(WP_URL, auth=(WP_USER, WP_PASS), json=data)
    if response.status_code == 201:
        return response.json().get('link') # Ye aapki website ka naya link hai
    return None

def rewrite_with_ai(raw_text):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Rewrite this content for an educational blog. No source links. Language: Hindi/Hinglish. Use HTML tags for formatting. Text: {raw_text[:4000]}"
    return model.generate_content(prompt).text.replace("```html", "").replace("```", "")

def process_news(url):
    try:
        # Website ka content fetch karo
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        soup = BeautifulSoup(res.content, 'html.parser')
        title = soup.title.string if soup.title else "New Educational Update"
        raw_text = " ".join([p.text for p in soup.find_all('p')])
        
        # AI se naya content likhwao
        new_content = rewrite_with_ai(raw_text)
        
        # WordPress par publish karo
        return publish_to_wp(title, new_content)
    except Exception as e:
        print(f"Error processing {url}: {e}")
        return None

def main():
    # RSS Feed se latest message uthao
    xml = requests.get(FEED_URL, timeout=90).text
    # Yahan simple regex se link extract karo (jo message ke andar hai)
    urls = re.findall(r'https?://[^\s<>"]+', xml)
    # Pehla external link jo telegram ka nahi hai
    target_url = next((u for u in urls if "t.me" not in u and "telegram.me" not in u), None)

    if target_url:
        new_link = process_news(target_url)
        if new_link:
            msg = f"🔥 New Update\n\nEk naya educational update aaya hai!\n\n🔗 Pura padhein: {new_link}\n\n━━━━━━━━━━━━━━\n{FOLLOW_LINE}"
            for ch in DEST_CHANNELS.split(","):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
    
if __name__ == "__main__":
    main()
