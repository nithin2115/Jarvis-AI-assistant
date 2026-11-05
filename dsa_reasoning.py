"""Deterministic DSA reasoning gate (Phase 3).

Runs AFTER the existing DSA critics (complexity, structure, compile, output-quality,
LFU, algorithm) inside ``dsa_critic.critique``. Its job is the one failure class the
other gates miss: **self-contradiction in the stated reasoning**. The AST complexity
validator compares the *claim* to the *code*; it cannot catch an answer that states
two different time complexities for itself, which is a tell-tale sign of confused /
stitched-together reasoning.

It also exposes ``stages_present`` — a read-only inventory of which of the forced
10-step reasoning stages are detectable in an answer — used by the benchmark to
measure reasoning completeness and by callers that want a soft signal.

Design rule (same as the other critics): NEVER reject a correct answer. The
contradiction check fires only on HIGH-CONFIDENCE evidence — two *labelled* and
*distinct* time-complexity claims for the solution — so a legitimate "naive is
O(n^2), optimal is O(n)" comparison in prose is not affected.
"""
import re

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n.*?```", re.DOTALL)

# A labelled time-complexity claim: the phrase "time complexity" followed (closely)
# by the first Big-O / Theta / Omega expression. Matches "Time Complexity: O(n)",
# "**Time Complexity:** O(n log n)", "- Time complexity is O(1)".
_TIME_CLAIM = re.compile(
    r"time\s*complexity[^\n]{0,40}?"
    r"([O\u0398\u03A9]\s*\(\s*[^)\n]{0,40}?\))",
    re.IGNORECASE,
)

# Reasoning-stage detectors (header- or keyword-based, leniently matched).
_STAGE_PATTERNS = {
    "problem_understanding": re.compile(
        r"problem\s+understanding|understand(?:ing)?\s+the\s+problem|restate", re.IGNORECASE),
    "optimal_algorithm": re.compile(
        r"optimal\s+algorithm|\balgorithm\b|technique|\bpattern\b|data\s+structure", re.IGNORECASE),
    "simulation": re.compile(
        r"dry[\s-]?run|walk\s*through|walkthrough|\btrace\b|simulat|step[\s-]by[\s-]step|"
        r"work(?:ed|ing)?\s+example", re.IGNORECASE),
    "edge_cases": re.compile(r"edge\s+cases?|corner\s+cases?|boundary", re.IGNORECASE),
    "complexity": re.compile(r"complexity|big[\s-]?o", re.IGNORECASE),
    "code": re.compile(r"```|###\s*code|class\s+\w+|def\s+\w+", re.IGNORECASE),
    "mental_compile": re.compile(
        r"compile[s]?\s+(?:logically|cleanly|mentally)|mental(?:ly)?\s+compile|"
        r"syntax\s+check|does\s+it\s+compile", re.IGNORECASE),
    "sample_tests": re.compile(
        r"sample\s+(?:test|input|output|case)|test\s+cases?|example\s+input|expected\s+output|"
        r">>>\s|assert\s", re.IGNORECASE),
    "verify_complexity": re.compile(
        r"verify\s+(?:the\s+)?complexity|re[\s-]?derive|confirm\s+(?:the\s+)?complexity|"
        r"double[\s-]?check\s+(?:the\s+)?complexity", re.IGNORECASE),
}


def _strip_code(text: str) -> str:
    return _FENCE.sub("\n", text or "")


def _normalize_bigo(expr: str) -> str:
    """Canonicalize a Big-O expression for equality: strip spaces, lowercase, and
    drop a leading currency artifact if the regex matched one."""
    s = re.sub(r"\s+", "", expr or "").lower()
    s = s.lstrip("$")
    return s


def stated_time_complexities(text: str) -> list:
    """Distinct, normalized time-complexity values explicitly claimed for the
    solution (code blocks stripped so code comments do not count)."""
    prose = _strip_code(text)
    seen = []
    for m in _TIME_CLAIM.finditer(prose):
        norm = _normalize_bigo(m.group(1))
        if norm and norm not in seen:
            seen.append(norm)
    return seen


def stages_present(text: str) -> set:
    """Which forced reasoning stages are detectable in the answer."""
    t = text or ""
    return {name for name, rx in _STAGE_PATTERNS.items() if rx.search(t)}


def check(user_query: str, response_text: str):
    """Deterministic reasoning/consistency gate. Return (ok: bool, reason: str)."""
    text = response_text or ""

    # Only applies to genuine solve attempts that ship code.
    try:
        import dsa_structure
        if not dsa_structure.is_solution_attempt(user_query, text):
            return True, ""
    except ImportError:
        pass

    claims = stated_time_complexities(text)
    if len(claims) >= 2:
        return False, (
            "The solution states two different time complexities for itself "
            f"({', '.join(claims)}). A correct answer has ONE consistent time "
            "complexity that matches the code. Resolve the contradiction: state the "
            "actual asymptotic cost of the implementation, and if you are comparing a "
            "naive approach, label it explicitly as the rejected alternative."
        )

    return True, ""
