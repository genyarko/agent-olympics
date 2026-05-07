import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

def list_models():
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = "us-central1"
    
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location
    )

    print(f"Listing models for Project: {project}, Location: {location}...")
    
    try:
        for model in client.models.list():
            print(f"Model Name: {model.name}, Supported Actions: {model.supported_actions}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models()
