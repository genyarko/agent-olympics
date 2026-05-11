import logging
import os
import json
import asyncio
from typing import List
import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from session_manager import manager
from agents.orchestrator import run_orchestrator
from agents.multimodal import process_pdf, process_image, process_url, process_docx
from security.policy import policy_engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Boardroom API")

# Global HTTP client for proxy
http_client: httpx.AsyncClient = None

@app.on_event("startup")
async def startup_event():
    global http_client
    http_client = httpx.AsyncClient(timeout=None)
    await manager.init_db()

@app.on_event("shutdown")
async def shutdown_event():
    global http_client
    if http_client:
        await http_client.aclose()

allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UrlInput(BaseModel):
    url: str

@app.post("/sessions")
async def create_session():
    session_id = await manager.create_session()
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}

@app.post("/sessions/{session_id}/inputs/document")
async def upload_document(session_id: str, file: UploadFile = File(...)):
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await file.read()
    filename_lower = file.filename.lower()
    
    # Upload to R2 (cold storage)
    await manager.upload_artifact_to_r2(session_id, file.filename, content)
    
    if filename_lower.endswith(".pdf"):
        text = await process_pdf(content)
    elif filename_lower.endswith(".docx"):
        text = await process_docx(content)
    else:
        text = content.decode("utf-8", errors="ignore")
    
    session.workspace["inputs"]["documents"].append({
        "filename": file.filename,
        "content": text
    })
    await manager.save_session(session)
    return {"status": "Document uploaded"}

@app.post("/sessions/{session_id}/inputs/image")
async def upload_image(session_id: str, file: UploadFile = File(...)):
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await file.read()
    
    # Upload to R2 (cold storage)
    storage_key = await manager.upload_artifact_to_r2(session_id, file.filename, content)
    
    description = await process_image(content)
    
    session.workspace["inputs"]["images"].append({
        "filename": file.filename,
        "description": description,
        "storage_key": storage_key
    })
    await manager.save_session(session)
    return {"status": "Image uploaded"}

@app.post("/sessions/{session_id}/inputs/url")
async def add_url(session_id: str, url_input: UrlInput):
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await process_url(url_input.url)
    session.workspace["inputs"]["urls"].append({
        "url": url_input.url,
        "content": content
    })
    await manager.save_session(session)
    return {"status": "URL added"}

@app.post("/sessions/{session_id}/inputs/text")
async def add_text(session_id: str, text_input: dict):
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    text = text_input.get("text", "")
    if text:
        # Prepend to raw_text if it already exists, or just set it
        if session.workspace["inputs"]["raw_text"]:
            session.workspace["inputs"]["raw_text"] += f"\n\n{text}"
        else:
            session.workspace["inputs"]["raw_text"] = text
        await manager.save_session(session)
            
    return {"status": "Text added"}

@app.post("/sessions/{session_id}/demo")
async def load_demo(session_id: str):
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Load TargetCo Demo Scenario
    session.workspace["inputs"]["documents"].append({
        "filename": "TargetCo_Pitch_Deck.pdf",
        "content": "TargetCo is a Series C SaaS company specializing in AI-driven supply chain optimization. Current ARR is $50M, growing at 40% YoY. Main competitors are LogiSmart and SupplyChainAI."
    })
    session.workspace["inputs"]["raw_text"] = (
        "Whiteboard sketch notes: Deal structure is $200M cash + $100M stock. "
        "Earn-out over 3 years based on EBITDA targets."
    )
    session.workspace["inputs"]["urls"].append({
        "url": "https://techcrunch.com/targetco-funding",
        "content": "TargetCo recently raised $80M in Series C funding led by VentureFront. Valuation was $1.2B post-money."
    })
    await manager.save_session(session)
    
    return {"status": "Demo scenario loaded"}

@app.post("/sessions/{session_id}/analyze")
async def analyze(session_id: str, background_tasks: BackgroundTasks):
    session = await manager.get_session(session_id)
    if not session:
        logger.warning(f"Session {session_id} not found for analysis")
        raise HTTPException(status_code=404, detail="Session not found")
    
    logger.info(f"Triggering Orchestrator for session: {session_id}")
    background_tasks.add_task(run_orchestrator, session_id)
    return {"status": "Analysis started"}

@app.get("/sessions/{session_id}/stream")
async def stream(session_id: str, request: Request):
    session = await manager.get_session(session_id)
    if not session:
        logger.warning(f"Session {session_id} not found for stream")
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        try:
            while True:
                # Check if client is still connected
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from session {session_id}")
                    break
                
                try:
                    # Wait for an event with a timeout to check disconnection periodically
                    event = await asyncio.wait_for(session.queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send a keep-alive comment
                    yield ": keep-alive\n\n"
                    continue
                    
        except Exception as e:
            logger.error(f"Error in stream for session {session_id}: {e}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str):
    trace = await manager.get_trace(session_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found for session")
    return {"session_id": session_id, "trace": trace}

@app.get("/")
async def root():
    return {"message": "Boardroom API is live", "status": "ok"}


import httpx
from starlette.background import BackgroundTask

@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_llm(path: str, request: Request):
    """Lobster Trap Security Proxy."""
    body = await request.body()
    body_str = body.decode("utf-8", errors="ignore")
    
    # Pass request body through centralized Policy Engine
    is_valid, violation_type, detail_msg = policy_engine.scan_request(body_str)
    if not is_valid:
        raise HTTPException(status_code=400, detail=detail_msg)

    # Forward the request
    headers = {}
    api_key = request.headers.get("x-goog-api-key") or os.getenv("GEMINI_API_KEY")
    if api_key:
        headers["x-goog-api-key"] = api_key
        
    if "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]
    elif "authorization" in request.headers:
        headers["Authorization"] = request.headers["authorization"]
        
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
        target_url = f"{base_url}/v1beta1/projects/{project}/locations/{location}/{rest}"
    else:
        # Default AI Studio
        base_url = "https://generativelanguage.googleapis.com"
        # The path might already contain v1beta/...
        target_url = f"{base_url}/{path}"

    req = http_client.build_request(
        request.method,
        target_url,
        content=body,
        headers=headers,
        params=request.query_params
    )
    
    # We do not use stream=True with BackgroundTask because the global client manages connection pooling.
    # Instead, we yield chunks manually to stream back the response.
    # However, httpx AsyncClient handles stream=True natively when used in a context manager, 
    # but since we want to return a StreamingResponse, we can yield from an async generator.
    
    async def stream_response():
        async with http_client.stream(request.method, target_url, content=body, headers=headers, params=request.query_params) as resp:
            async for chunk in resp.aiter_raw():
                yield chunk
                
    # To get headers and status code we need to initiate the request, which is tricky to do 
    # cleanly while also streaming the body without a context block holding open the connection.
    # A cleaner pattern for FastAPI proxying with httpx:
    resp = await http_client.send(req, stream=True)
    
    return StreamingResponse(
        resp.aiter_raw(), 
        status_code=resp.status_code, 
        headers=dict(resp.headers),
        background=BackgroundTask(resp.aclose)
    )
