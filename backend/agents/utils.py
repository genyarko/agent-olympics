import os
from google import genai
from google.genai.types import HttpOptions, ResourceScope


# --- Model selection -------------------------------------------------------
# Preview model IDs change/deprecate often, which would 500 the whole app.
# Keep the preview defaults the project wants, but make them overridable via
# env so the deployment can be repaired without a code change.
PRO_MODEL = os.getenv("BOARDROOM_PRO_MODEL", "gemini-3.1-pro-preview")
FLASH_MODEL = os.getenv("BOARDROOM_FLASH_MODEL", "gemini-3-flash-preview")


def get_prompt(agent_name: str) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{agent_name}.md")
    with open(prompt_path, "r") as f:
        return f.read()


def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    proxy_url = os.getenv("BOARDROOM_PROXY_URL", "http://127.0.0.1:8000/proxy")

    if api_key:
        # Use Google AI Studio (Generative AI API) which supports API Keys
        if proxy_url:
            return genai.Client(
                api_key=api_key,
                http_options=HttpOptions(base_url=proxy_url, api_version="v1beta"),
                vertexai=False
            )
        return genai.Client(api_key=api_key, vertexai=False)

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if location == "global":
        location = "us-central1"

    # Use Vertex AI (Enterprise) which requires Service Account / ADC
    if project:
        if proxy_url:
            # Note: For Vertex AI with custom base url, google-genai behaves differently.
            # We need to construct the Vertex endpoint proxy URL.
            vertex_proxy = f"{proxy_url}/vertex/{location}/{project}"
            return genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=HttpOptions(
                    base_url=vertex_proxy,
                    base_url_resource_scope=ResourceScope.COLLECTION
                )
            )
        return genai.Client(vertexai=True, project=project, location=location)

    raise ValueError("No authentication found. Set GEMINI_API_KEY for AI Studio or GOOGLE_CLOUD_PROJECT for Vertex AI.")


# --- Workspace helpers -----------------------------------------------------

def facts_text(workspace: dict) -> str:
    """Return the extracted facts as a single string regardless of whether the
    orchestrator stored a string or (legacy) a list."""
    facts = workspace.get("facts", "")
    if isinstance(facts, str):
        return facts
    if isinstance(facts, (list, tuple)):
        return "\n".join(str(f) for f in facts)
    return str(facts or "")


def research_findings_texts(workspace: dict) -> list[str]:
    """Return the textual content of each research finding."""
    out: list[str] = []
    for r in workspace.get("research_findings", []) or []:
        if isinstance(r, dict):
            content = r.get("content") or r.get("summary") or ""
            if content:
                out.append(str(content))
        elif r:
            out.append(str(r))
    return out


_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP — close enough for the genai API
    (b"BM", "image/bmp"),
)


def sniff_image_mime(data: bytes, filename: str | None = None) -> str:
    """Best-effort detection of an image's MIME type from magic bytes, with a
    filename-extension fallback. The Gemini API rejects mislabeled inline data,
    so guessing 'image/jpeg' for everything is not safe."""
    if data:
        for magic, mime in _IMAGE_MAGIC:
            if data.startswith(magic):
                if mime == "image/webp" and b"WEBP" not in data[:16]:
                    continue
                return mime
    if filename:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        return {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }.get(ext, "image/jpeg")
    return "image/jpeg"


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
        "facts": facts_text(workspace),
        "research_findings": workspace.get("research_findings", []),
        "analysis": workspace.get("analysis", ""),
        "red_team_critique": workspace.get("red_team_critique", ""),
        "conflict_matrix": workspace.get("conflict_matrix", ""),
    }
