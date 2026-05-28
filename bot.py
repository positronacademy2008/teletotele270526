import os, re, html, time, io
import requests
import pikepdf
from openai import OpenAI

# --- CONFIGURATION & ENV VARIABLES ---
FEED_URL = os.environ["FEED_URL"]
LAST_FILE = "last.txt"

# Setup Groq AI Client
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# Regex Patterns (Aapke original code se)
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

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
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def remove_links(s: str) -> str:
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def normalize(s: str) -> str:
    s = TRUNC_END_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def remove_prefixes(s: str) -> str:
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
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

def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    link = pick("link").strip()
    guid = (pick("guid").strip() or link)

    enc_url, enc_type = None, None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url = m_enc.group(1)
        enc_type = m_enc.group(2)

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)
    desc = re.sub(r"^\[Photo\]\s*", "", desc).strip()

    title = remove_links(title)
    desc = remove_links(desc)

    title_is_truncated = bool(TRUNC_END_RE.search(title_raw)) or bool(TRUNC_END_RE.search(title))
    t_norm = normalize(title)

    first_line = ""
    for ln in desc.splitlines():
        if ln.strip():
            first_line = ln.strip()
            break
    f_norm = normalize(first_line)
    d_norm = normalize(desc)

    if title_is_truncated:
        combined = desc
    else:
        if t_norm and f_norm and (f_norm == t_norm or f_norm.startswith(t_norm) or t_norm.startswith(f_norm)):
            combined = desc
        elif t_norm and d_norm and (d_norm == t_norm or d_norm.startswith(t_norm)):
            combined = desc
        else:
            combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)

    return {
        "guid": guid,
        "title": title if title else "Educational Update",
        "text": re.sub(r"\n{3,}", "\n\n", combined).strip(),
        "enclosure_url": enc_url,
        "enclosure_type": enc_type
    }

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

# --- GROQ AI COPYRIGHT-FREE REWRITING ---
def rewrite_with_groq(text: str) -> str:
    print("⏳ Rewriting text via Groq AI to make it copyright-free...")
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an expert content creator for Positron Academy. Rewrite the provided educational/news content to make it 100% unique, plagiarism-free, and engaging. Use an easy-to-understand mix of Hindi and English (Hinglish). Do not add any links or promotional tags."},
                {"role": "user", "content": f"Transform this content into an original blog paragraph:\n\n{text}"}
            ],
            model="llama3-8b-8192",
            temperature=0.6
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq AI Error: {e}. Using original clean text.")
        return text

# --- FIREWALL BYPASS WORDPRESS PUBLISHER ---
def publish_to_wordpress(title, content):
    print("⏳ Connecting to WordPress REST API...")
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    passwd = os.environ.get("WP_PASS")

    # ModSecurity & Firewall Bypass Headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    data = {
        'title': title,
        'content': content,
        'status': 'publish'
    }

    try:
        session = requests.Session()
        response = session.post(url, auth=(user, passwd), data=data, headers=headers, timeout=90)
        return response.status_code == 201
    except Exception as e:
        print(f"❌ WordPress POST Exception: {e}")
        return False

# --- MAIN ENGINE ---
def main():
    last_guid = read_last()
    print(f"DEBUG: Last processed GUID from memory: {last_guid}")

    print("⏳ Downloading RSS Feed XML...")
    xml = requests.get(FEED_URL, timeout=90).text
    items = parse_all_items(xml)
    
    if not items:
        print("⚠️ No items found in the RSS Feed.")
        return

    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            break
        new_items.append(it)

    if not new_items:
        print("✅ No new updates found. System is up to date.")
        return

    # Oldest first order restore
    new_items.reverse()

    for it in new_items:
        print(f"📥 Processing new item: {it['guid']}")
        
        # Step 1: AI Content Generation (Copyright-free)
        unique_content = rewrite_with_groq(it["text"])
        
        # Step 2: Handle attachments seamlessly inside content body
        ctype = (it["enclosure_type"] or "").lower()
        if it["enclosure_url"]:
            if ctype.startswith("image/"):
                unique_content += f'<br><br><img src="{it["enclosure_url"]}" alt="Update Image" style="max-width:100%;">'
            elif ctype == "application/pdf":
                unique_content += f'<br><br>📄 <b>Attachment Notice:</b> Document link available in the original source.'

        # Step 3: WordPress Publish with Firewall Bypass
        if publish_to_wordpress(it["title"], unique_content):
            print(f"🚀 SUCCESS: Published to WordPress!")
            write_last(it["guid"]) # Item publish hone par hi save hoga
        else:
            print("❌ FAILED to bypass or publish to WordPress. Stopping batch.")
            break

        time.sleep(2) # Cooldown to protect rate limits

if __name__ == "__main__":
    main()
