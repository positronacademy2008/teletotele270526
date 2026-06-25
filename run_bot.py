from __future__ import annotations

import html
import io
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import bot

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


WEB_FOLLOW_LINE = os.environ.get("WEB_FOLLOW_LINE", "").strip()
BRAND_IMAGES = os.environ.get("BRAND_IMAGES", "true").strip().lower() in {"1", "true", "yes", "on"}
IMAGE_BRAND_NAME = os.environ.get("IMAGE_BRAND_NAME", "POSITRON ACADEMY").strip()
IMAGE_BRAND_ADDRESS = os.environ.get(
    "IMAGE_BRAND_ADDRESS",
    "चौधरी के पास हॉस्पिटल, पांसल चौराहा,भीलवाड़ा",
).strip()
IMAGE_BRAND_CONTACT = os.environ.get("IMAGE_BRAND_CONTACT", "8104894648").strip()
SOURCE_PAGE_HOSTS = tuple(
    part.strip() for part in os.environ.get("SOURCE_PAGE_HOSTS", "indianaukrihelp.com").split(",") if part.strip()
)

_original_sanitize_html_content = bot.sanitize_html_content
_original_publish = bot.WordPressClient.publish
_original_upload_media_bytes = bot.WordPressClient.upload_media_bytes
_original_send_image_item = bot.MirrorBot.send_image_item


BOILERPLATE_CLASS_HINTS = (
    "advert",
    "breadcrumb",
    "comment",
    "footer",
    "header",
    "join",
    "latest",
    "menu",
    "newsletter",
    "pagination",
    "popular",
    "promo",
    "rank-math",
    "related",
    "share",
    "sidebar",
    "social",
    "sponsor",
    "subscribe",
    "telegram",
    "toc",
    "whatsapp",
    "widget",
)

BOILERPLATE_LINE_HINTS = (
    "advertisement",
    "all rights reserved",
    "also check",
    "comment",
    "disclaimer",
    "follow us",
    "join telegram",
    "join whatsapp",
    "latest post",
    "latest update",
    "privacy policy",
    "related post",
    "share this",
    "sponsored",
    "subscribe",
    "you may also like",
)

IMPORTANT_HEADING_RE = re.compile(
    r"\b(important|official|useful|quick|download)\s+(official\s+)?(links?|link|downloads?)\b",
    re.I,
)

DETAIL_HEADING_RE = re.compile(
    r"\b(vacancy|result|admit card|answer key|exam|application|notification|recruitment|eligibility|fees?|date|deadline)\b",
    re.I,
)


def _canonical_url(url: str) -> str:
    return bot.clean_url(url).split("#", 1)[0].rstrip("/")


def _host_matches(url: str, hosts: tuple[str, ...]) -> bool:
    parsed = urlparse(url or "")
    hostname = (parsed.netloc or parsed.path.split("/", 1)[0]).lower()
    hostname = hostname.split("@")[-1].split(":", 1)[0].removeprefix("www.")
    for raw_host in hosts:
        host = (raw_host or "").strip().lower()
        if not host:
            continue
        if "://" in host:
            host = urlparse(host).netloc.lower()
        host = host.split("/", 1)[0].split(":", 1)[0].removeprefix("www.")
        if hostname == host or hostname.endswith("." + host):
            return True
    return False


def _source_host_in_url(url: str) -> bool:
    lower = (url or "").lower()
    for raw_host in SOURCE_PAGE_HOSTS:
        host = raw_host.lower().replace("https://", "").replace("http://", "").split("/", 1)[0]
        host = host.removeprefix("www.")
        if host and host in lower:
            return True
    return False


def _is_pdf_url(url: str) -> bool:
    return urlparse(bot.clean_url(url)).path.lower().endswith(".pdf")


def _blocked_source_url(url: str) -> bool:
    return not _is_pdf_url(url) and (_host_matches(url, SOURCE_PAGE_HOSTS) or _source_host_in_url(url))


