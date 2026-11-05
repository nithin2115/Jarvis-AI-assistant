"""Deterministic Debug critic (Phase 7).

Enforces the debugger's cardinal rule that an LLM verifier is unreliable at policing:
**do not fabricate the user's code**. When the user supplied neither the failing code
nor a stack trace, the agent must ask for evidence and give a fix PATTERN — it must NOT
invent a complete "patched file" for code it has never seen.

Conservative by design (never reject a correct answer):
  * If the user DID provide code or a stack trace, any concrete fix is legitimate -> pass.
  * Otherwise, only a LARGE, definition-bearing code block (a fabricated full file) is
    rejected. Short illustrative snippets of a fix pattern are allowed.
"""
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.DOTALL)

# Signatures that mean the USER actually supplied error evidence in their query.
_TRACE = re.compile(
    r"(traceback \(most recent call last\)|exception in thread|caused by:|"
    r"\bat \w+(?:\.\w+)+\s*\(|\b\w*(?:error|exception)\s*:|segmentation fault|"
    r"panic:|file \".+\", line \d+|line \d+, in )",
    re.IGNORECASE,
)
# A real definition -> the block is source code, not config/log output.
_DEF = re.compile(
    r"(^|\n)\s*(def |class |function |func |fn |public |private |protected |"
    r"void |static |const \w+\s*=|let \w+\s*=|var \w+\s*=|@\w+)",
    re.IGNORECASE,
)
# A fabricated full file tends to be at least this many real code lines.
_PATCH_MIN_LINES = 12

# Evidence-first debugging: when the user gave NO trace/code, a substantive fix
# attempt must explicitly REQUEST the missing evidence rather than silently guess.
_EVIDENCE_ASK_RE = re.compile(
    r"evidence needed|stack\s*trace|full\s+trace|"
    r"share\s+[^.\n]*\b(code|trace|log|repo|snippet)\b|"
    r"provide\s+[^.\n]*\b(code|trace|stack|version|schema|log)\b|"
    r"paste\s+[^.\n]*\b(code|trace|error|log)\b|"
    r"need\s+(the|your|more)\s+[^.\n]*\b(code|trace|stack|details|version|info)\b|"
    r"which\s+(line|version|method)|what\s+[^.\n]*version|how\s+to\s+reproduce|"
    r"can\s+you\s+(share|send|provide|paste)",
    re.IGNORECASE,
)
# Signals the response is actually attempting a diagnosis/fix (not a one-liner).
_FIX_INTENT_RE = re.compile(
    r"\bfix\b|corrected|\bsolution\b|resolve|\bpatch\b|likely\s+cause|root\s+cause|"
    r"the\s+(?:problem|issue|error)\s+is",
    re.IGNORECASE,
)


def _code_blocks(text: str):
    return [m.group(1) for m in _FENCE.finditer(text or "")]


def _user_has_evidence(user_query: str) -> bool:
    q = user_query or ""
    return bool(_FENCE.search(q) or _TRACE.search(q))


def _looks_like_full_file(block: str) -> bool:
    lines = [ln for ln in block.splitlines()
             if ln.strip() and not ln.strip().startswith(("#", "//"))]
    return len(lines) >= _PATCH_MIN_LINES and bool(_DEF.search(block))


def critique(user_query: str, response_text: str) -> dict:
    """Return {"verified": bool, "feedback": str}. Deterministic only."""
    # If the user gave real evidence, a concrete corrected file is appropriate.
    if _user_has_evidence(user_query):
        return {"verified": True, "feedback": ""}

    # No evidence supplied: a large invented "patched file" is fabrication.
    for block in _code_blocks(response_text):
        if _looks_like_full_file(block):
            logger.warning("[DEBUG_CRITIC] Fabricated full patched file without user evidence")
            return {"verified": False, "feedback": (
                "You do not have the user's actual code or full stack trace, so do not "
                "fabricate a complete patched file. In 'Evidence Needed' request the "
                "failing code + the FULL stack trace + language/runtime version; list "
                "specific likely causes for this error type; and give the FIX PATTERN "
                "(e.g., null check / Optional / defensive init) rather than inventing "
                "their code."
            )}

    # No evidence supplied: a substantive diagnosis/fix must REQUEST the evidence
    # (evidence-first debugging) instead of silently guessing. A one-line response or
    # a pure clarification is exempt.
    text = response_text or ""
    substantive = bool(_code_blocks(text)) or bool(_FIX_INTENT_RE.search(text))
    if substantive and not _EVIDENCE_ASK_RE.search(text):
        logger.warning("[DEBUG_CRITIC] Fix attempt without requesting evidence")
        return {"verified": False, "feedback": (
            "Debug evidence-first: you have no stack trace or failing code, so add an "
            "'Evidence Needed' step requesting the FULL stack trace, the failing code, and "
            "the language/runtime version before (or alongside) proposing fixes — do not "
            "guess at a fix without asking for the evidence."
        )}

    return {"verified": True, "feedback": ""}
