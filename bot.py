import os, re, html, time, io
import requests
import urllib3
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# 🛡️ SSL Warnings Disable (Firewall bypass ke liye zaroori)
urllib3.disable_warnings()

# --- CONFIGURATION & ENV VARIABLES ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
LAST_FILE = "last.txt"

FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/RAJASTHAN_TODAY"
FOLLOW_LINE_WA = "📢 Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"

client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)(\s*\[\s*\.\.\.\s*\]\s*$)|(\s*\[\s*…\s*\]\s*$)|(\s*…\s*$)|(\s*\.\.\.\s*$)""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": True}, timeout=60).raise_for_status()

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

def strip_tags(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<.*?>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    print("🧹 Sanitizing PDF...")
    try:
        src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        for page in src.pages:
            annots = page.get("/Annots", None)
            if not annots: continue
            new_annots = []
            for a in annots:
                try:
                    obj = a.get_object()
                    if "/A" in obj: del obj["/A"]
                    if "/AA" in obj: del obj["/AA"]
                    if "/Dest" in obj: del obj["/Dest"]
                    if obj.get("/Subtype", None) == pikepdf.Name("/Link"): continue
                    new_annots.append(a)
                except Exception: continue
            if new_annots:
                page["/Annots"] = pikepdf.Array(new_annots)
            else:
                if "/Annots" in page: del page["/Annots"]
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except Exception as e:
        print(f"❌ Pikepdf error: {e}")
        return pdf_bytes

def download_asli_pdf_from_telegram():
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        if resp.get("ok") and len(resp["result"]) > 0:
            for update in reversed(resp["result"]):
                node = update.get("message") or update.get("channel_post")
                if node and "document" in node:
                    doc = node["document"]
                    if doc.get("mime_type") == "application/pdf" or doc.get("file_name", "").lower().endswith(".pdf"):
                        path_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={doc['file_id']}"
                        path_resp = requests.get(path_url).json()
                        if path_resp.get("ok"):
                            dl_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path_resp['result']['file_path']}"
                            return requests.get(dl_url, timeout=120).content
    except Exception: pass
    return None

def fetch_telegram_channel_messages():
    username = FEED_URL.strip().replace("https://t.me/s/", "").replace("@", "")
    scrape_url = f"https://t.me/s/{username}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(scrape_url, headers=headers, timeout=60, verify=False)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    items = []
    for block in soup.find_all('div', class_='tgme_widget_message'):
        guid = block.get('data-post')
        text_block = block.find('div', class_='tgme_widget_message_text')
        if not guid or not text_block: continue
        
        raw_text = text_block.get_text(separator='\n').strip()
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        title = lines[0] if lines else "Update"
        
        img_url = None
        photo_wrap = block.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_wrap and 'style' in photo_wrap.attrs:
            m = re.search(r"url\(['\"]?(.*?)['\"]?\)", photo_wrap['style'])
            if m: img_url = m.group(1)
                
        doc_url = None
        doc_anchor = block.find('a', class_=lambda x: x and 'document' in x)
        if doc_anchor and doc_anchor.get('href'):
            doc_url = doc_anchor['href']
                
        items.append({"guid": guid, "title": title[:80], "text": raw_text, "enclosure_url": img_url, "doc_url": doc_url})
    return items

def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("⏳ Rewriting content via Groq AI...")
    source_content = webpage_text if len(webpage_text) > 100 else telegram_text
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a professional educational blog writer for Positron Academy. Rewrite the provided data into a comprehensive, detailed, 100% unique, and plagiarism-free article in Hinglish. If the input text contains important references like '(Link: https...)', you MUST seamlessly embed them in your HTML output using <a href='...'> tags. Do NOT include any links related to 'indianaukrihelp.com' or words like 'शिक्षा विभाग समाचार राजस्थान'."
                },
                {"role": "user", "content": f"Create an original detailed website article based on this information:\n\n{source_content}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}")
        return telegram_text

