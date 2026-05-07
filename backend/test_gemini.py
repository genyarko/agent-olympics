import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

def test_gemini():
    # Configure client for Vertex AI as indicated by environment variables
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if location == "global":
        location = "us-central1" # standard location for vertex models
    
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location
    )

    print(f"Testing Gemini Flash via Vertex AI (Project: {project}, Location: {location})...")
    
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
