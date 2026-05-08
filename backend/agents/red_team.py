import json
import logging
from session_manager import manager
from agents.utils import get_prompt, get_gemini_client

logger = logging.getLogger(__name__)

async def run_red_team(session_id: str):
    logger.info(f"Starting Red Team agent for session {session_id}")
    session = manager.get_session(session_id)
    if not session:
        logger.error(f"Session {session_id} not found")
        return

    workspace = session.workspace
    analysis = workspace.get("analysis", "")
    research = json.dumps(workspace.get("research_findings", []), indent=2)
    facts = workspace.get("facts", "")
    inputs = json.dumps(workspace.get("inputs", {}), indent=2)

    client = get_gemini_client()
    system_instruction = get_prompt("red_team")

    await manager.emit_event(session_id, "red_team", "status", "starting")

    try:
        prompt = (
            f"Review the Analyst's analysis against the full available context. "
            f"Identify every weakness, risk, optimistic assumption, and counterargument.\n\n"
            f"Original Inputs:\n{inputs}\n\n"
            f"Extracted Facts:\n{facts}\n\n"
            f"Research Findings:\n{research}\n\n"
            f"Analyst Analysis:\n{analysis}"
        )

        response_stream = await client.aio.models.generate_content_stream(
            model='gemini-3.1-pro-preview',
            contents=prompt,
            config={'system_instruction': system_instruction},
        )

        full_critique = ""
        async for chunk in response_stream:
            if chunk.text:
                full_critique += chunk.text
                await manager.emit_event(session_id, "red_team", "thought", chunk.text)

        session.workspace["red_team_critique"] = full_critique

        await manager.emit_event(session_id, "red_team", "status", "done")
        logger.info(f"Red Team agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Red Team agent: {e}")
        await manager.emit_event(session_id, "red_team", "error", str(e))
