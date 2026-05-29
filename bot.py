import os, re, html, time, io, requests, urllib3, pikepdf, builtins
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openai import OpenAI

# 🔥 LIVE LOG FLUSHER
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# 🛡️ Disable SSL Warnings
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING: ANTI-404, BROKEN-LINK REMOVER & HTML MIRRORING MODE...")

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
    print(f"❌ [CRITICAL ERROR] Missing Environment Variables: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://[^\s<>"]+)\b""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": False}, timeout=60).raise_for_status()

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
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag": return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

def brand_replacer(text: str) -> str:
    if not text: return ""
    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    text = re.sub(r'@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+', fix_usernames, text)
    text = re.sub(r'https?://(www\.)?(t\.me|telegram\.me)/[A-Za-z0-9_]+', 'https://t.me/RAJASTHAN_TODAY', text)
    text = re.sub(r'https?://(www\.)?whatsapp\.com/channel/[A-Za-z0-9_]+', 'https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q', text)
    return text

# 🔥 SAFE CLICKABLE LINKS MAKER
def make_links_clickable(html_text: str) -> str:
    if not html_text: return ""
    try:
        raw_url_re = re.compile(r'(https?://[^\s<>"]+)')
        soup = BeautifulSoup(html_text, 'html.parser')
        
        text_nodes = list(soup.find_all(string=True))
        for text_node in text_nodes:
            if text_node.parent and text_node.parent.name in ['a', 'script', 'style', 'head', 'title', 'button']:
                continue
                
            original_text = str(text_node)
            if raw_url_re.search(original_text):
                new_text = raw_url_re.sub(r'<a href="\1" target="_blank" style="color: blue; text-decoration: underline;">\1</a>', original_text)
                new_node = BeautifulSoup(new_text, 'html.parser')
                text_node.replace_with(new_node)
        return str(soup)
    except Exception as e:
        print(f"   ↳ ⚠️ [DEBUG] Link clickable error: {e}")
        return html_text

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

# --- GROQ AI REWRITERS ---
def rewrite_telegram_post(source_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] AI rewriting SHORT Post (Max wait: 45s)...")
    system_prompt = "You are an expert SEO educational blog writer. Rewrite the provided update into a detailed, unique article in Hinglish. Do NOT include any references to 'indianaukrihelp.com'."
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Rewrite this update safely:\n\n{source_content[:3500]}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5,
            timeout=45.0
        )
        return response.choices[0].message.content
    except Exception as e: 
        print(f"   ↳ ❌ [DEBUG ERROR] AI Failed/Timed out: {e}")
        return source_content

def rewrite_html_page(html_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] AI rewriting FULL HTML PAGE (Max wait: 45s)...")
    system_prompt = (
        "You are an expert HTML editor. Rewrite the text content of the provided HTML into unique Hinglish. "
        "CRITICAL RULES: \n"
        "1. DO NOT modify ANY <img>, <figure>, <table>, <tr>, <td>, or <a> tags.\n"
        "2. Preserve all 'src' and 'href' attributes exactly.\n"
        "3. Only rewrite the plain text between HTML tags.\n"
        "4. Remove references to 'indianaukrihelp.com'.\n"
        "5. Return pure HTML without markdown blocks."
    )
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Rewrite this HTML safely:\n\n{html_content[:5000]}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.2,
            timeout=45.0
        )
        res = response.choices[0].message.content
        res = re.sub(r"^```html\s*", "", res, flags=re.I)
        return re.sub(r"```\s*$", "", res).strip()
    except Exception as e: 
        print(f"   ↳ ❌ [DEBUG ERROR] AI HTML Failed/Timed out: {e}")
        return html_content

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print(f"   ↳ ⏳ [DEBUG] Publishing to WordPress as PAGE...")
    final_content = make_links_clickable(content)
    page_api_url = WP_URL.replace("/posts", "/pages")
    
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    data = {
        'title': brand_replacer(title), 
        'content': final_content, 
        'status': 'publish', 
        'slug': f"update-{int(time.time() * 1000)}"
    }
    
    try:
        response = requests.post(page_api_url, auth=(WP_USER, WP_PASS), json=data, headers=headers, timeout=60, verify=False)
        if response.status_code in [200, 201]: 
            return response.json().get("link", "")
        else:
            print(f"   ↳ ❌ [DEBUG ERROR] WP rejected PAGE. Status: {response.status_code}")
    except Exception as e: 
        print(f"   ↳ ❌ [CRITICAL ERROR] WordPress request failed: {e}")
    return None