def publish_to_wordpress(title, content):
    print("⏳ Creating Page on WordPress Website...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    # 🛡️ THE WINNING STEALTH HEADERS
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive'
    }
    
    clean_slug = f"post-{int(time.time())}"
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': clean_slug}

    try:
        # verify=False is critical to bypass SSL blocks from the hosting
        response = requests.post(url, auth=(user, passwd), data=data, headers=headers, timeout=30, verify=False)
        if response.status_code == 201:
            print("✅ WordPress Publish Success!")
            return response.json().get("link", "")
        else:
            print(f"❌ WP Error: {response.text}")
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    
    items = fetch_telegram_channel_messages()
    if not items:
        print("⚠️ No valid data extracted from source channel preview.")
        return

    last_guid = read_last()
    print(f"🔍 Database Last GUID: {last_guid}")

    new_items = []
    if not last_guid:
        print("📝 last.txt is EMPTY. Only processing the absolute LATEST message.")
        new_items = [items[-1]] 
    else:
        found_idx = -1
        for i, it in enumerate(items):
            if it["guid"] == last_guid:
                found_idx = i
                break
        if found_idx != -1:
            new_items = items[found_idx + 1 :]
        else:
            print("⚠️ last_guid NOT FOUND. Channel changed? Resetting sequence...")
            new_items = [items[-1]]

    if not new_items:
        print("✅ System is Up To Date. No new messages.")
        return

    print(f"📥 Found {len(new_items)} pending messages to process!")

    for current_item in new_items:
        print(f"\n👉 Processing ID: {current_item['guid']}")
        raw_text = current_item["text"]
        ctype = "application/pdf" if current_item.get("doc_url") and ".pdf" in current_item["doc_url"].lower() else ""
        
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("🚫 Promotional Ad detected. Skipping.")
            write_last(current_item["guid"])
            continue

        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
            current_item["enclosure_url"] = None
            current_item["doc_url"] = None
            ctype = ""

        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)
        current_item["text"] = raw_text

        found_links = URL_RE.findall(raw_text)
        webpage_scraped_data = ""
        
        if found_links:
            primary_link = found_links[0]
            if not ("t.me/" in primary_link or "telegram.me/" in primary_link):
                try:
                    resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            href = a['href']
                            if "indianaukrihelp.com" not in href and href.startswith("http"):
                                a.replace_with(f"{a.get_text()} (Link: {href})")
                        for element in soup(["script", "style", "nav", "footer", "header"]):
                            element.extract()
                        page_text = soup.get_text(separator="\n").replace("indianaukrihelp.com", "").replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
                        lines = (line.strip() for line in page_text.splitlines())
                        webpage_scraped_data = '\n'.join(line for line in lines if line)[:3500]
                except Exception: pass

        ai_final_text = rewrite_with_groq(raw_text, webpage_scraped_data)
        wp_content = ai_final_text
        if current_item["enclosure_url"] and not current_item.get("doc_url"):
            wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

        new_page_link = publish_to_wordpress(current_item["title"][:50], wp_content)
        
        if new_page_link:
            clean_root_message = remove_links(raw_text)
            clean_root_message = TRUNC_END_RE.sub("", clean_root_message).strip()
            clean_root_message = re.sub(r'^(.*?)\s*\n+\1', r'\1', clean_root_message, flags=re.S).strip()
            
            telegram_caption = (
                f"{clean_root_message}\n\n"
                f"🌐 {new_page_link}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            ).strip()

            if current_item.get("doc_url") or ctype == "application/pdf":
                pdf_bytes = download_asli_pdf_from_telegram()
                if pdf_bytes:
                    safe_pdf_bytes = sanitize_pdf_remove_links(pdf_bytes)
                    for ch in channels: tg_send_document_bytes(safe_pdf_bytes, "official_circular.pdf", telegram_caption, ch)
                else:
                    for ch in channels: tg_send_text(telegram_caption, ch)
            elif current_item["enclosure_url"]:
                try:
                    img = requests.get(current_item["enclosure_url"], timeout=180, verify=False)
                    for ch in channels: tg_send_photo_bytes(img.content, telegram_caption, ch)
                except:
                    for ch in channels: tg_send_text(telegram_caption, ch)
            else:
                for ch in channels: tg_send_text(telegram_caption, ch)
            
            print(f"✅ Sab badhiya raha. last.txt update kar raha hu...")
            write_last(current_item["guid"])
        else:
            print("❌ WordPress failed. Stopping batch to prevent sequence break.")
            break

        time.sleep(3)

if __name__ == "__main__":
    main()
