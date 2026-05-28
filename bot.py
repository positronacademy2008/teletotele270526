import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# --- CONFIGURATION ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow TELEGRAM WHATSAPP https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q | TELEGRAM https://t.me/RAJASTHAN_TODAY")
LAST_FILE = "last.txt"

# Setup Groq AI
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Regex Patterns
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
    s = re.sub(r"\n{3,}", "\n\n", s)
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
        print(f"❌ Pikepdf error: {e}")
        return pdf_bytes

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

# --- GROQ AI & WORDPRESS ---
def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("⏳ Rewriting content via Groq AI...")
    source_content = webpage_text if len(webpage_text) > 100 else telegram_text
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional educational blog writer for Positron Academy. Rewrite the provided data into a comprehensive, detailed, 100% unique, and plagiarism-free article for a website post in Hinglish. Do NOT include any links related to 'indianaukrihelp.com'."},
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
    print("⏳ Posting to WordPress...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    short_slug = f"update-{int(time.time() * 1000)}"
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': short_slug}

    try:
        response = requests.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        if response.status_code == 201:
            return response.json().get("link", "")
        else:
            print(f"❌ WP Status Code: {response.status_code}")
            print(f"❌ WP ERROR DETAILS: {response.text}") # Ye line exact error batayegi
    except Exception as e:
        print(f"❌ WordPress Error: {e}")
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    if not channels:
        raise RuntimeError("DEST_CHANNEL is empty.")

    last_guid = read_last()
    print("⏳ Fetching Feed XML...")
    xml = requests.get(FEED_URL, timeout=90).text
    items = parse_all_items(xml)
    
    if not items:
        print("❌ No items found in XML Feed.")
        return

    # --- BATCH PROCESSING LOGIC ---
    new_items = []
    if not last_guid:
        print("📝 last.txt is EMPTY. Fetching ALL messages.")
        new_items = items
    else:
        for it in items:
            if it["guid"] == last_guid:
                break
            new_items.append(it)

    if not new_items:
        print("✅ No new posts found. Everything is up to date.")
        return

    # Oldest to Newest
    new_items.reverse()
    print(f"📥 Found {len(new_items)} new messages to process!")

    for current_item in new_items:
        print(f"\n👉 Processing message ID: {current_item['guid']}")

        raw_text = current_item['text']
        ctype = (current_item["enclosure_type"] or "").lower()

        # 🔥 RULE 3: AD BLOCKING
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("🚫 Promotional Ad detected. Skipping.")
            write_last(current_item["guid"])
            continue

        # 🔥 RULE 2: KEYWORD REPLACE & DROP ATTACHMENTS
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
            current_item["enclosure_url"] = None
            ctype = ""

        # 🔥 RULE 4: USERNAME REPLACE
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # 🔥 RULE 5: WEBPAGE SCRAPING (Ignore indianaukrihelp)
        found_links = URL_RE.findall(raw_text)
        webpage_scraped_data = ""
        
        if found_links:
            primary_link = found_links[0]
            if "indianaukrihelp.com" not in primary_link and not primary_link.startswith("https://t.me/"):
                print(f"🌐 Scraping External Link: {primary_link}")
                try:
                    resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
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
                except Exception as e:
                    print(f"⚠️ Scraping failed: {e}")

        # AI Website content creation
        ai_wp_content = rewrite_with_groq(raw_text, webpage_scraped_data)
        
        wp_body = ai_wp_content
        if current_item["enclosure_url"] and ctype.startswith("image/"):
            wp_body += f'<br><br><img src="{current_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

        # Publish to Website
        new_wp_link = publish_to_wordpress(current_item["title"], wp_body)

        if new_wp_link:
            # 🔥 RULE 1: Remove `[...]` and Double Headings from Caption
            clean_caption = remove_links(raw_text)
            clean_caption = TRUNC_END_RE.sub("", clean_caption).strip()
            # Double heading htane ka powerful regex
            clean_caption = re.sub(r'^(.*?)\s*\n+\1', r'\1', clean_caption, flags=re.S).strip()

            telegram_caption = (
                f"{clean_caption}\n\n"
                f"🌐 {new_wp_link}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE}"
            ).strip()

            # Route Payload properly
            if current_item["enclosure_url"] and ctype == "application/pdf":
                print("⏳ Downloading original PDF from RSS Enclosure...")
                try:
                    pdf = requests.get(current_item["enclosure_url"], timeout=300)
                    pdf.raise_for_status()
                    safe_pdf = sanitize_pdf_remove_links(pdf.content)
                    for ch in channels:
                        tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, ch)
                    print("🚀 SUCCESS: PDF Document sent!")
                except Exception as e:
                    print(f"❌ PDF Failed: {e}. Sending text instead.")
                    for ch in channels: tg_send_text(telegram_caption, ch)
                
            elif current_item["enclosure_url"] and ctype.startswith("image/"):
                try:
                    img = requests.get(current_item["enclosure_url"], timeout=180)
                    img.raise_for_status()
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                    print("🚀 SUCCESS: Image sent!")
                except:
                    for ch in channels: tg_send_text(telegram_caption, ch)
                
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
                print("🚀 SUCCESS: Text sent!")

            # Finalize and Save id
            write_last(current_item["guid"])
        else:
            print("❌ Stopping batch. WordPress post failed for this item.")
            break
        
        time.sleep(3)

if __name__ == "__main__":
    main()
