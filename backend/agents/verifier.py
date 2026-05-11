import logging
import json
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any
from rapidfuzz import fuzz

from session_manager import manager
from agents.utils import get_prompt, get_gemini_client

logger = logging.getLogger(__name__)

class Claim(BaseModel):
    text: str = Field(description="The atomic factual or quantitative claim.")
    type: Literal["QUANTITATIVE", "FACTUAL", "INTERPRETIVE"] = Field(description="The type of the claim.")

class ClaimExtractionList(BaseModel):
    claims: List[Claim]

async def run_verifier(session_id: str):
    logger.info(f"Starting Verifier agent for session {session_id}")
    await manager.emit_event(session_id, "verifier", "status", "starting")
    
    session = await manager.get_session(session_id)
    if not session:
        logger.error("Session not found")
        return
        
    synthesis = session.workspace.get("synthesis", {})
    if not synthesis:
        logger.warning("No synthesis found to verify.")
        await manager.emit_event(session_id, "verifier", "status", "skipped (no synthesis)")
        return

    final_brief = json.dumps(synthesis)
    facts = session.workspace.get("facts", [])
    research_findings = session.workspace.get("research_findings", [])
    
    # Combine all ground truth texts
    ground_truth_texts = [str(f) for f in facts] + [str(r) for r in research_findings]
    # Also add raw document inputs to ground truth corpus just in case
    for doc in session.workspace.get("inputs", {}).get("documents", []):
        ground_truth_texts.append(doc.get("content", ""))
    for text in session.workspace.get("inputs", {}).get("raw_text", "").split("\n"):
        if text.strip():
            ground_truth_texts.append(text)
            
    client = get_gemini_client()
    system_instruction = get_prompt("verifier")
    
    prompt = f"Extract all critical claims from the following Board Brief:\n\n{final_brief}"

    await manager.emit_event(session_id, "verifier", "thought", "Extracting claims for verification...")
    
    try:
        response = await client.aio.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config={
                'system_instruction': system_instruction,
                'response_mime_type': 'application/json',
                'response_schema': ClaimExtractionList
            },
        )
        
        extraction = response.parsed
        if not extraction or not hasattr(extraction, 'claims'):
            # Fallback if parsed fails
            raw_data = json.loads(response.text)
            claims_data = raw_data.get("claims", [])
        else:
            claims_data = [{"text": c.text, "type": c.type} for c in extraction.claims]
            
        await manager.emit_event(session_id, "verifier", "thought", f"Extracted {len(claims_data)} claims. Starting grounding checks.")
        
        verified_claims = []
        total_score = 0
        
        for claim in claims_data:
            claim_text = claim["text"]
            best_score = 0
            best_match = ""
            
            # 1. Fuzzy matching (rapidfuzz) against ground truth texts
            for truth in ground_truth_texts:
                if not truth: continue
                # We use partial_ratio to see if the claim is highly similar to a sub-string in the truth
                score = fuzz.partial_ratio(claim_text.lower(), truth.lower())
                if score > best_score:
                    best_score = score
                    best_match = truth
            
            # Simple threshold for fuzzy matching
            if best_score > 85:
                status = "VERIFIED"
            elif best_score > 60:
                status = "PLAUSIBLE"
            else:
                status = "UNVERIFIED"
                
            verified_claims.append({
                "claim": claim_text,
                "type": claim["type"],
                "score": round(best_score, 2),
                "status": status,
                "best_source_snippet": best_match[:200] + "..." if best_match else "None"
            })
            
            total_score += best_score
            
        # 2. Integrity Scoring
        integrity_score = 0
        if claims_data:
            integrity_score = round(total_score / len(claims_data), 2)
            
        report = {
            "integrity_score": integrity_score,
            "total_claims_checked": len(claims_data),
            "claims": verified_claims
        }
        
        session.workspace["verification_report"] = report
        await manager.save_session(session)
        
        await manager.emit_event(
            session_id, 
            "verifier", 
            "thought", 
            f"Verification complete. Overall Integrity Score: {integrity_score}/100"
        )
        
        await manager.emit_event(session_id, "verifier", "verification_report", json.dumps(report))
        await manager.emit_event(session_id, "verifier", "status", "done")
        logger.info(f"Verifier agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Verifier agent: {e}")
        await manager.emit_event(session_id, "verifier", "error", str(e))
