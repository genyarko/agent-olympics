import logging
from session_manager import manager
from agents.utils import get_prompt, get_gemini_client

logger = logging.getLogger(__name__)

async def run_analyst(session_id: str, prompt: str):
    logger.info(f"Starting Analyst agent for session {session_id}")
    client = get_gemini_client()
    system_instruction = get_prompt("analyst")

    await manager.emit_event(session_id, "analyst", "status", "starting")

    try:
        response_stream = await client.aio.models.generate_content_stream(
            model='gemini-2.0-pro-exp-02-05',
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
