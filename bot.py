import os
import requests
import urllib3

# Disable SSL warnings
urllib3.disable_warnings()

def test_wp_login():
    print("🛠 [TEST] Starting WordPress API Test...")
    
    # Secrets se details uthana
    wp_url = os.environ.get("WP_URL", "").strip()
    wp_user = os.environ.get("WP_USER", "").strip()
    wp_pass = os.environ.get("WP_PASS", "").strip()
    
    # Check karna ki secrets khali toh nahi hain
    if not wp_url or not wp_user or not wp_pass:
        print("❌ [ERROR] Missing WP_URL, WP_USER, or WP_PASS in secrets.")
        return

    print(f"👉 Target URL: {wp_url}")
    print(f"👉 Target USER: {wp_user}")
    print(f"👉 Password Length: {len(wp_pass)} characters (Password check ho raha hai...)")
    
    # Headers taaki server isey bot samajh kar block na kare
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    # Ek dummy post ka data jo 'draft' rahega (Logo ko nahi dikhega)
    data = {
        'title': 'API Test Post from GitHub Actions',
        'content': 'Agar aapko ye dikh raha hai, toh password ekdum sahi kaam kar raha hai!',
        'status': 'draft'
    }
    
    print("\n⏳ Sending request to WordPress...")
    
    try:
        response = requests.post(wp_url, auth=(wp_user, wp_pass), data=data, headers=headers, timeout=30, verify=False)
        
        print(f"📡 Status Code Received: {response.status_code}")
        
        if response.status_code == 201:
            print("\n✅ [SUCCESS] Login Test Passed! WordPress me ek Draft post successfully ban gayi hai.")
            print("Ab aap apna purana main bot code wapas use kar sakte hain!")
        else:
            print("\n❌ [FAILED] Login failed or permission denied.")
            print(f"🔍 EXACT ERROR FROM WP: {response.text}")
            
    except Exception as e:
        print(f"\n❌ [CRITICAL ERROR] Network timeout ya connection error: {e}")

if __name__ == "__main__":
    test_wp_login()
