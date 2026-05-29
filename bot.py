import builtins
import html
import io
import mimetypes
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import pikepdf
except Exception:
    pikepdf = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def print(*args, **kwargs):
    kwargs["flush"] = True
    builtins.print(*args, **kwargs)


urllib3.disable_warnings()

BOT_TOKEN = ""
DEST_CHANNELS = ""
FEED_URL = ""
LAST_FILE = "last.txt"
WP_URL = ""
WP_USER = ""
WP_PASS = ""
FOLLOW_LINE_TG = "Join Telegram: https://t.me/RAJASTHAN_TODAY"
FOLLOW_LINE_WA = "Join WhatsApp Channel: https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q"
client = None

URL_RE = re.compile(r"""(?ix)\b(https?://[^\s<>"]+)\b""")
IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-orig-file",
    "data-medium-file",
    "data-large-file",
    "data-url",
)
BAD_IMAGE_HINTS = ("placeholder", "spacer", "blank.gif", "lazyload", "loading.gif")
SOCIAL_HOST_HINTS = (
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "telegram.me",
    "t.me",
    "whatsapp.com",
)

session = requests.Session()
retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)


def load_config():
    global BOT_TOKEN, DEST_CHANNELS, FEED_URL, LAST_FILE, WP_URL, WP_USER, WP_PASS, client

    missing = [name for name in ("BOT_TOKEN", "DEST_CHANNEL", "FEED_URL") if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    BOT_TOKEN = os.environ["BOT_TOKEN"]
    DEST_CHANNELS = os.environ["DEST_CHANNEL"]
    FEED_URL = os.environ["FEED_URL"]
    LAST_FILE = os.environ.get("LAST_FILE", "last.txt")
    WP_URL = os.environ.get("WP_URL", "").strip()
    WP_USER = os.environ.get("WP_USER", "").strip()
    WP_PASS = os.environ.get("WP_PASS", "").strip()

    if OpenAI and os.environ.get("GROQ_API_KEY"):
        client = OpenAI(api_key=os.environ.get("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
    else:
        client = None


def wp_api_root():
    if not WP_URL:
        return ""

    clean_url = WP_URL.rstrip("/")
    marker = "/wp-json/wp/v2"
    if marker in clean_url:
        return clean_url.split(marker, 1)[0] + marker

    return clean_url + marker


def wp_endpoint(resource):
    root = wp_api_root()
    if not root:
        return ""
    return f"{root}/{resource.strip('/')}"


def wp_ready():
    return bool(WP_URL and WP_USER and WP_PASS)


def default_headers(referer=None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def read_last():
    if os.path.exists(LAST_FILE):
        return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""


def write_last(val):
    open(LAST_FILE, "w", encoding="utf-8").write(val)


def strip_tags(s):
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<.*?>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def remove_prefixes(s):
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s or "", flags=re.I).strip()


def fix_usernames(match):
    uname = match.group(0)
    if uname.lower() == "@shikshavibhag":
        return "@RAJASTHAN_TODAY"
    return "@KAPILRJ06"


def brand_replacer(text):
    if not text:
        return ""
    text = re.sub(r"indianaukrihelp\.com", "", text, flags=re.I)
    text = re.sub(r"@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+", fix_usernames, text)
    text = re.sub(r"https?://(www\.)?(t\.me|telegram\.me)/[A-Za-z0-9_]+", "https://t.me/RAJASTHAN_TODAY", text)
    text = re.sub(
        r"https?://(www\.)?whatsapp\.com/channel/[A-Za-z0-9_]+",
        "https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q",
        text,
    )
    return text


def make_links_clickable(html_text):
    if not html_text:
        return ""
    try:
        raw_url_re = re.compile(r"(https?://[^\s<>\"']+)")
        soup = BeautifulSoup(html_text, "html.parser")
        for text_node in list(soup.find_all(string=True)):
            if text_node.parent and text_node.parent.name in ("a", "script", "style", "head", "title", "button"):
                continue
            original_text = str(text_node)
            if raw_url_re.search(original_text):
                linked = raw_url_re.sub(
                    r'<a href="\1" target="_blank" rel="nofollow noopener" style="color: blue; text-decoration: underline;">\1</a>',
                    original_text,
                )
                text_node.replace_with(BeautifulSoup(linked, "html.parser"))
        return str(soup)
    except Exception as e:
        print(f"   -> Link clickable error: {e}")
        return html_text


def safe_url(raw_url, base_url=""):
    if not raw_url:
        return ""
    raw_url = html.unescape(str(raw_url).strip())
    if not raw_url or raw_url.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#")):
        return ""
    return urljoin(base_url, raw_url)


def parse_srcset(srcset_value, base_url=""):
    candidates = []
    for item in (srcset_value or "").split(","):
        parts = item.strip().split()
        if not parts:
            continue
        candidate_url = safe_url(parts[0], base_url)
        if not candidate_url:
            continue
        score = 0
        if len(parts) > 1:
            descriptor = parts[1]
            if descriptor.endswith("w"):
                try:
                    score = int(descriptor[:-1])
                except ValueError:
                    score = 0
            elif descriptor.endswith("x"):
                try:
                    score = int(float(descriptor[:-1]) * 1000)
                except ValueError:
                    score = 0
        candidates.append((score, candidate_url))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def looks_like_real_image(url):
    if not url:
        return False
    lower = url.lower()
    if lower.startswith("data:"):
        return False
    return not any(hint in lower for hint in BAD_IMAGE_HINTS)


def image_candidate_from_tag(img, base_url=""):
    candidates = []
    for attr in IMAGE_ATTRS:
        value = img.get(attr)
        if value:
            candidates.append(safe_url(value, base_url))

    for attr in ("srcset", "data-srcset"):
        value = img.get(attr)
        if value:
            candidates.append(parse_srcset(value, base_url))

    parent = img.parent
    if parent and getattr(parent, "name", "") == "picture":
        for source in parent.find_all("source"):
            candidates.append(parse_srcset(source.get("srcset") or source.get("data-srcset"), base_url))

    for candidate in candidates:
        if looks_like_real_image(candidate):
            return candidate
    return ""


def guess_filename(source_url, content_type=""):
    parsed_path = urlparse(source_url).path
    filename = os.path.basename(parsed_path).strip() or f"image-{int(time.time() * 1000)}"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")

    guessed_ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    if guessed_ext == ".jpe":
        guessed_ext = ".jpg"
    if "." not in filename and guessed_ext:
        filename += guessed_ext
    if "." not in filename:
        filename += ".jpg"
    return filename[:120]


def download_bytes(url, referer=None, timeout=40):
    response = session.get(url, headers=default_headers(referer), timeout=timeout, verify=False)
    response.raise_for_status()
    return response.content, response.headers.get("Content-Type", "")


def upload_media_bytes(media_bytes, source_url, content_type="", alt_text=""):
    if not wp_ready():
        return ""

    media_url = wp_endpoint("media")
    if not media_url:
        return ""

    content_type = (content_type or mimetypes.guess_type(source_url)[0] or "image/jpeg").split(";")[0]
    filename = guess_filename(source_url, content_type)
    headers = {
        "User-Agent": default_headers()["User-Agent"],
        "Accept": "application/json",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }

    try:
        response = session.post(
            media_url,
            auth=(WP_USER, WP_PASS),
            headers=headers,
            data=media_bytes,
            timeout=45,
            verify=False,
        )
        if response.status_code in (200, 201):
            payload = response.json()
            wp_source_url = payload.get("source_url") or payload.get("guid", {}).get("rendered", "")
            if alt_text and payload.get("id"):
                try:
                    session.post(
                        f"{media_url}/{payload['id']}",
                        auth=(WP_USER, WP_PASS),
                        json={"alt_text": alt_text[:120]},
                        timeout=15,
                        verify=False,
                    )
                except Exception:
                    pass
            return wp_source_url
        print(f"   -> WordPress media upload rejected. Status: {response.status_code}")
    except Exception as e:
        print(f"   -> WordPress media upload failed: {e}")
    return ""


def upload_media_from_url(source_url, referer=None, alt_text=""):
    if not source_url:
        return ""
    try:
        media_bytes, content_type = download_bytes(source_url, referer=referer, timeout=40)
        if not content_type.startswith("image/"):
            guessed = mimetypes.guess_type(source_url)[0] or ""
            if not guessed.startswith("image/"):
                print(f"   -> Skipping non-image media: {source_url}")
                return ""
            content_type = guessed
        return upload_media_bytes(media_bytes, source_url, content_type, alt_text)
    except Exception as e:
        print(f"   -> Image download failed: {e}")
    return ""


def merge_style(existing_style, required_style):
    existing = (existing_style or "").strip()
    if existing and not existing.endswith(";"):
        existing += ";"
    return (existing + " " + required_style).strip()


def normalize_links(soup_or_tag, base_url=""):
    for link in soup_or_tag.find_all("a"):
        href = safe_url(link.get("href"), base_url)
        if not href:
            continue
        link["href"] = href
        link["target"] = "_blank"
        link["rel"] = "nofollow noopener"


def normalize_images(soup_or_tag, base_url="", upload_to_wp=False):
    uploaded_cache = {}

    for source in soup_or_tag.find_all("source"):
        # A broken source inside picture can override a good img fallback.
        if source.parent and getattr(source.parent, "name", "") == "picture":
            source.decompose()
            continue
        srcset = source.get("srcset") or source.get("data-srcset")
        best_url = parse_srcset(srcset, base_url)
        if best_url:
            source["srcset"] = best_url

    for img in soup_or_tag.find_all("img"):
        source_url = image_candidate_from_tag(img, base_url)
        if not source_url:
            continue

        final_url = source_url
        if upload_to_wp and wp_ready():
            if source_url not in uploaded_cache:
                uploaded_cache[source_url] = upload_media_from_url(source_url, referer=base_url, alt_text=img.get("alt", ""))
            final_url = uploaded_cache[source_url] or source_url

        img["src"] = final_url
        img["loading"] = "lazy"
        img["decoding"] = "async"
        img["style"] = merge_style(img.get("style"), "max-width:100%; height:auto;")

        for attr in list(img.attrs):
            if attr.startswith("data-") or attr in ("srcset", "sizes"):
                del img[attr]


def normalize_content_assets(content, base_url=""):
    soup = BeautifulSoup(content or "", "html.parser")
    normalize_links(soup, base_url)
    normalize_images(soup, base_url, upload_to_wp=True)
    return str(soup)


def link_label(link):
    text = " ".join(link.get_text(" ", strip=True).split())
    title = " ".join((link.get("title") or "").split())
    aria = " ".join((link.get("aria-label") or "").split())
    label = text or title or aria
    if not label:
        href = link.get("href") or ""
        parsed = urlparse(href)
        label = parsed.netloc or href
    return label[:90]


def should_keep_official_link(label, href, source_host):
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    parsed = urlparse(href)
    if not parsed.scheme.startswith("http"):
        return False
    lower_href = href.lower()
    lower_label = label.lower()
    if any(host in lower_href for host in SOCIAL_HOST_HINTS):
        return False
    if any(word in lower_label for word in ("login", "register", "privacy", "terms", "advertise", "contact")):
        return False
    if len(label.strip()) < 2:
        return False
    return True


def extract_official_links(soup, page_url, max_links=18):
    source_host = urlparse(page_url).netloc.lower()
    containers = []
    for selector in (
        "header",
        "nav",
        "footer",
        ".menu",
        ".navbar",
        ".navigation",
        ".main-navigation",
        ".top-menu",
        ".quick-links",
        ".important-links",
        ".official-links",
    ):
        containers.extend(soup.select(selector))

    if not containers:
        containers = [soup]

    kept = []
    seen = set()
    for container in containers:
        for link in container.find_all("a", href=True):
            href = safe_url(link.get("href"), page_url)
            label = link_label(link)
            if not should_keep_official_link(label, href, source_host):
                continue
            key = href.split("#", 1)[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            kept.append((label, href))
            if len(kept) >= max_links:
                return kept
    return kept


def site_root(url):
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/"


def fetch_root_official_links(url):
    root_url = site_root(url)
    if not root_url or root_url == url:
        return []
    try:
        response = session.get(root_url, headers=default_headers(url), timeout=15, verify=False)
        if response.status_code != 200:
            return []
        root_soup = BeautifulSoup(response.text, "html.parser")
        normalize_links(root_soup, root_url)
        return extract_official_links(root_soup, root_url)
    except Exception as e:
        print(f"   -> Root link fetch failed: {e}")
        return []


def merge_link_lists(*link_lists, limit=24):
    merged = []
    seen = set()
    for link_list in link_lists:
        for label, href in link_list:
            key = href.split("#", 1)[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            merged.append((label, href))
            if len(merged) >= limit:
                return merged
    return merged


def official_links_block(links):
    if not links:
        return ""
    items = []
    for label, href in links:
        items.append(
            '<li style="margin: 6px 0;">'
            f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="nofollow noopener">'
            f"{html.escape(label)}</a></li>"
        )
    return (
        '<div class="important-official-links" '
        'style="border:1px solid #d8dee4; padding:14px; margin:18px 0; border-radius:6px;">'
        '<h3 style="margin-top:0;">Important Official Links</h3>'
        f'<ul style="margin:0; padding-left:20px;">{"".join(items)}</ul>'
        "</div>"
    )


def select_article(soup):
    candidates = [
        soup.find("article"),
        soup.find(class_=re.compile(r"entry-content|post-content|post-body|content-area|article-content", re.I)),
        soup.find(id=re.compile(r"post|article|content", re.I)),
        soup.find("main"),
        soup.find("body"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def clean_layout_noise(soup):
    for element in soup(["script", "style", "noscript", "iframe"]):
        element.extract()
    for element in soup.find_all(["nav", "footer", "header", "aside"]):
        element.extract()


def count_assets(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")
    image_count = len([img for img in soup.find_all("img") if img.get("src")])
    link_count = len([link for link in soup.find_all("a") if link.get("href")])
    return image_count, link_count


def assets_were_dropped(original_html, rewritten_html):
    original_images, original_links = count_assets(original_html)
    new_images, new_links = count_assets(rewritten_html)
    return new_images < original_images or new_links < max(0, original_links - 2)


def rewrite_telegram_post(source_content):
    print("   -> AI rewriting short post...")
    system_prompt = (
        "You are an expert SEO educational blog writer. Rewrite the provided update into detailed, unique Hinglish. "
        "Do not include any reference to indianaukrihelp.com. Keep official links clear and clickable."
    )
    if not client:
        return source_content
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Rewrite this update safely:\n\n{source_content[:3500]}"},
            ],
            model="llama-3.1-8b-instant",
            temperature=0.5,
            timeout=45.0,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"   -> AI short post failed: {e}")
        return source_content


def rewrite_html_page(html_content):
    print("   -> AI rewriting full HTML page...")
    system_prompt = (
        "You are an expert HTML editor. Rewrite only the visible text content into unique Hinglish. "
        "Do not modify img, picture, figure, table, tr, td, th, a, ul, ol, or li tags. "
        "Preserve every src and href exactly. Remove references to indianaukrihelp.com. "
        "Return pure HTML without markdown fences."
    )
    if not client:
        return html_content
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Rewrite this HTML safely:\n\n{html_content[:7000]}"},
            ],
            model="llama-3.1-8b-instant",
            temperature=0.2,
            timeout=45.0,
        )
        result = response.choices[0].message.content
        result = re.sub(r"^```html\s*", "", result, flags=re.I).strip()
        result = re.sub(r"```\s*$", "", result).strip()
        if assets_were_dropped(html_content, result):
            print("   -> AI output dropped images/links, using safe original HTML.")
            return html_content
        return result
    except Exception as e:
        print(f"   -> AI HTML failed: {e}")
        return html_content


def publish_to_wordpress(title, content):
    print("   -> Publishing to WordPress as PAGE...")
    if not wp_ready():
        print("   -> WordPress credentials missing. Set WP_URL, WP_USER, and WP_PASS.")
        return None

    final_content = make_links_clickable(content)
    final_content = normalize_content_assets(final_content, FEED_URL)
    page_api_url = wp_endpoint("pages")
    headers = {
        "User-Agent": default_headers()["User-Agent"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = {
        "title": brand_replacer(title),
        "content": final_content,
        "status": "publish",
        "slug": f"update-{int(time.time() * 1000)}",
    }

    try:
        response = session.post(
            page_api_url,
            auth=(WP_USER, WP_PASS),
            json=data,
            headers=headers,
            timeout=25,
            verify=False,
        )
        if response.status_code in (200, 201):
            return response.json().get("link", "")
        print(f"   -> WordPress rejected PAGE. Status: {response.status_code} Body: {response.text[:250]}")
    except Exception as e:
        print(f"   -> WordPress page publish failed: {e}")
    return None


def sanitize_pdf_remove_links(pdf_bytes):
    if not pikepdf:
        return pdf_bytes
    try:
        src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
        for page in src.pages:
            annots = page.get("/Annots", None)
            if not annots:
                continue
            new_annots = []
            for annot in annots:
                try:
                    obj = annot.get_object()
                    if "/A" in obj:
                        del obj["/A"]
                    if "/AA" in obj:
                        del obj["/AA"]
                    if "/Dest" in obj:
                        del obj["/Dest"]
                    if obj.get("/Subtype", None) == pikepdf.Name("/Link"):
                        continue
                    new_annots.append(annot)
                except Exception:
                    continue
            if new_annots:
                page["/Annots"] = pikepdf.Array(new_annots)
            elif "/Annots" in page:
                del page["/Annots"]
        out = io.BytesIO()
        src.save(out)
        return out.getvalue()
    except Exception:
        return pdf_bytes


def parse_all_items(xml_data):
    items = []
    try:
        soup = BeautifulSoup(xml_data, "xml")
        for item in soup.find_all("item"):
            title = item.title.text.strip() if item.title else "No Title"
            desc = item.description.text.strip() if item.description else ""
            guid = item.guid.text.strip() if item.guid else (item.link.text.strip() if item.link else title)

            enc_url, enc_type = None, None
            enclosure = item.find("enclosure")
            if enclosure and enclosure.has_attr("url"):
                enc_url = safe_url(enclosure["url"], FEED_URL) or enclosure["url"]
                enc_type = enclosure.get("type", "")

            title_clean = remove_prefixes(strip_tags(title))
            desc_clean = re.sub(r"^\[Photo\]\s*", "", strip_tags(desc)).strip()
            combined = f"{title_clean}\n\n{desc_clean}".strip() if title_clean and desc_clean else (title_clean or desc_clean)

            items.append(
                {
                    "guid": guid,
                    "title": title_clean[:80] if title_clean else "Educational Update",
                    "text": combined,
                    "enclosure_url": enc_url,
                    "enclosure_type": enc_type,
                }
            )
    except Exception as e:
        print(f"Failed to parse RSS: {e}")
    return items


def tg_send_text(text, channel):
    print(f"   -> Dispatching TEXT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    session.post(
        url,
        json={"chat_id": channel, "text": text[:3900], "disable_web_page_preview": False},
        timeout=15,
    ).raise_for_status()


def tg_send_photo_bytes(photo_bytes, caption, channel):
    print(f"   -> Dispatching PHOTO to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    session.post(url, data=data, files=files, timeout=40).raise_for_status()


def tg_send_document_bytes(doc_bytes, filename, caption, channel):
    print(f"   -> Dispatching DOCUMENT to {channel}...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    session.post(url, data=data, files=files, timeout=60).raise_for_status()


def deep_scrape_and_mirror(url):
    print(f"   -> Mirroring URL: {url}")
    try:
        response = session.get(url, headers=default_headers(), timeout=20, verify=False)
        if response.status_code != 200:
            print(f"   -> Source rejected mirror request. Status: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        normalize_links(soup, url)

        page_links = extract_official_links(soup, url)
        root_links = fetch_root_official_links(url)
        important_links = merge_link_lists(page_links, root_links)

        clean_layout_noise(soup)
        article = select_article(soup)
        if not article:
            return None

        normalize_links(article, url)
        normalize_images(article, url, upload_to_wp=True)

        page_html = str(article)
        page_title = soup.title.string.strip() if soup.title and soup.title.string else "Update Details"
        rewritten_html = rewrite_html_page(page_html)
        final_html = rewritten_html + official_links_block(important_links)

        mirrored_link = publish_to_wordpress(f"Details: {page_title[:40]}", final_html)
        if mirrored_link:
            print(f"   -> Successfully mirrored. New URL: {mirrored_link}")
            return mirrored_link
    except Exception as e:
        print(f"   -> Deep mirroring failed: {e}")
    return None


def add_enclosure_image_to_content(wp_content, enclosure_url):
    if not enclosure_url:
        return wp_content
    final_image_url = upload_media_from_url(enclosure_url, referer=FEED_URL) if wp_ready() else ""
    final_image_url = final_image_url or enclosure_url
    return (
        wp_content
        + '<br><br><figure>'
        + f'<img src="{html.escape(final_image_url, quote=True)}" '
        + 'style="max-width:100%; height:auto;" loading="lazy" decoding="async">'
        + "</figure>"
    )


def clean_telegram_caption(raw_text):
    clean_caption = re.sub(r"\[\s*\.\.\.\s*\]|\.\.\.", "", raw_text or "")
    clean_caption = re.sub(r"https?://(?:www\.)?positronacademy\.in[^\s<>\"]*", "", clean_caption)
    lines = [line.strip() for line in clean_caption.split("\n") if line.strip()]
    if len(lines) > 1 and (lines[0] in lines[1] or lines[1] in lines[0]):
        lines.pop(0)
    return "\n\n".join(lines).strip()


def main():
    print("SYSTEM BOOTING: image-safe and official-link-safe mirroring mode.")
    try:
        load_config()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return

    channels = [channel.strip() for channel in DEST_CHANNELS.split(",") if channel.strip()]
    last_guid = read_last()

    print(f"Fetching RSS from {FEED_URL}")
    try:
        xml_resp = session.get(FEED_URL, headers=default_headers(), timeout=20).text
        items = parse_all_items(xml_resp)
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return

    new_items = []
    for item in items:
        if item["guid"] == last_guid:
            break
        new_items.append(item)

    if not new_items:
        print("System up to date.")
        return

    new_items.reverse()
    print(f"Processing {len(new_items)} new messages.")

    for current_item in new_items:
        print(f"\nProcessing item: {current_item['title'][:40]}")
        try:
            raw_text = current_item["text"]
            ctype = (current_item["enclosure_type"] or "").lower()

            if any(kw in raw_text.lower() for kw in ("t.me/+", "sponsor", "paid promo", "aviator", "betting", "casino")):
                write_last(current_item["guid"])
                continue

            raw_text = brand_replacer(raw_text)

            found_urls = URL_RE.findall(raw_text)
            for found_url in set(found_urls):
                if "indianaukrihelp.com" in found_url.lower():
                    new_mirrored_link = deep_scrape_and_mirror(found_url)
                    raw_text = raw_text.replace(found_url, new_mirrored_link or "")

            wp_content = rewrite_telegram_post(raw_text)

            if current_item["enclosure_url"] and ctype.startswith("image/"):
                wp_content = add_enclosure_image_to_content(wp_content, current_item["enclosure_url"])

            new_wp_link = publish_to_wordpress(current_item["title"][:50], wp_content)

            if not new_wp_link:
                print("   -> WordPress failed. Skipping to next.")
                continue

            clean_caption = clean_telegram_caption(raw_text)
            telegram_caption = (
                f"{clean_caption}\n\n"
                f"Website: {new_wp_link}\n\n"
                "--------------\n"
                f"{FOLLOW_LINE_TG}\n"
                f"{FOLLOW_LINE_WA}"
            ).strip()

            if current_item["enclosure_url"] and ctype == "application/pdf":
                try:
                    pdf = session.get(current_item["enclosure_url"], headers=default_headers(), timeout=40, verify=False)
                    pdf.raise_for_status()
                    safe_pdf = sanitize_pdf_remove_links(pdf.content)
                    for channel in channels:
                        tg_send_document_bytes(safe_pdf, "official_circular.pdf", telegram_caption, channel)
                except Exception:
                    for channel in channels:
                        tg_send_text(telegram_caption, channel)
            elif current_item["enclosure_url"] and ctype.startswith("image/"):
                try:
                    image = session.get(current_item["enclosure_url"], headers=default_headers(), timeout=40, verify=False)
                    image.raise_for_status()
                    for channel in channels:
                        tg_send_photo_bytes(image.content, telegram_caption, channel)
                except Exception:
                    for channel in channels:
                        tg_send_text(telegram_caption, channel)
            else:
                for channel in channels:
                    tg_send_text(telegram_caption, channel)

            write_last(current_item["guid"])
        except Exception as e:
            print(f"Loop error: {e}")

        time.sleep(3)


if __name__ == "__main__":
    main()
