import os, re, html, time, io, uuid, ftplib, hashlib
import requests
import pikepdf
from bs4 import BeautifulSoup
import google.generativeai as genai

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow us")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

FTP_HOST = os.environ.get("FTP_HOST", "")
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
MY_DOMAIN = os.environ.get("MY_DOMAIN", "")
FTP_DIR = os.environ.get("FTP_DIR", "public_html")

LAST_FILE = "last.txt"
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)(\s*\[\s*\.\.\.\s*\]\s*$)|(\s*\[\s*…\s*\]\s*$)|(\s*…\s*$)|(\s*\.\.\.\s*$)""")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def tg_send_text(text: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": False}, timeout=60).raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files={"photo": ("image.jpg", photo_bytes)}, timeout=180).raise_for_status()

def read_last():
    if os.path.exists(LAST_FILE): return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)

def strip_tags(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<.*?>", "", s)
    return s.strip()

def remove_links(s: str) -> str:
    return URL_RE.sub("", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def extract_first_external_url(text: str):
    urls = URL_RE.findall(text)
    for u in urls:
        if "t.me" not in u and "telegram.me" not in u: return u
    return None

def rewrite_with_ai(raw_text: str) -> str:
    if not GEMINI_API_KEY: return "<p>AI API Key missing.</p>"
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Professional educator writer, rewrite this news without copyright. Language: Hindi/Hinglish. Use HTML tags <h3>, <p>, <ul>, <li>. Original text: {raw_text[:6000]}"
        return model.generate_content(prompt).text.replace("```html", "").replace("```", "").strip()
    except: return "<p>AI generation failed.</p>"

def scrape_and_publish_article(url: str) -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.content, 'html.parser')
        raw_text = " ".join([p.text for p in soup.find_all('p')])
        
        ai_content = rewrite_with_ai(raw_text)
        
        final_html = f"<html><body><div style='max-width:800px; margin:auto;'>{ai_content}</div></body></html>"
        
        filename = f"post_{hashlib.md5(url.encode()).hexdigest()[:10]}.html"
        with ftplib.FTP(FTP_HOST) as ftp:
            ftp.login(FTP_USER, FTP_PASS)
            ftp.cwd(FTP_DIR)
            ftp.storbinary(f"STOR {filename}", io.BytesIO(final_html.encode('utf-8')))
        return f"{MY_DOMAIN.rstrip('/')}/{filename}"
    except Exception as e:
        print(f"Error: {e}")
        return None

def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title = remove_links(remove_prefixes(strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title")))))
    desc = strip_tags(re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description")))
    url = extract_first_external_url(desc)
    
    custom_link = scrape_and_publish_article(url) if url else None
    text = f"{title}\n\n{desc}" + (f"\n\n🔗 Read Full Post: {custom_link}" if custom_link else "")
    
    return {"guid": pick("guid") or pick("link"), "text": text}

def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    xml = requests.get(FEED_URL, timeout=90).text
    items = [parse_item(m.group(1)) for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S)]
    
    new_items = [it for it in items if last_guid and it["guid"] != last_guid or not last_guid]
    if not new_items: return
    
    for it in reversed(new_items):
        for ch in channels: tg_send_text(f"🔥 New Update\n\n{it['text']}\n\n━━━━━━━━━━━━━━\n{FOLLOW_LINE}", ch)
        time.sleep(2)
        
    write_last(new_items[0]["guid"])

if __name__ == "__main__":
    main()