def _looks_like_url_only(value: str) -> bool:
    clean = bot.normalize_whitespace(value)
    return bool(clean and bot.URL_RE.fullmatch(clean.strip()))


def _remove_existing_important_link_sections(soup_or_tag) -> None:
    selectors = (
        ".important-links",
        ".important-link",
        ".important_official_links",
        ".important-official-links",
        "#important-links",
        "#important_link",
    )
    for element in list(soup_or_tag.select(",".join(selectors))):
        element.decompose()

    for heading in list(soup_or_tag.find_all(re.compile(r"^h[1-6]$"))):
        heading_text = bot.normalize_whitespace(heading.get_text(" ", strip=True))
        if not IMPORTANT_HEADING_RE.search(heading_text):
            continue
        container = heading.parent
        if container and getattr(container, "name", "") in {"section", "div", "article"}:
            container.decompose()
            continue
        sibling = heading.find_next_sibling()
        heading.decompose()
        while sibling and getattr(sibling, "name", "") in {"ul", "ol", "table", "p", "div"}:
            next_sibling = sibling.find_next_sibling()
            sibling.decompose()
            sibling = next_sibling


def _remove_layout_noise(soup_or_tag) -> None:
    for element in list(soup_or_tag(["script", "style", "noscript", "iframe", "form", "button", "svg"])):
        element.decompose()
    for element in list(soup_or_tag.find_all(["nav", "footer", "header", "aside"])):
        element.decompose()
    for element in list(soup_or_tag.find_all(True)):
        haystack = " ".join(
            str(value)
            for value in (
                element.get("id", ""),
                " ".join(element.get("class", [])) if isinstance(element.get("class"), list) else element.get("class", ""),
                element.get("role", ""),
                element.get("aria-label", ""),
            )
            if value
        ).lower()
        if any(hint in haystack for hint in BOILERPLATE_CLASS_HINTS):
            element.decompose()


def remove_disallowed_source_links(markup: str, base_url: str = "") -> str:
    if not markup:
        return markup
    soup = bot.make_soup(markup, "html.parser")
    _remove_layout_noise(soup)
    _remove_existing_important_link_sections(soup)

    for link in list(soup.find_all("a", href=True)):
        href = bot.safe_url(link.get("href"), base_url)
        if not href or not _blocked_source_url(href):
            continue
        label = bot.normalize_whitespace(link.get_text(" ", strip=True))
        if not label or _looks_like_url_only(label) or _source_host_in_url(label):
            link.decompose()
        else:
            link.replace_with(label)

    for text_node in list(soup.find_all(string=True)):
        parent_name = getattr(text_node.parent, "name", "")
        if parent_name in {"a", "script", "style", "textarea"}:
            continue
        original = str(text_node)

        def replace(match: re.Match[str]) -> str:
            url = bot.clean_url(match.group(1))
            return "" if _blocked_source_url(url) else url

        replaced = bot.URL_RE.sub(replace, original)
        if replaced != original:
            text_node.replace_with(replaced)
    return str(soup)


def sanitize_html_content(markup: str, base_url: str = "") -> str:
    return remove_disallowed_source_links(_original_sanitize_html_content(markup, base_url), base_url)


def important_links_block(links: list[bot.LinkInfo]) -> str:
    return ""


def _source_host_label(source_url: str) -> str:
    host = (urlparse(source_url).netloc or source_url).strip()
    return host.removeprefix("www.") or "source page"


def source_block(source_url: str) -> str:
    lines: list[str] = []
    if WEB_FOLLOW_LINE:
        lines.append(bot.linkify_text(html.escape(WEB_FOLLOW_LINE)))
    if source_url:
        host = _source_host_label(source_url)
        if _is_pdf_url(source_url) or not _blocked_source_url(source_url):
            href = html.escape(source_url, quote=True)
            lines.append(f'<a href="{href}" target="_blank" rel="nofollow noopener">{html.escape(host)}</a>')
        else:
            lines.append(f"Source attribution: {html.escape(host)}")
    if not lines:
        return ""
    return (
        '<section class="source-link">'
        "<h2>Follow & Source</h2>"
        + "".join(f"<p>{line}</p>" for line in lines)
        + "</section>"
    )


