import os, re, html, time, io
import requests
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI
from urllib.parse import urljoin

# --- CONFIGURATION & ENV VARIABLES ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"] # Comma-separated: @ch1,@ch2
FEED_URL = os.environ["FEED_URL"]          # Source Telegram Channel
LAST_FILE = "last.txt"

# Setup Groq AI Client
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Links detect karne aur hatane ke liye Regex
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
    requests.post(url, json={
        "chat_id": channel,
        "text": text[:3900],
        "disable_web_page_preview": False
    }, timeout=60).raise_for_status()

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
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

# --- ORIGINAL PIKEPDF LINK SANITIZER ---
def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    print("🧹 Sanitizing PDF: Removing internal/external clickable links...")
    src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
    for page in src.pages:
        annots = page.get("/Annots", None)
        if not annots: continue
        new_annots = []
        for a in annots:
            try:
                obj = a.get_object()
            except Exception: continue
            if "/A" in obj: del obj["/A"]
            if "/AA" in obj: del obj["/AA"]
            if "/Dest" in obj: del obj["/Dest"]
            if obj.get("/Subtype", None) == pikepdf.Name("/Link"): continue
            new_annots.append(a)
        if new_annots:
            page["/Annots"] = pikepdf.Array(new_annots)
        else:
            if "/Annots" in page: del page["/Annots"]
    out = io.BytesIO()
    src.save(out)
    return out.getvalue()

# --- TELEGRAM CHANNEL HTML SCRAPER ---
def fetch_telegram_channel_messages():
    username = FEED_URL.strip()
    if "t.me/" in username:
        username = username.split("t.me/")[-1]
    username = username.split("/")[0].replace("@", "").strip()
    
    scrape_url = f"https://t.me/s/{username}"
    print(f"⏳ Scraping Source Telegram Channel: {scrape_url}")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    resp = requests.get(scrape_url, headers=headers, timeout=60)
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    msg_blocks = soup.find_all('div', class_='tgme_widget_message')
    items = []
    
    for block in msg_blocks:
        guid = block.get('data-post')
        if not guid: continue
        
        text_block = block.find('div', class_='tgme_widget_message_text')
        if not text_block: continue
        
        raw_text = text_block.get_text(separator='\n').strip()
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        title = lines[0] if lines else "New Update"
        
        # Image check
        img_url = None
        photo_wrap = block.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_wrap and 'style' in photo_wrap.attrs:
            style_text = photo_wrap['style']
            img_m = re.search(r"url\(['\"]?(.*?)['\"]?\)", style_text)
            if img_m:
                img_url = img_m.group(1)
                
        # 🔥 ROOT MSG PDF EXTRACTOR: Root message post ke andar hi direct attached document/PDF link nikal rahe hain
        doc_url = None
        doc_anchor = block.find('a', class_=lambda x: x and 'document' in x)
        if doc_anchor and doc_anchor.get('href'):
            doc_url = doc_anchor['href']
        else:
            doc_block = block.find(class_=lambda x: x and 'document' in x)
            if doc_block:
                a_tag = doc_block.find('a', href=True)
                if a_tag:
                    doc_url = a_tag['href']
                
        items.append({
            "guid": guid,
            "title": title[:80],
            "text": raw_text,
            "enclosure_url": img_url,
            "doc_url": doc_url
        })
        
    return items

