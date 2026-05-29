import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

# 🛡️ Disable Warnings
urllib3.disable_warnings()
print("🛠 [DEBUG] SYSTEM BOOTING: BRAND PROTECTION & HTML MIRRORING MODE...")

# --- ENV VARIABLES ---
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
    
    client = OpenAI(api_key=os.environ.get("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Env Variables Missing: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

# --- TELEGRAM SENDER FUNCTIONS ---
def tg_send_text(text: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": True}, timeout=60)

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching PHOTO to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    requests.post(url, data={"chat_id": channel, "caption": caption[:900]}, files={"photo": ("image.jpg", photo_bytes)}, timeout=180)

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching PDF to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    requests.post(url, data={"chat_id": channel, "caption": caption[:900]}, files={"document": (filename, doc_bytes, "application/pdf")}, timeout=300)

# --- UTILITIES ---
def read_last():
    return open(LAST_FILE, "r", encoding="utf-8").read().strip() if os.path.exists(LAST_FILE) else ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)
    print(f"   ↳ 🛠 [DEBUG] last.txt updated with ID: {val}")

def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag": return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

# 🔥 CORE BRAND REPLACER
def brand_replacer(text):
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
            new_annots = [a for a in annots if not ("/A" in a.get_object() or "/AA" in a.get_object())]
            if new_annots: page["/Annots"] = pikepdf.Array(new_annots)
            elif "/Annots" in page: del page["/Annots"]
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except: return pdf_bytes

# --- WP & GROQ ---
def rewrite_with_groq(source_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] Sending content to Groq AI...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an expert SEO blog writer for Positron Academy. Rewrite the text into a detailed, unique article in Hinglish. Convert important URLs into clickable HTML buttons (e.g. <a href='...'>Click Here</a>). Do NOT include 'indianaukrihelp.com' or 'शिक्षा विभाग समाचार राजस्थान'."},
                {"role": "user", "content": f"Create a detailed website article:\n\n{source_content[:3000]}"}
            ],
            model="llama-3.1-8b-instant", temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"   ↳ ❌ [DEBUG] Groq AI Failed: {e}")
        return source_content

def publish_to_wordpress(title, content):
    print(f"   ↳ ⏳ [DEBUG] Publishing to WordPress...")
    clean_content = brand_replacer(content)
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    data = {'title': brand_replacer(title), 'content': clean_content, 'status': 'publish', 'slug': f"update-{int(time.time() * 1000)}"}
    try:
        response = requests.post(WP_URL, auth=(WP_USER, WP_PASS), data=data, headers=headers, timeout=60, verify=False)
        if response.status_code == 201: return response.json().get("link", "")
        else: print(f"   ↳ ❌ [DEBUG] WP Error {response.status_code}: {response.text}")
    except Exception as e: print(f"   ↳ ❌ [DEBUG] WP Request failed: {e}")
    return None

# 🔥 DEEP HTML SCRAPER (Fix for blank pages)
def deep_scrape_and_mirror(url):
    print(f"   ↳ 🕵️ [DEBUG] Mirroring Sub-Page: {url}")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
        if r.status_code != 200: return url
        
        soup = BeautifulSoup(r.text, 'html.parser')
        for e in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]): e.extract()
        
        # Pura HTML block nikalna jisse formatting bachi rahe
        article = soup.find(class_=re.compile("entry-content|post-content|content-area"))
        if not article: article = soup.find("main")
        if not article: article = soup.find("body")
        
        if not article: return url
        
        page_html = str(article) # Extract raw HTML instead of just text
        page_title = soup.title.string.strip() if soup.title else "Update Details"
        
        mirrored_link = publish_to_wordpress(f"Details: {page_title[:40]}", page_html)
        if mirrored_link:
            print(f"   ↳ ✅ [DEBUG] Mirrored Successfully! New WP Link: {mirrored_link}")
            return mirrored_link
    except Exception as e: print(f"   ↳ ⚠️ [DEBUG] Mirroring failed: {e}")
    return url

