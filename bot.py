import os
import re
import io
import json
import time
import html
import hashlib
import mimetypes
import requests
import urllib3
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from urllib.parse import urlparse
from openai import OpenAI
import pikepdf

# =====================================================
# CONFIG
# =====================================================

urllib3.disable_warnings()

CACHE_FILE = "processed_cache.json"
LOCK_FILE = "bot.lock"

FOLLOW_LINE_TG = "📢 Join Telegram: https://t.me/RAJASTHAN_TODAY"
FOLLOW_LINE_WA = "📢 Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"

BLOCKED_DOMAINS = {
    "indianaukrihelp.com",
}

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = [x.strip() for x in os.environ["DEST_CHANNEL"].split(",")]

FEED_URL = os.environ["FEED_URL"]

WP_URL = os.environ["WP_URL"]
WP_MEDIA_URL = os.environ["WP_MEDIA_URL"]

WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]

WP_CATEGORY_ID = int(os.environ.get("WP_CATEGORY_ID", "1"))

client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

URL_RE = re.compile(r'https?://\S+')

# =====================================================
# LOCK SYSTEM
# =====================================================

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        print("⚠️ Bot already running.")
        raise SystemExit()

    with open(LOCK_FILE, "w") as f:
        f.write(str(time.time()))

def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

# =====================================================
# CACHE
# =====================================================

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

CACHE = load_cache()

# =====================================================
# HELPERS
# =====================================================

def sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<.*?>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def remove_links(text):
    return URL_RE.sub("", text)

def replace_usernames(text):
    text = re.sub(r'@[A-Za-z0-9_]+', '@RAJASTHAN_TODAY', text)
    return text

def remove_competitor(text):
    for d in BLOCKED_DOMAINS:
        text = text.replace(d, "")

    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    return text

def sanitize_html(content):
    soup = BeautifulSoup(content, "html.parser")

    for tag in soup(["script", "iframe", "form", "style"]):
        tag.decompose()

    for a in soup.find_all("a"):
        txt = a.get_text(" ", strip=True)
        a.replace_with(txt)

    return str(soup)

# =====================================================
# TELEGRAM
# =====================================================

def tg(method, data=None, files=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    for _ in range(3):
        try:
            r = requests.post(
                url,
                data=data,
                files=files,
                timeout=120
            )

            if r.status_code == 200:
                return True

        except Exception as e:
            print("TG ERROR:", e)

        time.sleep(2)

    return False

def send_text(text):
    for ch in DEST_CHANNELS:
        tg("sendMessage", {
            "chat_id": ch,
            "text": text[:4000],
            "disable_web_page_preview": True
        })

def send_photo(img_bytes, caption):
    for ch in DEST_CHANNELS:
        tg(
            "sendPhoto",
            {"chat_id": ch, "caption": caption[:900]},
            {"photo": ("image.jpg", img_bytes)}
        )

def send_pdf(pdf_bytes, caption):
    for ch in DEST_CHANNELS:
        tg(
            "sendDocument",
            {"chat_id": ch, "caption": caption[:900]},
            {"document": ("file.pdf", pdf_bytes)}
        )

# =====================================================
# PDF SANITIZE
# =====================================================

def sanitize_pdf(pdf_bytes):
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

                    if obj.get("/Subtype") == pikepdf.Name("/Link"):
                        continue

                    new_annots.append(a)

                except:
                    pass

            if new_annots:
                page["/Annots"] = pikepdf.Array(new_annots)

        out = io.BytesIO()
        src.save(out)

        return out.getvalue()

    except:
        return pdf_bytes

# =====================================================
# RSS PARSER
# =====================================================

def parse_feed(xml):
    items = []

    root = ET.fromstring(xml)

    for item in root.findall(".//item"):

        data = {
            "title": "",
            "desc": "",
            "guid": "",
            "link": "",
            "pub": "",
            "enclosure_url": None,
            "enclosure_type": None
        }

        for child in item:

            tag = child.tag.split("}")[-1]

            if tag == "enclosure":
                data["enclosure_url"] = child.attrib.get("url")
                data["enclosure_type"] = child.attrib.get("type")
                continue

            val = "".join(child.itertext()).strip()

            if tag == "title":
                data["title"] = val

            elif tag == "description":
                data["desc"] = val

            elif tag == "guid":
                data["guid"] = val

            elif tag == "link":
                data["link"] = val

            elif tag == "pubDate":
                data["pub"] = val

        body = clean_text(data["desc"])

        content = f"{data['title']}\n\n{body}"

        data["content"] = content

        items.append(data)

    return items

# =====================================================
# SCRAPER
# =====================================================

def scrape_page(url):

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=25,
            verify=False
        )

        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        for a in soup.find_all("a"):
            txt = a.get_text(" ", strip=True)
            a.replace_with(txt)

        text = soup.get_text("\n")

        lines = []

        for line in text.splitlines():
            line = line.strip()

            if len(line) > 2:
                lines.append(line)

        text = "\n".join(lines)

        text = remove_competitor(text)

        return text[:5000]

    except Exception as e:
        print("SCRAPE ERROR:", e)
        return ""

