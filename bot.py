import os, re, html, time, io
import requests
import urllib3
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI

# 🛡️ SSL Warnings Disable
urllib3.disable_warnings()

print("🛠 [DEBUG] SYSTEM BOOTING UP - IMPROVED VERSION...")

# --- CONFIGURATION ---
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    DEST_CHANNELS = os.environ["DEST_CHANNEL"]
    FEED_URL = os.environ["FEED_URL"]
    LAST_FILE = "last.txt"
    
    # Apne Channels
    FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/RAJASTHAN_TODAY"
    FOLLOW_LINE_WA = "📢 Join WhatsApp: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"
    
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
    print("🛠 [DEBUG] Environment Variables Loaded Successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Missing Environment Variables: {e}")
    exit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

# --- TELEGRAM FUNCTIONS ---
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

# Username Fixer
def fix_usernames(match):
    uname = match.group(0).lower()
    if uname in ["@shikshavibhag", "@indianaukrihelp"]:
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

# PDF Sanitizer
def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    try:
        src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        for page in src.pages:
            if "/Annots" not in page:
                continue
            annots = page["/Annots"]
            new_annots = []
            for a in annots:
                try:
                    obj = a.get_object()
                    if "/A" in obj: del obj["/A"]
                    if "/AA" in obj: del obj["/AA"]
                    if "/Dest" in obj: del obj["/Dest"]
                    if obj.get("/Subtype") == pikepdf.Name("/Link"):
                        continue
                    new_annots.append(a)
                except:
                    continue
            page["/Annots"] = pikepdf.Array(new_annots) if new_annots else None
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except:
        return pdf_bytes

# --- RSS PARSER ---
def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return m.group(1).strip() if m else ""

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    guid = pick("guid") or pick("link")

    enc_url = enc_type = None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url, enc_type = m_enc.group(1), m_enc.group(2)

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)

    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)

    return {
        "guid": guid,
        "title": title[:100] if title else "Educational Update",
        "text": combined,
        "enclosure_url": enc_url,
        "enclosure_type": enc_type
    }

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

# --- GROQ REWRITER ---
def rewrite_with_groq(source_content: str) -> str:
    try:
        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert SEO blog writer for Positron Academy / Rajasthan Today.
Rewrite the given content into a detailed, engaging, unique Hinglish article.
- Never mention 'indianaukrihelp.com', 'शिक्षा विभाग समाचार राजस्थान' or any competitor.
- Replace any competitor Telegram/WhatsApp links with our links only.
- Convert important URLs into proper HTML anchor tags like <a href='URL'>Click Here</a>
- Keep content natural and informative."""
                },
                {"role": "user", "content": f"Create detailed article:\n\n{source_content}"}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.6
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq Error: {e}")
        return source_content

# --- WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    wp_url = os.environ.get("WP_URL")
    if not wp_url:
        return None

    clean_slug = f"rajasthan-update-{int(time.time())}"
    data = {
        'title': title,
        'content': content,
        'status': 'publish',
        'slug': clean_slug
    }

    try:
        response = requests.post(
            wp_url,
            auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")),
            data=data,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=60,
            verify=False
        )
        if response.status_code in [200, 201]:
            link = response.json().get("link", "")
            print(f"✅ WP Published: {link}")
            return link
    except Exception as e:
        print(f"WP Publish Error: {e}")
    return None

# --- MAIN ENGINE ---
def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_guid = read_last()

    try:
        xml_resp = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45)
        items = parse_all_items(xml_resp.text)
    except Exception as e:
        print(f"RSS Fetch Error: {e}")
        return

    if not items:
        return

    # Get new items
    new_items = []
    if not last_guid:
        new_items = items
    else:
        for i, item in enumerate(items):
            if item["guid"] == last_guid:
                new_items = items[i+1:]
                break
        else:
            new_items = [items[-1]]  # fallback

    if not new_items:
        print("✅ No new updates.")
        return

    new_items.reverse()  # oldest first

    for item in new_items:
        print(f"\n🔄 Processing: {item['guid']}")

        raw_text = item['text']
        ctype = (item["enclosure_type"] or "").lower()

        # Ad Blocker
        if any(kw in raw_text.lower() for kw in ['t.me/+', 'sponsor', 'betting', 'aviator', 'casino', 'paid']):
            write_last(item["guid"])
            continue

        # Competitor Name Replace
        raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "Rajasthan Today")
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # === CRITICAL FIX: Competitor Link Handling ===
        found_links = URL_RE.findall(raw_text)
        final_content_for_ai = raw_text
        wp_link_to_use = None

        if found_links:
            primary_link = found_links[0]
            
            # Agar competitor site hai to scrape + apna post banao
            if "indianaukrihelp.com" in primary_link:
                print("🕵️ Competitor link detected → Deep Scraping...")
                try:
                    resp = requests.get(primary_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                        element.extract()
                    
                    page_text = soup.get_text(separator="\n")
                    page_text = re.sub(r'indianaukrihelp\.com|शिक्षा विभाग समाचार राजस्थान', '', page_text, flags=re.I)
                    
                    final_content_for_ai = page_text[:4500]
                except Exception as e:
                    print(f"Deep scrape failed: {e}")

        # AI Rewrite
        wp_content = rewrite_with_groq(final_content_for_ai)

        # Add image if available
        if item["enclosure_url"] and ctype.startswith("image/"):
            wp_content += f'<br><br><img src="{item["enclosure_url"]}" style="max-width:100%;">'

        # Publish to WordPress
        new_wp_link = publish_to_wordpress(item["title"][:80], wp_content)

        if new_wp_link:
            # Clean caption for Telegram
            clean_caption = remove_links(raw_text)
            clean_caption = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', clean_caption)

            # Remove duplicate lines
            lines = [l.strip() for l in clean_caption.split('\n') if l.strip()]
            if len(lines) > 1 and (lines[0] in lines[1] or lines[1] in lines[0]):
                lines.pop(0)

            telegram_caption = (
                f"{'\n\n'.join(lines)}\n\n"
                f"🌐 Read Full Update: {new_wp_link}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            ).strip()

            # Send to Telegram
            if item["enclosure_url"] and ctype == "application/pdf":
                try:
                    pdf = requests.get(item["enclosure_url"], timeout=300, verify=False)
                    safe_pdf = sanitize_pdf_remove_links(pdf.content)
                    for ch in channels:
                        tg_send_document_bytes(safe_pdf, "official_notice.pdf", telegram_caption, ch)
                except:
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            elif item["enclosure_url"] and ctype.startswith("image/"):
                try:
                    img = requests.get(item["enclosure_url"], timeout=180, verify=False)
                    for ch in channels:
                        tg_send_photo_bytes(img.content, telegram_caption, ch)
                except:
                    for ch in channels:
                        tg_send_text(telegram_caption, ch)
            else:
                for ch in channels:
                    tg_send_text(telegram_caption, ch)

            write_last(item["guid"])
            print(f"✅ Successfully processed: {item['guid']}")
        else:
            print("❌ WP Publish Failed")
            break

        time.sleep(4)

if __name__ == "__main__":
    main()
