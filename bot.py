import os, requests, time, hashlib
from bs4 import BeautifulSoup
import google.generativeai as genai

# SECRETS
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
WP_URL = os.environ["WP_URL"]
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)

def publish_to_wordpress(title, content):
    data = {
        'title': title,
        'content': content,
        'status': 'publish'
    }
    response = requests.post(WP_URL, auth=(WP_USER, WP_PASS), json=data)
    return response.json().get('link')

def rewrite_with_ai(raw_text):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Rewrite this news for an educational blog. No source links. Language: Hindi/Hinglish. Use HTML tags. Text: {raw_text[:5000]}"
    return model.generate_content(prompt).text.replace("```html", "").replace("```", "")

def process_and_publish(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        soup = BeautifulSoup(response.content, 'html.parser')
        title = soup.title.string if soup.title else "New Update"
        raw_text = " ".join([p.text for p in soup.find_all('p')])
        
        content = rewrite_with_ai(raw_text)
        wp_link = publish_to_wordpress(title, content)
        return wp_link
    except Exception as e:
        print(f"Error publishing: {e}")
        return None

# Baki RSS parsing code waisa hi rahega jaisa purana tha...
