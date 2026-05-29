import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

# 🛡️ Disable SSL Warnings
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING: BRAND PROTECTION, HTML FORMAT MIRRORING & PAGE BUILDER MODE...")

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

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": False}, timeout=60).raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=180)

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    requests.post(url, data=data, files=files, timeout=300)

# --- UTILITIES ---
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
    return re.sub(r"<.*?>", "", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()

# 🔥 BRAND REPLACER
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

# --- GROQ AI REWRITER (HTML PRESERVER MODE) ---
def rewrite_with_groq(source_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] Sending content to Groq AI for rewriting...")
    system_prompt = (
        "You are an expert SEO HTML blog writer for Positron Academy. "
        "You will receive raw HTML or text. Your task: Rewrite the text into a unique, copyright-free article in Hinglish. "
        "CRITICAL RULE: You MUST PRESERVE the exact HTML structure, including all <table>, <tr>, <td>, <img>, <ul>, <ol>, <h2>, <h3>, and <strong> tags. "
        "Do NOT remove tables, images, or formatting. Only rewrite the textual content inside the tags. "
        "Make sure any unformatted web URLs are wrapped in <a href='...'> clickable tags. "
        "Do NOT include any references to 'indianaukrihelp.com'. "
        "Do NOT wrap the output in ```html markdown blocks, just return the raw HTML."
    )
    user_prompt = f"Rewrite this content preserving HTML structures (Tables/Images):\n\n{source_content[:4000]}"
    
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.3
        )
        print("   ↳ ✅ [DEBUG] Groq AI successfully generated the formatted article.")
        res = response.choices[0].message.content
        # Auto-clean any markdown formatting Groq might accidentally add
        res = re.sub(r"^```html\s*", "", res, flags=re.I)
        res = re.sub(r"```\s*$", "", res).strip()
        return res
    except Exception as e: 
        print(f"   ↳ ❌ [DEBUG ERROR] Groq AI Failed: {e}")
        return source_content

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print(f"   ↳ ⏳ [DEBUG] Publishing to WordPress as PAGE...")
    page_api_url = WP_URL.replace("/posts", "/pages")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Connection': 'keep-alive'
    }
    
    clean_slug = f"update-{int(time.time() * 1000)}"
    data = {
        'title': brand_replacer(title), 
        'content': content, 
        'status': 'publish', 
        'slug': clean_slug
    }
    
    try:
        response = requests.post(page_api_url, auth=(WP_USER, WP_PASS), json=data, headers=headers, timeout=60, verify=False)
        if response.status_code in [200, 201]: 
            link = response.json().get("link", "")
            print(f"   ↳ ✅ [DEBUG] WordPress PAGE Created Successfully! Link: {link}")
            return link
        else:
            print(f"   ↳ ❌ [DEBUG ERROR] WP rejected PAGE. Status: {response.status_code}. Response: {response.text}")
    except Exception as e: 
        print(f"   ↳ ❌ [CRITICAL ERROR] WordPress request failed: {e}")
    return None

