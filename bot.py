import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

urllib3.disable_warnings()
print("🛠 [DEBUG] SYSTEM BOOTING: BRAND PROTECTION & DEEP SCRAPER MODE...")

# --- CONFIGURATION ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")
LAST_FILE = "last.txt"
client = OpenAI(api_key=os.environ.get("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")

# --- CORE HELPERS (Fixing Data Mismatch & Branding) ---
def brand_replacer(text):
    text = re.sub(r'https?://t\.me/[A-Za-z0-9_]+', 'https://t.me/RAJASTHAN_TODAY', text)
    text = re.sub(r'https?://whatsapp\.com/channel/[A-Za-z0-9_]+', 'https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q', text)
    text = re.sub(r'@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+', '@KAPILRJ06', text)
    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    text = text.replace("indianaukrihelp.com", "positronacademy.in")
    return text

def parse_all_items(xml):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        title = re.sub(r"<!\[CDATA\[|\]\]>", "", re.search(r"<title>(.*?)</title>", m.group(1), re.S).group(1))
        desc = re.sub(r"<!\[CDATA\[|\]\]>", "", re.search(r"<description>(.*?)</description>", m.group(1), re.S).group(1))
        guid = re.search(r"<guid>(.*?)</guid>", m.group(1), re.S)
        items.append({"guid": guid.group(1) if guid else title, "title": title.strip(), "text": BeautifulSoup(desc, "html.parser").get_text()})
    return items

def rewrite_with_groq(text):
    try:
        resp = client.chat.completions.create(
            messages=[{"role": "system", "content": "Rewrite as a unique Positron Academy article in Hinglish. Replace all external links with relevant internal ones. No indianaukrihelp.com."}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant", temperature=0.5
        )
        return resp.choices[0].message.content
    except: return text

def publish_to_wordpress(title, content):
    print(f"⏳ [DEBUG] Publishing: {title}")
    data = {'title': brand_replacer(title), 'content': brand_replacer(content), 'status': 'publish'}
    try:
        r = requests.post(WP_URL, auth=(WP_USER, WP_PASS), data=data, timeout=60, verify=False)
        return r.json().get("link") if r.status_code == 201 else None
    except Exception as e:
        print(f"❌ [DEBUG] WP Fail: {e}")
        return None

# --- NEW RULE 6: DEEP SCRAPER ENGINE ---
def deep_scrape_and_post(url):
    print(f"🕵️ [DEBUG] Deep scraping competitor link: {url}")
    try:
        soup = BeautifulSoup(requests.get(url, verify=False).text, 'html.parser')
        title = soup.title.string if soup.title else "New Update"
        content = soup.get_text(separator="\n")
        return publish_to_wordpress(title, content)
    except: return None

# --- MAIN ENGINE ---
def main():
    xml = requests.get(FEED_URL, timeout=45).text
    items = parse_all_items(xml)
    last_guid = read_last()
    new_items = [it for it in items if it["guid"] != last_guid]
    new_items.reverse()

    for item in new_items:
        print(f"👉 [DEBUG] Processing: {item['title']}")
        raw_text = brand_replacer(item['text'])
        
        # Rule 6: Agar link indianaukrihelp ki hai, toh naya page banao
        link_match = re.search(r'https?://[^\s<>"]+', raw_text)
        final_link = None
        if link_match:
            url = link_match.group(0)
            if "indianaukrihelp.com" in url:
                final_link = deep_scrape_and_post(url)
            else:
                final_link = url

        # Content Prep
        wp_content = rewrite_with_groq(raw_text)
        if final_link:
            wp_content += f"<br><br><a href='{final_link}'>👉 पूरी जानकारी यहाँ देखें</a>"
        
        wp_link = publish_to_wordpress(item['title'], wp_content)
        
        # Telegram Dispatch
        if wp_link:
            msg = f"{brand_replacer(item['title'])}\n\n🌐 {wp_link}\n\n{FOLLOW_LINE_TG}"
            for ch in DEST_CHANNELS.split(","):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
            write_last(item['guid'])
        time.sleep(5)

if __name__ == "__main__":
    main()
