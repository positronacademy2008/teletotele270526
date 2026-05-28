import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI
from urllib.parse import urljoin

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

# --- REQUIREMENT 4: USERNAME REPLACER ---
def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

# --- PDF SANITIZER ---
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

# --- 🔥 RSS FEED PARSER (Restored your Original Gold Standard) ---
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

    return {
        "guid": guid,
        "title": title[:80] if title else "Educational Update",
        "text": combined,
        "enclosure_url": enc_url,
        "enclosure_type": enc_type
    }

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

# --- GROQ AI REWRITER ENGINE ---
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

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print("⏳ Creating Page on WordPress Website...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    # 🔥 REQUIREMENT 2: SUPER SHORT URL SLUG (Jaise: post-171804)
    clean_slug = f"post-{int(time.time())}"
    
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': clean_slug}

    try:
        response = requests.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        if response.status_code == 201:
            return response.json().get("link", "")
        else:
            print(f"❌ WP Status Code: {response.status_code}")
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    print("🚀 Starting Telegram Auto Post Script...")
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    print(f"📖 Database Last GUID: {last_guid}")
    
    print(f"⏳ Fetching RSS Feed from: {FEED_URL}")
    try:
        xml = requests.get(FEED_URL, timeout=90).text
        items = parse_all_items(xml)
        print(f"✅ RSS Feed Fetched Successfully! Total parsed items: {len(items)}")
    except Exception as e:
        print(f"❌ Failed to fetch/parse RSS Feed: {e}")
        return

    if not items:
        print("⚠️ No valid items found in the XML feed.")
        return

    # 🔥 BATCH PROCESSING: Sirf naye items uthao
    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            print(f"📍 Hit previously processed GUID: {last_guid}")
            break
        new_items.append(it)

    if not new_items:
        print("✅ System is Up To Date. No new messages.")
        return

    # Oldest se Newest sequence maintain karna
    new_items.reverse()
    print(f"📥 Found {len(new_items)} pending messages to process!")

    for current_item in new_items:
        print(f"\n👉 Processing ID: {current_item['guid']}")
        
        raw_text = current_item["text"]
        ctype = (current_item["enclosure_type"] or "").lower()
        
        # 🔥 REQUIREMENT 3: AD BLOCKING
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("🚫 Promotional Ad detected. Skipping.")
            write_last(current_item["guid"])
            continue

        # 🔥 REQUIREMENT 2: Key Replacement & Attachment Drops
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            print("🔄 Triggering Keyword Rules: Replacing name & Dropping PDF/Images")
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
            current_item["enclosure_url"] = None
            ctype = ""

        # 🔥 REQUIREMENT 4: Username replacement @
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # -----------------------------
        # Webpage Scraping (For WP Text Only)
        found_links = URL_RE.findall(raw_text)
        webpage_scraped_data = ""
        
        if found_links:
            primary_link = found_links[0]
            if not ("t.me/" in primary_link or "telegram.me/" in primary_link):
                print(f"🌐 Scraping External Link: {primary_link}")
                try:
                    resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        
                        # 🔥 REQUIREMENT 5: Extract important links except indianaukrihelp
                        for a in soup.find_all('a', href=True):
                            href = a['href']
                            if "indianaukrihelp.com" not in href and href.startswith("http"):
                                a.replace_with(f"{a.get_text()} (Link: {href})")
                                
                        for element in soup(["script", "style", "nav", "footer", "header"]):
                            element.extract()
                            
                        page_text = soup.get_text(separator="\n")
                        page_text = page_text.replace("indianaukrihelp.com", "")
                        page_text = page_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
                        
                        lines = (line.strip() for line in page_text.splitlines())
                        webpage_scraped_data = '\n'.join(line for line in lines if line)[:3500]
                except Exception as e: print(f"⚠️ Scraping failed: {e}")

        # AI Rewrite
        ai_final_text = rewrite_with_groq(raw_text, webpage_scraped_data)
        
        wp_content = ai_final_text
        if current_item["enclosure_url"] and ctype.startswith("image/"):
            wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

        new_page_link = publish_to_wordpress(current_item["title"][:50], wp_content)
        
        if new_page_link:
            # 🔥 REQUIREMENT 1: Remove `[...]` and repeating Headings from Telegram Text
            clean_root_message = remove_links(raw_text)
            clean_root_message = TRUNC_END_RE.sub("", clean_root_message).strip()
            # Double heading htane ke liye:
            clean_root_message = re.sub(r'^(.*?)\s*\n+\1', r'\1', clean_root_message, flags=re.S).strip()
            
            telegram_caption = (
                f"{clean_root_message}\n\n"
                f"🌐 {new_page_link}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            ).strip()

            if current_item["enclosure_url"] and ctype == "application/pdf":
                print("⏳ Downloading original PDF from RSS...")
                try:
                    pdf_bytes = requests.get(current_item["enclosure_url"], timeout=120).content
                    safe_pdf_bytes = sanitize_pdf_remove_links(pdf_bytes)
                    for ch in channels: tg_send_document_bytes(safe_pdf_bytes, "official_circular.pdf", telegram_caption, ch)
                    print("🚀 SUCCESS: PDF Document Sent!")
                except Exception as e:
                    print(f"❌ PDF Dispatch Failed: {e}. Falling back to text.")
                    for ch in channels: tg_send_text(telegram_caption, ch)
                    
            elif current_item["enclosure_url"] and ctype.startswith("image/"):
                try:
                    img = requests.get(current_item["enclosure_url"], timeout=180)
                    for ch in channels: tg_send_photo_bytes(img.content, telegram_caption, ch)
                    print("🚀 SUCCESS: Photo Sent!")
                except:
                    for ch in channels: tg_send_text(telegram_caption, ch)
            else:
                for ch in channels: tg_send_text(telegram_caption, ch)
                print("🚀 SUCCESS: Text Sent!")
            
            write_last(current_item["guid"])
        else:
            print("❌ WordPress failed. Stopping batch.")
            break

        time.sleep(3)

if __name__ == "__main__":
    main()
