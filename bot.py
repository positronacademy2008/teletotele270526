import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

print("🛠 [DEBUG] SYSTEM BOOTING UP...")

# --- CONFIGURATION & ENV VARIABLES ---
try:
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
    print("🛠 [DEBUG] ENV Variables Loaded Successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Missing Environment Variables: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)(\s*\[\s*\.\.\.\s*\]\s*$)|(\s*\[\s*…\s*\]\s*$)|(\s*…\s*$)|(\s*\.\.\.\s*$)""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    print(f"🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": True}, timeout=60).raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    print(f"🛠 [DEBUG] Dispatching PHOTO to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=180).raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    print(f"🛠 [DEBUG] Dispatching PDF/DOCUMENT to {channel}...")
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
    print(f"🛠 [DEBUG] last.txt updated with ID: {val}")

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
    print("🛠 [DEBUG] Sanitizing PDF (Removing clickable links)...")
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
        print(f"❌ [DEBUG ERROR] Pikepdf error: {e}")
        return pdf_bytes

def download_asli_pdf_from_telegram():
    print("🛠 [DEBUG] Contacting Telegram Bot API for Raw PDF...")
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        if resp.get("ok") and len(resp["result"]) > 0:
            for update in reversed(resp["result"]):
                node = update.get("message") or update.get("channel_post")
                if node and "document" in node:
                    doc = node["document"]
                    if doc.get("mime_type") == "application/pdf" or doc.get("file_name", "").lower().endswith(".pdf"):
                        print(f"🛠 [DEBUG] PDF found in API buffer. File ID: {doc['file_id']}")
                        path_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={doc['file_id']}"
                        path_resp = requests.get(path_url).json()
                        if path_resp.get("ok"):
                            dl_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path_resp['result']['file_path']}"
                            return requests.get(dl_url, timeout=120).content
    except Exception as e: 
        print(f"❌ [DEBUG ERROR] Telegram API PDF Fetch Failed: {e}")
    print("⚠️ [DEBUG] No raw PDF found in Telegram API.")
    return None

# --- RSS FEED PARSER ---
def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    link = pick("link").strip()
    guid = (pick("guid").strip() or link)

    enc_url, enc_type = None, None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url = m_enc.group(1)
        enc_type = m_enc.group(2)

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)
    desc = re.sub(r"^\[Photo\]\s*", "", desc).strip()
    
    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)
    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()

    return {"guid": guid, "title": title[:80] if title else "Educational Update", "text": combined, "enclosure_url": enc_url, "enclosure_type": enc_type}

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

# --- GROQ AI & WORDPRESS ---
def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("🛠 [DEBUG] Initiating AI Rewrite via Groq...")
    source_content = webpage_text if len(webpage_text) > 100 else telegram_text
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional educational blog writer for Positron Academy. Rewrite the provided data into a comprehensive, detailed, 100% unique, and plagiarism-free article in Hinglish. If the input text contains important references like '(Link: https...)', you MUST seamlessly embed them in your HTML output using <a href='...'> tags. Do NOT include any links related to 'indianaukrihelp.com' or words like 'शिक्षा विभाग समाचार राजस्थान'."},
                {"role": "user", "content": f"Create an original detailed website article based on this information:\n\n{source_content}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5
        )
        print("🛠 [DEBUG] AI Rewrite Successful.")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ [DEBUG ERROR] Groq AI Failed: {e}")
        return telegram_text

