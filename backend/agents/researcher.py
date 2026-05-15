import os
import logging
import httpx
from session_manager import manager
from agents.utils import get_prompt, get_gemini_client, PRO_MODEL, FLASH_MODEL, sniff_image_mime

logger = logging.getLogger(__name__)


# TargetCo cached results are kept only as a fallback for the built-in TargetCo
# demo scenario. They MUST NOT be returned for unrelated pitches — that
# contaminates the workspace with fictional logistics-SaaS financials (see
# 2026-05-15 CocoaGuard run where this produced "$1.2B logistics company"
# noise across the whole brief).
TARGETCO_DEMO_RESULTS = """Source: https://techcrunch.com/targetco-funding
Content: TargetCo raised $80M Series C led by VentureFront at a $1.2B post-money valuation. Customers cited include three Fortune 500 logistics operators; the top customer reportedly accounts for ~28% of ARR.

Source: https://www.crunchbase.com/organization/targetco
Content: Founded 2018, headquartered in Austin. ~220 FTEs, with ~60% in engineering. Reported ARR of $50M growing 40% YoY. Gross margin disclosed at ~72%; net retention 118%.

Source: https://news.example.com/logismart-vs-targetco
Content: Competitor LogiSmart announced an aggressive enterprise discount program and a $40M ARR milestone. Analysts note the supply-chain optimization category is consolidating.

Source: https://blog.targetco.com/security-incident-2025
Content: TargetCo disclosed a customer data exposure event in Q1 2025 affecting two enterprise tenants. The company says it has remediated and engaged a third-party auditor.
"""

NO_RESEARCH_STUB = (
    "[No external research available — TAVILY_API_KEY is not configured on this deployment, "
    "and no relevant cached fixture matches this topic.]\n\n"
    "Proceed using only the user-provided source materials (uploaded documents, images, URLs, "
    "and pasted text). Do NOT invent competitor names, funding rounds, ARR figures, customer "
    "concentration percentages, security incidents, or other quantitative facts. If a question "
    "requires external context you do not have, flag it as a follow-up rather than fabricating "
    "a number."
)


def _is_targetco_topic(topic: str) -> bool:
    """Return True only when the orchestrator's topic genuinely references the
    bundled TargetCo demo (so we don't dump SaaS-logistics numbers onto an
    agritech / healthcare / fintech pitch by accident)."""
    if not topic:
        return False
    t = topic.lower()
    return "targetco" in t or "logismart" in t


async def search_tavily(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        if _is_targetco_topic(query):
            logger.warning("TAVILY_API_KEY not set; serving TargetCo demo fixture for topic %r", query)
            return TARGETCO_DEMO_RESULTS
        logger.warning("TAVILY_API_KEY not set and topic %r is not the TargetCo demo; returning no-research stub", query)
        return NO_RESEARCH_STUB

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": 5,
                },
                timeout=15.0,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                logger.warning("Tavily returned no results for %r", query)
                if _is_targetco_topic(query):
                    return TARGETCO_DEMO_RESULTS
                return NO_RESEARCH_STUB
            return "\n\n".join(
                f"Source: {r['url']}\nContent: {r['content']}" for r in results
            )
        except Exception as e:
            logger.error(f"Tavily search error: {e}")
            if _is_targetco_topic(query):
                return TARGETCO_DEMO_RESULTS
            return NO_RESEARCH_STUB

async def run_researcher(session_id: str, topic: str):
    logger.info(f"Starting Researcher agent for session {session_id}")
    session = await manager.get_session(session_id)
    client = get_gemini_client()
    system_instruction = get_prompt("researcher")

    await manager.emit_event(session_id, "researcher", "status", "starting")

    try:
        await manager.emit_event(session_id, "researcher", "thought", f"Deciding search strategy for {topic}...")
        
        # Step 1: Generate search query
        search_query_response = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=f"Generate a single effective search query to find news, filings, and competitor intel for: {topic}",
            config={'system_instruction': system_instruction}
        )
        search_query = search_query_response.text.strip().strip('"')
        
        await manager.emit_event(session_id, "researcher", "thought", f"Searching for: {search_query}")
        
        # Step 2: Perform search
        search_results = await search_tavily(search_query)
        
        # Step 3: Synthesize with multimodal capabilities if images exist
        await manager.emit_event(session_id, "researcher", "thought", "Synthesizing research findings...")
        
        contents = [f"Based on these search results, provide a concise summary of findings for {topic}:\n\n{search_results}"]
        
        # Load images if any
        images = session.workspace.get("inputs", {}).get("images", []) if session else []
        image_data = []
        for img in images:
            storage_key = img.get("storage_key")
            if storage_key and storage_key != "local_or_unconfigured" and storage_key != "error":
                data = await manager.download_artifact_from_r2(storage_key)
                if data:
                    image_data.append({"filename": img.get("filename"), "data": data})

        if image_data:
            contents[0] += "\n\nAdditionally, please analyze the following visual assets provided in the workspace context."
            for img in image_data:
                contents.append({
                    "mime_type": sniff_image_mime(img["data"], img.get("filename")),
                    "data": img["data"]
                })

        response_stream = await client.aio.models.generate_content_stream(
            model=PRO_MODEL,  # advanced multimodal reasoning
            contents=contents,
            config={'system_instruction': system_instruction},
        )

        full_findings = ""
        async for chunk in response_stream:
            if chunk.text:
                full_findings += chunk.text
                await manager.emit_event(session_id, "researcher", "thought", chunk.text)

        session = await manager.get_session(session_id)
        if session:
            session.workspace["research_findings"].append({
                "topic": topic,
                "content": full_findings
            })
            await manager.save_session(session)

        await manager.emit_event(session_id, "researcher", "status", "done")
        logger.info(f"Researcher agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Researcher agent: {e}")
        await manager.emit_event(session_id, "researcher", "error", str(e))