def _slug_title_from_url(url: str) -> str:
    parsed = urlparse(url or "")
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(?:html?|php|aspx?|pdf)$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug.title() if slug else ""


def clean_title(title: str, source_url: str = "", fallback_text: str = "") -> str:
    candidates = [title]
    for line in (fallback_text or "").splitlines():
        line = bot.normalize_whitespace(line)
        if line and not bot.URL_RE.search(line):
            candidates.append(line)
            break
    candidates.append(_slug_title_from_url(source_url))

    for candidate in candidates:
        clean = bot.strip_tags(candidate)
        clean = bot.URL_RE.sub(" ", clean)
        for raw_host in SOURCE_PAGE_HOSTS:
            host = raw_host.replace("https://", "").replace("http://", "").split("/", 1)[0]
            clean = re.sub(re.escape(host), " ", clean, flags=re.I)
        clean = re.sub(r"\[[^\]]*\]", " ", clean)
        clean = re.sub(r"[*_`#>|]+", " ", clean)
        clean = re.sub(r"\b(click here|read more|check now|official link)\b", " ", clean, flags=re.I)
        clean = bot.normalize_whitespace(clean).strip(" -:|/\\.,")
        if len(clean) >= 8 and any(ch.isalpha() for ch in clean):
            return clean[:180]
    return "Educational Update"


def _line_is_noise(line: str) -> bool:
    lower = line.lower()
    if not line:
        return True
    if any(hint in lower for hint in BOILERPLATE_LINE_HINTS):
        return True
    if IMPORTANT_HEADING_RE.search(line):
        return True
    if bot.line_has_spam(line):
        return True
    return False


def _clean_text_for_digest(text: str, base_url: str = "") -> str:
    raw = bot.normalize_whitespace(text or "")
    raw = bot.remove_spam_urls_from_text(raw)

    def replace(match: re.Match[str]) -> str:
        url = bot.safe_url(match.group(1), base_url)
        return "" if _blocked_source_url(url) else url

    raw = bot.URL_RE.sub(replace, raw)
    output: list[str] = []
    seen: set[str] = set()
    skip_link_section = 0
    for raw_line in raw.splitlines():
        line = bot.normalize_whitespace(raw_line).strip(" -\t")
        if IMPORTANT_HEADING_RE.search(line):
            skip_link_section = 12
            continue
        if skip_link_section:
            skip_link_section -= 1
            if not line:
                skip_link_section = 0
            if bot.URL_RE.search(line) or len(line) < 90 or DETAIL_HEADING_RE.search(line):
                continue
            skip_link_section = 0
        if _line_is_noise(line):
            continue
        key = re.sub(r"\W+", "", line.lower())[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(line)
        if len(output) >= 18:
            break
    return bot.normalize_whitespace("\n".join(output))


def _text_from_html(markup: str, base_url: str = "") -> str:
    if not markup:
        return ""
    cleaned = remove_disallowed_source_links(markup, base_url)
    return _clean_text_for_digest(bot.html_to_text_with_links(cleaned, base_url), base_url)


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]{3,}", (value or "").lower())
    noisy = {"the", "and", "for", "with", "from", "online", "official", "update", "notification"}
    return {word for word in words if word not in noisy}


def _source_text_relevant(title: str, source_url: str, source_text: str) -> bool:
    if len(source_text) < 80:
        return False
    title_tokens = _tokens(title)
    slug_tokens = _tokens(_slug_title_from_url(source_url))
    wanted = list(title_tokens | slug_tokens)
    if len(wanted) < 3:
        return True
    haystack = source_text.lower()
    hits = sum(1 for token in wanted if token in haystack)
    threshold = 4 if len(wanted) >= 7 else 3
    return hits >= threshold