def publish_to_wordpress(title, content):
    wp_url = os.environ.get("WP_URL")
    print(f"🛠 [DEBUG] Preparing to POST to WordPress: {wp_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    
    clean_slug = f"update-{int(time.time())}"
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': clean_slug}

    try:
        print("🛠 [DEBUG] Establishing connection to Positron Academy Server...")
        # Added verify=False in case hosting SSL is rejecting python requests
        response = requests.post(wp_url, auth=(os.environ.get("WP_URL"), os.environ.get("WP_PASS")), data=data, headers=headers, timeout=60, verify=False)
        print(f"🛠 [DEBUG] WP Server Responded with Status Code: {response.status_code}")
        
        if response.status_code == 201:
            link = response.json().get("link", "")
            print(f"✅ [DEBUG] WP Post Published at: {link}")
            return link
        else:
            print(f"❌ [DEBUG ERROR] WP Rejection Body: {response.text}")
    except requests.exceptions.Timeout:
        print("❌ [CRITICAL DEBUG] CONNECTION TIMEOUT. Your hosting firewall (Hostinger/Cloudflare) is blocking GitHub's IP address.")
    except Exception as e:
        print(f"❌ [DEBUG ERROR] WordPress POST Exception: {e}")
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    print("🛠 [DEBUG] STEP 1: Setting up channels.")
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    if not channels:
        raise RuntimeError("DEST_CHANNEL is empty.")

    print("🛠 [DEBUG] STEP 2: Checking last.txt.")
    last_guid = read_last()
    print(f"🛠 [DEBUG] Memory state -> Last GUID: {last_guid}")

    print(f"🛠 [DEBUG] STEP 3: Downloading XML from {FEED_URL}")
    try:
        xml = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30).text
        items = parse_all_items(xml)
        print(f"🛠 [DEBUG] Successfully parsed {len(items)} items from feed.")
    except Exception as e:
        print(f"❌ [CRITICAL DEBUG] Failed to fetch RSS: {e}")
        return

    if not items:
        print("❌ [DEBUG] Feed is empty or could not be parsed.")
        return

    print("🛠 [DEBUG] STEP 4: Calculating new items sequence.")
    new_items = []
    if not last_guid:
        print("🛠 [DEBUG] No last.txt found. Fetching ALL items.")
        new_items = items
    else:
        for it in items:
            if it["guid"] == last_guid:
                break
            new_items.append(it)

    if not new_items:
        print("✅ [DEBUG] System is Up To Date. Terminating script.")
        return

    new_items.reverse()
    print(f"📥 [DEBUG] Found {len(new_items)} pending messages to process.")

    for current_item in new_items:
        print(f"\n👉 [DEBUG] ====== PROCESSING ITEM: {current_item['guid']} ======")
        raw_text = current_item['text']
        ctype = (current_item["enclosure_type"] or "").lower()

        # Ad Blocker
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("🚫 [DEBUG] Promotional Ad detected. Skipping.")
            write_last(current_item["guid"])
            continue

        # Keywords Logic
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            print("🛠 [DEBUG] Triggering Competitor Replace Logic...")
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
            current_item["enclosure_url"] = None
            ctype = ""

        # Username Logic
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # Webpage Scraping
        found_links = URL_RE.findall(raw_text)
        webpage_scraped_data = ""
        if found_links:
            primary_link = found_links[0]
            if "indianaukrihelp.com" not in primary_link and not primary_link.startswith("https://t.me/"):
                print(f"🛠 [DEBUG] Scraping external URL: {primary_link}")
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
                        print("🛠 [DEBUG] External URL Scraped successfully.")
                except Exception as e:
                    print(f"⚠️ [DEBUG] Webpage scrape failed: {e}")

        # Processing AI and WP
        ai_final_text = rewrite_with_groq(raw_text, webpage_scraped_data)
        wp_content = ai_final_text
        if current_item["enclosure_url"] and ctype.startswith("image/"):
            wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;">'

        new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)
        
        if new_wp_link:
            print("🛠 [DEBUG] WP published. Constructing Telegram Caption...")
            clean_caption = remove_links(raw_text)
            clean_caption = TRUNC_END_RE.sub("", clean_caption).strip()
            clean_caption = re.sub(r'^(.*?)\s*\n+\1', r'\1', clean_caption, flags=re.S).strip()

            telegram_caption = (
                f"{clean_caption}\n\n"
                f"🌐 {new_wp_link}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            ).strip()

            if current_item["enclosure_url"] and ctype == "application/pdf":
                print("🛠 [DEBUG] Attempting to dispatch PDF...")
                try:
                    pdf = requests.get(current_item["enclosure_url"], timeout=300, verify=False)
                    pdf.raise_for_status()
                    safe_pdf = sanitize_pdf_remove_links(pdf.content)
                    for ch in channels: tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, ch)
                    print("🚀 [SUCCESS] PDF Document dispatched!")
                except Exception as e:
                    print(f"❌ [DEBUG] PDF Failed: {e}. Sending text instead.")
                    for ch in channels: tg_send_text(telegram_caption, ch)
                
            elif current_item["enclosure_url"] and ctype.startswith("image/"):
                print("🛠 [DEBUG] Attempting to dispatch Image...")
                try:
                    img = requests.get(current_item["enclosure_url"], timeout=180, verify=False)
                    img.raise_for_status()
                    for ch in channels: tg_send_photo_bytes(img.content, telegram_caption, ch)
                    print("🚀 [SUCCESS] Image dispatched!")
                except:
                    for ch in channels: tg_send_text(telegram_caption, ch)
                
            else:
                print("🛠 [DEBUG] Dispatching pure Text...")
                for ch in channels: tg_send_text(telegram_caption, ch)
                print("🚀 [SUCCESS] Text dispatched!")

            write_last(current_item["guid"])
        else:
            print("❌ [CRITICAL] WordPress completely failed. Halting batch loop to protect sequence.")
            break
        
        time.sleep(3)

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings() # Disables SSL warnings if WP server rejects certificates
    main()
