from __future__ import annotations

import hashlib
import html
import io
import logging
import mimetypes
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import urllib3
except Exception:  # pragma: no cover - urllib3 comes with requests in normal installs.
    urllib3 = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - handled during startup with a clear error.
    BeautifulSoup = None

try:
    import pikepdf
except Exception:
    pikepdf = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


LOGGER = logging.getLogger("improved_bot")

URL_RE = re.compile(r"""(?ix)\b(https?://[^\s<>"')\]]+)""")
TRAILING_URL_PUNCT = ".,;:!?)]]}"

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
MEDIA_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

SPAM_TEXT_HINTS = (
    "betting",
    "casino",
    "aviator",
    "paid promo",
    "sponsored",
    "sponsor",
    "prediction game",
    "earn money",
)
SPAM_HOST_HINTS = (
    "1xbet",
    "bet365",
    "parimatch",
    "stake.com",
    "dream11",
    "casino",
    "aviator",
)
SUSPICIOUS_INVITE_PATTERNS = (
    "t.me/+",
    "telegram.me/+",
    "t.me/joinchat",
    "telegram.me/joinchat",
)
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
OFFICIAL_DOMAIN_HINTS = (
    ".gov.in",
    ".nic.in",
    ".ac.in",
    ".edu",
    ".edu.in",
    "rajasthan.gov.in",
    "recruitment",
    "exam",
    "admission",
    "board",
    "university",
    "ssc.nic.in",
    "upsc.gov.in",
    "nta.ac.in",
)
IMPORTANT_LABEL_HINTS = (
    "official",
    "notification",
    "advertisement",
    "apply",
    "online",
    "admit card",
    "result",
    "answer key",
    "syllabus",
    "exam",
    "recruitment",
    "vacancy",
    "eligibility",
    "fee",
    "deadline",
    "circular",
    "pdf",
    "download",
)

