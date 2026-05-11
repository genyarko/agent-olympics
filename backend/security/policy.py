import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class PolicyEngine:
    """
    Centralized Policy Engine for enforcing security, privacy, and investment guardrails.
    """
    
    def __init__(self):
        # 1. PII Regex Patterns
        self.pii_patterns = {
            "ssn": re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
            "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
            # Add more sophisticated patterns here as needed (e.g. Presidio integration)
        }
        
        # 2. Adversarial Prompt Patterns (Lobster Trap)
        # Using word boundaries to avoid catching partial matches
        self.adversarial_patterns = [
            re.compile(r"\bignore previous instructions\b", re.IGNORECASE),
            re.compile(r"\bbypass\b", re.IGNORECASE),
            re.compile(r"\bjailbreak\b", re.IGNORECASE),
            re.compile(r"\bdo not follow\b", re.IGNORECASE)
        ]
        
        # 3. Investment Guardrails
        self.guardrails = [
            re.compile(r"\binfinite risk\b", re.IGNORECASE),
            re.compile(r"\bunlimited budget\b", re.IGNORECASE),
            re.compile(r"\bguaranteed return\b", re.IGNORECASE),
            re.compile(r"\ball-in\b", re.IGNORECASE),
            re.compile(r"\bliquidate everything\b", re.IGNORECASE)
        ]

    def scan_request(self, body_text: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Scans a request body against all policies.
        Returns: (is_valid, violation_type, detail_message)
        """
        # 1. PII Check
        for pii_type, pattern in self.pii_patterns.items():
            if pattern.search(body_text):
                logger.warning(f"Lobster Trap: PII leak detected ({pii_type})!")
                return False, "pii_leak", f"Lobster Trap: PII leak detected ({pii_type})"

        # 2. Adversarial Check
        for pattern in self.adversarial_patterns:
            if pattern.search(body_text):
                logger.warning("Lobster Trap: Adversarial pattern detected!")
                return False, "adversarial", "Lobster Trap: Adversarial pattern detected"

        # 3. Guardrail Check
        for pattern in self.guardrails:
            if pattern.search(body_text):
                logger.warning("Policy Engine: Investment guardrail violation!")
                return False, "guardrail", "Policy Engine: Investment guardrail violation"

        return True, None, None

policy_engine = PolicyEngine()
