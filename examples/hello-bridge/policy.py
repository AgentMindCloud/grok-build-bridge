"""Self-imposed policy layer for grok-build-bridge.
   Blocks any prompt that mentions .gov, .mil, or similar government domains.
   Pure Python, zero dependencies, your rules only.
"""

from __future__ import annotations
import re

# === EDIT THIS LIST TO MATCH YOUR POLICY ===
BLOCKED_PATTERNS = [
    r'\.gov(/|$|\?)',           # fda.gov, sec.gov, treasury.gov, etc.
    r'\.mil(/|$|\?)',
    r'federalreserve\.gov',
    r'irs\.gov',
    r'cdc\.gov',
    r'who\.int',                # optional: international orgs
    # add any others you want
]

BLOCKED_REGEX = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)


def is_government_domain(text: str | None) -> bool:
    """Return True if the text contains any blocked government domain."""
    if not text:
        return False
    return bool(BLOCKED_REGEX.search(text))


def blocked_error() -> dict:
    """Standard error response for blocked requests."""
    return {
        "error": "policy_violation",
        "message": (
            "This grok-build-bridge instance has a hard self-imposed policy: "
            "it will not process any request involving .gov, .mil, or similar government domains."
        ),
        "blocked_by": "bridge_operator_policy",
        "suggestion": "Remove all government domain references from your prompt."
    }
