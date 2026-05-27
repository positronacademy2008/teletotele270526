import os
import google.generativeai as genai

# API Key check karo
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("❌ Error: GEMINI_API_KEY nahi mili!")
else:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        print("⏳ AI se sampark kar rahe hain...")
        response = model.generate_content("Hello, kya tum kaam kar rahe ho? Bas 'Yes' bolo.")
        
        print(f"✅ SUCCESS! AI ka jawab: {response.text}")
    except Exception as e:
        print(f"❌ AI Login Failed! Error: {e}")