AI_SYSTEM_PROMPT = """Rewrite in clear Hinglish.
Keep all facts, dates, numbers, fees, eligibility, deadlines, official names, and links unchanged.
Do not invent details.
Do not remove official/source links.
Make it suitable for an educational/news update channel.
Return plain text for Telegram captions and clean HTML for WordPress content when requested."""


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: str | None, default: int, minimum: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        LOGGER.warning("Invalid integer value %r; using %s", value, default)
        return default
    return max(minimum, parsed)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class Config:
    bot_token: str
    dest_channels: list[str]
    feed_url: str
    wp_url: str = ""
    wp_user: str = ""
    wp_pass: str = ""
    groq_api_key: str = ""
    admin_chat_id: str = ""
    db_file: str = "bot_state.sqlite3"
    max_items_per_run: int = 10
    max_retries: int = 3
    allow_insecure_ssl: bool = False
    dry_run: bool = False
    follow_line_tg: str = ""
    follow_line_wa: str = ""
    wp_post_type: str = "pages"
    groq_model: str = "llama-3.1-8b-instant"

    @classmethod
    def from_env(cls) -> "Config":
        missing = [name for name in ("BOT_TOKEN", "DEST_CHANNEL", "FEED_URL") if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        post_type = os.environ.get("WP_POST_TYPE", "pages").strip().lower() or "pages"
        if post_type not in {"pages", "posts"}:
            raise RuntimeError("WP_POST_TYPE must be either 'pages' or 'posts'")

        channels = [part.strip() for part in os.environ["DEST_CHANNEL"].split(",") if part.strip()]
        if not channels:
            raise RuntimeError("DEST_CHANNEL must contain at least one Telegram chat/channel")

        return cls(
            bot_token=os.environ["BOT_TOKEN"].strip(),
            dest_channels=channels,
            feed_url=os.environ["FEED_URL"].strip(),
            wp_url=os.environ.get("WP_URL", "").strip(),
            wp_user=os.environ.get("WP_USER", "").strip(),
            wp_pass=os.environ.get("WP_PASS", "").strip(),
            groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
            admin_chat_id=os.environ.get("ADMIN_CHAT_ID", "").strip(),
            db_file=os.environ.get("DB_FILE", "bot_state.sqlite3").strip() or "bot_state.sqlite3",
            max_items_per_run=parse_int(os.environ.get("MAX_ITEMS_PER_RUN"), 10, minimum=1),
            max_retries=parse_int(os.environ.get("MAX_RETRIES"), 3, minimum=0),
            allow_insecure_ssl=parse_bool(os.environ.get("ALLOW_INSECURE_SSL"), False),
            dry_run=parse_bool(os.environ.get("DRY_RUN"), False),
            follow_line_tg=os.environ.get("FOLLOW_LINE_TG", "").strip(),
            follow_line_wa=os.environ.get("FOLLOW_LINE_WA", "").strip(),
            wp_post_type=post_type,
            groq_model=os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip() or "llama-3.1-8b-instant",
        )

    @property
    def verify_ssl(self) -> bool:
        return not self.allow_insecure_ssl

    @property
    def wordpress_ready(self) -> bool:
        return bool(self.wp_url and self.wp_user and self.wp_pass)


@dataclass
class LinkInfo:
    label: str
    href: str


@dataclass
class FeedItem:
    guid: str
    title: str
    text: str
    html_content: str
    source_url: str
    enclosure_url: str = ""
    enclosure_type: str = ""
    content_hash: str = ""


def build_session(config: Config) -> requests.Session:
    if config.allow_insecure_ssl and urllib3:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        LOGGER.warning("ALLOW_INSECURE_SSL=true; HTTPS certificate verification is disabled.")

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "POST", "PUT", "PATCH"}),
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def default_headers(referer: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def make_soup(markup: str, parser: str = "html.parser") -> Any:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required. Install it with: pip install beautifulsoup4")
    try:
        return BeautifulSoup(markup or "", parser)
    except Exception:
        return BeautifulSoup(markup or "", "html.parser")


def clean_url(raw_url: str) -> str:
    return (raw_url or "").strip().rstrip(TRAILING_URL_PUNCT)


def safe_url(raw_url: str | None, base_url: str = "") -> str:
    if not raw_url:
        return ""
    raw_url = html.unescape(str(raw_url).strip())
    if not raw_url or raw_url.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#")):
        return ""
    return clean_url(urljoin(base_url, raw_url))


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.findall(text or ""):
        url = clean_url(match)
        key = url.rstrip("/")
        if url and key not in seen:
            seen.add(key)
            urls.append(url)
    return urls


def is_spam_url(url: str) -> bool:
    lower = (url or "").lower()
    if any(pattern in lower for pattern in SUSPICIOUS_INVITE_PATTERNS):
        return True
    host = urlparse(url).netloc.lower()
    return any(hint in host or hint in lower for hint in SPAM_HOST_HINTS)


def line_has_spam(text: str) -> bool:
    lower = (text or "").lower()
    return any(hint in lower for hint in SPAM_TEXT_HINTS) or any(pattern in lower for pattern in SUSPICIOUS_INVITE_PATTERNS)


def strip_tags(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<.*?>", "", value, flags=re.S)
    return normalize_whitespace(value)


def normalize_whitespace(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def remove_prefixes(value: str) -> str:
    return re.sub(r"^\[(?:Photo|Media|Video|Document)\]\s*", "", value or "", flags=re.I).strip()


def remove_spam_lines(text: str) -> str:
    kept: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            kept.append("")
            continue
        urls = extract_urls(line)
        if line_has_spam(line) or any(is_spam_url(url) for url in urls):
            LOGGER.info("Removed spam/promotional line: %s", line[:120])
            continue
        kept.append(raw_line)
    return normalize_whitespace("\n".join(kept))


def remove_spam_urls_from_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = clean_url(match.group(1))
        return "" if is_spam_url(url) else url

    return remove_spam_lines(URL_RE.sub(replace, text or ""))


def html_to_text_with_links(markup: str, base_url: str = "") -> str:
    soup = make_soup(markup or "", "html.parser")
    for element in soup(["script", "style", "noscript", "iframe"]):
        element.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(["p", "div", "section", "article", "tr", "h1", "h2", "h3", "h4"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for link in soup.find_all("a", href=True):
        href = safe_url(link.get("href"), base_url)
        label = normalize_whitespace(link.get_text(" ", strip=True))
        if not href or is_spam_url(href):
            link.unwrap()
            continue
        if href not in label:
            link.append(f" ({href})")
    return remove_spam_urls_from_text(normalize_whitespace(soup.get_text("\n", strip=False)))


def text_to_html(text: str) -> str:
    paragraphs: list[str] = []
    for block in re.split(r"\n{2,}", normalize_whitespace(text or "")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        escaped = "<br>".join(linkify_text(html.escape(line)) for line in lines)
        paragraphs.append(f"<p>{escaped}</p>")
    return "\n".join(paragraphs)


def linkify_text(escaped_text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = clean_url(html.unescape(match.group(1)))
        safe_href = html.escape(url, quote=True)
        return f'<a href="{safe_href}" target="_blank" rel="nofollow noopener">{html.escape(url)}</a>'

    return URL_RE.sub(replace, escaped_text)


def normalize_links(soup_or_tag: Any, base_url: str = "") -> None:
    for link in soup_or_tag.find_all("a"):
        href = safe_url(link.get("href"), base_url)
        if not href or is_spam_url(href):
            link.unwrap()
            continue
        link["href"] = href
        link["target"] = "_blank"
        link["rel"] = "nofollow noopener"


def parse_srcset(srcset_value: str | None, base_url: str = "") -> str:
    candidates: list[tuple[int, str]] = []
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


def looks_like_real_image(url: str) -> bool:
    lower = (url or "").lower()
    if not lower or lower.startswith("data:") or is_spam_url(lower):
        return False
    return not any(hint in lower for hint in BAD_IMAGE_HINTS)


def image_candidate_from_tag(img: Any, base_url: str = "") -> str:
    candidates: list[str] = []
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


def merge_style(existing_style: str | None, required_style: str) -> str:
    existing = (existing_style or "").strip()
    if existing and not existing.endswith(";"):
        existing += ";"
    return (existing + " " + required_style).strip()


def sanitize_html_content(markup: str, base_url: str = "") -> str:
    soup = make_soup(markup or "", "html.parser")
    for element in soup(["script", "style", "noscript", "iframe", "form", "button"]):
        element.decompose()
    normalize_links(soup, base_url)
    for text_node in list(soup.find_all(string=True)):
        parent_name = getattr(text_node.parent, "name", "")
        if parent_name in {"a", "script", "style", "textarea"}:
            continue
        original = str(text_node)
        if URL_RE.search(original):
            linked = linkify_text(html.escape(original))
            text_node.replace_with(make_soup(linked, "html.parser"))
    for link in list(soup.find_all("a", href=True)):
        if is_spam_url(link.get("href", "")) or line_has_spam(link.get_text(" ", strip=True)):
            link.unwrap()
    return str(soup)


def link_label(link: Any) -> str:
    text = normalize_whitespace(link.get_text(" ", strip=True))
    title = normalize_whitespace(link.get("title") or "")
    aria = normalize_whitespace(link.get("aria-label") or "")
    label = text or title or aria
    if not label:
        href = link.get("href") or ""
        parsed = urlparse(href)
        label = parsed.netloc or href
    return label[:100]


def is_important_link(label: str, href: str) -> bool:
    if not href or is_spam_url(href):
        return False
    parsed = urlparse(href)
    if parsed.scheme not in {"http", "https"}:
        return False
    lower_href = href.lower()
    lower_label = label.lower()
    if any(host in lower_href for host in SOCIAL_HOST_HINTS):
        return False
    if any(word in lower_label for word in ("privacy", "terms", "advertise", "contact", "about us")):
        return False
    official_domain = any(hint in lower_href for hint in OFFICIAL_DOMAIN_HINTS)
    useful_label = any(hint in lower_label or hint in lower_href for hint in IMPORTANT_LABEL_HINTS)
    return official_domain or useful_label


def dedupe_links(links: Iterable[LinkInfo], limit: int = 24) -> list[LinkInfo]:
    output: list[LinkInfo] = []
    seen: set[str] = set()
    for link in links:
        href = safe_url(link.href)
        if not href:
            continue
        key = href.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        output.append(LinkInfo(label=link.label.strip()[:100] or urlparse(href).netloc, href=href))
        if len(output) >= limit:
            break
    return output


def extract_links_from_html(markup: str, base_url: str = "") -> list[LinkInfo]:
    soup = make_soup(markup or "", "html.parser")
    links: list[LinkInfo] = []
    for link in soup.find_all("a", href=True):
        href = safe_url(link.get("href"), base_url)
        if not href or is_spam_url(href):
            continue
        links.append(LinkInfo(label=link_label(link), href=href))
    for url in extract_urls(soup.get_text(" ", strip=True)):
        if not is_spam_url(url):
            links.append(LinkInfo(label=urlparse(url).netloc or "Source", href=url))
    return dedupe_links(links)


def extract_important_links(markup: str, base_url: str = "", extra_urls: Iterable[str] = ()) -> list[LinkInfo]:
    links = extract_links_from_html(markup, base_url)
    for url in extra_urls:
        if url and not is_spam_url(url):
            links.append(LinkInfo(label=urlparse(url).netloc or "Source", href=url))
    return dedupe_links((link for link in links if is_important_link(link.label, link.href)), limit=24)


def important_links_block(links: list[LinkInfo]) -> str:
    if not links:
        return ""
    items = []
    for link in links:
        href = html.escape(link.href, quote=True)
        label = html.escape(link.label or link.href)
        items.append(f'<li><a href="{href}" target="_blank" rel="nofollow noopener">{label}</a></li>')
    return (
        '<section class="important-links">'
        "<h2>Important Links</h2>"
        f"<ul>{''.join(items)}</ul>"
        "</section>"
    )


def source_block(source_url: str) -> str:
    if not source_url:
        return ""
    href = html.escape(source_url, quote=True)
    label = html.escape(urlparse(source_url).netloc or source_url)
    return (
        '<section class="source-link">'
        "<h2>Official/Source Link</h2>"
        f'<p><a href="{href}" target="_blank" rel="nofollow noopener">{label}</a></p>'
        "</section>"
    )


def select_article(soup: Any) -> Any:
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


def clean_layout_noise(soup: Any) -> None:
    for element in soup(["script", "style", "noscript", "iframe", "form"]):
        element.decompose()
    for element in soup.find_all(["nav", "footer", "header", "aside"]):
        element.decompose()


class StateStore:
    def __init__(self, db_file: str) -> None:
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                guid TEXT PRIMARY KEY,
                title TEXT,
                source_url TEXT,
                content_hash TEXT,
                status TEXT CHECK(status IN ('pending', 'published', 'failed', 'skipped')),
                wp_link TEXT,
                error TEXT,
                created_at TEXT,
                updated_at TEXT,
                retries INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(items)")}
        if "retries" not in columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN retries INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get(self, guid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM items WHERE guid = ?", (guid,)).fetchone()

    def upsert_pending(self, item: FeedItem) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO items (
                guid, title, source_url, content_hash, status, wp_link, error, created_at, updated_at, retries
            )
            VALUES (?, ?, ?, ?, 'pending', '', '', ?, ?, 0)
            ON CONFLICT(guid) DO UPDATE SET
                title = excluded.title,
                source_url = excluded.source_url,
                content_hash = excluded.content_hash,
                updated_at = excluded.updated_at
            WHERE items.status NOT IN ('published', 'skipped')
            """,
            (item.guid, item.title, item.source_url, item.content_hash, now, now),
        )
        self.conn.commit()

    def set_wp_link(self, guid: str, wp_link: str) -> None:
        self.conn.execute(
            "UPDATE items SET wp_link = ?, updated_at = ? WHERE guid = ?",
            (wp_link or "", utc_now(), guid),
        )
        self.conn.commit()

    def mark_published(self, guid: str, wp_link: str = "") -> None:
        self.conn.execute(
            """
            UPDATE items
            SET status = 'published', wp_link = COALESCE(NULLIF(?, ''), wp_link), error = '', updated_at = ?
            WHERE guid = ?
            """,
            (wp_link or "", utc_now(), guid),
        )
        self.conn.commit()

    def mark_failed(self, guid: str, error: str) -> None:
        self.conn.execute(
            """
            UPDATE items
            SET status = 'failed', error = ?, retries = COALESCE(retries, 0) + 1, updated_at = ?
            WHERE guid = ?
            """,
            (error[:1000], utc_now(), guid),
        )
        self.conn.commit()

    def mark_skipped(self, guid: str, reason: str) -> None:
        self.conn.execute(
            """
            UPDATE items
            SET status = 'skipped', error = ?, updated_at = ?
            WHERE guid = ?
            """,
            (reason[:1000], utc_now(), guid),
        )
        self.conn.commit()


class TelegramClient:
    def __init__(self, config: Config, session: requests.Session) -> None:
        self.config = config
        self.session = session

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.config.bot_token}/{method}"

    def send_admin_critical(self, message: str) -> None:
        if not self.config.admin_chat_id:
            return
        try:
            self.send_text(self.config.admin_chat_id, f"Critical bot error:\n{message[:3500]}", disable_preview=True)
        except Exception as exc:
            LOGGER.error("Could not notify ADMIN_CHAT_ID: %s", exc)

    def send_text(self, chat_id: str, text: str, disable_preview: bool = False) -> None:
        text = trim_preserving_urls(text, 3900)
        if self.config.dry_run:
            LOGGER.info("[DRY_RUN] Would send text to %s: %s", chat_id, text[:200])
            return
        LOGGER.info("Sending Telegram text to %s", chat_id)
        response = self.session.post(
            self._api_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_preview},
            timeout=20,
        )
        response.raise_for_status()

    def send_photo(self, chat_id: str, photo_bytes: bytes, caption: str, content_type: str) -> None:
        content_type = normalize_mime(content_type)
        if content_type not in MEDIA_IMAGE_TYPES:
            raise ValueError(f"Unsupported image MIME for Telegram photo: {content_type or 'unknown'}")
        caption = trim_preserving_urls(caption, 900)
        if self.config.dry_run:
            LOGGER.info("[DRY_RUN] Would send photo to %s with caption: %s", chat_id, caption[:200])
            return
        LOGGER.info("Sending Telegram photo to %s", chat_id)
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        files = {"photo": (f"image{ext}", photo_bytes, content_type)}
        data = {"chat_id": chat_id, "caption": caption}
        response = self.session.post(self._api_url("sendPhoto"), data=data, files=files, timeout=60)
        response.raise_for_status()

    def send_document(self, chat_id: str, document_bytes: bytes, filename: str, caption: str) -> None:
        caption = trim_preserving_urls(caption, 900)
        if self.config.dry_run:
            LOGGER.info("[DRY_RUN] Would send document to %s with caption: %s", chat_id, caption[:200])
            return
        LOGGER.info("Sending Telegram document to %s", chat_id)
        files = {"document": (filename, document_bytes, "application/pdf")}
        data = {"chat_id": chat_id, "caption": caption}
        response = self.session.post(self._api_url("sendDocument"), data=data, files=files, timeout=75)
        response.raise_for_status()


class WordPressClient:
    def __init__(self, config: Config, session: requests.Session) -> None:
        self.config = config
        self.session = session
        self.upload_cache: dict[str, str] = {}

    @property
    def ready(self) -> bool:
        return self.config.wordpress_ready

    def api_root(self) -> str:
        clean = self.config.wp_url.rstrip("/")
        marker = "/wp-json/wp/v2"
        if marker in clean:
            return clean.split(marker, 1)[0] + marker
        return clean + marker

    def endpoint(self, resource: str) -> str:
        return f"{self.api_root()}/{resource.strip('/')}"

    def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", default_headers()["User-Agent"])
        headers.setdefault("Accept", "application/json")
        last_error = ""
        for attempt in range(1, 4):
            try:
                response = self.session.request(
                    method,
                    url,
                    auth=(self.config.wp_user, self.config.wp_pass),
                    headers=headers,
                    timeout=kwargs.pop("timeout", 45),
                    verify=self.config.verify_ssl,
                    **kwargs,
                )
                if response.status_code in (200, 201):
                    return response.json()
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
            except Exception as exc:
                last_error = str(exc)
            sleep_for = min(2 ** attempt, 10)
            LOGGER.warning("WordPress API attempt %s failed: %s", attempt, last_error)
            time.sleep(sleep_for)
        raise RuntimeError(f"WordPress API failed: {last_error}")

    def upload_media_bytes(self, media_bytes: bytes, source_url: str, content_type: str, alt_text: str = "") -> str:
        if not self.ready:
            return ""
        content_type = normalize_mime(content_type) or mimetypes.guess_type(source_url)[0] or "image/jpeg"
        if not content_type.startswith("image/"):
            LOGGER.warning("Skipping WordPress upload for non-image media: %s", source_url)
            return ""
        filename = guess_filename(source_url, content_type)
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        }
        payload = self.request_json(
            "POST",
            self.endpoint("media"),
            headers=headers,
            data=media_bytes,
            timeout=60,
        )
        media_url = payload.get("source_url") or payload.get("guid", {}).get("rendered", "")
        media_id = payload.get("id")
        if alt_text and media_id:
            try:
                self.request_json("POST", self.endpoint(f"media/{media_id}"), json={"alt_text": alt_text[:120]}, timeout=20)
            except Exception as exc:
                LOGGER.warning("Could not update WordPress media alt text: %s", exc)
        return media_url

    def upload_media_from_url(self, source_url: str, referer: str = "", alt_text: str = "") -> str:
        if not source_url:
            return ""
        if source_url in self.upload_cache:
            return self.upload_cache[source_url]
        try:
            response = self.session.get(
                source_url,
                headers=default_headers(referer),
                timeout=45,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            content_type = normalize_mime(response.headers.get("Content-Type", ""))
            if not content_type.startswith("image/"):
                guessed = mimetypes.guess_type(source_url)[0] or ""
                if not guessed.startswith("image/"):
                    LOGGER.warning("Skipping non-image media from %s (%s)", source_url, content_type or "unknown")
                    self.upload_cache[source_url] = ""
                    return ""
                content_type = guessed
            uploaded = self.upload_media_bytes(response.content, source_url, content_type, alt_text)
            self.upload_cache[source_url] = uploaded
            return uploaded
        except Exception as exc:
            LOGGER.warning("WordPress image upload failed for %s: %s", source_url, exc)
            self.upload_cache[source_url] = ""
            return ""

    def normalize_images(self, soup_or_tag: Any, base_url: str = "") -> None:
        for source in soup_or_tag.find_all("source"):
            if source.parent and getattr(source.parent, "name", "") == "picture":
                source.decompose()
                continue
            best_url = parse_srcset(source.get("srcset") or source.get("data-srcset"), base_url)
            if best_url:
                source["srcset"] = best_url

        for img in soup_or_tag.find_all("img"):
            source_url = image_candidate_from_tag(img, base_url)
            if not source_url:
                continue
            final_url = source_url
            if self.ready:
                final_url = self.upload_media_from_url(source_url, referer=base_url, alt_text=img.get("alt", "")) or source_url
            img["src"] = final_url
            img["loading"] = "lazy"
            img["decoding"] = "async"
            img["style"] = merge_style(img.get("style"), "max-width:100%; height:auto;")
            for attr in list(img.attrs):
                if attr.startswith("data-") or attr in {"srcset", "sizes"}:
                    del img[attr]

    def publish(self, title: str, content_html: str, base_url: str = "") -> str:
        if not self.ready:
            LOGGER.info("WordPress credentials are not configured; skipping WordPress publish.")
            return ""
        if self.config.dry_run:
            LOGGER.info("[DRY_RUN] Would publish %s to WordPress.", self.config.wp_post_type)
            return ""

        soup = make_soup(content_html, "html.parser")
        normalize_links(soup, base_url)
        self.normalize_images(soup, base_url)
        final_content = str(soup)
        data = {
            "title": title[:180],
            "content": final_content,
            "status": "publish",
            "slug": f"update-{int(time.time() * 1000)}",
        }
        LOGGER.info("Publishing WordPress %s: %s", self.config.wp_post_type[:-1], title[:80])
        payload = self.request_json(
            "POST",
            self.endpoint(self.config.wp_post_type),
            headers={"Content-Type": "application/json"},
            json=data,
            timeout=60,
        )
        return payload.get("link", "")


class AIRewriter:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client: Any = None
        if not config.groq_api_key:
            return
        if OpenAI is None:
            LOGGER.warning("GROQ_API_KEY is set but openai package is missing; AI rewriting disabled.")
            return
        self.client = OpenAI(api_key=config.groq_api_key, base_url="https://api.groq.com/openai/v1")

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def rewrite_plain(self, source_text: str) -> str:
        return self._rewrite(
            source_text,
            "Return plain text for a Telegram caption/digest. Keep every URL visible.",
            is_html=False,
        )

    def rewrite_html(self, source_html: str) -> str:
        return self._rewrite(
            source_html,
            "Return clean HTML for WordPress content. Preserve every href and src attribute.",
            is_html=True,
        )

    def _rewrite(self, source: str, instruction: str, is_html: bool) -> str:
        if not self.enabled:
            return source
        try:
            response = self.client.chat.completions.create(
                model=self.config.groq_model,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{instruction}\n\n{source[:8000]}"},
                ],
                temperature=0.25 if is_html else 0.4,
                timeout=45.0,
            )
            result = response.choices[0].message.content or ""
            result = strip_markdown_fence(result)
            if not fact_safety_check(source, result, is_html=is_html):
                LOGGER.warning("AI output failed fact-safety checks; using cleaned original content.")
                return source
            return result
        except Exception as exc:
            LOGGER.warning("AI rewriting failed; using cleaned original content. Error: %s", exc)
            return source


def strip_markdown_fence(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"^```(?:html|text|txt)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def count_html_assets(markup: str) -> tuple[int, int]:
    soup = make_soup(markup or "", "html.parser")
    images = len([img for img in soup.find_all("img") if img.get("src")])
    links = len([link for link in soup.find_all("a") if link.get("href")])
    return images, links


def fact_safety_check(original: str, candidate: str, is_html: bool) -> bool:
    if not candidate or not normalize_whitespace(strip_tags(candidate if is_html else candidate)):
        return False

    original_text = strip_tags(original) if is_html else normalize_whitespace(original)
    candidate_text = strip_tags(candidate) if is_html else normalize_whitespace(candidate)
    if len(original_text) > 180 and len(candidate_text) < max(80, int(len(original_text) * 0.35)):
        return False

    original_urls = set(extract_urls(original))
    candidate_urls = set(extract_urls(candidate))
    if original_urls:
        missing = original_urls - candidate_urls
        allowed_missing = max(1, len(original_urls) // 4)
        if len(missing) > allowed_missing:
            return False

    if is_html:
        original_images, original_links = count_html_assets(original)
        new_images, new_links = count_html_assets(candidate)
        if new_images < original_images:
            return False
        if new_links < max(0, original_links - max(1, original_links // 4)):
            return False
    return True


def guess_filename(source_url: str, content_type: str = "") -> str:
    parsed_path = urlparse(source_url).path
    filename = os.path.basename(parsed_path).strip() or f"file-{int(time.time() * 1000)}"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-")
    guessed_ext = mimetypes.guess_extension(normalize_mime(content_type)) or ""
    if guessed_ext == ".jpe":
        guessed_ext = ".jpg"
    if "." not in filename and guessed_ext:
        filename += guessed_ext
    if "." not in filename:
        filename += ".bin"
    return filename[:120]


def normalize_mime(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    if pikepdf is None:
        LOGGER.warning("pikepdf is not installed; PDF link sanitization skipped.")
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
    except Exception as exc:
        LOGGER.warning("PDF sanitization failed; sending original PDF bytes. Error: %s", exc)
        return pdf_bytes


def parse_feed(xml_data: str, feed_url: str) -> list[FeedItem]:
    soup = make_soup(xml_data, "xml")
    nodes = soup.find_all("item")
    if not nodes:
        nodes = soup.find_all("entry")

    items: list[FeedItem] = []
    for node in nodes:
        title_raw = node.title.get_text(" ", strip=True) if node.find("title") else "Educational Update"
        link = extract_feed_link(node, feed_url)
        guid = extract_feed_guid(node, link, title_raw)
        content_html = extract_feed_content_html(node)
        text = html_to_text_with_links(content_html, link or feed_url)
        title = remove_prefixes(strip_tags(title_raw)) or "Educational Update"
        text = remove_prefixes(text)
        if title and text and title.lower() not in text[:160].lower():
            text = normalize_whitespace(f"{title}\n\n{text}")
        source_url = link or first_non_spam_url(text) or feed_url
        enclosure_url, enclosure_type = extract_enclosure(node, feed_url)
        content_hash = sha256_text("|".join([title, text, content_html, source_url, enclosure_url]))
        items.append(
            FeedItem(
                guid=guid,
                title=title[:180],
                text=text,
                html_content=content_html,
                source_url=source_url,
                enclosure_url=enclosure_url,
                enclosure_type=enclosure_type,
                content_hash=content_hash,
            )
        )
    return items


def extract_feed_link(node: Any, feed_url: str) -> str:
    link_node = node.find("link")
    if not link_node:
        return ""
    if link_node.get("href"):
        return safe_url(link_node.get("href"), feed_url)
    return safe_url(link_node.get_text(" ", strip=True), feed_url)


def extract_feed_guid(node: Any, source_url: str, title: str) -> str:
    for tag_name in ("guid", "id"):
        tag = node.find(tag_name)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return source_url or sha256_text(title)


def extract_feed_content_html(node: Any) -> str:
    for tag_name in ("content:encoded", "encoded", "content", "description", "summary"):
        tag = node.find(tag_name)
        if tag and tag.get_text(strip=True):
            content = tag.decode_contents() if tag.contents else tag.get_text(" ", strip=True)
            return html.unescape(content)
    return ""


def extract_enclosure(node: Any, feed_url: str) -> tuple[str, str]:
    enclosure = node.find("enclosure")
    if enclosure and enclosure.get("url"):
        return safe_url(enclosure.get("url"), feed_url), normalize_mime(enclosure.get("type", ""))

    media = node.find("media:content") or node.find("content", attrs={"url": True})
    if media and media.get("url"):
        return safe_url(media.get("url"), feed_url), normalize_mime(media.get("type", ""))

    for link in node.find_all("link"):
        rel = " ".join(link.get("rel", []) if isinstance(link.get("rel"), list) else [str(link.get("rel", ""))])
        if "enclosure" in rel.lower() and link.get("href"):
            return safe_url(link.get("href"), feed_url), normalize_mime(link.get("type", ""))
    return "", ""


def first_non_spam_url(text: str) -> str:
    for url in extract_urls(text):
        if not is_spam_url(url):
            return url
    return ""


def build_wordpress_content(item: FeedItem, ai: AIRewriter, important_links: list[LinkInfo]) -> str:
    raw_html = item.html_content or text_to_html(item.text)
    cleaned_html = sanitize_html_content(raw_html, item.source_url or "")
    cleaned_html = add_digest_heading(cleaned_html, item.title)
    cleaned_html = ai.rewrite_html(cleaned_html)
    pieces = [cleaned_html, source_block(item.source_url), important_links_block(important_links)]
    if item.enclosure_url and normalize_mime(item.enclosure_type).startswith("image/"):
        pieces.append(
            "<figure>"
            f'<img src="{html.escape(item.enclosure_url, quote=True)}" alt="{html.escape(item.title, quote=True)}" '
            'style="max-width:100%; height:auto;" loading="lazy" decoding="async">'
            "</figure>"
        )
    return "\n".join(piece for piece in pieces if piece)


def add_digest_heading(content_html: str, title: str) -> str:
    escaped_title = html.escape(title)
    return f"<h1>{escaped_title}</h1>\n{content_html}"


def sentence_candidates(text: str) -> list[str]:
    clean = remove_spam_urls_from_text(strip_tags(text))
    clean = re.sub(r"\[[^\]]{0,20}\]", "", clean)
    parts: list[str] = []
    for line in clean.splitlines():
        line = line.strip(" -\t")
        if not line or URL_RE.search(line) or len(line) < 8:
            continue
        subparts = re.split(r"(?<=[.!?])\s+", line)
        for part in subparts:
            part = normalize_whitespace(part).strip(" -")
            if 8 <= len(part) <= 240 and not line_has_spam(part):
                parts.append(part)
    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = re.sub(r"\W+", "", part.lower())[:80]
        if key and key not in seen:
            seen.add(key)
            output.append(part)
        if len(output) >= 8:
            break
    return output


def build_caption(
    title: str,
    content_text: str,
    fallback_text: str,
    wp_link: str,
    source_url: str,
    important_links: list[LinkInfo],
    config: Config,
    limit: int,
) -> str:
    title_key = re.sub(r"\W+", "", title.lower())
    points = sentence_candidates(content_text)
    points = [point for point in points if re.sub(r"\W+", "", point.lower()) != title_key]
    if len(points) < 3:
        for point in sentence_candidates(fallback_text):
            point_key = re.sub(r"\W+", "", point.lower())
            if point not in points and point_key != title_key:
                points.append(point)
            if len(points) >= 5:
                break
    points = points[:5]

    source = source_url or (important_links[0].href if important_links else "")
    fixed_tail: list[str] = []
    if wp_link:
        fixed_tail.append(f"Website: {wp_link}")
    if source:
        fixed_tail.append(f"Official/Source link: {source}")
    if config.follow_line_tg:
        fixed_tail.append(config.follow_line_tg)
    if config.follow_line_wa:
        fixed_tail.append(config.follow_line_wa)

    for point_count in range(min(5, len(points)), -1, -1):
        lines = [title.strip()[:180]]
        lines.extend(f"- {point}" for point in points[:point_count])
        if fixed_tail:
            lines.append("")
            lines.extend(fixed_tail)
        candidate = normalize_whitespace("\n".join(lines))
        if len(candidate) <= limit:
            return candidate

    minimal = normalize_whitespace("\n".join([title.strip()[:180], "", *fixed_tail]))
    return trim_preserving_urls(minimal, limit)


def trim_preserving_urls(text: str, limit: int) -> str:
    text = normalize_whitespace(text)
    if len(text) <= limit:
        return text

    lines = text.splitlines()
    output: list[str] = []
    current_len = 0
    suffix = "\n..."
    for line in lines:
        add_len = len(line) + (1 if output else 0)
        if current_len + add_len <= limit:
            output.append(line)
            current_len += add_len
            continue
        if URL_RE.search(line):
            continue
        remaining = limit - current_len - len(suffix) - (1 if output else 0)
        if remaining > 20:
            output.append(line[:remaining].rstrip() + "...")
        break
    trimmed = "\n".join(output).strip()
    return trimmed[:limit].rstrip()


class MirrorBot:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = build_session(config)
        self.state = StateStore(config.db_file)
        self.telegram = TelegramClient(config, self.session)
        self.wordpress = WordPressClient(config, self.session)
        self.ai = AIRewriter(config)

    def close(self) -> None:
        self.state.close()

    def fetch_feed(self) -> str:
        LOGGER.info("Fetching feed: %s", self.config.feed_url)
        response = self.session.get(
            self.config.feed_url,
            headers=default_headers(),
            timeout=30,
            verify=self.config.verify_ssl,
        )
        response.raise_for_status()
        return response.text

    def run(self) -> None:
        xml_data = self.fetch_feed()
        items = parse_feed(xml_data, self.config.feed_url)
        LOGGER.info("Parsed %s feed item(s).", len(items))
        selected = self.select_items(items)
        if not selected:
            LOGGER.info("No pending items to process.")
            return
        LOGGER.info("Processing %s item(s).", len(selected))
        for item in reversed(selected):
            self.process_one(item)
            time.sleep(2)

    def select_items(self, items: list[FeedItem]) -> list[FeedItem]:
        selected: list[FeedItem] = []
        for item in items:
            self.state.upsert_pending(item)
            row = self.state.get(item.guid)
            if row and row["status"] in {"published", "skipped"}:
                LOGGER.info("Skipping already %s item: %s", row["status"], item.title[:80])
                continue
            if row and row["status"] == "failed" and int(row["retries"] or 0) >= self.config.max_retries:
                reason = f"MAX_RETRIES exceeded ({self.config.max_retries})"
                LOGGER.warning("Skipping %s: %s", item.title[:80], reason)
                self.state.mark_skipped(item.guid, reason)
                continue
            selected.append(item)
            if len(selected) >= self.config.max_items_per_run:
                break
        return selected

    def process_one(self, item: FeedItem) -> None:
        LOGGER.info("Processing item: %s", item.title[:100])
        try:
            item.text = remove_spam_urls_from_text(item.text)
            if not item.text and not item.html_content:
                self.state.mark_skipped(item.guid, "No useful content after spam cleanup")
                LOGGER.warning("Item skipped after cleanup: %s", item.title[:80])
                return

            source_page_html, page_links = self.fetch_source_context(item.source_url)
            important_links = dedupe_links(
                [
                    *extract_important_links(item.html_content or item.text, item.source_url),
                    *extract_important_links(source_page_html, item.source_url),
                    *page_links,
                ],
                limit=24,
            )

            row = self.state.get(item.guid)
            wp_link = row["wp_link"] if row and row["wp_link"] else ""
            if self.wordpress.ready and not wp_link:
                wp_content = build_wordpress_content(item, self.ai, important_links)
                wp_link = self.wordpress.publish(item.title, wp_content, item.source_url or self.config.feed_url)
                if not wp_link and not self.config.dry_run:
                    raise RuntimeError("WordPress publish did not return a link")
                if wp_link:
                    self.state.set_wp_link(item.guid, wp_link)

            if self.config.dry_run:
                LOGGER.info("[DRY_RUN] Processed item without changing published/skipped state: %s", item.title[:80])
                return

            self.dispatch_telegram(item, wp_link, important_links)
            self.state.mark_published(item.guid, wp_link)
            LOGGER.info("Published item: %s", item.title[:100])
        except Exception as exc:
            error = str(exc)
            self.state.mark_failed(item.guid, error)
            LOGGER.error("Item failed: %s | %s", item.title[:100], error)

    def fetch_source_context(self, source_url: str) -> tuple[str, list[LinkInfo]]:
        if not source_url or is_spam_url(source_url):
            return "", []
        try:
            response = self.session.get(
                source_url,
                headers=default_headers(self.config.feed_url),
                timeout=20,
                verify=self.config.verify_ssl,
            )
            if response.status_code != 200:
                return "", []
            if "text/html" not in normalize_mime(response.headers.get("Content-Type", "text/html")):
                return "", []
            soup = make_soup(response.text, "html.parser")
            normalize_links(soup, source_url)
            links = extract_important_links(str(soup), source_url)
            clean_layout_noise(soup)
            article = select_article(soup)
            if not article:
                return "", links
            normalize_links(article, source_url)
            return sanitize_html_content(str(article), source_url), links
        except Exception as exc:
            LOGGER.warning("Source context fetch failed for %s: %s", source_url, exc)
            return "", []

    def dispatch_telegram(self, item: FeedItem, wp_link: str, important_links: list[LinkInfo]) -> None:
        ctype = normalize_mime(item.enclosure_type)
        clean_text = remove_spam_urls_from_text(item.text)
        rewritten_text = self.ai.rewrite_plain(clean_text)
        media_caption = build_caption(
            item.title,
            rewritten_text,
            clean_text,
            wp_link,
            item.source_url,
            important_links,
            self.config,
            900,
        )
        text_caption = build_caption(
            item.title,
            rewritten_text,
            clean_text,
            wp_link,
            item.source_url,
            important_links,
            self.config,
            3900,
        )

        if item.enclosure_url and ctype == "application/pdf":
            self.send_pdf_item(item, media_caption, text_caption)
            return

        if item.enclosure_url and (ctype.startswith("image/") or looks_like_real_image(item.enclosure_url)):
            self.send_image_item(item, media_caption, text_caption)
            return

        for channel in self.config.dest_channels:
            self.telegram.send_text(channel, text_caption)

    def send_pdf_item(self, item: FeedItem, media_caption: str, fallback_text: str) -> None:
        try:
            response = self.session.get(
                item.enclosure_url,
                headers=default_headers(self.config.feed_url),
                timeout=60,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            content_type = normalize_mime(response.headers.get("Content-Type", "")) or normalize_mime(item.enclosure_type)
            if content_type != "application/pdf":
                raise ValueError(f"Enclosure MIME is not application/pdf: {content_type or 'unknown'}")
            safe_pdf = sanitize_pdf_remove_links(response.content)
            filename = guess_filename(item.enclosure_url, "application/pdf")
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
        except Exception as exc:
            LOGGER.warning("PDF download/sanitization failed; falling back to text message. Error: %s", exc)
            for channel in self.config.dest_channels:
                self.telegram.send_text(channel, fallback_text)
            return

        for channel in self.config.dest_channels:
            try:
                self.telegram.send_document(channel, safe_pdf, filename, media_caption)
            except Exception as exc:
                LOGGER.warning("PDF send failed for %s; falling back to text. Error: %s", channel, exc)
                self.telegram.send_text(channel, fallback_text)

    def send_image_item(self, item: FeedItem, media_caption: str, fallback_text: str) -> None:
        try:
            response = self.session.get(
                item.enclosure_url,
                headers=default_headers(self.config.feed_url),
                timeout=60,
                verify=self.config.verify_ssl,
            )
            response.raise_for_status()
            content_type = normalize_mime(response.headers.get("Content-Type", "")) or normalize_mime(item.enclosure_type)
            if not content_type.startswith("image/"):
                guessed = mimetypes.guess_type(item.enclosure_url)[0] or ""
                if not guessed.startswith("image/"):
                    raise ValueError(f"Enclosure MIME is not an image: {content_type or 'unknown'}")
                content_type = guessed
        except Exception as exc:
            LOGGER.warning("Image download/validation failed; falling back to text message. Error: %s", exc)
            for channel in self.config.dest_channels:
                self.telegram.send_text(channel, fallback_text)
            return

        for channel in self.config.dest_channels:
            try:
                self.telegram.send_photo(channel, response.content, media_caption, content_type)
            except Exception as exc:
                LOGGER.warning("Photo send failed for %s; falling back to text. Error: %s", channel, exc)
                self.telegram.send_text(channel, fallback_text)


def main() -> None:
    setup_logging()
    bot: MirrorBot | None = None
    try:
        config = Config.from_env()
        if BeautifulSoup is None:
            raise RuntimeError("beautifulsoup4 is required. Install it with: pip install beautifulsoup4")
        bot = MirrorBot(config)
        LOGGER.info("Bot started. DRY_RUN=%s DB_FILE=%s", config.dry_run, config.db_file)
        bot.run()
        LOGGER.info("Bot finished.")
    except Exception as exc:
        LOGGER.critical("Critical bot error: %s", exc)
        try:
            if bot is not None:
                bot.telegram.send_admin_critical(str(exc))
            else:
                config = Config.from_env()
                telegram = TelegramClient(config, build_session(config))
                telegram.send_admin_critical(str(exc))
        except Exception:
            pass
    finally:
        if bot is not None:
            bot.close()


if __name__ == "__main__":
    main()