def _extract_pdf_links(*sources: tuple[str, str]) -> list[bot.LinkInfo]:
    links: list[bot.LinkInfo] = []
    seen: set[str] = set()
    for content, base_url in sources:
        if not content:
            continue
        if "<" in content and ">" in content:
            soup = bot.make_soup(content, "html.parser")
            for link in soup.find_all("a", href=True):
                href = bot.safe_url(link.get("href"), base_url)
                if not href or not _is_pdf_url(href):
                    continue
                label = bot.normalize_whitespace(link.get_text(" ", strip=True)) or "PDF Download"
                key = _canonical_url(href)
                if key not in seen:
                    seen.add(key)
                    links.append(bot.LinkInfo(label=label[:100], href=href))
        for url in bot.extract_urls(content):
            href = bot.safe_url(url, base_url)
            if href and _is_pdf_url(href):
                key = _canonical_url(href)
                if key not in seen:
                    seen.add(key)
                    links.append(bot.LinkInfo(label="PDF Download", href=href))
    return links[:8]


def _paragraphs_from_text(text: str, title: str, limit: int = 5) -> list[str]:
    title_key = re.sub(r"\W+", "", title.lower())
    paragraphs: list[str] = []
    for line in text.splitlines():
        line = bot.normalize_whitespace(line).strip(" -")
        if not line or bot.URL_RE.fullmatch(line):
            continue
        key = re.sub(r"\W+", "", line.lower())
        if key == title_key or title_key and key.startswith(title_key[:80]):
            continue
        if len(line) > 360:
            line = line[:357].rsplit(" ", 1)[0].rstrip() + "..."
        if line not in paragraphs:
            paragraphs.append(line)
        if len(paragraphs) >= limit:
            break
    return paragraphs


def _html_paragraph(text: str) -> str:
    escaped = html.escape(text)
    return bot.linkify_text(escaped)


def _build_pdf_block(pdf_links: list[bot.LinkInfo]) -> str:
    if not pdf_links:
        return ""
    items = []
    for index, link in enumerate(pdf_links, start=1):
        href = html.escape(link.href, quote=True)
        label = html.escape(clean_title(link.label, link.href) if link.label != "PDF Download" else f"PDF Download {index}")
        items.append(f'<li><a href="{href}" target="_blank" rel="nofollow noopener">{label}</a></li>')
    return '<section class="pdf-downloads"><h2>PDF Download</h2><ul>' + "".join(items) + "</ul></section>"


def _build_digest_html(
    title: str,
    source_url: str,
    primary_text: str,
    source_html: str,
    ai: bot.AIRewriter,
    image_url: str = "",
    image_alt: str = "",
) -> str:
    display_title = clean_title(title, source_url, primary_text)
    primary = _clean_text_for_digest(primary_text, source_url)
    source_text = _text_from_html(source_html, source_url)
    if source_text and _source_text_relevant(display_title, source_url, source_text):
        combined_text = bot.normalize_whitespace(primary + "\n" + source_text)
    else:
        combined_text = primary or source_text

    points = bot.sentence_candidates(combined_text)
    paragraphs = _paragraphs_from_text(combined_text, display_title)
    pdf_links = _extract_pdf_links((source_html, source_url), (primary_text, source_url), (combined_text, source_url))

    pieces: list[str] = [f"<h1>{html.escape(display_title)}</h1>"]
    if image_url and not _blocked_source_url(image_url):
        pieces.append(
            "<figure>"
            f'<img src="{html.escape(image_url, quote=True)}" alt="{html.escape(image_alt or display_title, quote=True)}" '
            'style="max-width:100%; height:auto;" loading="lazy" decoding="async">'
            "</figure>"
        )

    if points:
        bullet_items = "".join(f"<li>{_html_paragraph(point)}</li>" for point in points[:5])
        pieces.append(f'<section class="pa-summary"><h2>Quick Summary</h2><ul>{bullet_items}</ul></section>')

    if paragraphs:
        body = "".join(f"<p>{_html_paragraph(paragraph)}</p>" for paragraph in paragraphs)
        pieces.append(f'<section class="pa-details"><h2>Key Details</h2>{body}</section>')
    elif not points:
        pieces.append(
            '<section class="pa-details"><h2>Key Details</h2>'
            "<p>Please verify the latest details from the official notice/source before taking action.</p>"
            "</section>"
        )

    pieces.append(_build_pdf_block(pdf_links))
    main_html = "\n".join(piece for piece in pieces if piece)
    rewritten = ai.rewrite_html(main_html)
    return remove_disallowed_source_links(rewritten, source_url) + "\n" + source_block(source_url)


