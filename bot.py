import os
import requests

def test_wp_direct():
    url = os.environ.get("WP_URL")
    user = os.environ.get("WP_USER")
    password = os.environ.get("WP_PASS")
    
    # Headers ko "Real Browser" jaisa bana rahe hain
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }
    
    data = {
        'title': 'CONNECTION TEST',
        'content': 'GitHub Actions successfully connected to WordPress!',
        'status': 'publish'
    }
    
    print(f"Connecting to: {url}")
    try:
        response = requests.post(url, auth=(user, password), data=data, headers=headers, timeout=60)
        print(f"Response Code: {response.status_code}")
        print(f"Response Text: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_wp_direct()
