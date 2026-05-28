import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# --- CONFIGURATION & ENV VARIABLES ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"] # Comma-separated: @ch1,@ch2
FEED_URL = os.environ["FEED_URL"]          # Source Telegram Channel
LAST_FILE = "last.txt"

# Setup Groq AI Client
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Links detect karne aur hatane ke liye Regex
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

# --- SENDER FUNCTIONS ---
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

# --- UTILITIES ---
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

# --- 🔥 DEEP WEBPAGE CONTENT SCRAPER ---
def fetch_external_link_data(url: str) -> str:
    """
    Message ke andar jo original link hai, ye function us website par 
    jaakar uska poora readable text utha laega.
    """
    # Telegram ke internal promotion links ko skip karega
    if "t.me/" in url or "telegram.me/" in url:
        return ""
        
    print(f"🌐 Deep Scraping Original Link Content: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=25)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # फालतू chizein jaise scripts aur styles hatao
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.extract()
                
            # Paragraphs (<p>) se text nikalo
            paragraphs = soup.find_all('p')
            page_text = "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
            
            if not page_text:
                page_text = soup.get_text(separator="\n")
                
            # Extra clean spaces
            lines = (line.strip() for line in page_text.splitlines())
            clean_text = '\n'.join(line for line in lines if line)
            return clean_text[:3500] # Tokens optimize rakhne ke liye length capped
    except Exception as e:
        print(f"⚠️ Link data fetch error: {e}")
    return ""

# --- TELEGRAM CHANNEL SCRAPER ---
def fetch_telegram_channel_messages():
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
        guid = block.get('data-post')
        if not guid: continue
        
        text_block = block.find('div', class_='tgme_widget_message_text')
        if not text_block: continue
        
        raw_text = text_block.get_text(separator='\n').strip()
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        title = lines[0] if lines else "New Update"
        
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

# --- NAYA GROQ AI REWRITER ENGINE ---
def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("⏳ Rewriting content via Groq AI (Active Model: llama-3.1-8b-instant)...")
    
    # Dono content ko mix karke context build karenge
    combined_input = f"Telegram Message Info:\n{telegram_text}\n\nDeep Webpage Detailed Data:\n{webpage_text}"
    
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a senior professional educational content writer for Positron Academy. Your task is to combine the short Telegram message snapshot and the deep scraped web data into one comprehensive, 100% unique, plagiarism-free blog post. Write in a brilliant, informative mix of Hindi and English (Hinglish). Do NOT echo old URLs or credit tags."
                },
                {"role": "user", "content": f"Create an original, copyright-free detailed article from this compiled source content:\n\n{combined_input}"}
            ],
            model="llama-3.1-8b-instant", # Naya functional model update
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}. Falling back to filtered original message text.")
        return telegram_text

# --- WORDPRESS PUBLISHER ---
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
            print(f"✅ WordPress Page Created Successfully: {wp_link}")
            return wp_link
        else:
            print(f"❌ WP Status Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
        return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    print(f"DEBUG: Last GUID in database memory: {last_guid}")

    items = fetch_telegram_channel_messages()
    if not items:
        print("⚠️ No valid data extracted from source channel.")
        return

    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            break
        new_items.append(it)

    if not new_items:
        print("✅ No new posts to process.")
        return

    new_items.reverse() # Restore sequence flow

    for it in new_items:
        print(f"📥 Processing Update ID: {it['guid']}")
        
        # 1. Message se pehle link dhoondo aur uska internal website data fetch karo
        found_links = URL_RE.findall(it["text"])
        webpage_scraped_data = ""
        
        if found_links:
            # Pehle link ka content download karenge
            webpage_scraped_data = fetch_external_link_data(found_links[0])
            
        # 2. Purane links ko saaf karo content se
        clean_source_msg_text = remove_links(it["text"])
        
        # 3. Groq AI se dynamic merging aur unique rewrite karwao
        ai_final_text = rewrite_with_groq(clean_source_msg_text, webpage_scraped_data)
        
        # WP body draft with image attachments
        wp_content = ai_final_text
        if it["enclosure_url"]:
            wp_content += f'<br><br><img src="{it["enclosure_urlスト"]}" alt="Update Image" style="max-width:100%;">'

        # 4. Post on WordPress & Get your own new website page link
        new_page_link = publish_to_wordpress(it["title"], wp_content)
        
        if new_page_link:
            # 5. Build final output message for your New Telegram Group
            telegram_caption = (
                f"📢 **New Educational Update**\n\n"
                f"{ai_final_text}\n\n"
                f"🌐 **Poori details aur official circular yahan download karein:**\n{new_page_link}"
            ).strip()

            # Forward output payload to targets
            if it["enclosure_url"]:
                try:
                    img = requests.get(it["enclosure_url"], timeout=180)
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                except Exception as e:
                    print(f"⚠️ Photo fallback text routing triggered: {e}")
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
            
            print(f"🚀 SUCCESS: Content deep analyzed, published to WP, and forwarded to group!")
            write_last(it["guid"])
        else:
            print("❌ Workflow stopped due to WordPress error.")
            break

        time.sleep(4)

if __name__ == "__main__":
    main()
