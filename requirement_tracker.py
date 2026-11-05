import logging
import re

logger = logging.getLogger(__name__)


def _collapse(s: str) -> str:
    """Lowercase and strip all non-alphanumerics so separator variants match
    (e.g. 'real-time' / 'real time' / 'realtime' all collapse to 'realtime')."""
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


# ── Requirement levels (Phase 2) ────────────────────────────────────────────
# MANDATORY  -> missing => FAIL (regenerate / never ship without it)
# RECOMMENDED-> missing => warning only (does NOT block shipping)
# OPTIONAL   -> missing => ignored (never fails, never warns)
LEVEL_MANDATORY = "MANDATORY"
LEVEL_RECOMMENDED = "RECOMMENDED"
LEVEL_OPTIONAL = "OPTIONAL"

# "Nice-to-have" deep-dives. Matched as substrings of the requirement text.
_OPTIONAL_KEYWORDS = (
    "cost analysis", "cost estimation", "detailed cost", "cost breakdown",
    "sizing", "capacity planning", "capacity estimation", "back of the envelope",
)
# Quality enhancers that should not block a solid answer.
_RECOMMENDED_KEYWORDS = (
    "monitoring", "observability", "tradeoff", "trade-off", "trade off",
    "security", "logging", "alerting", "documentation",
)


def classify_requirement(req: str) -> str:
    """Classify a single requirement string into a level. Explicit user
    requirements default to MANDATORY unless they are recognized as a
    recommended quality-enhancer or an optional deep-dive."""
    r = (req or "").lower().strip()
    rc = _collapse(req)
    # "Detailed X" deep-dives are always optional (e.g. 'Detailed Redis Sizing').
    if r.startswith("detailed"):
        return LEVEL_OPTIONAL
    for kw in _OPTIONAL_KEYWORDS:
        if kw in r or _collapse(kw) in rc:
            return LEVEL_OPTIONAL
    for kw in _RECOMMENDED_KEYWORDS:
        if kw in r or _collapse(kw) in rc:
            return LEVEL_RECOMMENDED
    return LEVEL_MANDATORY


def extract_requirements(user_query: str) -> dict:
    """
    Extracts requirements from the user query.
    First tries regex for explicit "Requirements:" block.
    If not found, uses brain_manager to extract implicitly.
    """
    requirements = {}
    
    # 1. Explicit "Requirements:" block. Supports bulleted, numbered, AND plain
    #    newline-separated items (e.g. "Requirements:\nRedis\nKafka\nMonitoring").
    match = re.search(r'requirements?\s*:\s*(.*)', user_query, re.IGNORECASE | re.DOTALL)
    if match:
        req_section = match.group(1)
        for raw in req_section.splitlines():
            line = raw.strip()
            if not line:
                # Blank line terminates the list once we've started collecting.
                if requirements:
                    break
                continue
            # Strip leading bullet / number markers.
            line = re.sub(r'^(?:[\*\-\+\u2022\u2023\u25E6]|\d+[\.\)])\s*', '', line).strip()
            line = line.strip('.,;:').strip()
            if not line:
                continue
            # Lines with many words are prose, not requirement keywords -> stop.
            if len(line.split()) > 5:
                break
            requirements[line.lower()] = False
                
    if requirements:
        logger.info(f"[REQUIREMENTS] Extracted explicitly: {list(requirements.keys())}")
        return requirements

    # No explicit "Requirements:" block -> no hard requirements to enforce.
    #
    # We deliberately do NOT ask an LLM to "guess" implicit requirements. That
    # approach hallucinated generic meta-categories (e.g. "data structures",
    # "algorithms", "http") which then failed naive substring matching and caused
    # spurious draft rejections. Quality/completeness of un-listed requirements is
    # instead enforced by the Verifier agent against each agent's section spec.
    logger.info("[REQUIREMENTS] No explicit requirements block found")
    return {}

def check_requirements_satisfied(text: str, requirements: dict) -> dict:
    """
    Checks which requirements are satisfied in the text.
    Updates the dictionary in-place.
    """
    text_lower = text.lower()
    text_collapsed = _collapse(text)
    for req in requirements:
        if requirements[req]:
            continue
        req_lower = req.lower()
        req_collapsed = _collapse(req)
        if not req_collapsed:
            requirements[req] = True
            continue
        # Match either as a plain substring OR with all separators removed, so
        # "real-time"/"real time" satisfy the requirement "realtime" and vice versa.
        if req_lower in text_lower or req_collapsed in text_collapsed:
            requirements[req] = True
            logger.info(f"[REQUIREMENTS] Satisfied: {req}")
    return requirements

def get_missing_requirements(requirements: dict, level: str = None) -> list:
    """Return the list of unsatisfied requirements.

    If ``level`` is given (MANDATORY / RECOMMENDED / OPTIONAL), only requirements
    of that level are returned. With no level, ALL missing requirements are
    returned (backwards-compatible)."""
    out = []
    for req, satisfied in requirements.items():
        if satisfied:
            continue
        if level is None or classify_requirement(req) == level:
            out.append(req)
    return out
