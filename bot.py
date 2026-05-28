import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

urllib3.disable_warnings()
print("🛠 [DEBUG] SYSTEM BOOTING: BRAND PROTECTION MODE ACTIVE...")

# --- CONFIGURATION ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")
LAST_FILE = "last.txt"
client = OpenAI(api_key=os.environ.get("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")

# --- BRAND PROTECTION & FORMATTING ---
def brand_replacer(text):
    text = re.sub(r'https?://t\.me/[A-Za-z0-9_]+', 'https://t.me/RAJASTHAN_TODAY', text)
    text = re.sub(r'https?://whatsapp\.com/channel/[A-Za-z0-9_]+', 'https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q', text)
    text = re.sub(r'@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+', '@KAPILRJ06', text)
    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    text = text.replace("indianaukrihelp.com", "positronacademy.in")
    return text

def clean_heading(text):
    # Requirement 1: heading repetition and [...] remove
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) > 1 and (lines[0] in lines[1] or lines[1] in lines[0]):
        lines.pop(0)
    text = '\n'.join(lines)
    return re.sub(r'\[\s*\.\.\.\s*\]|…|\.\.\.', '', text)

# --- SCRAPER & PUBLISHER ---
def deep_scrape(url):
    print(f"🕵️ [DEBUG] Scraping competitor content: {url}")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.title.string if soup.title else "Deep Scraped Post"
        content = soup.get_text(separator="\n")
        # Mirroring the post on your WP
        return publish_to_wordpress(title, content)
    except Exception as e:
        print(f"❌ [DEBUG] Deep scrape failed: {e}")
        return None

def publish_to_wordpress(title, content):
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    clean_content = brand_replacer(content)
    data = {'title': brand_replacer(title), 'content': clean_content, 'status': 'publish', 'slug': f"post-{int(time.time())}"}
    try:
        r = requests.post(WP_URL, auth=(WP_USER, WP_PASS), data=data, headers=headers, timeout=60, verify=False)
        return r.json().get("link") if r.status_code == 201 else None
    except Exception as e:
        print(f"❌ [DEBUG] WP Publish failed: {e}")
        return None

# --- MAIN LOOP ---
def main():
    xml = requests.get(FEED_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=45).text
    soup = BeautifulSoup(xml, 'xml')
    items = []
    for item in soup.find_all('item'):
        items.append({"guid": item.guid.text if item.guid else item.title.text, "title": item.title.text, "text": item.description.text})
    
    last_guid = open(LAST_FILE, "r").read().strip() if os.path.exists(LAST_FILE) else ""
    new_items = [it for it in items if it["guid"] != last_guid]
    new_items.reverse()
    
    print(f"📥 [DEBUG] Found {len(new_items)} items.")
    for item in new_items:
        print(f"👉 [DEBUG] Processing: {item['title'][:30]}")
        
        # Rule 3: Ad Check
        if any(ad in item['text'].lower() for ad in ['sponsor', 'betting', 'casino', 'aviator']):
            print("🚫 [DEBUG] Ad blocked.")
            open(LAST_FILE, "w").write(item['guid'])
            continue

        raw_text = clean_heading(brand_replacer(item['text']))
        
        # Rule 6: Mirroring logic
        final_link = None
        links = re.findall(r'https?://[^\s<>"]+', raw_text)
        if links:
            if "indianaukrihelp.com" in links[0]:
                final_link = deep_scrape(links[0])
            else:
                final_link = links[0]

        # AI & Post
        wp_content = rewrite_with_groq(raw_text)
        if final_link: wp_content += f"<br><br><a href='{final_link}'>👉 पूरी जानकारी यहाँ देखें</a>"
        
        wp_link = publish_to_wordpress(item['title'], wp_content)
        
        if wp_link:
            msg = f"{brand_replacer(item['title'])}\n\n🌐 {wp_link}\n\n{FOLLOW_LINE_TG}"
            for ch in DEST_CHANNELS.split(","):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
            open(LAST_FILE, "w").write(item['guid'])
        
        time.sleep(5)

# (Make sure to keep your existing rewrite_with_groq function here)
