import os
import re
import html
import time
import io
import hashlib
import requests
import urllib3
from bs4 import BeautifulSoup
import pikepdf
from openai import OpenAI
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

# =========================================================
# CONFIG
# =========================================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("🛠 [DEBUG] SYSTEM BOOTING UP WITH FIXED RSS + SAFE LINK ROUTING...")

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
    print("🛠 [DEBUG] Environment variables loaded successfully.")
except Exception as e:
    print(f"❌ [CRITICAL ERROR] Missing environment variables: {e}")
    raise SystemExit(1)

URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
BLOCKED_SOURCE_DOMAINS = {"indianaukrihelp.com"}

# =========================================================
# TELEGRAM SENDERS
# =========================================================

def tg_send_text(text: str, channel: str):
    print(f"   ↳ 🛠 [DEBUG] Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": channel,
        "text": text[:3900],
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload, timeout=60).raise_for_status()

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

# =========================================================
# BASIC UTILS
# =========================================================

def read_last():
    if os.path.exists(LAST_FILE):
        with open(LAST_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def write_last(val: str):
    with open(LAST_FILE, "w", encoding="utf-8") as f:
        f.write(val)
    print(f"   ↳ 🛠 [DEBUG] last.txt updated with ID: {val}")

def strip_tags(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s or "")
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s or "", flags=re.I).strip()

def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def is_blocked_source(url: str) -> bool:
    d = domain_of(url)
    return any(blocked == d or d.endswith("." + blocked) for blocked in BLOCKED_SOURCE_DOMAINS)

def clean_code_fences(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:html|markdown|md)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

def stable_key(item: dict) -> str:
    base = f"{item.get('guid','')}|{item.get('link','')}|{item.get('title','')}"
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()

# =========================================================
# PDF SANITIZER
# =========================================================

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    print("   ↳ 🛠 [DEBUG] Sanitizing PDF (removing clickable links)...")
    try:
        src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        for page in src.pages:
            annots = page.get("/Annots", None)
            if not annots:
                continue

            new_annots = []
            for a in annots:
                try:
                    obj = a.get_object()
                    if "/A" in obj:
                        del obj["/A"]
                    if "/AA" in obj:
                        del obj["/AA"]
                    if "/Dest" in obj:
                        del obj["/Dest"]
                    if obj.get("/Subtype", None) == pikepdf.Name("/Link"):
                        continue
                    new_annots.append(a)
                except Exception:
                    continue

            if new_annots:
                page["/Annots"] = pikepdf.Array(new_annots)
            elif "/Annots" in page:
                del page["/Annots"]

        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except Exception as e:
        print(f"   ↳ ❌ [DEBUG] PikePDF error: {e}")
        return pdf_bytes

# =========================================================
# RSS PARSING
# =========================================================

def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def parse_item_element(item_el) -> dict:
    data = {
        "title": "",
        "description": "",
        "link": "",
        "guid": "",
        "pubDate": "",
        "enclosure_url": None,
        "enclosure_type": None,
    }

    for child in list(item_el):
        tag = strip_ns(child.tag).lower()

        if tag == "enclosure":
            data["enclosure_url"] = child.attrib.get("url")
            data["enclosure_type"] = child.attrib.get("type")
            continue

        text = "".join(child.itertext()) if child is not None else ""
        text = text.strip()

        if tag in data:
            data[tag] = text

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", data["title"] or "")
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", data["description"] or "")

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)
    desc = re.sub(r"^\[Photo\]\s*", "", desc).strip()

    guid = (data["guid"] or data["link"] or "").strip()
    if not guid:
        guid = hashlib.sha1(f"{title}|{desc}".encode("utf-8", errors="ignore")).hexdigest()

    combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)

    return {
        "guid": guid,
        "title": title[:80] if title else "Educational Update",
        "link": data["link"].strip(),
        "pubDate": data["pubDate"].strip(),
        "text": combined,
        "enclosure_url": data["enclosure_url"],
        "enclosure_type": data["enclosure_type"],
        "fingerprint": stable_key({"guid": guid, "link": data["link"], "title": title}),
    }

