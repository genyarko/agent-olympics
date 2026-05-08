import os
from google import genai
from dotenv import load_dotenv
from agents.utils import get_gemini_client

load_dotenv()

def test_gemini():
    client = get_gemini_client()
    print("Testing Gemini connection...")
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Hello, tell me a one-sentence joke about executives.'
        )
        print("\nResponse from Gemini:")
        print(response.text)
        print("\nAPI connection verified successfully!")
    except Exception as e:
        print(f"\nError connecting to Gemini API: {e}")

if __name__ == "__main__":
    test_gemini()
