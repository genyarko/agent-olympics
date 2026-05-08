import logging
import os
import json
import asyncio
from typing import List
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from session_manager import manager
from agents.orchestrator import run_orchestrator
from agents.multimodal import process_pdf, process_image, process_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Boardroom API")

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
    session_id = manager.create_session()
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}

@app.post("/sessions/{session_id}/inputs/document")
async def upload_document(session_id: str, file: UploadFile = File(...)):
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await file.read()
    if file.filename.lower().endswith(".pdf"):
        text = await process_pdf(content)
    else:
        text = content.decode("utf-8", errors="ignore")
    
    session.workspace["inputs"]["documents"].append({
        "filename": file.filename,
        "content": text
    })
    return {"status": "Document uploaded"}

@app.post("/sessions/{session_id}/inputs/image")
async def upload_image(session_id: str, file: UploadFile = File(...)):
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await file.read()
    description = await process_image(content)
    
    session.workspace["inputs"]["images"].append({
        "filename": file.filename,
        "description": description
    })
    return {"status": "Image uploaded"}

@app.post("/sessions/{session_id}/inputs/url")
async def add_url(session_id: str, url_input: UrlInput):
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    content = await process_url(url_input.url)
    session.workspace["inputs"]["urls"].append({
        "url": url_input.url,
        "content": content
    })
    return {"status": "URL added"}

@app.post("/sessions/{session_id}/inputs/text")
async def add_text(session_id: str, text_input: dict):
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    text = text_input.get("text", "")
    if text:
        # Prepend to raw_text if it already exists, or just set it
        if session.workspace["inputs"]["raw_text"]:
            session.workspace["inputs"]["raw_text"] += f"\n\n{text}"
        else:
            session.workspace["inputs"]["raw_text"] = text
            
    return {"status": "Text added"}

@app.post("/sessions/{session_id}/demo")
async def load_demo(session_id: str):
    session = manager.get_session(session_id)
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
    
    return {"status": "Demo scenario loaded"}

@app.post("/sessions/{session_id}/analyze")
async def analyze(session_id: str, background_tasks: BackgroundTasks):
    session = manager.get_session(session_id)
    if not session:
        logger.warning(f"Session {session_id} not found for analysis")
        raise HTTPException(status_code=404, detail="Session not found")
    
    logger.info(f"Triggering Orchestrator for session: {session_id}")
    background_tasks.add_task(run_orchestrator, session_id)
    return {"status": "Analysis started"}

@app.get("/sessions/{session_id}/stream")
async def stream(session_id: str, request: Request):
    session = manager.get_session(session_id)
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

@app.get("/")
async def root():
    return {"message": "Boardroom API is live", "status": "ok"}