def parse_all_items(xml_text: str):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"❌ [CRITICAL ERROR] RSS XML parse failed: {e}")
        return items

    for item_el in root.findall(".//item"):
        try:
            items.append(parse_item_element(item_el))
        except Exception as e:
            print(f"   ↳ ⚠️ [DEBUG] Skipping broken item: {e}")
            continue
    return items

# =========================================================
# PAGE SCRAPING
# =========================================================

def scrape_page_to_text(page_url: str) -> str:
    """
    Fetch page and convert visible content to text.
    External links are stripped from the final text to prevent click-outs.
    """
    print(f"   ↳ 🌐 [DEBUG] Scraping page: {page_url}")
    resp = requests.get(
        page_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
        verify=False
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for element in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        element.extract()

    # Remove anchors that point to blocked/external domains
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http"):
            text = a.get_text(" ", strip=True)
            a.replace_with(text if text else "")
        else:
            # relative links / fragments are also flattened for safety
            text = a.get_text(" ", strip=True)
            a.replace_with(text if text else "")

    page_text = soup.get_text(separator="\n")
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    page_text = "\n".join(lines)

    # Clean source branding leakage
    page_text = page_text.replace("indianaukrihelp.com", "")
    page_text = page_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")

    return page_text[:4000].strip()

# =========================================================
# GROQ REWRITE
# =========================================================

def rewrite_with_groq(source_content: str) -> str:
    print("   ↳ ⏳ [DEBUG] Sending content to Groq AI for rewriting...")
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert SEO blog writer for Positron Academy. "
                        "Rewrite the text into a detailed, unique article in Hinglish. "
                        "Use clean HTML. Do not include external promotional channel links. "
                        "Do not mention any competitor brand names unless they are part of the source text and necessary for context. "
                        "Do not output code fences."
                    )
                },
                {
                    "role": "user",
                    "content": f"Create a detailed website article from this source:\n\n{source_content}"
                }
            ],
        )
        content = response.choices[0].message.content or ""
        print("   ↳ ✅ [DEBUG] Groq AI generated article.")
        return clean_code_fences(content)
    except Exception as e:
        print(f"   ↳ ❌ [DEBUG ERROR] Groq AI failed: {e}")
        return source_content

def normalize_wp_html(html_text: str) -> str:
    """
    Strip risky/external click-outs from the article body.
    We keep the content self-contained and then add one owned CTA after publish.
    """
    soup = BeautifulSoup(html_text or "", "html.parser")

    for tag in soup(["script", "style", "iframe", "form"]):
        tag.decompose()

    # Remove all external links from article body.
    for a in soup.find_all("a", href=True):
        visible = a.get_text(" ", strip=True)
        a.replace_with(visible if visible else "")

    # Basic cleanup
    out = str(soup)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

# =========================================================
# WORDPRESS PUBLISH / UPDATE
# =========================================================

def get_wp_api_base() -> str:
    wp_url = os.environ.get("WP_URL", "").strip()
    if not wp_url:
        raise RuntimeError("WP_URL missing")
    return wp_url.rstrip("/")

