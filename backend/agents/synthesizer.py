import logging
import json
from pydantic import BaseModel, Field
from typing import List
from session_manager import manager
from agents.utils import get_prompt, get_gemini_client, workspace_for_synthesis

logger = logging.getLogger(__name__)

class Strength(BaseModel):
    point: str
    source_citation: str

class Risk(BaseModel):
    point: str
    severity: str = Field(description="high, medium, or low")
    source_citation: str

class ExecutiveBrief(BaseModel):
    recommendation: str = Field(description="Proceed, Proceed with conditions, Decline, or Investigate further")
    confidence_score: int = Field(description="Score from 0-100")
    confidence_explanation: str
    one_paragraph_summary: str
    key_strengths: List[Strength]
    key_risks: List[Risk]
    follow_up_questions: List[str]
    dissenting_views: List[str]

async def run_synthesizer(session_id: str):
    logger.info(f"Starting Synthesizer agent for session {session_id}")
    session = manager.get_session(session_id)
    if not session:
        logger.error(f"Session {session_id} not found")
        return

    workspace_summary = json.dumps(workspace_for_synthesis(session.workspace), indent=2)

    client = get_gemini_client()
    system_instruction = get_prompt("synthesizer")

    await manager.emit_event(session_id, "synthesizer", "status", "starting")

    try:
        await manager.emit_event(session_id, "synthesizer", "thought", "Synthesizing all agent findings into a board-ready brief...")

        prompt = (
            f"Review the entire workspace and produce the final executive brief.\n\n"
            f"Workspace State:\n{workspace_summary}"
        )

        # Stream a short reasoning pass first so the panel shows live work
        # before the schema-constrained call returns.
        reasoning_stream = await client.aio.models.generate_content_stream(
            model='gemini-2.0-pro-exp-02-05',
            contents=(
                "Briefly walk through how you will weigh the Analyst's findings "
                "against the Red Team's critique to produce the recommendation. "
                "Two short paragraphs maximum.\n\n"
                f"Workspace State:\n{workspace_summary}"
            ),
            config={'system_instruction': system_instruction},
        )
        async for chunk in reasoning_stream:
            if chunk.text:
                await manager.emit_event(session_id, "synthesizer", "thought", chunk.text)

        await manager.emit_event(session_id, "synthesizer", "thought", "Producing structured brief...")

        response = await client.aio.models.generate_content(
            model='gemini-2.0-pro-exp-02-05',
            contents=prompt,
            config={
                'system_instruction': system_instruction,
                'response_mime_type': 'application/json',
                'response_schema': ExecutiveBrief,
            },
        )

        brief_data = response.parsed
        session.workspace["synthesis"] = brief_data.model_dump()

        # Emit the brief as a final event content
        await manager.emit_event(session_id, "synthesizer", "brief", json.dumps(session.workspace["synthesis"]))

        await manager.emit_event(session_id, "synthesizer", "status", "done")
        logger.info(f"Synthesizer agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Synthesizer agent: {e}")
        await manager.emit_event(session_id, "synthesizer", "error", str(e))
