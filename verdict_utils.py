"""Shared, robust verdict parsing for the Critic and Verifier agents.

LLMs frequently ramble before emitting their final VERIFIED / REJECTED verdict,
and sometimes mention both words. Naive ``text.startswith("VERIFIED")`` therefore
misclassifies valid answers as rejected. ``parse_verdict`` honours the LAST verdict
token that appears, which matches how models conclude their reasoning.
"""
import re

_VERIFIED_RE = re.compile(r'\bVERIFIED\b')
_REJECTED_RE = re.compile(r'\bREJECTED?\b')  # REJECT or REJECTED


def parse_verdict(text: str, default_verified: bool = False):
    """Return ``(verified: bool, feedback: str)``.

    Rules:
    - Only VERIFIED present  -> verified.
    - Only REJECTED present  -> rejected.
    - Both present           -> whichever appears LAST wins (final verdict).
    - Neither present        -> ``default_verified`` (verifier defaults to reject
      so unchecked content never passes).
    """
    t = (text or "").strip()
    up = t.upper()

    v_matches = list(_VERIFIED_RE.finditer(up))
    r_matches = list(_REJECTED_RE.finditer(up))
    has_v = bool(v_matches)
    has_r = bool(r_matches)

    if has_v and not has_r:
        verified = True
    elif has_r and not has_v:
        verified = False
    elif has_v and has_r:
        verified = v_matches[-1].start() > r_matches[-1].start()
    else:
        verified = default_verified

    if verified:
        return True, ""

    feedback = _REJECTED_RE.sub("", t)
    feedback = _VERIFIED_RE.sub("", feedback)
    feedback = re.sub(r'^[\s:.\-]+', '', feedback).strip()
    return False, feedback
