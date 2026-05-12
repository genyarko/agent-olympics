"""Verifier agent — a grounding + consistency pipeline over the final Board Brief.

Modelled on Conti/TrustLayer's pipeline (extractor -> grounder -> consistency ->
aggregator), but adapted to Boardroom's single-process layout:

  1. Extraction   — break the brief into atomic claims (factual/quantitative/interpretive).
  2. Grounding    — rapidfuzz fast path against source passages, then an LLM
                    semantic check for anything that isn't an obvious textual match.
  3. Consistency  — one LLM pass for internal contradictions + contradictions
                    against the source material.
  4. Aggregation  — weighted per-claim Integrity Score (grounding/consistency/type)
                    and an overall score with a hallucination penalty; claims are
                    classified VERIFIED / PLAUSIBLE / FLAGGED / HALLUCINATION.
"""
import logging
import json
import re
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any, Optional
from rapidfuzz import fuzz

from session_manager import manager
from agents.utils import (
    get_prompt, get_gemini_client, FLASH_MODEL,
    facts_text, research_findings_texts,
)

logger = logging.getLogger(__name__)

# --- Tunables --------------------------------------------------------------
FUZZY_VERIFIED = 88            # >= this fuzzy score -> treat as directly grounded
GROUNDING_WEIGHT = 0.50
CONSISTENCY_WEIGHT = 0.35
TYPE_WEIGHT = 0.15
HALLUCINATION_GROUNDING_MAX = 40
PARTIAL_GROUNDING_MIN = 60
VERIFIED_GROUNDING_MIN = 85
MAX_CORPUS_CHARS = 40000       # keep prompt size sane (see SCALING_NOTES.md)
MAX_PASSAGES = 600

_TYPE_MODIFIER = {"FACTUAL": 100, "QUANTITATIVE": 100, "INTERPRETIVE": 85}
_CONSISTENCY_SCORE = {"CONSISTENT": 100, "MINOR_CONCERN": 75, "INCONSISTENT": 25, "CONTRADICTORY": 0}

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


# --- Schemas ---------------------------------------------------------------
class Claim(BaseModel):
    text: str = Field(description="The atomic factual or quantitative claim.")
    type: Literal["QUANTITATIVE", "FACTUAL", "INTERPRETIVE"] = Field(description="The type of the claim.")


class ClaimExtractionList(BaseModel):
    claims: List[Claim]


class GroundingVerdict(BaseModel):
    index: int = Field(description="0-based index of the claim being judged.")
    support: Literal["FULL", "PARTIAL", "NONE"]
    confidence: int = Field(ge=0, le=100)
    matched_snippet: str = Field(default="", description="Verbatim source text that supports the claim, or empty string.")
    reasoning: str = ""


class GroundingBatch(BaseModel):
    verdicts: List[GroundingVerdict]


class ConsistencyVerdict(BaseModel):
    index: int
    verdict: Literal["CONSISTENT", "MINOR_CONCERN", "INCONSISTENT", "CONTRADICTORY"]
    confidence: int = Field(ge=1, le=10)
    reasoning: str = ""


class ConsistencyBatch(BaseModel):
    verdicts: List[ConsistencyVerdict]


# --- Helpers ---------------------------------------------------------------
def _split_passages(source: str) -> List[str]:
    """Sentence-ish passages so fuzzy matching scores against a real claim-sized
    span instead of an arbitrary window of a huge concatenated blob."""
    if not source.strip():
        return []
    out: List[str] = []
    for m in _SENTENCE_RE.finditer(source):
        s = m.group(0).strip()
        if len(s) >= 4:
            out.append(s)
        if len(out) >= MAX_PASSAGES:
            break
    if not out:
        out = [source.strip()]
    return out


def _best_fuzzy(query: str, passages: List[str]) -> tuple[int, str]:
    q = query.lower()
    best_score, best_passage = 0, ""
    for p in passages:
        s = max(fuzz.token_set_ratio(q, p.lower()), fuzz.partial_ratio(q, p.lower()))
        if s > best_score:
            best_score, best_passage = int(round(s)), p
    return best_score, best_passage