# --- DEEP SCRAPER & COPYRIGHT FREE MIRRORING ---
def deep_scrape_and_mirror(url):
    print(f"   ↳ 🕵️ [DEBUG] Mirroring & Rewriting Competitor URL: {url}")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20, verify=False)
        if r.status_code != 200: return url
        
        soup = BeautifulSoup(r.text, 'html.parser')
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.extract()
            
        article = soup.find(class_=re.compile("entry-content|post-content|content-area"))
        if not article: article = soup.find("main")
        if not article: article = soup.find("body")
        if not article: return url
        
        # 🔥 EXTRACTING RAW HTML TO PRESERVE TABLES AND IMAGES
        page_html = str(article)
        page_title = soup.title.string.strip() if soup.title else "Update Details"
        
        # Make content copyright free using Groq AI (It will preserve tables & images)
        rewritten_html = rewrite_with_groq(page_html)
        
        print(f"   ↳ ⏳ [DEBUG] Creating sub-PAGE for mirrored content...")
        mirrored_link = publish_to_wordpress(f"Details: {page_title[:40]}", rewritten_html)
        
        if mirrored_link:
            return mirrored_link
    except Exception as e:
        print(f"   ↳ ⚠️ [DEBUG] Deep mirroring failed: {e}")
    return url 

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
    if not last_guid: 
        new_items = items
    else:
        for i, it in enumerate(items):
            if it["guid"] == last_guid:
                break
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
            ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
            if any(kw in raw_text.lower() for kw in ad_keywords):
                print("   ↳ 🚫 [DEBUG] Promotional Ad detected. Skipping.")
                write_last(current_item["guid"])
                continue

            raw_text = brand_replacer(raw_text)

            # Attachment Dropper for Competitor Keywords
            if "राजस्थान न्यूज़ टूडे" in raw_text:
                current_item["enclosure_url"] = None
                ctype = "" 

            # Webpage Scraping (Retaining HTML Formatting)
            found_urls = re.findall(r'https?://[^\s<>"]+', raw_text)
            webpage_scraped_html = raw_text
            
            if found_urls:
                primary_link = found_urls[0]
                
                # Rule 6: Mirror ONLY indianaukrihelp.com
                if "indianaukrihelp.com" in primary_link:
                    new_mirrored_link = deep_scrape_and_mirror(primary_link)
                    raw_text = raw_text.replace(primary_link, new_mirrored_link)
                    webpage_scraped_html = raw_text
                
                # Standard web scraping for normal official links
                elif not primary_link.startswith("[https://t.me/](https://t.me/)") and "positronacademy.in" not in primary_link:
                    print(f"   ↳ 🌐 [DEBUG] Valid Link found. Scraping for HTML structure: {primary_link}")
                    try:
                        resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
                        if resp.status_code == 200:
                            soup = BeautifulSoup(resp.text, 'html.parser')
                            for a in soup.find_all('a', href=True):
                                href = a['href']
                                anchor_text = a.get_text(strip=True) or "Link"
                                
                                if "indianaukrihelp.com" in href:
                                    mirrored_href = deep_scrape_and_mirror(href)
                                    a.replace_with(f"{anchor_text} (Link: {mirrored_href})")
                                elif href.startswith("http") and not href.startswith("[https://t.me/](https://t.me/)"):
                                    pass # Keep official links as they are
                                else:
                                    a.decompose()
                                    
                            for element in soup(["script", "style", "nav", "footer", "header"]):
                                element.extract()
                                
                            # 🔥 Grab the HTML block instead of pure text
                            article_main = soup.find(class_=re.compile("entry-content|post-content|content-area"))
                            if not article_main: article_main = soup.find("main")
                            if not article_main: article_main = soup.find("body")
                            
                            if article_main:
                                page_html_code = str(article_main)
                                webpage_scraped_html = brand_replacer(page_html_code)[:4500]
                    except Exception as e: 
                        print(f"   ↳ ⚠️ [DEBUG] Webpage scrape failed: {e}")

            # AI processing (Pass HTML)
            wp_content = rewrite_with_groq(webpage_scraped_html)
            if current_item["enclosure_url"] and ctype.startswith("image/"):
                wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;">'

            new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)
            
            if new_wp_link:
                print("   ↳ 🛠 [DEBUG] Formatting Final Telegram Caption...")
                
                # Removing double headings and [...] without removing links
                clean_caption = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', raw_text)
                
                # Cleanup HTML tags if they accidentally leaked into Telegram raw_text
                clean_caption = strip_tags(clean_caption)
                
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
                print("   ↳ ❌ [DEBUG] WordPress failed for this item. Proceeding to next.")
        except Exception as e:
            print(f"   ↳ ❌ [CRITICAL] Loop error on item: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    main()
