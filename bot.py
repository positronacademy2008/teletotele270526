import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

# 🛡️ Disable SSL Warnings (Important for Hostinger/cPanel bypass)
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING: BRAND PROTECTION & HTML MIRRORING MODE...")

# --- CONFIGURATION & ENV VARIABLES ---
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    DEST_CHANNELS = os.environ["DEST_CHANNEL"]
    FEED_URL = os.environ["FEED_URL"]
    LAST_FILE = "last.txt"
    WP_URL = os.environ.get("WP_URL")
    WP_USER = os.environ.get("WP_USER")
    WP_PASS = os.environ.get("WP_PASS")

    FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/RAJASTHAN_TODAY"
    FOLLOW_LINE_WA = "📢 Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"
    
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Environment Variables Missing: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": True}, timeout=60).raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching PHOTO to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=180).raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching PDF/DOCUMENT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=300).raise_for_status()

# --- UTILITIES & MEMORY ---
def read_last():
    if os.path.exists(LAST_FILE): 
        return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)
    print(f"   ↳ 🛠 [DEBUG] last.txt updated with ID: {val}")

def strip_tags(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<.*?>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

# --- BRAND PROTECTION REPLACER ---
def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag": return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

def brand_replacer(text: str) -> str:
    if not text: return ""
    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    text = text.replace("indianaukrihelp.com", "positronacademy.in")
    text = re.sub(r'@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+', fix_usernames, text)
    text = re.sub(r'https?://(www\.)?(t\.me|telegram\.me)/[A-Za-z0-9_]+', 'https://t.me/RAJASTHAN_TODAY', text)
    text = re.sub(r'https?://(www\.)?whatsapp\.com/channel/[A-Za-z0-9_]+', 'https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q', text)
    return text

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    print("   ↳ 🛠 [DEBUG] Sanitizing PDF (Removing clickable links)...")
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
                except: continue
            if new_annots: page["/Annots"] = pikepdf.Array(new_annots)
            else:
                if "/Annots" in page: del page["/Annots"]
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except Exception as e: 
        print(f"   ↳ ❌ [DEBUG] Pikepdf error: {e}")
        return pdf_bytes

# --- RSS PARSER ---
def parse_all_items(xml_data: str):
    items = []
    try:
        soup = BeautifulSoup(xml_data, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text.strip() if item.title else "No Title"
            desc = item.description.text.strip() if item.description else ""
            guid = item.guid.text.strip() if item.guid else (item.link.text.strip() if item.link else title)
            
            enc_url, enc_type = None, None
            enclosure = item.find('enclosure')
            if enclosure and enclosure.has_attr('url'):
                enc_url = enclosure['url']
                enc_type = enclosure.get('type', '')

            title_clean = remove_prefixes(strip_tags(title))
            desc_clean = re.sub(r"^\[Photo\]\s*", "", strip_tags(desc)).strip()
            combined = f"{title_clean}\n\n{desc_clean}".strip() if title_clean and desc_clean else (title_clean or desc_clean)
            
            items.append({
                "guid": guid,
                "title": title_clean[:80] if title_clean else "Educational Update",
                "text": combined,
                "enclosure_url": enc_url,
                "enclosure_type": enc_type
            })
    except Exception as e:
        print(f"❌ [CRITICAL ERROR] Failed to parse RSS securely: {e}")
    return items

# --- GROQ AI & WORDPRESS (WITH MODSECURITY BYPASS) ---
def rewrite_with_groq(source_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] Sending content to Groq AI for rewriting...")
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are an expert SEO blog writer for Positron Academy. Rewrite the text into a detailed, unique article in Hinglish. VERY IMPORTANT: If the text contains important URLs written as '(Link: https...)', convert them into clickable HTML buttons or anchor tags (e.g. <a href='...'>Click Here</a>) logically in the article. Do NOT include any references to 'indianaukrihelp.com' or 'शिक्षा विभाग समाचार राजस्थान'."
                },
                {"role": "user", "content": f"Create a detailed website article:\
