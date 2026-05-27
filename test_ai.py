import os
import google.generativeai as genai

# Setup API Key from Secrets
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

# FlashLite 8B Model
model = genai.GenerativeModel('gemini-1.5-flash-8b')

def test_ai():
    print("⏳ AI FlashLite 8B Testing...")
    try:
        response = model.generate_content("Say 'FlashLite Active'")
        print(f"✅ AI Response: {response.text}")
    except Exception as e:
        print(f"❌ AI Error: {e}")

if __name__ == "__main__":
    test_ai()