# --- MAIN LOOP ---
def main():
    print("🛠 [DEBUG] STEP 1: Starting RSS Fetch...")
    try:
        xml_resp = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45).text
        soup = BeautifulSoup(xml_resp, 'xml')
        items = []
        for item in soup.find_all('item'):
            title = item.title.text.strip() if item.title else "Update"
            desc = item.description.text.strip() if item.description else ""
            guid = item.guid.text.strip() if item.guid else title
            
            enc_url = item.enclosure['url'] if item.find('enclosure') and item.find('enclosure').has_attr('url') else None
            enc_type = item.enclosure['type'] if item.find('enclosure') and item.find('enclosure').has_attr('type') else ""
            
            clean_title = re.sub(r"^\[Photo\]\s*", "", title)
            clean_desc = re.sub(r"^\[Photo\]\s*", "", BeautifulSoup(desc, "html.parser").get_text())
            items.append({"guid": guid, "title": clean_title, "text": f"{clean_title}\n\n{clean_desc}", "enclosure_url": enc_url, "enclosure_type": enc_type})
    except Exception as e:
        print(f"❌ [CRITICAL] RSS Error: {e}")
        return

    last_guid = read_last()
    new_items = []
    if not last_guid: new_items = items
    else:
        for i, it in enumerate(items):
            if it["guid"] == last_guid: break
            new_items.append(it)
    
    if not new_items: 
        print("✅ [DEBUG] System Up To Date.")
        return
        
    new_items.reverse()
    print(f"📥 [DEBUG] Processing {len(new_items)} new messages.")

    for current_item in new_items:
        print(f"\n👉 [DEBUG] ====== ITEM: {current_item['title'][:40]} ======")
        try:
            raw_text = current_item['text']
            ctype = (current_item["enclosure_type"] or "").lower()

            if any(kw in raw_text.lower() for kw in ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']):
                print("   ↳ 🚫 [DEBUG] Ad skipped.")
                write_last(current_item["guid"])
                continue

            raw_text = brand_replacer(raw_text)
            if "राजस्थान न्यूज़ टूडे" in raw_text:
                current_item["enclosure_url"] = None
                ctype = "" 

            found_links = URL_RE.findall(raw_text)
            if found_links:
                primary_link = found_links[0]
                if "indianaukrihelp.com" in primary_link:
                    mirrored_link = deep_scrape_and_mirror(primary_link)
                    raw_text = raw_text.replace(primary_link, mirrored_link)
            
            wp_content = rewrite_with_groq(raw_text)
            if current_item["enclosure_url"] and ctype.startswith("image/"):
                wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;">'

            new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)
            
            if new_wp_link:
                # Telegram formatting
                clean_cap = URL_RE.sub("", raw_text).strip()
                clean_cap = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', clean_cap)
                
                lines = [l.strip() for l in clean_cap.split('\n') if l.strip()]
                if len(lines) > 1 and (lines[0] in lines[1] or lines[1] in lines[0]): lines.pop(0)
                
                tg_caption = f"{chr(10).join(lines)}\n\n🌐 {new_wp_link}\n\n━━━━━━━━━━━━━━\n{FOLLOW_LINE_TG}\n{FOLLOW_LINE_WA}"

                channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
                if current_item["enclosure_url"] and ctype == "application/pdf":
                    try:
                        safe_pdf = sanitize_pdf_remove_links(requests.get(current_item["enclosure_url"], timeout=60, verify=False).content)
                        for ch in channels: tg_send_document_bytes(safe_pdf, "official_circular.pdf", tg_caption, ch)
                    except:
                        for ch in channels: tg_send_text(tg_caption, ch)
                elif current_item["enclosure_url"] and ctype.startswith("image/"):
                    try:
                        img = requests.get(current_item["enclosure_url"], timeout=60, verify=False).content
                        for ch in channels: tg_send_photo_bytes(img, tg_caption, ch)
                    except:
                        for ch in channels: tg_send_text(tg_caption, ch)
                else:
                    for ch in channels: tg_send_text(tg_caption, ch)

                write_last(current_item["guid"])
            else:
                print("   ↳ ❌ [DEBUG] WP failed for this post, continuing to next.")
            time.sleep(3)
        except Exception as e:
            print(f"   ↳ ❌ [CRITICAL] Error processing item: {e}")

if __name__ == "__main__":
    main()
