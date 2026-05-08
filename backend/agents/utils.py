import os
from google import genai


def get_prompt(agent_name: str) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{agent_name}.md")
    with open(prompt_path, "r") as f:
        return f.read()


def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        # Use Google AI Studio (Generative AI API) which supports API Keys
        return genai.Client(api_key=api_key)

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if location == "global":
        location = "us-central1"
    
    # Use Vertex AI (Enterprise) which requires Service Account / ADC
    if project:
        return genai.Client(vertexai=True, project=project, location=location)
    
    raise ValueError("No authentication found. Set GEMINI_API_KEY for AI Studio or GOOGLE_CLOUD_PROJECT for Vertex AI.")


def workspace_for_synthesis(workspace: dict) -> dict:
    """Return a copy of the workspace suitable for prompting the Synthesizer.

    Strips the streamed events log and the bytes-heavy image entries so the
    prompt stays focused on committed agent findings.
    """
    return {
        "inputs": {
            "documents": workspace.get("inputs", {}).get("documents", []),
            "urls": workspace.get("inputs", {}).get("urls", []),
            "raw_text": workspace.get("inputs", {}).get("raw_text", ""),
            "images": [
                {"filename": img.get("filename"), "description": img.get("description")}
                for img in workspace.get("inputs", {}).get("images", [])
            ],
        },
        "facts": workspace.get("facts", ""),
        "research_findings": workspace.get("research_findings", []),
        "analysis": workspace.get("analysis", ""),
        "red_team_critique": workspace.get("red_team_critique", ""),
    }
