import os, re, html, time, io
import requests
import urllib3
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# 🛡️ SSL Warnings Disable (Firewall bypass ke liye zaroori)
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING UP WITH 6 RULES & DEEP DEBUGGING...")

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
    print("🛠 [DEBUG] Environment Variables Loaded Successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Missing Environment Variables: {e}")
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
    s = re.sub(r"<.*?>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

# 🔥 RULE 4: Username Replacer
def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

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
    print("   ↳ ⏳ [DEBUG] Sending content to Groq AI for rewriting...")
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
        print("   ↳ ✅ [DEBUG] Groq AI successfully generated the article.")
        return response.choices[0].message.content
    except Exception as e: 
        print(f"   ↳ ❌ [DEBUG ERROR] Groq AI Failed: {e}")
        return source_content

def publish_to_wordpress(title, content):
    wp_url = os.environ.get("WP_URL")
    print(f"   ↳ ⏳ [DEBUG] Publishing to WordPress: {wp_url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0',
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    clean_slug = f"update-{int(time.time())}"
    data = {'title': title, 'content': content, 'status': 'publish', 'slug': clean_slug}
    try:
        response = requests.post(wp_url, auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")), data=data, headers=headers, timeout=60, verify=False)
        if response.status_code == 201: 
            link = response.json().get("link", "")
            print(f"   ↳ ✅ [DEBUG] WordPress Publish Success! Link: {link}")
            return link
        else:
            print(f"   ↳ ❌ [DEBUG ERROR] WP rejected post. Status Code: {response.status_code}. Response: {response.text}")
    except Exception as e: 
        print(f"   ↳ ❌ [CRITICAL ERROR] WordPress request failed: {e}")
    return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    print("\n🛠 [DEBUG] STEP 1: Fetching settings.")
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    print(f"   ↳ Memory state -> Last GUID: '{last_guid}'")

    print(f"🛠 [DEBUG] STEP 2: Fetching RSS from {FEED_URL}")
    try:
        xml_resp = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45)
        items = parse_all_items(xml_resp.text)
        print(f"   ↳ ✅ [DEBUG] Parsed {len(items)} items from feed.")
    except Exception as e: 
        print(f"❌ [CRITICAL ERROR] Failed to fetch RSS: {e}")
        return

    if not items: return

    print("🛠 [DEBUG] STEP 3: Calculating pending sequence.")
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

    if not new_items: 
        print("✅ [DEBUG] System Up To Date.")
        return
        
    new_items.reverse() # Process oldest first
    print(f"📥 [DEBUG] Processing {len(new_items)} new messages.")

    for current_item in new_items:
        print(f"\n👉 [DEBUG] ====== PROCESSING ITEM: {current_item['guid']} ======")
        raw_text = current_item['text']
        ctype = (current_item["enclosure_type"] or "").lower()

        # 🔥 RULE 3: Ad Blocker
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("   ↳ 🚫 [DEBUG] Promotional Ad detected. Skipping.")
            write_last(current_item["guid"])
            continue

        # 🔥 RULE 2: Keyword Replacement & Attachment Dropper
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            print("   ↳ 🛠 [DEBUG] Competitor keyword found. Replacing and dropping PDF/Image.")
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
            current_item["enclosure_url"] = None
            ctype = "" # Drop PDF/Image

        # 🔥 RULE 4: Smart Username Replacer
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # 🔥 RULE 5 & 6: Webpage Scraping & Deep Link Extraction
        found_links = URL_RE.findall(raw_text)
        webpage_scraped_data = raw_text # Fallback
        
        if found_links:
            primary_link = found_links[0]
            if not primary_link.startswith("https://t.me/"):
                print(f"   ↳ 🌐 [DEBUG] Valid Link found. Scraping: {primary_link}")
                try:
                    resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25, verify=False)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            href = a['href']
                            anchor_text = a.get_text(strip=True) or "Link"
                            
                            # 🔥 RULE 6: Deep Scraper (Competitor ke page ke andar se Asli link nikalna)
                            if "indianaukrihelp.com" in href:
                                print(f"   ↳ 🕵️ [DEBUG] Deep scraping competitor link: {href}")
                                try:
                                    deep_resp = requests.get(href, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
                                    deep_soup = BeautifulSoup(deep_resp.text, 'html.parser')
                                    deep_links_extracted = []
                                    for deep_a in deep_soup.find_all('a', href=True):
                                        dh = deep_a['href']
                                        if dh.startswith("http") and "indianaukrihelp.com" not in dh and not dh.startswith("https://t.me/"):
                                            deep_links_extracted.append(f"{deep_a.get_text(strip=True)} (Link: {dh})")
                                    if deep_links_extracted:
                                        a.replace_with(" | ".join(deep_links_extracted))
                                    else:
                                        a.decompose()
                                except: a.decompose()
                            
                            # 🔥 RULE 5: Keep normal useful links
                            elif href.startswith("http") and not href.startswith("https://t.me/"):
                                a.replace_with(f"{anchor_text} (Link: {href})")
                            else:
                                a.decompose()
                                
                        for element in soup(["script", "style", "nav", "footer", "header"]):
                            element.extract()
                            
                        page_text = soup.get_text(separator="\n").replace("indianaukrihelp.com", "").replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
                        lines = (line.strip() for line in page_text.splitlines() if line.strip())
                        webpage_scraped_data = '\n'.join(lines)[:4000]
                except Exception as e: 
                    print(f"   ↳ ⚠️ [DEBUG] Webpage scrape failed: {e}")

        # AI processing
        wp_content = rewrite_with_groq(webpage_scraped_data)
        if current_item["enclosure_url"] and ctype.startswith("image/"):
            wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;">'

        new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)
        
        if new_wp_link:
            # 🔥 RULE 1: Remove Duplicate Headings & `[...]`
            print("   ↳ 🛠 [DEBUG] Formatting Final Telegram Caption...")
            clean_caption = remove_links(raw_text)
            clean_caption = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', clean_caption) # Gayab karo [...]
            
            # Agar pehli aur dusri line same hai toh ek ko delete karo
            lines = [l.strip() for l in clean_caption.split('\n') if l.strip()]
            if len(lines) > 1:
                if lines[0] in lines[1] or lines[1] in lines[0]:
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
                except Exception as e:
                    print(f"   ↳ ❌ [DEBUG] PDF Failed: {e}. Sending text instead.")
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
            print("❌ [CRITICAL] WordPress completely failed. Halting batch loop to protect sequence.")
            break 
        
        time.sleep(3)

if __name__ == "__main__":
    main()
