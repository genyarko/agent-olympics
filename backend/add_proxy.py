
import re

with open("C:/Users/genya/Downloads/agent olympics/backend/main.py", "r") as f:
    code = f.read()

proxy_code = """
import httpx
from starlette.background import BackgroundTask

@app.post("/proxy/{path:path}")
async def proxy_llm(path: str, request: Request):
    \"\"\"Lobster Trap Security Proxy.\"\"\"
    body = await request.body()
    body_str = body.decode("utf-8", errors="ignore")
    
    # 1. Lobster Trap: Scan for PII leaks
    pii_patterns = ["social security", "ssn", "credit card", "passport"]
    if any(p in body_str.lower() for p in pii_patterns):
        logger.warning("Lobster Trap: PII leak detected!")
        raise HTTPException(status_code=400, detail="Lobster Trap: PII leak detected")
        
    # 2. Lobster Trap: Detect adversarial prompt patterns
    adversarial_patterns = ["ignore previous instructions", "bypass", "jailbreak", "do not follow"]
    if any(p in body_str.lower() for p in adversarial_patterns):
        logger.warning("Lobster Trap: Adversarial pattern detected!")
        raise HTTPException(status_code=400, detail="Lobster Trap: Adversarial pattern detected")
        
    # 3. Policy Enforcement: "Investment Guardrails"
    # Ensure recommendations stay within pre-defined financial risk parameters.
    guardrails = ["infinite risk", "unlimited budget", "guaranteed return", "all-in", "liquidate everything"]
    if any(g in body_str.lower() for g in guardrails):
        logger.warning("Policy Engine: Investment guardrail violation!")
        raise HTTPException(status_code=400, detail="Policy Engine: Investment guardrail violation")

    # Forward the request
    headers = {}
    api_key = request.headers.get("x-goog-api-key") or os.getenv("GEMINI_API_KEY")
    if api_key:
        headers["x-goog-api-key"] = api_key
    elif "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]
        
    for k, v in request.headers.items():
        if k.lower().startswith("x-goog-") and k.lower() != "x-goog-api-key":
            headers[k] = v
            
    if "Content-Type" in request.headers:
        headers["Content-Type"] = request.headers["Content-Type"]

    if path.startswith("vertex/"):
        # vertex/location/project/path...
        parts = path.split("/")
        location = parts[1]
        project = parts[2]
        rest = "/".join(parts[3:])
        base_url = f"https://{location}-aiplatform.googleapis.com"
        target_url = f"{base_url}/v1/projects/{project}/locations/{location}/publishers/google/{rest}"
    else:
        # Default AI Studio
        base_url = "https://generativelanguage.googleapis.com"
        # The path might already contain v1beta/...
        target_url = f"{base_url}/{path}"

    client = httpx.AsyncClient()
    req = client.build_request(
        request.method,
        target_url,
        content=body,
        headers=headers,
        params=request.query_params
    )
    resp = await client.send(req, stream=True)
    
    return StreamingResponse(
        resp.aiter_raw(), 
        status_code=resp.status_code, 
        headers=dict(resp.headers),
        background=BackgroundTask(lambda: asyncio.create_task(client.aclose()))
    )
"""

if "proxy_llm" not in code:
    code += "\n" + proxy_code
    with open("C:/Users/genya/Downloads/agent olympics/backend/main.py", "w") as f:
        f.write(code)
    print("Proxy added")
else:
    print("Proxy already exists")