def build_wordpress_content(item: bot.FeedItem, ai: bot.AIRewriter, important_links: list[bot.LinkInfo]) -> str:
    raw_text = bot.normalize_whitespace("\n".join([item.text or "", bot.html_to_text_with_links(item.html_content or "", item.source_url)]))
    image_url = item.enclosure_url if bot.normalize_mime(item.enclosure_type).startswith("image/") else ""
    return _build_digest_html(
        item.title,
        item.source_url or "",
        raw_text,
        item.html_content or "",
        ai,
        image_url=image_url,
        image_alt=item.title,
    )


def build_source_page_content(
    title: str,
    source_url: str,
    source_html: str,
    fallback_text: str,
    ai: bot.AIRewriter,
    important_links: list[bot.LinkInfo],
) -> str:
    return _build_digest_html(title, source_url, fallback_text, source_html, ai)


def build_caption(
    title: str,
    content_text: str,
    fallback_text: str,
    wp_link: str,
    source_url: str,
    important_links: list[bot.LinkInfo],
    config: bot.Config,
    limit: int,
) -> str:
    display_title = clean_title(title, source_url, fallback_text or content_text)
    title_key = re.sub(r"\W+", "", display_title.lower())
    caption_source = content_text or fallback_text
    if "<" in caption_source and ">" in caption_source:
        caption_source = fallback_text or bot.html_to_text_with_links(caption_source, source_url)
    clean_text = _clean_text_for_digest(bot.normalize_whitespace(caption_source), source_url)
    points = bot.sentence_candidates(bot.URL_RE.sub("", clean_text))
    section_names = {"quick summary", "key details", "pdf download", "follow & source"}
    points = [point for point in points if point.strip().lower() not in section_names]
    points = [point for point in points if re.sub(r"\W+", "", point.lower()) != title_key]
    if len(points) < 3:
        for point in bot.sentence_candidates(fallback_text):
            point_key = re.sub(r"\W+", "", point.lower())
            if point not in points and point_key != title_key:
                points.append(point)
            if len(points) >= 5:
                break
    points = points[:5]

    fixed_tail: list[str] = []
    if wp_link:
        fixed_tail.append(f"Website: {wp_link}")

    for point_count in range(min(5, len(points)), -1, -1):
        lines = [display_title[:180]]
        lines.extend(f"- {point}" for point in points[:point_count])
        if fixed_tail:
            lines.append("")
            lines.extend(fixed_tail)
        candidate = bot.normalize_whitespace("\n".join(lines))
        if len(candidate) <= limit:
            return candidate

    minimal = bot.normalize_whitespace("\n".join([display_title[:180], "", *fixed_tail]))
    return bot.trim_preserving_urls(minimal, limit)


def publish(self, title: str, content_html: str, base_url: str = "") -> str:
    clean = clean_title(title, base_url, bot.html_to_text_with_links(content_html, base_url))
    return _original_publish(self, clean, content_html, base_url)


@dataclass(frozen=True)
class BrandConfig:
    brand_images: bool
    image_brand_name: str
    image_brand_address: str
    image_brand_contact: str


def _brand_config() -> BrandConfig:
    return BrandConfig(
        brand_images=BRAND_IMAGES,
        image_brand_name=IMAGE_BRAND_NAME,
        image_brand_address=IMAGE_BRAND_ADDRESS,
        image_brand_contact=IMAGE_BRAND_CONTACT,
    )


