import os, requests
import google.generativeai as genai

# ... (AI Configuration wahi rakho) ...

def publish_to_wp(title, content):
    url = os.environ.get("WP_URL")
    # API Password use karna zaroori hai (normal admin password nahi)
    auth = (os.environ.get("WP_USER"), os.environ.get("WP_PASS"))
    
    # 1. JSON ki jagah data dict
    # 2. Timeout aur Headers
    payload = {'title': title, 'content': content, 'status': 'publish'}
    
    try:
        # verify=False add kiya hai taaki SSL firewall issue solve ho sake
        response = requests.post(url, auth=auth, data=payload, timeout=60, verify=False)
        print(f"DEBUG: Status {response.status_code}")
        print(f"DEBUG: Response {response.text}")
        return response.status_code == 201
    except Exception as e:
        print(f"WP Publish Exception: {e}")
        return False
