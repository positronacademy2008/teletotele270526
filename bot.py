import os, re, html, time, io, uuid, ftplib, hashlib
import requests
import pikepdf
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow us")

# FTP & Cloning Details
FTP_HOST = os.environ.get("FTP_HOST", "")
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
MY_DOMAIN = os.environ.get("MY_DOMAIN", "")
FTP_DIR = os.environ.get("FTP_DIR", "public_html")

LAST_FILE = "last.txt"
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)(\s*\[\s*\.\.\.\s*\]\s*$)|(\s*\[\s*…\s*\]\s*$)|(\s*…\s*$)|(\s*\.\.\.\s*$)""")

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
    return re.sub(r"\s+", " ", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
    for page in src.pages:
        annots = page.get("/Annots", None)
        if not annots: continue
        new_annots = []
        for a in annots:
            try:
                obj = a.get_object()
                for key in ["/A", "/AA", "/Dest"]:
                    if key in obj: del obj[key]
                if obj.get("/Subtype", None) != pikepdf.Name("/Link"):
                    new_annots.append(a)
            except Exception:
                continue
        if new_annots: page["/Annots"] = pikepdf.Array(new_annots)
        elif "/Annots" in page: del page["/Annots"]
    out = io.BytesIO()
    src.save(out)
    return out.getvalue()

def clone_and_host_page(original_url: str) -> str:
    if not FTP_HOST or not FTP_USER:
        return None
    try:
        response = requests.get(original_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        if soup.head:
            # Original links ko fix karne ke liye base tag
            base_tag = soup.new_tag("base", href=original_url)
            soup.head.insert(0, base_tag)
            
            # MAGIC CSS: Loaders ko chhupane aur content ko forcefully dikhane ke liye
            style_tag = soup.new_tag("style")
            style_tag.string = """
                /* Gol circle aur loading screens ko hide karo */
                [class*="loader"], [class*="spinner"], [class*="preloader"], [id*="loader"], [id*="spinner"], .loading, .loader {
                    display: none !important;
                    opacity: 0 !important;
                    visibility: hidden !important;
                }
                /* Main content ko hamesha visible rakho */
                body, html, .tgme_page_wrap, #main, .content {
                    display: block !important;
                    opacity: 1 !important;
                    visibility: visible !important;
                    overflow: auto !important;
                }
            """
            soup.head.append(style_tag)
            
        # JS scripts aur iframes hata dein taaki koi background loading na ho
        for script in soup(["script", "noscript", "iframe"]):
            script.extract()
            
        modified_html = str(soup)
        
        # URL se hash banana taaki duplicate pages na banein
        url_hash = hashlib.md5(original_url.encode('utf-8')).hexdigest()[:10]
        filename = f"post_{url_hash}.html"
        
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
        print(f"Cloning failed for {original_url}: {e}")
        return None

def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    original_link = pick("link").strip()
    guid = (pick("guid").strip() or original_link)

    enc_url, enc_type = None, None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url, enc_type = m_enc.group(1), m_enc.group(2)

    custom_link = None
    if original_link:
        custom_link = clone_and_host_page(original_link)

    title = remove_links(remove_prefixes(strip_tags(title_raw)))
    desc = remove_links(re.sub(r"^\[Photo\]\s*", "", strip_tags(desc_raw)).strip())

    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)
    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()

    if custom_link:
        combined = f"{combined}\n\n🔗 Read Full Post: {custom_link}"

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
        print(f"Error: RSS Feed URL block ho gaya hai ya chal nahi raha. Details: {e}")
        return

    items = parse_all_items(xml)
    
    if not items:
        print("Error: RSS Feed server se mili lekin usme koi messages (items) nahi the.")
        return

    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid: break
        new_items.append(it)

    if not new_items: 
        print("Bot properly chala: Koi naye messages nahi hain (Sab up-to-date hai).")
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
