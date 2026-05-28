import os, re, html, time, io
import requests
import pikepdf
from openai import OpenAI

# --- CONFIGURATION ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow @topgkguru")
LAST_FILE = "last.txt"

# Setup Groq AI
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Regex Patterns
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

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

def normalize(s: str) -> str:
    s = TRUNC_END_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

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
def rewrite_with_groq(text: str) -> str:
    print("⏳ Rewriting content via Groq AI...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional educational blog writer for Positron Academy. Rewrite the provided data into a comprehensive, detailed, 100% unique, and plagiarism-free article for a website post in Hinglish. No external URLs."},
                {"role": "user", "content": f"Create an original detailed website article based on this information:\n\n{text}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}")
        return text

def publish_to_wordpress(title, content):
    print("⏳ Posting to WordPress...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    # 🔥 FIX 2: Generate Short Clean URL slug (update-timestamp)
    short_slug = f"update-{int(time.time() * 1000)}"

    data = {
        'title': title, 
        'content': content, 
        'status': 'publish',
        'slug': short_slug
    }

    try:
        response = requests.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        if response.status_code == 201:
            return response.json().get("link", "")
        else:
            print(f"❌ WP Status Code: {response.status_code}")
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
        print("No items found")
        return

    # 🔥 FIX 1: Pata lagao kitne naye messages hain (Batch Processing)
    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            break
        new_items.append(it)

    if not new_items:
        print("✅ No new posts found. Everything is up to date.")
        return

    # Purane se naye ki taraf process karna taki sequence sahi rahe
    new_items.reverse()
    print(f"📥 Found {len(new_items)} new messages to process!")

    for latest_item in new_items:
        print(f"\n👉 Processing message ID: {latest_item['guid']}")

        # Clean links from original text
        clean_original_text = remove_links(latest_item['text'])
        
        # AI Website content creation
        ai_wp_content = rewrite_with_groq(clean_original_text)
        
        wp_body = ai_wp_content
        ctype = (latest_item["enclosure_type"] or "").lower()
        
        # Insert Image in WP Post if exists
        if latest_item["enclosure_url"] and ctype.startswith("image/"):
            wp_body += f'<br><br><img src="{latest_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

        # Publish to Website
        new_wp_link = publish_to_wordpress(latest_item["title"], wp_body)

        if new_wp_link:
            # 🔥 FIX 3: Caption se "**Website Link:**" hata diya gaya
            telegram_caption = (
                f"🔥 New Update\n\n"
                f"{clean_original_text}\n\n"
                f"🌐 {new_wp_link}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE}"
            ).strip()

            # Route Payload properly
            if latest_item["enclosure_url"] and ctype == "application/pdf":
                print("⏳ Downloading original PDF from RSS Enclosure...")
                pdf = requests.get(latest_item["enclosure_url"], timeout=300)
                pdf.raise_for_status()
                safe_pdf = sanitize_pdf_remove_links(pdf.content)
                
                for ch in channels:
                    tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, ch)
                print("🚀 SUCCESS: PDF Document sent!")
                
            elif latest_item["enclosure_url"] and ctype.startswith("image/"):
                img = requests.get(latest_item["enclosure_url"], timeout=180)
                img.raise_for_status()
                for ch in channels:
                    tg_send_photo_bytes(img.content, telegram_caption, ch)
                print("🚀 SUCCESS: Image sent!")
                
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
                print("🚀 SUCCESS: Text sent!")

            # Finalize and Save id
            write_last(latest_item["guid"])
        else:
            print("❌ Stopping batch. WordPress post failed for this item.")
            break
        
        # Thoda gap dena zaruri hai taaki spam na lage aur limit cross na ho
        time.sleep(3)

if __name__ == "__main__":
    main()
