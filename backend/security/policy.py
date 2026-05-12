"""Centralized policy engine (the "Lobster Trap" inspection layer).

It inspects the *body of every outbound LLM request* (the agents route their
Gemini calls through `/proxy`). Two tiers:

  * BLOCK   — obvious PII / secret leaks and clear prompt-injection patterns.
              These abort the request with HTTP 400.
  * WARN    — "investment guardrail" phrases (reckless-recommendation language).
              These are logged and surfaced via a response header but do NOT
              block the call — blocking on a single English word inside an
              uploaded deal document would break legitimate analyses.

The patterns are intentionally specific. Earlier versions flagged bare 9-digit
numbers (EINs are 9 digits and appear in every real M&A document) and the lone
word "bypass"/"all-in" (both common in finance), which made the proxy unusable.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    allowed: bool = True
    violation_type: Optional[str] = None
    detail: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # Back-compat: callers used to unpack a 3-tuple.
    def as_tuple(self) -> Tuple[bool, Optional[str], Optional[str]]:
        return self.allowed, self.violation_type, self.detail


class PolicyEngine:
    def __init__(self):
        # --- PII / secrets (BLOCK) -----------------------------------------
        # Require canonical separators so we don't trip on EINs, order IDs, etc.
        self.pii_patterns = {
            "ssn": re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
            "credit_card": re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"),
            "secret_assignment": re.compile(
                r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|password|passwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{8,}",
                re.IGNORECASE,
            ),
        }

        # --- Prompt injection / jailbreak (BLOCK) --------------------------
        _instr = r"(?:instructions?|prompts?|messages?|rules?|guidelines?|directions?|context|policy|policies|system prompt)"
        _prev = r"(?:all\s+|the\s+|your\s+|these\s+|any\s+|earlier\s+)*(?:previous|prior|preceding|above|earlier|original)"
        self.adversarial_patterns = [
            re.compile(rf"\b(?:ignore|disregard|forget)\s+{_prev}\s+{_instr}", re.IGNORECASE),
            re.compile(rf"\bdo not (?:follow|obey|adhere to)\s+(?:your|the|any|all)?\s*{_instr}", re.IGNORECASE),
            re.compile(rf"\bbypass\s+(?:your|the|all|any)?\s*(?:safety|guard\s?rails?|restrictions?|filters?|content polic\w*|{_instr})", re.IGNORECASE),
            re.compile(r"\bjailbreak(?:ing|en|ed)?\b", re.IGNORECASE),
            re.compile(r"\b(?:reveal|print|show|repeat|output|disclose)\s+(?:your|the)?\s*(?:full\s+|hidden\s+|secret\s+|exact\s+)?(?:system\s+)?(?:prompt|instructions)\b", re.IGNORECASE),
            re.compile(r"\byou are (?:now |actually )?(?:an? )?(?:unrestricted|unfiltered|uncensored|jailbroken|developer[- ]mode)\b", re.IGNORECASE),
            re.compile(r"\b(?:enable|activate)\s+(?:developer|dan|god)\s*mode\b", re.IGNORECASE),
        ]

        # --- Investment guardrails (WARN only) -----------------------------
        self.guardrails = [
            re.compile(r"\binfinite risk\b", re.IGNORECASE),
            re.compile(r"\bunlimited budget\b", re.IGNORECASE),
            re.compile(r"\bguaranteed returns?\b", re.IGNORECASE),
            re.compile(r"\brisk[-\s]?free (?:return|investment|profit)\b", re.IGNORECASE),
            re.compile(r"\b(?:can(?:no|')?t|cannot) lose\b", re.IGNORECASE),
            re.compile(r"\bliquidate everything\b", re.IGNORECASE),
            re.compile(r"\bbet the (?:company|farm|business)\b", re.IGNORECASE),
        ]

    def scan_request(self, body_text: str) -> ScanResult:
        body_text = body_text or ""

        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(body_text):
                logger.warning("Lobster Trap: blocked outbound request — possible %s leak.", pii_type)
                return ScanResult(False, "pii_leak", f"Lobster Trap: possible {pii_type.replace('_', ' ')} in request body")

        for pattern in self.adversarial_patterns:
            if pattern.search(body_text):
                logger.warning("Lobster Trap: blocked outbound request — adversarial / prompt-injection pattern.")
                return ScanResult(False, "adversarial", "Lobster Trap: adversarial / prompt-injection pattern detected")

        warnings: List[str] = []
        for pattern in self.guardrails:
            m = pattern.search(body_text)
            if m:
                phrase = m.group(0)
                logger.warning("Policy Engine: investment-guardrail phrase present (%r) — allowing but flagging.", phrase)
                warnings.append(f"guardrail:{phrase.strip().lower()}")

        return ScanResult(True, None, None, warnings)


policy_engine = PolicyEngine()
