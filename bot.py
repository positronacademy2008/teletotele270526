import os, re, html, time, io, requests, urllib3, pikepdf
from bs4 import BeautifulSoup
from openai import OpenAI

# 🛡️ SSL Warnings Disable
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

# --- UTILITIES (RE-ADDED MISSING FUNCTIONS) ---
def read_last():
    if os.path.exists(LAST_FILE): return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val):
    open(LAST_FILE, "w", encoding="utf-8").write(val)
    print(f"   ↳ 🛠 [DEBUG] last.txt updated with ID: {val}")

# --- BRAND REPLACER ---
def brand_replacer(text):
    text = re.sub(r'https?://t\.me/[A-Za-z0-9_]+', 'https://t.me/RAJASTHAN_TODAY', text)
    text = re.sub(r'https?://whatsapp\.com/channel/[A-Za-z0-9_]+', 'https://whatsapp.com/channel/0029VaZYv1G1noz4mprmxQ0q', text)
    text = re.sub(r'@(?!RAJASTHAN_TODAY|KAPILRJ06)[A-Za-z0-9_]+', '@KAPILRJ06', text)
    text = text.replace("शिक्षा विभाग समाचार राजस्थान", "राजस्थान न्यूज़ टूडे")
    text = text.replace("indianaukrihelp.com", "positronacademy.in")
    return text

# --- CORE FUNCTIONS ---
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
            messages=[{"role": "system", "content": "Rewrite as a unique Positron Academy article in Hinglish. Replace all external links. No indianaukrihelp.com."}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant", temperature=0.5
        )
        return resp.choices[0].message.content
    except: return text

def publish_to_wordpress(title, content):
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    data = {'title': brand_replacer(title), 'content': brand_replacer(content), 'status': 'publish', 'slug': f"post-{int(time.time())}"}
    try:
        r = requests.post(WP_URL, auth=(WP_USER, WP_PASS), data=data, headers=headers, timeout=60, verify=False)
        return r.json().get("link") if r.status_code == 201 else None
    except: return None

def deep_scrape(url):
    try:
        soup = BeautifulSoup(requests.get(url, verify=False, timeout=20).text, 'html.parser')
        for e in soup(["script", "style", "nav", "footer", "header"]): e.extract()
        return publish_to_wordpress(soup.title.string or "Update", brand_replacer(soup.get_text()))
    except: return None

# --- MAIN ENGINE ---
def main():
    print("🛠 [DEBUG] Starting Main Logic...")
    xml = requests.get(FEED_URL, timeout=45).text
    items = parse_all_items(xml)
    last_guid = read_last()
    new_items = [it for it in items if it["guid"] != last_guid]
    new_items.reverse()

    for item in new_items:
        print(f"👉 Processing: {item['title']}")
        raw_text = brand_replacer(item['text'])
        links = re.findall(r'https?://[^\s<>"]+', raw_text)
        
        final_link = deep_scrape(links[0]) if links and "indianaukrihelp.com" in links[0] else (links[0] if links else None)
        
        wp_content = rewrite_with_groq(raw_text)
        if final_link: wp_content += f"<br><a href='{final_link}'>👉 Click here for details</a>"
        
        wp_link = publish_to_wordpress(item['title'], wp_content)
        if wp_link:
            msg = f"{brand_replacer(item['title'])}\n\n🌐 {wp_link}\n\n{FOLLOW_LINE_TG}"
            for ch in DEST_CHANNELS.split(","):
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ch.strip(), "text": msg})
            write_last(item['guid'])
        time.sleep(5)

if __name__ == "__main__":
    main()