# --- GROQ AI REWRITER ENGINE ---
def rewrite_with_groq(telegram_text: str, webpage_text: str) -> str:
    print("⏳ Rewriting content via Groq AI (Active Model: llama-3.1-8b-instant)...")
    source_content = webpage_text if len(webpage_text) > 100 else telegram_text
    
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system", 
                    "content": "You are a professional educational blog writer for Positron Academy. Rewrite the provided data into a comprehensive, detailed, 100% unique, and plagiarism-free article paragraph for a website post. Write in an engaging mix of Hindi and English (Hinglish). Do NOT include any external URLs, links or source channel credits."
                },
                {"role": "user", "content": f"Create an original detailed website article based on this information:\n\n{source_content}"}
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.5
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}. Using original message text as backup.")
        return telegram_text

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print("⏳ Creating Page on WordPress Website...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    data = {'title': title, 'content': content, 'status': 'publish'}

    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        if response.status_code == 201:
            wp_link = response.json().get("link", "")
            print(f"✅ WordPress Page Created Successfully: {wp_link}")
            return wp_link
        else:
            print(f"❌ WP Status Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
        return None

# --- MAIN CONTROLLER ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()
    print(f"DEBUG: Last GUID in database memory: {last_guid}")

    items = fetch_telegram_channel_messages()
    if not items:
        print("⚠️ No valid data extracted from source channel.")
        return

    # Sirf absolute list ka aakhri item (latest) uthao
    latest_item = items[-1]
    
    if last_guid and latest_item["guid"] == last_guid:
        print(f"✅ Latest post ({latest_item['guid']}) is already up to date. No action needed.")
        return

    print(f"📥 Processing ONLY the absolute latest message ID: {latest_item['guid']}")
    
    # 🔥 DIRECT FIX: PDF URL seedhe message ke original post attachment se hi li jayegi
    pdf_url = latest_item.get("doc_url")
    
    # Text content links check (Sirf WordPress article content scraping ke liye)
    found_links = URL_RE.findall(latest_item["text"])
    webpage_scraped_data = ""
    
    if found_links:
        primary_link = found_links[0]
        if not ("t.me/" in primary_link or "telegram.me/" in primary_link):
            print(f"🌐 Deep Scraping External Webpage for Article Text: {primary_link}")
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                resp = requests.get(primary_link, headers=headers, timeout=25)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for element in soup(["script", "style", "nav", "footer", "header"]):
                        element.extract()
                    paragraphs = soup.find_all('p')
                    page_text = "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
                    if not page_text:
                        page_text = soup.get_text(separator="\n")
                    lines = (line.strip() for line in page_text.splitlines())
                    webpage_scraped_data = '\n'.join(line for line in lines if line)[:3500]
            except Exception as e:
                print(f"⚠️ External Link text scrape error: {e}")

    # Step 3: Groq AI Rewrite for WordPress Page Content
    ai_final_text = rewrite_with_groq(latest_item["text"], webpage_scraped_data)
    
    wp_content = ai_final_text
    if latest_item["enclosure_url"]:
        wp_content += f'<br><br><img src="{latest_item["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'

    # Step 4: WordPress Publisher
    new_page_link = publish_to_wordpress(latest_item["title"], wp_content)
    
    if new_page_link:
        # Step 5: Clean root message for Telegram destination group
        clean_root_message = remove_links(latest_item["text"])
        
        telegram_caption = (
            f"{clean_root_message}\n\n"
            f"🌐 **Poori details aur official circular website par dekhein:**\n{new_page_link}"
        ).strip()

        # 🔥 Step 6: Direct Root Attached PDF Routing Execution
        if pdf_url:
            print(f"⏳ Downloading Root Attached PDF File: {pdf_url}")
            try:
                pdf_resp = requests.get(pdf_url, timeout=300)
                pdf_resp.raise_for_status()
                
                # Pikepdf Sanitizer (Purane links saaf karne ke liye)
                safe_pdf_bytes = sanitize_pdf_remove_links(pdf_resp.content)
                
                # Naye document bytes ko modified caption ke sath send karega
                for ch in channels:
                    tg_send_document_bytes(safe_pdf_bytes, "official_notification.pdf", telegram_caption, ch)
                print("🚀 SUCCESS: Root attached PDF Document + Modified caption sent to your channel!")
            except Exception as e:
                print(f"❌ PDF routing failed: {e}. Falling back to image/text.")
                pdf_url = None 

        # Fallback logic agar message ke sath direct PDF attached nahi tha
        if not pdf_url:
            if latest_item["enclosure_url"]:
                try:
                    img = requests.get(latest_item["enclosure_url"], timeout=180)
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                    print("📢 Photo + Caption forwarded successfully!")
                except Exception as e:
                    print(f"⚠️ Photo fallback text routing triggered: {e}")
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
                print("📢 Pure Text forwarded successfully!")
        
        print(f"🚀 TASK COMPLETION: Saved state to database memory.")
        write_last(latest_item["guid"])
    else:
        print("❌ Workflow stopped due to WordPress error.")

if __name__ == "__main__":
    main()
