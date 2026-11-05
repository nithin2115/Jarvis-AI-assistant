"""
Phase 7 — Code Review critic / knowledge-base regression suite.

Deterministic tests for critique-before-code, complete-refactor, and no-truncation
enforcement, plus verifier short-circuit behavior. Run:
    python -m pytest tests/test_codereview.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import codereview_critic as cr

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _block(code, lang="python"):
    return f"```{lang}\n{code}\n```"


REFACTOR = _block(
    "def login(conn, username, password):\n"
    "    row = conn.execute(\n"
    "        \"SELECT id, hash FROM users WHERE name = ?\", (username,)\n"
    "    ).fetchone()\n"
    "    if not row or not verify(password, row[1]):\n"
    "        raise AuthError()\n"
    "    return row[0]"
)

CRITIQUE = (
    "### Architecture & Structure\n"
    "The handler mixes DB access with HTTP logic; extract a service layer.\n\n"
    "### Performance & Security\n"
    "[Critical] SQL injection: the query concatenates user input — parameterize it.\n\n"
    "### Readability & Maintainability\n"
    "Rename `x` to `userId`; use guard clauses to reduce nesting.\n\n"
)

FULL_REVIEW = CRITIQUE + "### Refactored Code\n" + REFACTOR

TRUNCATED_REVIEW = CRITIQUE + "### Refactored Code\n" + _block(
    "def login(conn, username, password):\n"
    "    # ... rest of the code unchanged\n"
    "    return row[0]"
)

NO_CODE_REVIEW = CRITIQUE  # critique but never ships the refactor

CODE_ONLY = "Here is the improved version:\n" + REFACTOR

CLARIFICATION = "Please paste the code you'd like me to review and the language/framework."

# Critique + refactor, but only ONE dimension (readability) -> too shallow.
SHALLOW_REVIEW = (
    "### Readability\n"
    "Rename the variable `x` to `userId` for readability.\n\n"
    "### Refactored Code\n" + REFACTOR
)

# Exactly three distinct dimensions (security + performance + maintainability) -> passes.
THREE_DIM_REVIEW = (
    "### Findings\n"
    "[Critical] SQL injection in the query — parameterize it (security).\n"
    "The N+1 query pattern hurts performance under load.\n"
    "Rename `x` to `userId` to improve readability.\n\n"
    "### Refactored Code\n" + REFACTOR
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_is_review_detection():
    assert cr._is_review(FULL_REVIEW) is True
    assert cr._is_review(CODE_ONLY) is True
    assert cr._is_review(CLARIFICATION) is False


def test_has_critique_detection():
    assert cr._has_critique(CRITIQUE) is True
    assert cr._has_critique(CODE_ONLY) is False


# ---------------------------------------------------------------------------
# Critic behavior
# ---------------------------------------------------------------------------
def test_full_review_passes():
    assert cr.critique("Review this Python login", FULL_REVIEW)["verified"] is True


def test_truncated_refactor_rejected():
    r = cr.critique("Review this", TRUNCATED_REVIEW)
    assert r["verified"] is False
    assert "truncat" in r["feedback"].lower() or "unchanged" in r["feedback"].lower()


def test_review_without_code_rejected():
    r = cr.critique("Review this", NO_CODE_REVIEW)
    assert r["verified"] is False
    assert "refactored code" in r["feedback"].lower()


def test_code_without_critique_rejected():
    r = cr.critique("Review this", CODE_ONLY)
    assert r["verified"] is False
    assert "critique" in r["feedback"].lower()


def test_clarification_defers():
    assert cr.critique("Review my code", CLARIFICATION)["verified"] is True


def test_shallow_single_dimension_review_rejected():
    r = cr.critique("Review this", SHALLOW_REVIEW)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "shallow" in fb or "dimension" in fb


def test_three_dimension_review_passes():
    assert cr.critique("Review this", THREE_DIM_REVIEW)["verified"] is True


def test_full_review_covers_multiple_dimensions():
    covered = cr._dimension_coverage(FULL_REVIEW)
    assert len(covered) >= cr.MIN_DIMENSIONS, covered


# ---------------------------------------------------------------------------
# Verifier integration
# ---------------------------------------------------------------------------
def test_verifier_rejects_truncated_review_without_network():
    import verifier_agent
    r = verifier_agent.verify("CODE_REVIEW_AGENT", "Review this Python login", TRUNCATED_REVIEW)
    assert r["verified"] is False


def test_verifier_passes_full_review(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("CODE_REVIEW_AGENT", "Review this Python login", FULL_REVIEW)
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Knowledge base wiring
# ---------------------------------------------------------------------------
def test_codereview_knowledge_base_file_exists():
    assert os.path.exists(os.path.join(BASE, "CODE_REVIEW_KNOWLEDGE_BASE.md"))


def test_codereview_knowledge_base_injected_into_prompt():
    import router
    prompt = router.AGENT_PROMPTS[router.CODE_REVIEW_AGENT].lower()
    assert "severity tagging" in prompt
    assert "n+1 queries" in prompt


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