# --- DEEP SCRAPER & COPYRIGHT FREE HTML MIRRORING ---
def deep_scrape_and_mirror(url):
    print(f"   ↳ 🕵️ [DEBUG] Mirroring Competitor URL: {url}")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
        if r.status_code != 200: return None
        
        soup = BeautifulSoup(r.text, 'html.parser')
        
        for img in soup.find_all('img'):
            if img.get('src'): img['src'] = urljoin(url, img['src'])
            if img.get('data-src'): img['src'] = urljoin(url, img['data-src']) 
            if img.get('srcset'): del img['srcset'] 
        for a in soup.find_all('a'):
            if a.get('href'): a['href'] = urljoin(url, a['href'])
            
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.extract()
            
        article = soup.find(class_=re.compile("entry-content|post-content|content-area"))
        if not article: article = soup.find("main")
        if not article: article = soup.find("body")
        if not article: return None
        
        page_html = str(article)
        page_title = soup.title.string.strip() if soup.title else "Update Details"
        
        rewritten_html = rewrite_html_page(page_html)
        mirrored_link = publish_to_wordpress(f"Details: {page_title[:40]}", rewritten_html)
        
        if mirrored_link:
            print(f"   ↳ ✅ [DEBUG] Successfully mirrored! New URL: {mirrored_link}")
            return mirrored_link
    except Exception as e:
        print(f"   ↳ ⚠️ [DEBUG] Deep mirroring failed: {e}")
    return None 

# --- MAIN CONTROLLER ENGINE ---
def main():
    print("\n🛠 [DEBUG] STEP 1: Fetching settings.")
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()

    print(f"🛠 [DEBUG] STEP 2: Fetching RSS from {FEED_URL}")
    try:
        xml_resp = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45)
        items = parse_all_items(xml_resp.text)
    except Exception as e: 
        print(f"❌ [CRITICAL ERROR] Failed to fetch RSS: {e}")
        return

    new_items = []
    for it in items:
        if it["guid"] == last_guid: break
        new_items.append(it)

    if not new_items: 
        print("✅ [DEBUG] System Up To Date.")
        return
        
    new_items.reverse() 
    print(f"📥 [DEBUG] Processing {len(new_items)} new messages.")

    for current_item in new_items:
        print(f"\n👉 [DEBUG] ====== PROCESSING ITEM: {current_item['title'][:40]} ====== ")
        try:
            raw_text = current_item['text']
            ctype = (current_item["enclosure_type"] or "").lower()

            # Ad Blocker
            if any(kw in raw_text.lower() for kw in ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']):
                write_last(current_item["guid"])
                continue

            raw_text = brand_replacer(raw_text)

            if "राजस्थान न्यूज़ टूडे" in raw_text:
                current_item["enclosure_url"] = None
                ctype = "" 

            # 🔥 FIX: STRICT URL REPLACEMENT TO AVOID 404s
            found_urls = URL_RE.findall(raw_text)
            for url in set(found_urls):
                if "indianaukrihelp.com" in url:
                    new_mirrored_link = deep_scrape_and_mirror(url)
                    if new_mirrored_link:
                        # SUCCESS: Replace old URL with our working sub-page URL
                        raw_text = raw_text.replace(url, new_mirrored_link)
                    else:
                        # FAIL: Delete the broken link from text completely so it doesn't cause 404
                        raw_text = raw_text.replace(url, "")

            wp_content = rewrite_telegram_post(raw_text)
            
            if current_item["enclosure_url"] and ctype.startswith("image/"):
                wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;">'

            new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)
            
            if new_wp_link:
                print("   ↳ 🛠 [DEBUG] Formatting Final Telegram Caption...")
                # Cleaning stray ellipses
                clean_caption = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', raw_text)
                
                # 🔥 STRICT TG CAPTION CLEANUP
                clean_caption = re.sub(r'https?://(?:www\.)?positronacademy\.in[^\s<>"]*', '', clean_caption)
                
                lines = [l.strip() for l in clean_caption.split('\n') if l.strip()]
                if len(lines) > 1 and (lines[0] in lines[1] or lines[1] in lines[0]): 
                    lines.pop(0)
                clean_caption = '\n\n'.join(lines).strip()

                telegram_caption = (
                    f"{clean_caption}\n\n"
                    f"🌐 {new_wp_link}\n\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"{FOLLOW_LINE_TG}\n"
                    f"{FOLLOW_LINE_WA}"
                ).strip()

                if current_item["enclosure_url"] and ctype == "application/pdf":
                    try:
                        pdf = requests.get(current_item["enclosure_url"], timeout=300, verify=False)
                        safe_pdf = sanitize_pdf_remove_links(pdf.content)
                        for ch in channels: tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, ch)
                    except:
                        for ch in channels: tg_send_text(telegram_caption, ch)
                elif current_item["enclosure_url"] and ctype.startswith("image/"):
                    try:
                        img = requests.get(current_item["enclosure_url"], timeout=180, verify=False)
                        for ch in channels: tg_send_photo_bytes(img.content, telegram_caption, ch)
                    except:
                        for ch in channels: tg_send_text(telegram_caption, ch)
                else:
                    for ch in channels: tg_send_text(telegram_caption, ch)

                write_last(current_item["guid"])
            else:
                print("   ↳ ❌ [DEBUG] WordPress failed. Skipping.")
        except Exception as e:
            print(f"   ↳ ❌ [CRITICAL] Loop error: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    main()