def publish_to_wordpress(title: str, content: str):
    wp_url = get_wp_api_base()
    print(f"   ↳ ⏳ [DEBUG] Publishing to WordPress: {wp_url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }

    data = {
        "title": title,
        "content": content,
        "status": "publish",
        "slug": f"update-{int(time.time())}"
    }

    try:
        response = requests.post(
            wp_url,
            auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")),
            data=data,
            headers=headers,
            timeout=60,
            verify=False
        )

        if response.status_code in (200, 201):
            try:
                payload = response.json()
            except Exception:
                payload = {}

            post_id = payload.get("id")
            link = payload.get("link", "")
            print(f"   ↳ ✅ [DEBUG] WordPress publish success! ID={post_id}, Link={link}")
            return post_id, link
        else:
            print(f"   ↳ ❌ [DEBUG ERROR] WP rejected post. Status Code: {response.status_code}. Response: {response.text[:500]}")
    except Exception as e:
        print(f"   ↳ ❌ [CRITICAL ERROR] WordPress request failed: {e}")

    return None, None

def update_wordpress_post(post_id, title: str, content: str):
    if not post_id:
        return False

    wp_url = get_wp_api_base()
    endpoint = f"{wp_url}/{post_id}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }

    data = {
        "title": title,
        "content": content,
        "status": "publish",
    }

    try:
        response = requests.post(
            endpoint,
            auth=(os.environ.get("WP_USER"), os.environ.get("WP_PASS")),
            data=data,
            headers=headers,
            timeout=60,
            verify=False
        )

        if response.status_code in (200, 201):
            print("   ↳ ✅ [DEBUG] WordPress post updated with final CTA.")
            return True
        else:
            print(f"   ↳ ⚠️ [DEBUG] WP update failed. Status={response.status_code}, resp={response.text[:300]}")
    except Exception as e:
        print(f"   ↳ ⚠️ [DEBUG] WP update exception: {e}")

    return False

def build_telegram_caption(raw_text: str, wp_link: str) -> str:
    clean_caption = remove_links(raw_text)
    clean_caption = re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', clean_caption)

    lines = [l.strip() for l in clean_caption.split("\n") if l.strip()]
    if len(lines) > 1:
        if lines[0] in lines[1] or lines[1] in lines[0]:
            lines.pop(0)

    clean_caption = "\n\n".join(lines).strip()

    caption = (
        f"{clean_caption}\n\n"
        f"🌐 {wp_link}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"{FOLLOW_LINE_TG}\n"
        f"{FOLLOW_LINE_WA}"
    ).strip()

    return caption[:3900]

# =========================================================
# MAIN
# =========================================================

def main():
    print("\n🛠 [DEBUG] STEP 1: Loading channels and last state.")
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    last_key = read_last()
    print(f"   ↳ Memory state -> Last key: '{last_key}'")

    print(f"🛠 [DEBUG] STEP 2: Fetching RSS from {FEED_URL}")
    try:
        xml_resp = requests.get(
            FEED_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=45
        )
        xml_resp.raise_for_status()
        items = parse_all_items(xml_resp.text)
        print(f"   ↳ ✅ [DEBUG] Parsed {len(items)} items from feed.")
    except Exception as e:
        print(f"❌ [CRITICAL ERROR] Failed to fetch RSS: {e}")
        return

    if not items:
        print("✅ [DEBUG] No feed items found.")
        return

    print("🛠 [DEBUG] STEP 3: Calculating pending items.")
    new_items = []

    if not last_key:
        new_items = items
    else:
        found_idx = -1
        for i, it in enumerate(items):
            key = it.get("fingerprint") or it.get("guid")
            if key == last_key:
                found_idx = i
                break

        if found_idx != -1:
            new_items = items[found_idx + 1:]
        else:
            # Fallback: process only the newest item if last key not found
            new_items = [items[-1]]

    if not new_items:
        print("✅ [DEBUG] System up to date.")
        return

    new_items.reverse()  # oldest first
    print(f"📥 [DEBUG] Processing {len(new_items)} new items.")

    for current_item in new_items:
        item_key = current_item.get("fingerprint") or current_item.get("guid")
        print(f"\n👉 [DEBUG] ====== PROCESSING ITEM: {item_key} ======")

        raw_text = current_item["text"] or ""
        ctype = (current_item.get("enclosure_type") or "").lower()

        # -------------------------------------------------
        # Ad / spam skip
        # -------------------------------------------------
        ad_keywords = ['t.me/+', 'sponsor', 'paid promo', 'aviator', 'betting', 'casino']
        if any(kw in raw_text.lower() for kw in ad_keywords):
            print("   ↳ 🚫 [DEBUG] Promotional ad detected. Skipping.")
            write_last(item_key)
            continue

        # -------------------------------------------------
        # Brand replacement
        # -------------------------------------------------
        if "शिक्षा विभाग समाचार राजस्थान" in raw_text:
            print("   ↳ 🛠 [DEBUG] Brand string found. Replacing.")
            raw_text = raw_text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")

        # Username normalization
        raw_text = re.sub(r'@[A-Za-z0-9_]+', fix_usernames, raw_text)

        # -------------------------------------------------
        # Source page extraction
        # -------------------------------------------------
        source_for_ai = raw_text
        found_links = URL_RE.findall(raw_text)

        if found_links:
            primary_link = found_links[0].strip()

            # Never send Telegram links to scrape stage.
            if not primary_link.startswith("https://t.me/") and not primary_link.startswith("http://t.me/"):
                print(f"   ↳ 🌐 [DEBUG] Found link, preparing page extraction: {primary_link}")

                try:
                    # If it's a blocked domain or any external source page,
                    # extract text only and remove click-out links.
                    source_for_ai = scrape_page_to_text(primary_link)

                except Exception as e:
                    print(f"   ↳ ⚠️ [DEBUG] Page scrape failed: {e}")
                    source_for_ai = raw_text

        # -------------------------------------------------
        # AI rewrite
        # -------------------------------------------------
        wp_content = rewrite_with_groq(source_for_ai)
        wp_content = normalize_wp_html(wp_content)

        # For image enclosure, append image tag after rewrite
        if current_item.get("enclosure_url") and ctype.startswith("image/"):
            wp_content += f'<br><br><img src="{current_item["enclosure_url"]}" style="max-width:100%;height:auto;">'

        # -------------------------------------------------
        # First publish
        # -------------------------------------------------
        temp_content = wp_content + "\n\n<!-- CTA_PLACEHOLDER -->"
        post_id, new_wp_link = publish_to_wordpress(current_item["title"][:50], temp_content)

        if not new_wp_link:
            print("❌ [CRITICAL] WordPress publish failed. Halting batch loop to protect sequence.")
            break

        # -------------------------------------------------
        # Update WP post with own CTA link only
        # -------------------------------------------------
        final_wp_content = wp_content + (
            f'<br><br><a href="{new_wp_link}" '
            f'style="display:inline-block;padding:12px 18px;background:#111;color:#fff;'
            f'text-decoration:none;border-radius:8px;font-weight:700;">'
            f'Read Full Update on Our Website</a>'
        )
        update_wordpress_post(post_id, current_item["title"][:50], final_wp_content)

        # -------------------------------------------------
        # Telegram caption: only own WP link + own channel links
        # -------------------------------------------------
        telegram_caption = build_telegram_caption(raw_text, new_wp_link)

        if current_item.get("enclosure_url") and ctype == "application/pdf":
            try:
                pdf = requests.get(current_item["enclosure_url"], timeout=300, verify=False)
                pdf.raise_for_status()
                safe_pdf = sanitize_pdf_remove_links(pdf.content)
                for ch in channels:
                    tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, ch)
            except Exception as e:
                print(f"   ↳ ❌ [DEBUG] PDF failed: {e}. Sending text instead.")
                for ch in channels:
                    tg_send_text(telegram_caption, ch)

        elif current_item.get("enclosure_url") and ctype.startswith("image/"):
            try:
                img = requests.get(current_item["enclosure_url"], timeout=180, verify=False)
                img.raise_for_status()
                for ch in channels:
                    tg_send_photo_bytes(img.content, telegram_caption, ch)
            except Exception as e:
                print(f"   ↳ ⚠️ [DEBUG] Image send failed: {e}. Sending text instead.")
                for ch in channels:
                    tg_send_text(telegram_caption, ch)
        else:
            for ch in channels:
                tg_send_text(telegram_caption, ch)

        write_last(item_key)
        time.sleep(3)

if __name__ == "__main__":
    main()
