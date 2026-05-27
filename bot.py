import os, requests
from requests.auth import HTTPBasicAuth

# --- CONFIG ---
WP_URL = os.environ.get("WP_URL") 
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")

def test_wp_auth():
    print(f"DEBUG: WP_URL: {WP_URL}")
    print(f"DEBUG: WP_USER: {WP_USER}")
    # Password mat dikhana, bas check karo ki variable empty toh nahi hai
    if not WP_PASS:
        print("❌ ERROR: WP_PASS missing!")
        return

    # WordPress REST API Test (Check Auth)
    try:
        response = requests.post(
            WP_URL, 
            auth=HTTPBasicAuth(WP_USER, WP_PASS),
            json={'title': 'Test Post', 'content': 'Testing connection...', 'status': 'publish'},
            timeout=30
        )
        if response.status_code == 201:
            print("✅ SUCCESS: WordPress se connection jud gaya!")
        else:
            print(f"❌ WP AUTH FAILED! Status: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    test_wp_auth()
