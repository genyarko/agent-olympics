import os
import asyncio
import logging
from google import genai
from session_manager import manager

logger = logging.getLogger(__name__)

async def run_analyst(session_id: str, prompt: str):
    logger.info(f"Starting Analyst agent for session {session_id}")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if location == "global":
        location = "us-central1"
    
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location
    )

    system_instruction = (
        "You are the Lead Analyst in a high-stakes M&A war room. "
        "Your goal is to evaluate the business model, financials, and market fit of a target company. "
        "Be professional, data-driven, and thorough. "
        "Stream your reasoning and findings as you work."
    )

    await manager.emit_event(session_id, "analyst", "status", "starting")

    try:
        response_stream = await client.aio.models.generate_content_stream(
            model='gemini-2.5-flash',
            contents=prompt,
            config={'system_instruction': system_instruction},
        )

        full_analysis = ""
        async for chunk in response_stream:
            if chunk.text:
                full_analysis += chunk.text
                await manager.emit_event(session_id, "analyst", "thought", chunk.text)

        session = manager.get_session(session_id)
        if session:
            session.workspace["analysis"] = full_analysis

        await manager.emit_event(session_id, "analyst", "status", "done")
        logger.info(f"Analyst agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Analyst agent: {e}")
        await manager.emit_event(session_id, "analyst", "error", str(e))
