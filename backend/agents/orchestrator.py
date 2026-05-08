import asyncio
import logging
import json
import re
from session_manager import manager
from agents.utils import get_prompt, get_gemini_client
from agents.researcher import run_researcher
from agents.analyst import run_analyst
from agents.red_team import run_red_team
from agents.synthesizer import run_synthesizer

logger = logging.getLogger(__name__)


def _clean_target_name(raw: str) -> str:
    """Validate the model-suggested target name. Reject empty, unknown, or
    obviously-not-a-name responses (long sentences, multi-line)."""
    if not raw:
        return "TargetCo"
    name = raw.strip().strip('"').strip("'").strip()
    name = name.splitlines()[0].strip() if name else ""
    if not name:
        return "TargetCo"
    if name.lower() in {"unknown", "n/a", "none", "not specified"}:
        return "TargetCo"
    # A company name shouldn't be a sentence — cap word count and length.
    if len(name) > 60 or len(name.split()) > 6:
        return "TargetCo"
    if not re.search(r"[A-Za-z]", name):
        return "TargetCo"
    return name


async def _detect_conflicts(client, analysis: str, critique: str) -> str:
    """Compare Analyst output against Red Team critique and return a one-line
    summary of the strongest disagreement, or empty string if none."""
    if not analysis.strip() or not critique.strip():
        return ""
    prompt = (
        "Compare the Analyst's analysis with the Red Team's critique. "
        "Identify the single strongest point of disagreement between them. "
        "Respond with ONE sentence in the form: "
        "'Analyst said X; Red Team flagged Y.' "
        "If they substantially agree, respond with exactly the word NONE.\n\n"
        f"Analyst:\n{analysis}\n\n"
        f"Red Team:\n{critique}"
    )
    try:
        resp = await client.aio.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        text = (resp.text or "").strip()
        if not text or text.upper().startswith("NONE"):
            return ""
        return text
    except Exception as e:
        logger.warning(f"Conflict detection failed: {e}")
        return ""


async def run_orchestrator(session_id: str):
    logger.info(f"Starting Orchestrator for session {session_id}")
    session = manager.get_session(session_id)
    if not session:
        logger.error(f"Session {session_id} not found")
        return

    client = get_gemini_client()
    system_instruction = get_prompt("orchestrator")

    await manager.emit_event(session_id, "orchestrator", "status", "starting")

    try:
        # Step 1: Parse inputs and extract facts
        await manager.emit_event(session_id, "orchestrator", "thought", "Parsing inputs and extracting key facts...")
        
        inputs_summary = json.dumps(session.workspace["inputs"], indent=2)
        
        facts_response = await client.aio.models.generate_content(
            model='gemini-2.0-flash',
            contents=f"Extract the most important facts from these inputs for an M&A analysis:\n\n{inputs_summary}",
            config={'system_instruction': system_instruction}
        )
        
        facts = facts_response.text
        session.workspace["facts"] = facts
        await manager.emit_event(session_id, "orchestrator", "thought", f"Extracted facts: {facts[:200]}...")

        # Step 2: Define a plan
        await manager.emit_event(session_id, "orchestrator", "thought", "Defining execution plan for specialized agents...")
        
        # Step 3: Run Researcher and Analyst in parallel
        await manager.emit_event(session_id, "orchestrator", "thought", "Launching Researcher and Analyst agents in parallel.")
        
        # Try to extract target name from facts
        name_extract = await client.aio.models.generate_content(
            model='gemini-2.0-flash',
            contents=f"What is the name of the target company in these facts? Return ONLY the company name, nothing else.\n\n{facts}",
        )
        target_name = _clean_target_name(name_extract.text if name_extract else "")

        results = await asyncio.gather(
            run_researcher(session_id, target_name),
            run_analyst(session_id, f"Analyze the acquisition of {target_name} based on the provided facts: {facts}"),
            return_exceptions=True,
        )
        for agent_name, result in zip(("researcher", "analyst"), results):
            if isinstance(result, Exception):
                logger.error(f"{agent_name} raised: {result}")
                await manager.emit_event(session_id, agent_name, "error", str(result))

        # Step 4: Run Red Team
        await manager.emit_event(session_id, "orchestrator", "thought", "Research and initial analysis complete. Launching Red Team for adversarial critique.")
        await run_red_team(session_id)

        # Step 5: Conflict detection (real, not hardcoded)
        await manager.emit_event(session_id, "orchestrator", "thought", "Checking for conflicts between Analyst findings and Red Team critique...")
        conflict = await _detect_conflicts(
            client,
            session.workspace.get("analysis", ""),
            session.workspace.get("red_team_critique", ""),
        )
        if conflict:
            await manager.emit_event(session_id, "orchestrator", "thought", f"⚡ Conflict detected: {conflict}")
        else:
            await manager.emit_event(session_id, "orchestrator", "thought", "No material conflict detected between Analyst and Red Team.")

        # Step 6: Run Synthesizer
        await manager.emit_event(session_id, "orchestrator", "thought", "All analyses complete. Synthesizing final board-ready brief.")
        await run_synthesizer(session_id)

        await manager.emit_event(session_id, "orchestrator", "status", "done")
        logger.info(f"Orchestrator finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Orchestrator: {e}")
        await manager.emit_event(session_id, "orchestrator", "error", str(e))
