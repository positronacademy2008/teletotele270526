import os, re, html, time, io, uuid, ftplib, hashlib
import requests
import pikepdf
from bs4 import BeautifulSoup
import google.generativeai as genai

# --- API KEYS & SECRETS ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow us")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- FTP SECRETS ---
FTP_HOST = os.environ.get("FTP_HOST", "")
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
MY_DOMAIN = os.environ.get("MY_DOMAIN", "")
FTP_DIR = os.environ.get("FTP_DIR", "public_html")

LAST_FILE = "last.txt"
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)(\s*\[\s*\.\.\.\s*\]\s*$)|(\s*\[\s*…\s*\]\s*$)|(\s*…\s*$)|(\s*\.\.\.\s*$)""")

# Gemini AI Configure
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def tg_send_text(text: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": False}, timeout=60)
    r.raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    r = requests.post(url, data=data, files=files, timeout=180)
    r.raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    r = requests.post(url, data=data, files=files, timeout=300)
    r.raise_for_status()

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
    return s.strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def extract_first_external_url(text: str):
    # Telegram message mein se actual news website ka link nikalna
    urls = URL_RE.findall(text)
    for u in urls:
        if "t.me" not in u and "telegram.me" not in u:
            return u
    return None

def rewrite_with_ai(raw_text: str) -> str:
    if not GEMINI_API_KEY:
        return "<p>AI API Key missing.</p>"
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Aap ek professional content writer aur educator hain. Neeche di gayi news ya article ko puri tarah se apne shabdon mein rewrite karein taaki koi copyright issue na aaye. 
        Tone: Professional, informative, aur students ke liye helpful.
        Language: Hinglish ya Hindi (Devanagari).
        Formatting: Sirf HTML tags use karein jaise <h3>, <p>, <ul>, <li>. Body ya Html tags mat lagana.
        Original link ka koi mention nahi karna hai.
        
        Original Text:
        {raw_text[:6000]}
        """
        response = model.generate_content(prompt)
        clean_html = response.text.replace("```html", "").replace("```", "").strip()
        return clean_html
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return "<p>Content fetch karne mein error aayi.</p>"

def scrape_and_publish_article(url: str) -> str:
    if not FTP_HOST or not FTP_USER:
        return None
    try:
        # 1. Website se content scrape karna
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Sirf paragraphs (text) nikalna taaki kachra na aaye
        paragraphs = soup.find_all('p')
        raw_text = " ".join([p.text for p in paragraphs])
        
        if len(raw_text) < 100:
            return None # Agar website ne text nahi diya
            
        # 2. AI se Rewrite karwana
        ai_rewritten_content = rewrite_with_ai(raw_text)
        
        # 3. Positron Academy ke brand format mein naya HTML banana (No Source Link)
        modified_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Positron Academy Updates</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; display: flex; justify-content: center; align-items: flex-start; min-height: 100vh; }}
        .post-wrapper {{ background: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.08); width: 100%; max-width: 800px; line-height: 1.6; color: #333; }}
        .header {{ text-align: center; margin-bottom: 25px; border-bottom: 2px solid #f0f2f5; padding-bottom: 15px; }}
        .header h2 {{ margin: 0; color: #1a73e8; font-size: 26px; text-transform: uppercase; letter-spacing: 1px; }}
        .header p {{ margin: 5px 0 0 0; color: #666; font-size: 14px; }}
        .content h3 {{ color: #2c3e50; margin-top: 20px; }}
        .content p {{ font-size: 16px; margin-bottom: 15px; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 12px; color: #999; border-top: 1px solid #eee; padding-top: 15px; }}
    </style>
</head>
<body>
    <div class="post-wrapper">
        <div class="header">
            <h2>Positron Academy</h2>
            <p>Exclusive Educational Update</p>
        </div>
        <div class="content">
            {ai_rewritten_content}
        </div>
        <div class="footer">
            &copy; 2026 Positron Academy. All Rights Reserved.
        </div>
    </div>
</body>
</html>"""
        
        # 4. FTP par upload karna
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:10]
        filename = f"news_{url_hash}.html"
        
        with ftplib.FTP(FTP_HOST) as ftp:
            ftp.login(FTP_USER, FTP_PASS)
            try:
                ftp.cwd(FTP_DIR)
            except ftplib.error_perm:
                pass 
                
            bio = io.BytesIO(modified_html.encode('utf-8'))
            ftp.storbinary(f"STOR {filename}", bio)
            
        return f"{MY_DOMAIN.rstrip('/')}/{filename}"
    except Exception as e:
        print(f"Scraping/AI failed for {url}: {e}")
        return None

def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    
    # Text mein se external link dhoondho
    full_desc = strip_tags(desc_raw)
    external_link = extract_first_external_url(full_desc)
    
    guid = pick("guid").strip()

    enc_url, enc_type = None, None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url, enc_type = m_enc.group(1), m_enc.group(2)

    # NAYA SYSTEM: AI se webpage generate karna
    custom_link = None
    if external_link:
        custom_link = scrape_and_publish_article(external_link)

    title = remove_links(remove_prefixes(strip_tags(title_raw)))
    desc = remove_links(re.sub(r"^\[Photo\]\s*", "", full_desc).strip())

    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)
    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()

    if custom_link:
        combined = f"{combined}\n\n🔗 Click to Read Full Article: {custom_link}"

    return {"guid": guid, "text": combined, "enclosure_url": enc_url, "enclosure_type": enc_type}

def parse_all_items(xml: str):
    return [parse_item(m.group(1)) for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S)]

def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    if not channels: 
        print("Error: Destination channel set nahi hai.")
        return

    last_guid = read_last()
    
    print("RSS Feed fetch kar rahe hain...")
    try:
        response = requests.get(FEED_URL, timeout=90)
        response.raise_for_status()
        xml = response.text
    except Exception as e:
        print(f"Error: RSS Feed URL chal nahi raha. Details: {e}")
        return

    items = parse_all_items(xml)
    if not items: return

    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid: break
        new_items.append(it)

    if not new_items: 
        print("Bot up-to-date hai.")
        return
        
    new_items.reverse()

    for it in new_items:
        out = f"🔥 New Update\n\n{it['text']}\n\n━━━━━━━━━━━━━━\n{FOLLOW_LINE}".strip()
        ctype = (it["enclosure_type"] or "").lower()

        try:
            if it["enclosure_url"] and ctype.startswith("image/"):
                img = requests.get(it["enclosure_url"], timeout=180)
                img.raise_for_status()
                for ch in channels: tg_send_photo_bytes(img.content, out, ch)
            elif it["enclosure_url"] and ctype == "application/pdf":
                pdf = requests.get(it["enclosure_url"], timeout=300)
                pdf.raise_for_status()
                safe_pdf = sanitize_pdf_remove_links(pdf.content)
                for ch in channels: tg_send_document_bytes(safe_pdf, "document.pdf", out, ch)
            else:
                for ch in channels: tg_send_text(out, ch)
        except Exception as e:
            print(f"Error sending message to Telegram: {e}")
            
        time.sleep(1)

    write_last(new_items[-1]["guid"])
    print(f"Posted {len(new_items)} items. Last: {new_items[-1]['guid']}")

if __name__ == "__main__":
    main()
