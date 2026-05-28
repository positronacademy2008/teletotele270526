import os
import requests
import urllib3

urllib3.disable_warnings()

def test_wp_login():
    print("🛠 [TEST] Starting WordPress API Test (With Anti-Blocker Headers)...")
    
    wp_url = os.environ.get("WP_URL", "").strip()
    wp_user = os.environ.get("WP_USER", "").strip()
    wp_pass = os.environ.get("WP_PASS", "").strip()

    print(f"👉 Target URL: {wp_url}")
    print(f"👉 Target USER: {wp_user}")
    print(f"👉 Password Length: {len(wp_pass)} characters")
    
    # 🛡️ ULTIMATE STEALTH HEADERS (Firewall bypass karne ke liye)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive'
    }
    
    data = {
        'title': 'API Test Post',
        'content': 'Password ekdum sahi hai, aur Firewall bypass ho gaya!',
        'status': 'draft'
    }
    
    print("\n⏳ Sending request to WordPress...")
    
    try:
        response = requests.post(wp_url, auth=(wp_user, wp_pass), data=data, headers=headers, timeout=30)
        
        print(f"📡 Status Code Received: {response.status_code}")
        
        if response.status_code == 201:
            print("\n✅ [SUCCESS] Login Test Passed! Firewall bypassed and password is correct.")
        elif response.status_code == 401:
            print("\n❌ [FAILED] Firewall allow kar raha hai, par Username ya Password galat hai.")
            print(f"🔍 EXACT ERROR: {response.text}")
        else:
            print("\n❌ [FAILED] Request reached but failed.")
            print(f"🔍 EXACT ERROR: {response.text}")
            
    except requests.exceptions.Timeout:
        print("\n❌ [CRITICAL TIMEOUT ERROR] Server ne connection raste mein hi kaat diya.")
        print("💡 ACTION: Aapko Hostinger hPanel mein jakar 'ModSecurity' OFF karna hi padega.")
    except Exception as e:
        print(f"\n❌ [CRITICAL ERROR] Network error: {e}")

if __name__ == "__main__":
    test_wp_login()