# =====================================================
# AI REWRITE
# =====================================================

def ai_rewrite(text):

    try:

        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.5,
            messages=[
                {
                    "role": "system",
                    "content": """
You are expert Hindi-Hinglish SEO writer.

Rules:
- Write detailed clean HTML article.
- Do not include competitor links.
- Do not include external telegram/whatsapp links.
- Use headings.
- Use bullet points.
- Do not use markdown.
"""
                },
                {
                    "role": "user",
                    "content": text[:5000]
                }
            ]
        )

        html_content = resp.choices[0].message.content

        html_content = sanitize_html(html_content)

        return html_content

    except Exception as e:
        print("AI ERROR:", e)
        return f"<p>{text}</p>"

# =====================================================
# FEATURED IMAGE
# =====================================================

def upload_featured_image(image_url):

    try:

        r = requests.get(
            image_url,
            headers=HEADERS,
            timeout=120,
            verify=False
        )

        mime = r.headers.get(
            "content-type",
            "image/jpeg"
        )

        ext = mimetypes.guess_extension(mime) or ".jpg"

        files = {
            "file": (f"image{ext}", r.content, mime)
        }

        headers = {
            "Content-Disposition": f'attachment; filename="image{ext}"'
        }

        res = requests.post(
            WP_MEDIA_URL,
            auth=(WP_USER, WP_PASS),
            headers=headers,
            files=files,
            timeout=120,
            verify=False
        )

        if res.status_code in [200, 201]:
            return res.json()["id"]

    except Exception as e:
        print("IMG UPLOAD ERROR:", e)

    return None

# =====================================================
# WORDPRESS
# =====================================================

def publish_post(title, content, featured_media=None):

    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "categories": [WP_CATEGORY_ID]
    }

    if featured_media:
        payload["featured_media"] = featured_media

    try:

        r = requests.post(
            WP_URL,
            auth=(WP_USER, WP_PASS),
            json=payload,
            timeout=120,
            verify=False
        )

        if r.status_code in [200, 201]:

            j = r.json()

            return j["link"]

        print(r.text)

    except Exception as e:
        print("WP ERROR:", e)

    return None

# =====================================================
# MAIN
# =====================================================

def process():

    acquire_lock()

    try:

        r = requests.get(
            FEED_URL,
            headers=HEADERS,
            timeout=60
        )

        items = parse_feed(r.text)

        items.reverse()

        for item in items:

            unique_id = sha(
                item["guid"] +
                item["title"]
            )

            if unique_id in CACHE:
                continue

            print("PROCESSING:", item["title"])

            content = item["content"]

            content = replace_usernames(content)

            content = remove_competitor(content)

            links = URL_RE.findall(content)

            scraped = ""

            if links:

                first = links[0]

                if not first.startswith("https://t.me/"):

                    scraped = scrape_page(first)

            source = scraped if scraped else content

            rewritten = ai_rewrite(source)

            featured_media = None

            if (
                item["enclosure_url"]
                and
                item["enclosure_type"]
                and
                item["enclosure_type"].startswith("image/")
            ):
                featured_media = upload_featured_image(
                    item["enclosure_url"]
                )

            wp_link = publish_post(
                item["title"],
                rewritten,
                featured_media
            )

            if not wp_link:
                continue

            final_caption = (
                f"{remove_links(content)}\n\n"
                f"🌐 {wp_link}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            )

            if (
                item["enclosure_url"]
                and
                item["enclosure_type"]
            ):

                if item["enclosure_type"] == "application/pdf":

                    try:

                        pdf = requests.get(
                            item["enclosure_url"],
                            timeout=120,
                            verify=False
                        )

                        safe_pdf = sanitize_pdf(
                            pdf.content
                        )

                        send_pdf(
                            safe_pdf,
                            final_caption
                        )

                    except:
                        send_text(final_caption)

                elif item["enclosure_type"].startswith("image/"):

                    try:

                        img = requests.get(
                            item["enclosure_url"],
                            timeout=120,
                            verify=False
                        )

                        send_photo(
                            img.content,
                            final_caption
                        )

                    except:
                        send_text(final_caption)

                else:
                    send_text(final_caption)

            else:
                send_text(final_caption)

            CACHE[unique_id] = {
                "title": item["title"],
                "time": time.time()
            }

            save_cache(CACHE)

            time.sleep(3)

    finally:
        release_lock()

# =====================================================
# START
# =====================================================

if __name__ == "__main__":

    process()
