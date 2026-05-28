import os, re, html, time, io
import requests
import urllib3
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# 🛡️ SSL Warnings Disable (Firewall bypass ke liye zaroori)
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING UP WITH 6 NEW RULES...")

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
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Missing Environment Variables: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

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
    if os.path.exists(LAST_FILE): return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)

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

# 🔥 RULE 4: Username Replacer Function
def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
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
    except Exception: return pdf_bytes

# --- RSS PARSER ---
def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")
    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    guid = (pick("guid").strip() or pick("link").strip())
    
    enc_url, enc_type = None, None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url = m_enc.group(1)
        enc_type = m_enc.group(2)

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)
    desc = re.sub(r"^\[Photo\]\s*", "", desc).strip()
    
    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)
    return {"guid": guid, "title": title[:80] if title else "Educational Update", "text": combined, "enclosure_url": enc_url, "enclosure_type": enc_type}

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

# --- GROQ AI & WORDPRESS ---
def rewrite_with_groq(source_content: str) -> str:
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are an expert SEO blog writer for Positron Academy. Rewrite the text into a detailed, unique article in Hinglish. VERY IMPORTANT: If the text contains important URLs written as '(Link: https...)', you MUST convert them into clickable HTML buttons or anchor tags (e.g. <a href='...'>Click Here</a>) logically in the article. Do NOT include any references to 'indianaukrihelp.com' or 'शिक्षा विभाग समाचार राजस्थान'."
                },
                {"role": "user", "content": f"Create a detailed website article:\n\n{source_content}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception: return source_content

def publish_to_wordpress(title, content):
    wp_url = os.environ.get("WP_URL")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0',
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    clean_slug = f"update-{int(time.time())}"
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': clean_slug}
    try:
        response = requests.post(wp_url, auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")), data=data, headers=headers, timeout=60, verify=False)
        if response.status_code == 201: return response.json().get("link", "")
    except Exception: pass
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()

    try:
        xml_resp = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45)
        items = parse_all_items(xml_resp.text)
    except: return

    if not items: return

    new_items = []
    if not last_guid: new_items = items
    else:
        found_idx = -1
        for i, it in enumerate(items):
            if it["guid"] == last_guid:
                found_idx = i
                break
        if found_idx != -1: new_items = items[found_idx + 1 :]
        else: new_items = [items[-1]]

    if not new_items: return
    new_items.reverse() # Process oldest first

    for current_item in new_items:
        raw_text = current_item['text']
        ctype = (current_item["enclosure_type"] or "").lower()

        # 🔥 RULE 3: Ad Blocker
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            write_last(current_item["guid"])
            continue

        # 🔥 RULE 2: Keyword Replacement & Attachment Dropper
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            raw_text = raw_text.
