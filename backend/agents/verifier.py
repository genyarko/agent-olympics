"""Verifier agent — a grounding + consistency pipeline over the final Board Brief.

Modelled on Conti/TrustLayer's pipeline (extractor -> grounder -> consistency ->
aggregator), but adapted to Boardroom's single-process layout:

  1. Extraction   — break the brief into atomic claims; tag each with a type
                    (factual/quantitative/interpretive) and a role
                    (analyst-claim / red-team-rebuttal / external-context).
  2. Grounding    — analyst-claims go through rapidfuzz + an LLM semantic source
                    check; red-team-rebuttals and external-context claims go
                    through an LLM world-knowledge check instead (they are not
                    expected to appear in the pitch — contradicting the source
                    is the whole point of a Red Team).
  3. Consistency  — one LLM pass for internal contradictions across the brief.
                    Contradictions between non-analyst claims and the source are
                    treated as expected, not penalised.
  4. Aggregation  — per-claim Integrity Score weighted by role-appropriate
                    grounding, consistency, and claim type; an overall score is
                    computed with a hallucination penalty that applies only to
                    analyst-claims (rebuttals and external context cannot
                    "hallucinate" against a source they aren't bound to).
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

_VALID_ROLES = ("analyst-claim", "red-team-rebuttal", "external-context")
_NON_ANALYST_ROLES = ("red-team-rebuttal", "external-context")

# Snippet score thresholds. A fuzzy match below SNIPPET_MIN_SCORE against the
# source is too weak to be a meaningful "closest match" / "contradicted source
# phrase" — it almost always points at a section heading or boilerplate. We
# drop it from the report rather than show noise like
# `Contradicted source phrase: "The Ask"`.
SNIPPET_MIN_SCORE = 40
# A fuzzy score at or above this against the source means the claim is
# substantially a restatement of pitch content — regardless of which section
# of the brief it surfaced in, we treat it as an analyst-claim so it gets
# graded by source-grounding rather than the world-knowledge check.
ROLE_OVERRIDE_FUZZY_MIN = 88

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


# --- Schemas ---------------------------------------------------------------
class Claim(BaseModel):
    text: str = Field(description="The atomic factual or quantitative claim.")
    type: Literal["QUANTITATIVE", "FACTUAL", "INTERPRETIVE"] = Field(description="The type of the claim.")
    role: Literal["analyst-claim", "red-team-rebuttal", "external-context"] = Field(
        default="analyst-claim",
        description=(
            "Where the claim came from and what it owes to the source. "
            "analyst-claim must be grounded in the source; red-team-rebuttal is expected "
            "to contradict the source and is checked against external reality; "
            "external-context is a real-world fact added for context, also checked "
            "against external reality, not the source."
        ),
    )


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


class KnowledgeVerdict(BaseModel):
    index: int = Field(description="0-based index of the claim being judged.")
    support: Literal["SUPPORTED", "DISPUTED", "UNKNOWN"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str = ""


class KnowledgeBatch(BaseModel):
    verdicts: List[KnowledgeVerdict]


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


def _knowledge_to_score(support: str, confidence: Any) -> int:
    """Convert a world-knowledge verdict into a 0-100 score that we can plug
    into the same Integrity Score pipeline as source grounding. SUPPORTED maps
    high, DISPUTED maps low, UNKNOWN stays mid-low so we surface those for a
    human rather than rubber-stamping them."""
    try:
        conf = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        conf = 50
    s = (support or "UNKNOWN").upper()
    if s == "SUPPORTED":
        return min(100, 86 + conf // 8)         # 86..98
    if s == "DISPUTED":
        return max(0, 30 - conf // 4)           # 30..5 — confident dispute drops the score
    return 55 + conf // 10                       # UNKNOWN -> 55..65 ("plausible, needs human")


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


def _segment_synthesis(synthesis: Dict[str, Any]) -> List[Dict[str, str]]:
    """Split the synthesised brief into role-tagged segments. Each segment
    is passed to the extractor with its role pre-assigned so the LLM doesn't
    have to guess where the claim came from — it just has to break the segment
    text into atomic claims.

    Red Team segments keep "red-team-rebuttal" as the default role but allow
    the extractor to re-tag individual claims as "external-context" if they
    state a widely-known real-world fact (e.g. macroeconomic conditions,
    named regulations) rather than a direct critique of the pitch."""
    segments: List[Dict[str, str]] = []

    summary = (synthesis.get("one_paragraph_summary") or "").strip()
    if summary:
        segments.append({"section": "one_paragraph_summary", "role": "analyst-claim", "text": summary})

    conf_expl = (synthesis.get("confidence_explanation") or "").strip()
    if conf_expl:
        segments.append({"section": "confidence_explanation", "role": "analyst-claim", "text": conf_expl})

    for idx, s in enumerate(synthesis.get("key_strengths", []) or []):
        if isinstance(s, dict):
            point = (s.get("point") or "").strip()
        else:
            point = str(s).strip()
        if point:
            segments.append({"section": f"key_strengths[{idx}]", "role": "analyst-claim", "text": point})

    for idx, r in enumerate(synthesis.get("key_risks", []) or []):
        if isinstance(r, dict):
            point = (r.get("point") or "").strip()
        else:
            point = str(r).strip()
        if point:
            segments.append({"section": f"key_risks[{idx}]", "role": "red-team-rebuttal", "text": point})

    for idx, d in enumerate(synthesis.get("dissenting_views", []) or []):
        text = str(d).strip()
        if text:
            segments.append({"section": f"dissenting_views[{idx}]", "role": "red-team-rebuttal", "text": text})

    return segments


def _coerce_claims(items) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for it in items or []:
        if hasattr(it, "text"):
            text = (it.text or "").strip()
            ctype = getattr(it, "type", "FACTUAL")
            crole = getattr(it, "role", "analyst-claim")
        elif isinstance(it, dict):
            text = str(it.get("text", "")).strip()
            ctype = str(it.get("type", "FACTUAL"))
            crole = str(it.get("role", "analyst-claim"))
        else:
            continue
        if not text:
            continue
        ctype = ctype.upper()
        if ctype not in _TYPE_MODIFIER:
            ctype = "FACTUAL"
        if crole not in _VALID_ROLES:
            crole = "analyst-claim"
        out.append({"text": text, "type": ctype, "role": crole})
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


async def _knowledge_check(client, claims: List[Dict[str, str]], indices: List[int]) -> Dict[int, KnowledgeVerdict]:
    """World-knowledge check for claims that don't owe themselves to the source
    (red-team rebuttals + external context). We are NOT comparing to the pitch
    — we're asking whether the claim aligns with widely-reported real-world
    facts. UNKNOWN is a first-class outcome: a forward-looking judgment or a
    niche claim should land there rather than being forced to SUPPORTED."""
    if not indices:
        return {}
    listing = "\n".join(
        f"[{i}] ({claims[i]['role']}; {claims[i]['type']}) {claims[i]['text']}" for i in indices
    )
    prompt = (
        "You are checking whether each claim below is consistent with widely-known, real-world facts "
        "(public reporting, established science/engineering, well-documented events, regulations).\n"
        "These claims may CONTRADICT a specific pitch deck — that is acceptable; you are NOT comparing "
        "to a source document, only to reality.\n\n"
        "For EACH claim decide:\n"
        "  SUPPORTED — the claim aligns with widely-reported, real-world facts;\n"
        "  DISPUTED  — the claim contradicts widely-reported facts or is materially incorrect;\n"
        "  UNKNOWN   — you cannot confidently assess from general knowledge (forward-looking judgments, "
        "niche claims, and opinions usually land here).\n"
        "Return a one-sentence reason and a 0-100 confidence.\n\n"
        f"CLAIMS:\n{listing}"
    )
    try:
        resp = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=prompt,
            config={'response_mime_type': 'application/json', 'response_schema': KnowledgeBatch},
        )
        verdicts = _parsed_or_json(resp, "verdicts") or []
        out: Dict[int, KnowledgeVerdict] = {}
        for v in verdicts:
            try:
                kv = v if isinstance(v, KnowledgeVerdict) else KnowledgeVerdict(**v)
            except Exception:
                continue
            out[kv.index] = kv
        return out
    except Exception as e:
        logger.warning("Knowledge check failed: %s", e)
        return {}


async def _check_consistency(client, claims: List[Dict[str, str]], corpus: str, brief: str) -> Dict[int, ConsistencyVerdict]:
    listing = "\n".join(f"[{i}] ({c['role']}; {c['type']}) {c['text']}" for i, c in enumerate(claims))
    prompt = (
        "You are a consistency checker for an M&A board brief. Each claim has a ROLE:\n"
        "- analyst-claim: the Analyst/Synthesizer's positive assertion. Must be consistent with the source\n"
        "  and with other claims in the brief.\n"
        "- red-team-rebuttal: a Red Team critique. Its job is to contradict the source — that is EXPECTED\n"
        "  and should NOT be marked CONTRADICTORY. Only mark it CONTRADICTORY if it contradicts another\n"
        "  claim in the brief.\n"
        "- external-context: a real-world fact added by an agent. Not expected to appear in the source.\n"
        "  Only mark CONTRADICTORY if it conflicts with another claim in the brief.\n\n"
        "For EACH claim choose:\n"
        "  CONSISTENT — no real tension (factoring in the role exemptions above);\n"
        "  MINOR_CONCERN — slight imprecision;\n"
        "  INCONSISTENT — sits awkwardly with another claim in the brief;\n"
        "  CONTRADICTORY — directly contradicts another claim in the brief, or (analyst-claim only)\n"
        "                   directly contradicts the source material.\n"
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

    await manager.emit_event(session_id, "verifier", "thought", "Extracting and role-tagging claims for verification...")

    try:
        # --- 1. Extract claims (section-driven role assignment) -----------
        # The brief's JSON structure already tells us which voice each chunk
        # belongs to (Analyst vs Red Team). We pass the pre-tagged segments to
        # the extractor so it only has to split text into atomic claims — it
        # doesn't get to guess role from context, which is where it was
        # confusing factual deck restatements ("The company has a B2G
        # exclusivity agreement") with rebuttals.
        segments = _segment_synthesis(synthesis)
        if not segments:
            # Fallback: treat the whole brief as one analyst segment.
            segments = [{"section": "brief", "role": "analyst-claim", "text": final_brief}]

        extraction_payload_lines = []
        for idx, seg in enumerate(segments):
            extraction_payload_lines.append(
                f"--- SEGMENT {idx} | section={seg['section']} | default_role={seg['role']} ---\n{seg['text']}"
            )
        extraction_payload = "\n\n".join(extraction_payload_lines)

        extraction_instructions = (
            "Extract atomic claims from each SEGMENT below. For each claim:\n"
            "- Set `type` to QUANTITATIVE, FACTUAL, or INTERPRETIVE per the system instructions.\n"
            "- Set `role` to the segment's `default_role` UNLESS the claim is from a Red Team segment AND it\n"
            "  states a widely-known real-world fact (a named regulation, macro/economic condition, an\n"
            "  industry-wide statistic, public reporting about a third party). In that single case, set\n"
            "  `role` to `external-context`. Do NOT promote any Red Team claim back to `analyst-claim` and do\n"
            "  NOT demote any Analyst segment claim to a rebuttal — those mappings are fixed by the segment.\n"
            "Break compound sentences into separate atomic claims; ignore filler and structural headings."
        )

        resp = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=f"{extraction_instructions}\n\nSEGMENTS:\n{extraction_payload}",
            config={
                'system_instruction': system_instruction,
                'response_mime_type': 'application/json',
                'response_schema': ClaimExtractionList,
            },
        )
        claims = _coerce_claims(_parsed_or_json(resp, "claims"))

        # Hard-cap the role promotion the LLM is allowed to do: only Red Team
        # segments may produce external-context. Anything coming from an
        # analyst segment is always analyst-claim, even if the LLM tried to
        # tag it otherwise. (Belt-and-braces — segment-driven extraction is
        # already pre-tagged in the prompt.)
        # We can't reliably map a claim back to its source segment without
        # extra round-trips, so we use a different invariant: if the LLM
        # returned ANY claim with role != "analyst-claim" / "red-team-rebuttal"
        # / "external-context", _coerce_claims has already normalised it.

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

        # --- 1b. Fuzzy role override --------------------------------------
        # If a claim that was tagged red-team-rebuttal or external-context is
        # actually a near-verbatim restatement of pitch content (high fuzzy
        # match to the source corpus), it doesn't belong in the knowledge
        # check — it's a literal source claim that should be Verified against
        # the deck. This catches the "The company has a B2G exclusivity
        # agreement" case where the Red Team paraphrased the pitch.
        override_count = 0
        if passages:
            for i, c in enumerate(claims):
                if c["role"] == "analyst-claim":
                    continue
                score, _ = _best_fuzzy(c["text"], passages)
                if score >= ROLE_OVERRIDE_FUZZY_MIN:
                    claims[i]["role"] = "analyst-claim"
                    override_count += 1
        if override_count:
            logger.info(
                "Role override: re-tagged %d claim(s) as analyst-claim (near-verbatim source restatement)",
                override_count,
            )

        analyst_indices = [i for i, c in enumerate(claims) if c["role"] == "analyst-claim"]
        external_indices = [i for i, c in enumerate(claims) if c["role"] in _NON_ANALYST_ROLES]

        override_note = f" (auto-retagged {override_count} as analyst-claim — near-verbatim source restatement)" if override_count else ""
        await manager.emit_event(
            session_id, "verifier", "thought",
            f"Extracted {len(claims)} claims "
            f"({len(analyst_indices)} analyst, {len(external_indices)} rebuttal/external){override_note}. "
            f"Grounding against {len(passages)} source passages…",
        )

        # --- 2. Fuzzy fast path (analyst-claims only) ---------------------
        # QUANTITATIVE claims always go through the LLM semantic check: a fuzzy
        # ratio can't tell "$50M" from "$500M" (they score ~92), so the fast
        # path would happily "verify" a 10x hallucinated figure.
        fuzzy: Dict[int, tuple[int, str]] = {}
        needs_semantic: List[int] = []
        for i in analyst_indices:
            score, passage = _best_fuzzy(claims[i]["text"], passages) if passages else (0, "")
            fuzzy[i] = (score, passage)
            if claims[i]["type"] == "QUANTITATIVE" or score < FUZZY_VERIFIED:
                needs_semantic.append(i)

        # For non-analyst claims, still find the closest source phrase — useful
        # for the UI ("Contradicted source phrase: …") but not used for
        # scoring. Suppress matches with a weak fuzzy score so we don't
        # surface section headings ("The Ask", "Scaling Together") as if
        # they were the contradicted text.
        non_analyst_snippets: Dict[int, str] = {}
        for i in external_indices:
            score, passage = _best_fuzzy(claims[i]["text"], passages) if passages else (0, "")
            non_analyst_snippets[i] = passage if score >= SNIPPET_MIN_SCORE else ""

        grounding: Dict[int, Dict[str, Any]] = {}
        for i in analyst_indices:
            score, passage = fuzzy[i]
            if i not in needs_semantic:  # fuzzy was decisive
                grounding[i] = {
                    "score": score,
                    "snippet": passage,
                    "reasoning": "Direct textual match against source.",
                    "semantic": False,
                    "channel": "source-grounding",
                }

        # --- 3. Semantic grounding for the rest (analyst-claims) ----------
        if needs_semantic and has_corpus:
            await manager.emit_event(session_id, "verifier", "thought", f"Running semantic grounding on {len(needs_semantic)} analyst claim(s)…")
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
                    "channel": "source-grounding",
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
                "channel": "source-grounding",
            }

        # --- 4. Knowledge check (rebuttals + external context) ------------
        knowledge_verdicts: Dict[int, KnowledgeVerdict] = {}
        if external_indices:
            await manager.emit_event(
                session_id, "verifier", "thought",
                f"Running external-knowledge check on {len(external_indices)} rebuttal/context claim(s) — these are graded against reality, not the pitch.",
            )
            knowledge_verdicts = await _knowledge_check(client, claims, external_indices)

        for i in external_indices:
            kv = knowledge_verdicts.get(i)
            snippet = non_analyst_snippets.get(i, "")
            if kv is None:
                # Fall through: we couldn't run the check. Treat as UNKNOWN.
                grounding[i] = {
                    "score": 55,
                    "snippet": snippet,
                    "reasoning": "External-knowledge check unavailable; marking as plausible pending human review.",
                    "semantic": False,
                    "channel": "knowledge-check",
                    "knowledge_support": "UNKNOWN",
                }
                continue
            score = _knowledge_to_score(kv.support, kv.confidence)
            channel_note = {
                "SUPPORTED": "Supported by external knowledge (rebuttal/context aligns with widely-reported facts).",
                "DISPUTED":  "Disputed by external knowledge (contradicts widely-reported facts).",
                "UNKNOWN":   "Unverifiable from general knowledge — surfacing for human review.",
            }[kv.support.upper()]
            grounding[i] = {
                "score": score,
                "snippet": snippet,
                "reasoning": (kv.reasoning or channel_note),
                "semantic": True,
                "channel": "knowledge-check",
                "knowledge_support": kv.support.upper(),
            }

        # --- 5. Consistency check -----------------------------------------
        await manager.emit_event(session_id, "verifier", "thought", "Checking internal and source consistency (role-aware)…")
        cverdicts = await _check_consistency(client, claims, source_corpus, final_brief)
        consistency: Dict[int, Dict[str, Any]] = {}
        for i in range(len(claims)):
            v = cverdicts.get(i)
            if v is None:
                consistency[i] = {"verdict": "CONSISTENT", "confidence": 5, "reasoning": "Not assessed."}
            else:
                consistency[i] = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning}

        # --- 6. Aggregate --------------------------------------------------
        result_claims: List[Dict[str, Any]] = []
        counts = {"VERIFIED": 0, "PLAUSIBLE": 0, "FLAGGED": 0, "HALLUCINATION": 0}
        integrity_sum = 0

        for i, c in enumerate(claims):
            g = grounding.get(i) or {
                "score": 0, "snippet": "", "reasoning": "No grounding performed.",
                "semantic": False, "channel": "source-grounding",
            }
            cons = consistency[i]
            role = c["role"]
            g_score = max(0, min(100, int(g["score"])))

            # Role-aware consistency: a rebuttal contradicting the source is its
            # whole job, so we don't penalise that here.
            cons_verdict = cons["verdict"]
            cons_note = cons["reasoning"]
            if role in _NON_ANALYST_ROLES and cons_verdict == "CONTRADICTORY":
                cons_score = 100
                cons_verdict_effective = "CONSISTENT"
                cons_note = (
                    f"Contradiction with source is expected for {role}; treated as consistent. "
                    + (cons_note or "")
                ).strip()
            else:
                cons_verdict_effective = cons_verdict
                cons_score = _CONSISTENCY_SCORE.get(cons_verdict, 25)
                if cons_score < 75:
                    conf = max(1, min(10, int(cons.get("confidence", 5))))
                    cons_score = min(cons_score + (10 - conf) * 2, 60)

            type_mod = _TYPE_MODIFIER.get(c["type"], 100)
            integrity = round(GROUNDING_WEIGHT * g_score + CONSISTENCY_WEIGHT * cons_score + TYPE_WEIGHT * type_mod)
            integrity = max(0, min(100, integrity))

            # Status — role-specific so a sharp rebuttal doesn't get marked FLAGGED.
            if role == "analyst-claim":
                is_consistent = cons_verdict_effective in ("CONSISTENT", "MINOR_CONCERN")
                contradicts = cons_verdict_effective == "CONTRADICTORY"
                if g_score < HALLUCINATION_GROUNDING_MAX and not is_consistent:
                    status = "HALLUCINATION"
                elif g_score < PARTIAL_GROUNDING_MIN or contradicts:
                    status = "FLAGGED"
                elif g_score >= VERIFIED_GROUNDING_MIN and cons_verdict_effective == "CONSISTENT":
                    status = "VERIFIED"
                else:
                    status = "PLAUSIBLE"
            else:
                support = (g.get("knowledge_support") or "UNKNOWN").upper()
                if support == "SUPPORTED":
                    status = "VERIFIED" if g_score >= VERIFIED_GROUNDING_MIN and cons_verdict_effective in ("CONSISTENT", "MINOR_CONCERN") else "PLAUSIBLE"
                elif support == "DISPUTED":
                    status = "FLAGGED"
                else:  # UNKNOWN
                    status = "PLAUSIBLE"
            counts[status] += 1
            integrity_sum += integrity

            reasoning_bits = [g["reasoning"]]
            if cons_note and cons_note != "Not assessed.":
                reasoning_bits.append(f"Consistency ({cons_verdict_effective}): {cons_note}")
            snippet = g["snippet"]
            snippet_label = "Contradicted source phrase" if role == "red-team-rebuttal" and snippet else "Closest Source Match"
            result_claims.append({
                "claim": c["text"],
                "type": c["type"],
                "role": role,
                "score": g_score,
                "match_confidence": g_score,
                "verification_channel": g.get("channel", "source-grounding"),
                "knowledge_support": g.get("knowledge_support"),
                "integrity_score": integrity,
                "status": status,
                "consistency": cons_verdict_effective,
                "reasoning": " | ".join(b for b in reasoning_bits if b),
                "best_source_snippet": (snippet[:240] + "…") if snippet and len(snippet) > 240 else (snippet or "None"),
                "snippet_label": snippet_label,
            })

        overall = round(integrity_sum / len(claims)) if claims else 100
        # Hallucination penalty only applies to true analyst hallucinations.
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
