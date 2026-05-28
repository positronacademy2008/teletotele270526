import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# --- CONFIGURATION & ENV VARIABLES ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"] # Comma-separated: @ch1,@ch2
FEED_URL = os.environ["FEED_URL"]          # Source Telegram Channel link/username
LAST_FILE = "last.txt"

# Setup Groq AI Client
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Links hatane ke liye Regex (Website, t.me links sab saaf karega)
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

# --- NEW TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": channel,
        "text": text[:3900],
        "disable_web_page_preview": False
    }, timeout=60).raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=180).raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=300).raise_for_status()

# --- TEXT & FILE UTILITIES ---
def read_last():
    if os.path.exists(LAST_FILE):
        return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def normalize(s: str) -> str:
    s = TRUNC_END_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s

# --- DIRECT TELEGRAM CHANNEL HTML SCRAPER ---
def fetch_telegram_channel_messages():
    # Username extract karega chahe link ho ya simple text
    username = FEED_URL.strip()
    if "t.me/" in username:
        username = username.split("t.me/")[-1]
    username = username.split("/")[0].replace("@", "").strip()
    
    scrape_url = f"https://t.me/s/{username}"
    print(f"⏳ Scraping Source Telegram Channel: {scrape_url}")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(scrape_url, headers=headers, timeout=60)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    msg_blocks = soup.find_all('div', class_='tgme_widget_message')
    items = []
    
    for block in msg_blocks:
        guid = block.get('data-post') # Format: channel_name/123
        if not guid: continue
        
        text_block = block.find('div', class_='tgme_widget_message_text')
        if not text_block: continue
        
        raw_text = text_block.get_text(separator='\n').strip()
        
        # Pehli line ko title maan lete hain WordPress ke liye
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        title = lines[0] if lines else "New Update"
        
        # Image check karega agar post mein photo hai
        img_url = None
        photo_wrap = block.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_wrap and 'style' in photo_wrap.attrs:
            style_text = photo_wrap['style']
            img_m = re.search(r"url\(['\"]?(.*?)['\"]?\)", style_text)
            if img_m:
                img_url = img_m.group(1)
                
        items.append({
            "guid": guid,
            "title": title[:80],
            "text": raw_text,
            "enclosure_url": img_url
        })
        
    return items

# --- GROQ AI COPYRIGHT-FREE REWRITER ---
def rewrite_with_groq(text: str) -> str:
    print("⏳ Rewriting text via Groq AI to make it copyright-free...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an expert educational content writer for Positron Academy. Rewrite the provided update to make it 100% unique, plagiarism-free, and highly engaging. Use a clean and professional mix of Hindi and English (Hinglish). Do not output any links or promotional credits."},
                {"role": "user", "content": f"Transform this content into an original blog post:\n\n{text}"}
            ],
            model="llama3-8b-8192",
            temperature=0.6
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}. Using original clean text.")
        return text

# --- WORDPRESS FIREWALL BYPASS PUBLISHER ---
def publish_to_wordpress(title, content):
    print("⏳ Creating Page on WordPress Website...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}

    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        if response.status_code == 201:
            wp_link = response.json().get("link", "")
            print(f"✅ WordPress Page Created: {wp_link}")
            return wp_link
        else:
            print(f"❌ WP Status Error: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
        return None

# --- MAIN ENGINE CONTROLLER ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    print(f"DEBUG: Last GUID in memory: {last_guid}")

    # Step 1: Fetch source channel messages via Scraper
    items = fetch_telegram_channel_messages()
    if not items:
        print("⚠️ No valid text messages found in source channel.")
        return

    # Filter out old messages using last_guid
    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            break
        new_items.append(it)

    if not new_items:
        print("✅ No new posts found in the source channel.")
        return

    # Oldest first sequence restore
    new_items.reverse()

    for it in new_items:
        print(f"📥 Processing message ID: {it['guid']}")
        
        # 🔥 CRITICAL STEP: Purane saare weblinks message se remove karo
        clean_source_text = remove_links(it["text"])
        
        # Step 2: Groq AI Rewrite (Copyright free strategy)
        ai_clean_text = rewrite_with_groq(clean_source_text)
        
        # Prepare content body for WordPress Page
        wp_content = ai_clean_text
        if it["enclosure_url"]:
            wp_content += f'<br><br><img src="{it["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

        # Step 3: Publish to Website to get New Link
        new_page_link = publish_to_wordpress(it["title"], wp_content)
        
        if new_page_link:
            # Step 4: Final text structure for the New Telegram Group
            telegram_caption = (
                f"📢 **New Educational Update**\n\n"
                f"{ai_clean_text}\n\n"
                f"🌐 **Poori details aur official tables website par dekhein:**\n{new_page_link}"
            ).strip()

            # Step 5: Route to new group with image if available
            if it["enclosure_url"]:
                try:
                    img = requests.get(it["enclosure_url"], timeout=180)
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                except Exception as e:
                    print(f"⚠️ Image download error: {e}. Sending text instead.")
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
            
            print(f"🚀 SUCCESS: Processed and forwarded to new group!")
            write_last(it["guid"])
        else:
            print("❌ WordPress publishing failed. Stopping batch.")
            break

        time.sleep(3)

if __name__ == "__main__":
    main()