def _semantic_to_score(support: str, confidence: Any) -> int:
    try:
        conf = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        conf = 50
    s = (support or "NONE").upper()
    if s == "FULL":
        return min(100, 88 + conf // 9)        # 88..99
    if s == "PARTIAL":
        return min(87, 62 + conf // 4)          # 62..87
    return max(0, 30 - conf // 4)               # 30..5 (more-confident NONE -> lower)


def _parsed_or_json(response, key: str) -> Optional[list]:
    """Return the list under `key` from a schema-constrained response, falling
    back to parsing the raw text if `.parsed` didn't materialise."""
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        items = getattr(parsed, key, None)
        if items is not None:
            return list(items)
    try:
        data = json.loads(response.text)
        items = data.get(key)
        return list(items) if isinstance(items, list) else None
    except Exception:
        return None


def _coerce_claims(items) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for it in items or []:
        if hasattr(it, "text"):
            text, ctype = (it.text or "").strip(), getattr(it, "type", "FACTUAL")
        elif isinstance(it, dict):
            text, ctype = str(it.get("text", "")).strip(), str(it.get("type", "FACTUAL"))
        else:
            continue
        if not text:
            continue
        ctype = ctype.upper()
        if ctype not in _TYPE_MODIFIER:
            ctype = "FACTUAL"
        out.append({"text": text, "type": ctype})
    return out


# --- LLM passes ------------------------------------------------------------
async def _semantic_ground(client, claims: List[Dict[str, str]], indices: List[int], corpus: str) -> Dict[int, GroundingVerdict]:
    listing = "\n".join(f"[{i}] ({claims[i]['type']}) {claims[i]['text']}" for i in indices)
    prompt = (
        "You are grounding claims from an M&A board brief against the available source material.\n"
        "For EACH claim below, decide whether the SOURCE MATERIAL supports it:\n"
        "  FULL  — the source clearly states (or directly entails) the claim, numbers included;\n"
        "  PARTIAL — the source partially supports it / supports a weaker version;\n"
        "  NONE  — the source does not support it (this includes numbers that don't match).\n"
        "Be strict about quantitative claims: a different figure means NONE, not FULL.\n"
        "Return the verbatim supporting snippet when there is one.\n\n"
        f"SOURCE MATERIAL:\n{corpus}\n\n"
        f"CLAIMS:\n{listing}"
    )
    try:
        resp = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=prompt,
            config={'response_mime_type': 'application/json', 'response_schema': GroundingBatch},
        )
        verdicts = _parsed_or_json(resp, "verdicts") or []
        out: Dict[int, GroundingVerdict] = {}
        for v in verdicts:
            try:
                gv = v if isinstance(v, GroundingVerdict) else GroundingVerdict(**v)
            except Exception:
                continue
            out[gv.index] = gv
        return out
    except Exception as e:
        logger.warning("Semantic grounding failed: %s", e)
        return {}


async def _check_consistency(client, claims: List[Dict[str, str]], corpus: str, brief: str) -> Dict[int, ConsistencyVerdict]:
    listing = "\n".join(f"[{i}] ({c['type']}) {c['text']}" for i, c in enumerate(claims))
    prompt = (
        "You are a consistency checker for an M&A board brief. For EACH claim below, judge whether it is\n"
        "consistent (a) with the SOURCE MATERIAL and (b) with the OTHER claims in the brief:\n"
        "  CONSISTENT — no tension with the source or with sibling claims;\n"
        "  MINOR_CONCERN — slight tension / imprecision, not a real contradiction;\n"
        "  INCONSISTENT — sits awkwardly with the source or with another claim;\n"
        "  CONTRADICTORY — directly contradicts the source material or another claim.\n"
        "Give a confidence 1-10 and a one-sentence reason.\n\n"
        f"SOURCE MATERIAL:\n{corpus}\n\n"
        f"BOARD BRIEF (for cross-claim context):\n{brief}\n\n"
        f"CLAIMS:\n{listing}"
    )
    try:
        resp = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=prompt,
            config={'response_mime_type': 'application/json', 'response_schema': ConsistencyBatch},
        )
        verdicts = _parsed_or_json(resp, "verdicts") or []
        out: Dict[int, ConsistencyVerdict] = {}
        for v in verdicts:
            try:
                cv = v if isinstance(v, ConsistencyVerdict) else ConsistencyVerdict(**v)
            except Exception:
                continue
            out[cv.index] = cv
        return out
    except Exception as e:
        logger.warning("Consistency check failed: %s", e)
        return {}


# --- Main ------------------------------------------------------------------
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

    final_brief = json.dumps(synthesis, indent=2)

    # --- Build the ground-truth corpus (facts + research + raw inputs) ------
    corpus_parts: List[str] = []
    f = facts_text(session.workspace)
    if f.strip():
        corpus_parts.append(f)
    corpus_parts.extend(research_findings_texts(session.workspace))
    inputs = session.workspace.get("inputs", {}) or {}
    for doc in inputs.get("documents", []) or []:
        c = (doc or {}).get("content", "")
        if c:
            corpus_parts.append(str(c))
    for u in inputs.get("urls", []) or []:
        c = (u or {}).get("content", "")
        if c:
            corpus_parts.append(str(c))
    for img in inputs.get("images", []) or []:
        d = (img or {}).get("description", "")
        if d:
            corpus_parts.append(str(d))
    raw = inputs.get("raw_text", "") or ""
    if raw.strip():
        corpus_parts.append(raw)

    source_corpus = "\n\n".join(p for p in corpus_parts if p and p.strip())
    if len(source_corpus) > MAX_CORPUS_CHARS:
        source_corpus = source_corpus[:MAX_CORPUS_CHARS] + "\n…[source material truncated]"
    passages = _split_passages(source_corpus)
    has_corpus = bool(source_corpus.strip())

    client = get_gemini_client()
    system_instruction = get_prompt("verifier")

    await manager.emit_event(session_id, "verifier", "thought", "Extracting claims for verification...")

    try:
        # --- 1. Extract claims --------------------------------------------
        resp = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=f"Extract all critical claims from the following Board Brief:\n\n{final_brief}",
            config={
                'system_instruction': system_instruction,
                'response_mime_type': 'application/json',
                'response_schema': ClaimExtractionList,
            },
        )
        claims = _coerce_claims(_parsed_or_json(resp, "claims"))

        if not claims:
            report = {
                "integrity_score": 100,
                "total_claims_checked": 0,
                "verified_count": 0, "plausible_count": 0,
                "flagged_count": 0, "hallucination_count": 0,
                "claims": [],
                "note": "No verifiable claims were extracted from the brief.",
            }
            session = await manager.get_session(session_id)
            if session:
                session.workspace["verification_report"] = report
                await manager.save_session(session)
            await manager.emit_event(session_id, "verifier", "verification_report", json.dumps(report))
            await manager.emit_event(session_id, "verifier", "status", "done")
            return

        await manager.emit_event(session_id, "verifier", "thought", f"Extracted {len(claims)} claims. Grounding against {len(passages)} source passages…")

        # --- 2. Fuzzy fast path -------------------------------------------
        # QUANTITATIVE claims always go through the LLM semantic check: a fuzzy
        # ratio can't tell "$50M" from "$500M" (they score ~92), so the fast
        # path would happily "verify" a 10x hallucinated figure.
        fuzzy: List[tuple[int, str]] = []
        needs_semantic: List[int] = []
        for i, c in enumerate(claims):
            score, passage = _best_fuzzy(c["text"], passages) if passages else (0, "")
            fuzzy.append((score, passage))
            if c["type"] == "QUANTITATIVE" or score < FUZZY_VERIFIED:
                needs_semantic.append(i)

        semantic_set = set(needs_semantic)
        grounding: Dict[int, Dict[str, Any]] = {}
        for i, (score, passage) in enumerate(fuzzy):
            if i not in semantic_set:  # fuzzy was decisive
                grounding[i] = {"score": score, "snippet": passage, "reasoning": "Direct textual match against source.", "semantic": False}

        # --- 3. Semantic grounding for the rest ---------------------------
        if needs_semantic and has_corpus:
            await manager.emit_event(session_id, "verifier", "thought", f"Running semantic grounding on {len(needs_semantic)} claim(s)…")
            verdicts = await _semantic_ground(client, claims, needs_semantic, source_corpus)
        else:
            verdicts = {}

        for i in needs_semantic:
            fz_score, fz_passage = fuzzy[i]
            v = verdicts.get(i)
            if v is None:
                grounding[i] = {
                    "score": fz_score,
                    "snippet": fz_passage,
                    "reasoning": "Fuzzy match against source." if has_corpus else "No source material available for grounding.",
                    "semantic": False,
                }
                continue
            sem_score = _semantic_to_score(v.support, v.confidence)
            if v.support.upper() == "NONE":
                final_score = min(fz_score, sem_score)        # downgrade fuzzy false-positives
            else:
                final_score = max(fz_score, sem_score)
            grounding[i] = {
                "score": max(0, min(100, final_score)),
                "snippet": (v.matched_snippet or "").strip() or fz_passage,
                "reasoning": v.reasoning or f"Semantic grounding verdict: {v.support}.",
                "semantic": True,
            }

        # --- 4. Consistency check -----------------------------------------
        await manager.emit_event(session_id, "verifier", "thought", "Checking internal and source consistency…")
        cverdicts = await _check_consistency(client, claims, source_corpus, final_brief)
        consistency: Dict[int, Dict[str, Any]] = {}
        for i in range(len(claims)):
            v = cverdicts.get(i)
            if v is None:
                consistency[i] = {"verdict": "CONSISTENT", "confidence": 5, "reasoning": "Not assessed."}
            else:
                consistency[i] = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning}

        # --- 5. Aggregate --------------------------------------------------
        result_claims: List[Dict[str, Any]] = []
        counts = {"VERIFIED": 0, "PLAUSIBLE": 0, "FLAGGED": 0, "HALLUCINATION": 0}
        integrity_sum = 0

        for i, c in enumerate(claims):
            g = grounding[i]
            cons = consistency[i]
            g_score = max(0, min(100, int(g["score"])))

            cons_score = _CONSISTENCY_SCORE.get(cons["verdict"], 25)
            if cons_score < 75:
                conf = max(1, min(10, int(cons.get("confidence", 5))))
                cons_score = min(cons_score + (10 - conf) * 2, 60)
            type_mod = _TYPE_MODIFIER.get(c["type"], 100)

            integrity = round(GROUNDING_WEIGHT * g_score + CONSISTENCY_WEIGHT * cons_score + TYPE_WEIGHT * type_mod)
            integrity = max(0, min(100, integrity))

            is_consistent = cons["verdict"] in ("CONSISTENT", "MINOR_CONCERN")
            contradicts = cons["verdict"] == "CONTRADICTORY"
            if g_score < HALLUCINATION_GROUNDING_MAX and not is_consistent:
                status = "HALLUCINATION"
            elif g_score < PARTIAL_GROUNDING_MIN or contradicts:
                status = "FLAGGED"
            elif g_score >= VERIFIED_GROUNDING_MIN and cons["verdict"] == "CONSISTENT":
                status = "VERIFIED"
            else:
                status = "PLAUSIBLE"
            counts[status] += 1
            integrity_sum += integrity

            reasoning_bits = [g["reasoning"]]
            if cons["reasoning"] and cons["reasoning"] != "Not assessed.":
                reasoning_bits.append(f"Consistency ({cons['verdict']}): {cons['reasoning']}")
            snippet = g["snippet"]
            result_claims.append({
                "claim": c["text"],
                "type": c["type"],
                "score": g_score,
                "integrity_score": integrity,
                "status": status,
                "consistency": cons["verdict"],
                "reasoning": " | ".join(b for b in reasoning_bits if b),
                "best_source_snippet": (snippet[:240] + "…") if snippet else "None",
            })

        overall = round(integrity_sum / len(claims))
        overall = max(0, min(100, overall - min(30, counts["HALLUCINATION"] * 10)))

        report = {
            "integrity_score": overall,
            "total_claims_checked": len(claims),
            "verified_count": counts["VERIFIED"],
            "plausible_count": counts["PLAUSIBLE"],
            "flagged_count": counts["FLAGGED"],
            "hallucination_count": counts["HALLUCINATION"],
            "claims": result_claims,
        }

        session = await manager.get_session(session_id)
        if session:
            session.workspace["verification_report"] = report
            await manager.save_session(session)

        flagged = counts["FLAGGED"] + counts["HALLUCINATION"]
        summary = f"Verification complete. Integrity Score: {overall}/100"
        if flagged:
            summary += f" — {flagged} claim(s) flagged for human review ({counts['HALLUCINATION']} possible hallucination(s))."
        await manager.emit_event(session_id, "verifier", "thought", summary)
        await manager.emit_event(session_id, "verifier", "verification_report", json.dumps(report))
        await manager.emit_event(session_id, "verifier", "status", "done")
        logger.info(f"Verifier agent finished for session {session_id}")

    except Exception as e:
        logger.error(f"Error in Verifier agent: {e}")
        await manager.emit_event(session_id, "verifier", "error", str(e))
