import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
import json
import asyncio
from dotenv import load_dotenv
from session_manager import manager
from agents.analyst import run_analyst

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

@app.post("/sessions")
async def create_session():
    session_id = manager.create_session()
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}

@app.post("/sessions/{session_id}/analyze")
async def analyze(session_id: str, background_tasks: BackgroundTasks):
    session = manager.get_session(session_id)
    if not session:
        logger.warning(f"Session {session_id} not found for analysis")
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Hardcoded prompt for Phase 1
    prompt = "Evaluate the financials of TargetCo (a mid-sized SaaS company) based on a hypothetical $50M ARR and 20% YoY growth."
    
    logger.info(f"Triggering analysis for session: {session_id}")
    background_tasks.add_task(run_analyst, session_id, prompt)
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
