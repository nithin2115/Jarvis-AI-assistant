"""Deterministic Code Review critic (Phase 7).

Enforces the review contract mechanically: a real critique must accompany the
refactor, the refactored code must actually be present, and it must not be truncated.

Conservative gating (never reject a correct answer):
  * Only runs once the response is actually a REVIEW (has review section headers, a
    refactor section, or code). A clarification that asks the user to paste their code
    is passed through to the LLM verifier.
"""
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.DOTALL)
_TRUNCATION = re.compile(
    r"(//\s*TODO|#\s*TODO|\bTODO:|omitted for brevity|"
    r"rest of (?:the |your )?(?:code|implementation|method|class)|"
    r"your code (?:goes )?here|\.\.\.\s*\(truncated\)|"
    r"(?:remains|stays|is)\s+unchanged|same as (?:before|above))",
    re.IGNORECASE,
)
_REFACTOR = re.compile(r"refactor", re.IGNORECASE)
# Substrings identifying a critique section header.
_CRITIQUE_TERMS = ("architecture", "structure", "performance", "security",
                   "readability", "maintainability", "design", "review", "issues",
                   "findings")

# A real review examines MULTIPLE facets, not one. We require coverage of at least
# MIN_DIMENSIONS distinct areas (matched anywhere in the prose, leniently) so a
# shallow "rename x for readability" note is rejected while a grouped multi-facet
# review (e.g. "Performance & Security") passes.
MIN_DIMENSIONS = 3
_DIMENSIONS = {
    "correctness": re.compile(
        r"correct(?:ness)?|logic\s+error|edge\s+case|off[-\s]by[-\s]one|"
        r"wrong\s+(?:result|output|behaviou?r)|behaviou?r", re.IGNORECASE),
    "bugs": re.compile(
        r"\bbug\b|\bnull\b|\bnpe\b|exception|race\s+condition|deadlock|leak|crash|"
        r"error\s+handling|boundary|unhandled", re.IGNORECASE),
    "security": re.compile(
        r"security|injection|\bxss\b|\bcsrf\b|\bssrf\b|sanitiz|escap|vulnerab|"
        r"\bauth\b|authoriz|authentic|secret|hard[-\s]?coded|encrypt", re.IGNORECASE),
    "performance": re.compile(
        r"performance|\bslow\b|n\+1|latency|optimiz|efficien|throughput|\bmemory\b|"
        r"allocation|\bcache", re.IGNORECASE),
    "complexity": re.compile(
        r"complexity|big[-\s]o|o\(n|time\s+complexity|space\s+complexity|\balgorithm",
        re.IGNORECASE),
    "maintainability": re.compile(
        r"readab|maintainab|naming|\brename\b|duplicat|\bdry\b|clean|modular|"
        r"cohesion|magic\s+number|nesting", re.IGNORECASE),
    "design": re.compile(
        r"architecture|\bdesign\b|separation\s+of\s+concerns|\blayer\b|\bpattern\b|"
        r"responsibilit|abstraction|\bsolid\b|coupling", re.IGNORECASE),
}


def _code_blocks(text: str):
    return [m.group(1) for m in _FENCE.finditer(text or "")]


def _headers(text: str):
    out = []
    for line in (text or "").splitlines():
        s = line.strip().lower()
        if not s:
            continue
        if s.startswith("#") or s.startswith("**") or (s.endswith(":") and len(s) < 48):
            out.append(re.sub(r"[#*`:_]", "", s).strip())
    return out


def _has_critique(text: str) -> bool:
    return any(any(term in h for term in _CRITIQUE_TERMS) for h in _headers(text))


def _dimension_coverage(text: str):
    """Distinct review dimensions addressed anywhere in the text."""
    return {area for area, rx in _DIMENSIONS.items() if rx.search(text or "")}


def _is_review(text: str) -> bool:
    return _has_critique(text) or bool(_REFACTOR.search(text)) or bool(_code_blocks(text))


def critique(user_query: str, response_text: str) -> dict:
    """Return {"verified": bool, "feedback": str}. Deterministic only."""
    text = response_text or ""

    # Not yet a review (e.g., asking the user to paste their code) -> defer.
    if not _is_review(text):
        return {"verified": True, "feedback": ""}

    m = _TRUNCATION.search(text)
    if m:
        logger.warning(f"[CODEREVIEW_CRITIC] Truncated refactor: {m.group(0)!r}")
        return {"verified": False, "feedback": (
            f"The Refactored Code is truncated/placeholder ('{m.group(0).strip()}'). "
            f"Provide the COMPLETE refactored code that preserves all original "
            f"functionality — no TODO, no 'omitted', no 'unchanged'."
        )}

    if not _code_blocks(text):
        logger.warning("[CODEREVIEW_CRITIC] Review without refactored code block")
        return {"verified": False, "feedback": (
            "Include the complete Refactored Code in a fenced code block — a review "
            "must end with the production-ready, refactored implementation."
        )}

    if not _has_critique(text):
        logger.warning("[CODEREVIEW_CRITIC] Code dumped without a critique")
        return {"verified": False, "feedback": (
            "Provide the critique BEFORE the code: Architecture & Structure, "
            "Performance & Security, and Readability & Maintainability — then the "
            "Refactored Code. Do not dump code without the analysis."
        )}

    covered = _dimension_coverage(text)
    if len(covered) < MIN_DIMENSIONS:
        logger.warning(f"[CODEREVIEW_CRITIC] Shallow review; dimensions covered: {covered}")
        return {"verified": False, "feedback": (
            "The review is too shallow. A thorough code review must examine MULTIPLE "
            "dimensions — correctness/bugs, security, performance, and maintainability "
            "(plus complexity and design where relevant) — before shipping the refactor. "
            f"Only addressed: {', '.join(sorted(covered)) or 'a single area'}."
        )}

    return {"verified": True, "feedback": ""}
