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

FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/topgkguru"
FOLLOW_LINE_WA = "📢 Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"

client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

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

def remove_links(s: str) -> str:
    return URL_RE.sub("", s).strip()

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
                except Exception:
                    continue
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
    print("⏳ Fetching PDF from Telegram Bot API...")
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        resp = requests.get(url, timeout=30).json()
        if resp.get("ok"):
            for update in reversed(resp["result"]):
                node = update.get("message") or update.get("channel_post")
                if node and "document" in node:
                    file_id = node["document"]["file_id"]
                    path_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
                    file_path = requests.get(path_url).json()["result"]["file_path"]
                    return requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}", timeout=120).content
    except Exception as e:
        print(f"❌ PDF Grabber Error: {e}")
    return None

def fetch_telegram_channel_messages():
    username = FEED_URL.strip().replace("https://t.me/s/", "").replace("@", "")
    scrape_url = f"https://t.me/s/{username}"
    resp = requests.get(scrape_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
    soup = BeautifulSoup(resp.text, 'html.parser')
    items = []
    for block in soup.find_all('div', class_='tgme_widget_message'):
        guid = block.get('data-post')
        text_block = block.find('div', class_='tgme_widget_message_text')
        if not guid or not text_block: continue
        
        raw_text = text_block.get_text(separator='\n').strip()
        img_wrap = block.find('a', class_='tgme_widget_message_photo_wrap')
        img_url = re.search(r"url\(['\"]?(.*?)['\"]?\)", img_wrap['style']) if img_wrap and 'style' in img_wrap.attrs else None
        
        doc_anchor = block.find('a', class_=lambda x: x and 'document' in x)
        doc_url = doc_anchor['href'] if doc_anchor else None
        
        items.append({"guid": guid, "title": raw_text[:80], "text": raw_text, "enclosure_url": img_url, "doc_url": doc_url})
    return items

def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("⏳ Rewriting content via Groq AI...")
    source = webpage_text if len(webpage_text) > 100 else telegram_text
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional educational blog writer. Rewrite content into a unique, plagiarism-free article in Hinglish. No external links."},
                {"role": "user", "content": f"Article text:\n\n{source}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception:
        return telegram_text

def publish_to_wordpress(title, content):
    print("⏳ Posting to WP...")
    try:
        resp = requests.post(os.environ["WP_URL"], auth=(os.environ["WP_USER"], os.environ["WP_PASS"]), 
                             data={'title': title, 'content': content, 'status': 'publish'}, timeout=90)
        return resp.json().get("link") if resp.status_code == 201 else None
    except: return None

def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",")]
    items = fetch_telegram_channel_messages()
    if not items: return
    
    latest = items[-1]
    if read_last() == latest["guid"]: return

    clean_text = remove_links(latest["text"])
    ai_content = rewrite_with_groq(clean_text, "") # Scraper removed for stability
    
    wp_content = ai_content
    if latest["enclosure_url"]: wp_content += f'<br><img src="{latest["enclosure_url"]}">'
    
    link = publish_to_wordpress(latest["title"], wp_content)
    if link:
        cap = f"{clean_text}\n\n🌐 Website: {link}\n\n{FOLLOW_LINE_TG}\n{FOLLOW_LINE_WA}"
        pdf = download_asli_pdf_from_telegram()
        
        if pdf:
            for ch in channels: tg_send_document_bytes(sanitize_pdf_remove_links(pdf), "circular.pdf", cap, ch)
        elif latest["enclosure_url"]:
            img = requests.get(latest["enclosure_url"]).content
            for ch in channels: tg_send_photo_bytes(img, cap, ch)
        else:
            for ch in channels: tg_send_text(cap, ch)
            
        write_last(latest["guid"])

if __name__ == "__main__":
    main()