def find_brand_font(size: int) -> Any:
    if ImageFont is None:
        return None
    candidates = (
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/mangal.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def brand_image_bytes(image_bytes: bytes, content_type: str, config: BrandConfig) -> tuple[bytes, str]:
    content_type = bot.normalize_mime(content_type)
    if not config.brand_images or Image is None or ImageDraw is None or ImageFont is None:
        return image_bytes, content_type
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        return image_bytes, content_type

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGBA")
            width, height = img.size
            if width < 220 or height < 120:
                return image_bytes, content_type

            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            bar_height = max(58, min(height // 4, 130))
            draw.rectangle((0, height - bar_height, width, height), fill=(10, 20, 35, 190))

            title_font = find_brand_font(max(16, min(width // 22, 34)))
            body_font = find_brand_font(max(12, min(width // 34, 22)))
            lines = [
                config.image_brand_name or IMAGE_BRAND_NAME,
                config.image_brand_address or IMAGE_BRAND_ADDRESS,
                f"Contact: {config.image_brand_contact or IMAGE_BRAND_CONTACT}",
            ]
            y = height - bar_height + 8
            x = max(12, width // 35)
            for index, line in enumerate(lines):
                font = title_font if index == 0 else body_font
                fill = (255, 255, 255, 245) if index == 0 else (235, 245, 255, 235)
                draw.text((x, y), line, font=font, fill=fill)
                bbox = draw.textbbox((x, y), line, font=font)
                y += max(16, bbox[3] - bbox[1] + 4)

            branded = Image.alpha_composite(img, overlay)
            out = io.BytesIO()
            if content_type == "image/png":
                branded.save(out, format="PNG", optimize=True)
                return out.getvalue(), "image/png"
            if content_type == "image/webp":
                branded.convert("RGB").save(out, format="WEBP", quality=88, method=6)
                return out.getvalue(), "image/webp"
            branded.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception as exc:
        bot.LOGGER.warning("Image branding failed; using original image. Error: %s", exc)
        return image_bytes, content_type


def upload_media_bytes(self, media_bytes: bytes, source_url: str, content_type: str, alt_text: str = "") -> str:
    branded_bytes, branded_type = brand_image_bytes(media_bytes, content_type, _brand_config())
    return _original_upload_media_bytes(self, branded_bytes, source_url, branded_type, alt_text)


def send_image_item(self, item: bot.FeedItem, media_caption: str, fallback_text: str) -> None:
    try:
        response = self.session.get(
            item.enclosure_url,
            headers=bot.default_headers(self.config.feed_url),
            timeout=60,
            verify=self.config.verify_ssl,
        )
        response.raise_for_status()
        content_type = bot.normalize_mime(response.headers.get("Content-Type", "")) or bot.normalize_mime(
            item.enclosure_type
        )
        if not content_type.startswith("image/"):
            guessed = mimetypes.guess_type(item.enclosure_url)[0] or ""
            if not guessed.startswith("image/"):
                raise ValueError(f"Enclosure MIME is not an image: {content_type or 'unknown'}")
            content_type = guessed
        image_bytes, content_type = brand_image_bytes(response.content, content_type, _brand_config())
    except Exception as exc:
        bot.LOGGER.warning("Image download/branding failed; falling back to text message. Error: %s", exc)
        for channel in self.config.dest_channels:
            self.telegram.send_text(channel, fallback_text)
        return

    for channel in self.config.dest_channels:
        try:
            self.telegram.send_photo(channel, image_bytes, media_caption, content_type)
        except Exception as exc:
            bot.LOGGER.warning("Photo send failed for %s; falling back to text. Error: %s", channel, exc)
            self.telegram.send_text(channel, fallback_text)


bot.sanitize_html_content = sanitize_html_content
bot.important_links_block = important_links_block
bot.source_block = source_block
bot.build_wordpress_content = build_wordpress_content
bot.build_source_page_content = build_source_page_content
bot.build_caption = build_caption
bot.WordPressClient.publish = publish
bot.WordPressClient.upload_media_bytes = upload_media_bytes
bot.MirrorBot.send_image_item = send_image_item

if __name__ == "__main__":
    bot.main()
