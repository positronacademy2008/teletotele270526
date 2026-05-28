import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# --- CONFIGURATION & ENV VARIABLES ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"] # Comma-separated: @ch1,@ch2
FEED_URL = os.environ["FEED_URL"]          # Source Telegram Channel Username/Link
LAST_FILE = "last.txt"

# 🔥 AAPKE FOLLOW LINKS (Aap yahan se links change bhi kar sakte hain)
FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/topgkguru"
FOLLOW_LINE_WA = "📢 Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"

# Setup Groq AI Client
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Links clean karne ke liye Regex
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
        "disable_web_page_preview": True
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

# --- ORIGINAL PIKEPDF LINK SANITIZER ---
def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    print("🧹 Sanitizing PDF: Removing internal/external clickable links...")
    try:
        src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        for page in src.pages:
            annots = page.get("/Annots", None)
            if not annots: continue
            new_annots = []
            for a in annots:
                try:
                    obj = a.get_object()
                except Exception: continue
                if "/A" in obj: del obj["/A"]
                if "/AA" in obj: del obj["/AA"]
                if "/Dest" in obj: del obj["/Dest"]
                if obj.get("/Subtype", None) == pikepdf.Name("/Link"): continue
                new_annots.append(a)
            if new_annots:
                page["/Annots"] = pikepdf.Array(new_annots)
            else:
                if "/Annots" in page: del page["/Annots"]
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except Exception as e:
        print(f"❌ Pikepdf error during sanitization: {e}")
        return pdf_bytes

# --- 🔥 REAL BOT API ADVANCED PDF GRABBER ---
def download_asli_pdf_from_telegram():
    """
    Telegram getUpdates long polling se seedhe asli binary PDF download 
    karega taaki file corrupt na ho.
    """
    print("⏳ Fetching original PDF binary from Telegram Bot API updates...")
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        if resp.get("ok") and len(resp["result"]) > 0:
            # Piche se search karenge latest update ke liye
            for update in reversed(resp["result"]):
                message_node = update.get("message") or update.get("channel_post")
                if message_node and "document" in message_node:
                    doc = message_node["document"]
                    if doc.get("mime_type") == "application/pdf" or doc.get("file_name", "").lower().endswith(".pdf"):
                        file_id = doc["file_id"]
                        
                        # Get File Path
                        path_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
                        path_resp = requests.get(path_url).json()
                        if path_resp.get("ok"):
                            file_path = path_resp["result"]["file_path"]
                            
                            # Download Asli File Stream
                            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                            print(f"🎯 Downloading raw PDF from: {download_url}")
                            file_data = requests.get(download_url, timeout=120).content
                            return file_data
        print("⚠️ No raw PDF attachment found directly inside recent Bot API buffer.")
    except Exception as e:
        print(f"❌ Real PDF Grabber Error: {e}")
    return None

# --- TELEGRAM CHANNEL WEB PREVIEW SCRAPER ---
def fetch_telegram_channel_messages():
    username = FEED_URL.strip()
    if "t.me/" in username:
        username = username.split("t.me/")[-1]
    username = username.split("/")[0].replace("@", "").strip()
    
    scrape_url = f"https://t.me/s/{username}"
    print(f"⏳ Scraping Source Telegram Channel Preview: {scrape_url}")
    
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
        title = lines[0] if lines else "New Educational Update"
        
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

# --- GROQ AI REWRITER ENGINE ---
def rewrite_with_groq(text: str) -> str:
    print("⏳ Rewriting text via Groq AI (Active Model: llama-3.1-8b-instant)...")
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a senior professional educational content writer for Positron Academy. Rewrite the provided announcement text to make it 100% unique, plagiarism-free, and clean for a website post. Write in an engaging mix of Hindi and English (Hinglish). Do NOT include any external URLs, links, or original group credit names."
                },
                {"role": "user", "content": f"Transform this update into an original website post body:\n\n{text}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}. Using fallback.")
        return text

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print("⏳ Creating Page on WordPress Website...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    headers = {
        'User-Agent': 'Mozilla/5.0',
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
            print(f"❌ WP Status Error: {response.status_code}")
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
        print("⚠️ No valid data extracted from source channel preview.")
        return

    # Sirf absolute list ka aakhri item (latest) uthao
    latest_item = items[-1]
    
    if last_guid and latest_item["guid"] == last_guid:
        print(f"✅ Latest post ({latest_item['guid']}) is already up to date. No action needed.")
        return

    print(f"📥 Processing ONLY the absolute latest message ID: {latest_item['guid']}")
    
    # Clean old links from text for AI processing
    clean_source_msg_text = remove_links(latest_item["text"])
    
    # Step 2: Groq AI Rewrite for website content
    ai_final_text = rewrite_with_groq(clean_source_msg_text, "")
    
    wp_content = ai_final_text
    if latest_item["enclosure_url"]:
        wp_content += f'<br><br><img src="{latest_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

    # Step 3: WordPress Publisher
    new_page_link = publish_to_wordpress(latest_item["title"], wp_content)
    
    if new_page_link:
        # 🔥 Step 4: MODIFIED CAPTION STRUCTURING WITH FOLLOW LINKS
        telegram_caption = (
            f"{clean_source_msg_text}\n\n"
            f"🌐 **Poori details website par dekhein:**\n{new_page_link}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{FOLLOW_LINE_TG}\n"
            f"{FOLLOW_LINE_WA}"
        ).strip()

        # 🔥 Step 5: ADVANCED REAL PDF CHECK & ROUTING
        # Pehle check karega agar direct dynamic buffer se binary PDF milta hai
        pdf_content_bytes = download_asli_pdf_from_telegram()
        
        if pdf_content_bytes:
            try:
                # Purane clickable links hatane ke liye Sanitizer chalega
                safe_pdf_bytes = sanitize_pdf_remove_links(pdf_content_bytes)
                
                # Send authentic PDF to all channels with our follow caption
                for ch in channels:
                    tg_send_document_bytes(safe_pdf_bytes, "official_circular.pdf", telegram_caption, ch)
                print("🚀 SUCCESS: Authentic PDF Document + Follow Links sent to your channels!")
            except Exception as e:
                print(f"❌ PDF processing crashed: {e}. Switching to media fallback.")
                pdf_content_bytes = None

        # Fallback logic agar post mein direct PDF nahi tha
        if not pdf_content_bytes:
            if latest_item["enclosure_url"]:
                try:
                    img = requests.get(latest_item["enclosure_url"], timeout=180)
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                    print("📢 Photo + Follow Links caption forwarded successfully!")
                except Exception as e:
                    print(f"⚠️ Media fallback triggered text layout: {e}")
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
                print("📢 Pure Text + Follow Links forwarded successfully!")
        
        print(f"🚀 TASK COMPLETION: Saved state.")
        write_last(latest_item["guid"])
    else:
        print("❌ Workflow stopped due to WordPress error.")

if __name__ == "__main__":
    main()
