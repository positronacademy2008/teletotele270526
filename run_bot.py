from __future__ import annotations

import html
import os
import re
from urllib.parse import urlparse

import bot

WEB_FOLLOW_LINE = os.environ.get(
    "WEB_FOLLOW_LINE",
    "📢 Follow TELEGRAM WHATSAPP https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q | TELEGRAM https://t.me/RAJASTHAN_TODAY",
).strip()
SOURCE_PAGE_HOSTS = tuple(
    part.strip() for part in os.environ.get("SOURCE_PAGE_HOSTS", "indianaukrihelp.com").split(",") if part.strip()
)

_original_sanitize_html_content = bot.sanitize_html_content
_original_build_wordpress_content = bot.build_wordpress_content
_original_build_source_page_content = bot.build_source_page_content


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


def _is_pdf_url(url: str) -> bool:
    return urlparse(bot.clean_url(url)).path.lower().endswith(".pdf")


def _blocked_source_url(url: str) -> bool:
    return _host_matches(url, SOURCE_PAGE_HOSTS) and not _is_pdf_url(url)


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
        heading_text = bot.normalize_whitespace(heading.get_text(" ", strip=True)).lower()
        if "important links" not in heading_text and "important official links" not in heading_text:
            continue
        container = heading.parent
        if container and getattr(container, "name", "") in {"section", "div", "article"}:
            container.decompose()
        else:
            sibling = heading.find_next_sibling()
            heading.decompose()
            if sibling and getattr(sibling, "name", "") in {"ul", "ol", "table", "p", "div"}:
                sibling.decompose()


def remove_disallowed_source_links(markup: str, base_url: str = "") -> str:
    if not markup:
        return markup
    soup = bot.make_soup(markup, "html.parser")
    _remove_existing_important_link_sections(soup)

    for link in list(soup.find_all("a", href=True)):
        href = bot.safe_url(link.get("href"), base_url)
        if not href or not _blocked_source_url(href):
            continue
        label = bot.normalize_whitespace(link.get_text(" ", strip=True))
        if not label or bot.URL_RE.fullmatch(label):
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


def source_block(source_url: str) -> str:
    lines: list[str] = []
    if WEB_FOLLOW_LINE:
        lines.append(html.escape(WEB_FOLLOW_LINE))
    if source_url:
        host = urlparse(source_url).netloc or source_url
        if _is_pdf_url(source_url):
            href = html.escape(source_url, quote=True)
            label = html.escape(host)
            lines.append(f'<a href="{href}" target="_blank" rel="nofollow noopener">{label}</a>')
        else:
            lines.append(f"Source attribution: {html.escape(host)}")
    if not lines:
        return ""
    return (
        '<section class="source-link">'
        "<h2>Official/Source Link</h2>"
        + "".join(f"<p>{line}</p>" for line in lines)
        + "</section>"
    )


def build_wordpress_content(item: bot.FeedItem, ai: bot.AIRewriter, important_links: list[bot.LinkInfo]) -> str:
    html_content = _original_build_wordpress_content(item, ai, [])
    return remove_disallowed_source_links(html_content, item.source_url or "")


def build_source_page_content(
    title: str,
    source_url: str,
    source_html: str,
    fallback_text: str,
    ai: bot.AIRewriter,
    important_links: list[bot.LinkInfo],
) -> str:
    html_content = _original_build_source_page_content(title, source_url, source_html, fallback_text, ai, [])
    return remove_disallowed_source_links(html_content, source_url)


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
    title_key = re.sub(r"\W+", "", title.lower())
    points = bot.sentence_candidates(content_text)
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
        lines = [title.strip()[:180]]
        lines.extend(f"- {point}" for point in points[:point_count])
        if fixed_tail:
            lines.append("")
            lines.extend(fixed_tail)
        candidate = bot.normalize_whitespace("\n".join(lines))
        if len(candidate) <= limit:
            return candidate

    minimal = bot.normalize_whitespace("\n".join([title.strip()[:180], "", *fixed_tail]))
    return bot.trim_preserving_urls(minimal, limit)


bot.sanitize_html_content = sanitize_html_content
bot.important_links_block = important_links_block
bot.source_block = source_block
bot.build_wordpress_content = build_wordpress_content
bot.build_source_page_content = build_source_page_content
bot.build_caption = build_caption

if __name__ == "__main__":
    bot.main()
