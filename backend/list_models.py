import os
from google import genai
from dotenv import load_dotenv
from agents.utils import get_gemini_client

load_dotenv()

def list_models():
    client = get_gemini_client()
    print("Listing models...")
    
    try:
        for model in client.models.list():
            print(f"Model Name: {model.name}, Supported Actions: {model.supported_actions}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models()
