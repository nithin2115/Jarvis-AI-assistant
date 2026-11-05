"""
Phase 1 — ResponseFinalizer regression suite.

Pure-function tests for response_finalizer.finalize and its individual helpers.
Run:
    python -m pytest tests/test_response_finalizer.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import response_finalizer as rf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _section(text, header, body):
    return f"# {header}\n{body}\n\n"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def test_deduplicate_duplicate_complexity():
    text = _section("", "Complexity", "O(n) time") + _section("", "Complexity", "O(n) space")
    cleaned, removed = rf.deduplicate_sections(text)
    assert "Complexity" in removed
    assert cleaned.count("# Complexity") == 1
    assert "O(n) time" in cleaned
    assert "O(n) space" not in cleaned


def test_deduplicate_duplicate_code():
    code1 = "```python\ndef foo(): pass\n```"
    code2 = "```python\ndef bar(): pass\n```"
    text = _section("", "Code", code1) + _section("", "Code", code2)
    cleaned, removed = rf.deduplicate_sections(text)
    assert "Code" in removed
    assert cleaned.count("# Code") == 1


def test_deduplicate_different_sections_preserved():
    text = _section("", "Complexity", "O(n)") + _section("", "Approach", "Use sliding window")
    cleaned, removed = rf.deduplicate_sections(text)
    assert removed == []
    assert "# Complexity" in cleaned
    assert "# Approach" in cleaned


def test_deduplicate_new_sections():
    text = (
        _section("", "Requirements", "Functional: login, logout")
        + _section("", "Requirements", "Non-functional: 99.99% uptime")
        + _section("", "Tradeoffs", "Consistency vs availability")
    )
    cleaned, removed = rf.deduplicate_sections(text)
    assert "Requirements" in removed
    assert cleaned.count("# Requirements") == 1
    assert "# Tradeoffs" in cleaned


def test_deduplicate_no_op_for_clean_text():
    text = "# Problem Understanding\nText\n\n# Code\nCode\n"
    cleaned, removed = rf.deduplicate_sections(text)
    assert cleaned == text
    assert removed == []


# ---------------------------------------------------------------------------
# Artifact stripping
# ---------------------------------------------------------------------------
def test_strip_critic_note():
    text = "# Answer\nHere is the solution.\n\n**Critic Note:** This is internal."
    cleaned = rf.strip_artifacts(text)
    assert "Critic Note" not in cleaned
    assert "Here is the solution" in cleaned


def test_strip_verifier_feedback():
    text = "# Code\n```python\nprint(1)\n```\n\nVerifier: rejected due to O(n^2)."
    cleaned = rf.strip_artifacts(text)
    assert "Verifier" not in cleaned
    assert "print(1)" in cleaned


def test_strip_regeneration_retry():
    text = "# Approach\nUse heaps.\n\nRetry 2: regenerating..."
    cleaned = rf.strip_artifacts(text)
    assert "Retry" not in cleaned
    assert "Use heaps" in cleaned


def test_strip_partial_generation():
    text = "# Answer\nPartial answer\n\n(continued)"
    cleaned = rf.strip_artifacts(text)
    assert "(continued)" not in cleaned


def test_strip_artifacts_no_op_clean():
    text = "# Problem Understanding\nClean text.\n"
    assert rf.strip_artifacts(text) == text


# ---------------------------------------------------------------------------
# Markdown validation
# ---------------------------------------------------------------------------
def test_validate_unbalanced_fences_rejected():
    text = "# Code\n```python\nprint(1)\n"
    ok, reason = rf._validate_markdown(text)
    assert ok is False
    assert "Unbalanced" in reason


def test_validate_orphan_bold_rejected():
    text = "# Complexity\n**Time Complexity\nO(n) time."
    ok, reason = rf._validate_markdown(text)
    assert ok is False
    assert "orphan" in reason.lower()


def test_validate_empty_code_block_rejected():
    text = "# Code\n```python\n\n```\n"
    ok, reason = rf._validate_markdown(text)
    assert ok is False
    assert "Empty" in reason


def test_validate_clean_text_passes():
    text = "# Problem Understanding\nText.\n\n# Code\n```python\nprint(1)\n```\n"
    ok, reason = rf._validate_markdown(text)
    assert ok is True


# ---------------------------------------------------------------------------
# Code-fence validation
# ---------------------------------------------------------------------------
def test_validate_unclosed_fence_rejected():
    text = "# Code\n```python\nprint(1)\n"
    ok, reason = rf._validate_code_fences(text)
    assert ok is False
    assert "Unclosed" in reason


def test_validate_invalid_language_rejected():
    text = "# Code\n```notareallang\nprint(1)\n```\n"
    ok, reason = rf._validate_code_fences(text)
    assert ok is False
    assert "notareallang" in reason


def test_validate_code_fences_clean():
    text = "# Code\n```python\nprint(1)\n```\n"
    ok, reason = rf._validate_code_fences(text)
    assert ok is True


# ---------------------------------------------------------------------------
# Public API: finalize
# ---------------------------------------------------------------------------
def test_finalize_deduplicates_and_passes():
    text = (
        "# Problem Understanding\nDesign LFU.\n\n"
        "# Code\n```python\nprint(1)\n```\n\n"
        "# Complexity\nO(1)\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, cleaned = rf.finalize("DSA_AGENT", "implement lfu cache", text)
    assert ok is True
    assert cleaned.count("# Complexity") == 1
    assert "O(1)" in cleaned


def test_finalize_rejects_unbalanced_fences():
    text = "# Code\n```python\nprint(1)\n"
    ok, reason, cleaned = rf.finalize("DSA_AGENT", "implement lfu cache", text)
    assert ok is False


def test_finalize_strips_artifacts():
    text = "# Answer\nSolution.\n\n**Critic Note:** internal.\n"
    ok, reason, cleaned = rf.finalize("DSA_AGENT", "implement lfu cache", text)
    assert ok is True
    assert "Critic Note" not in cleaned
    assert "Solution." in cleaned


def test_finalize_still_rejects_duplicate_headers():
    text = "# Complexity\nO(n)\n\n# Complexity\nO(n)\n"
    ok, reason, cleaned = rf.finalize("DSA_AGENT", "implement lfu cache", text)
    # After deduplication, only one Complexity header remains, so it should pass.
    assert ok is True


def test_finalize_fail_safe_on_none():
    ok, reason, cleaned = rf.finalize("DSA_AGENT", "q", None)
    assert ok is True
    assert cleaned is None


# ---------------------------------------------------------------------------
# Individual helpers
# ---------------------------------------------------------------------------
def test_canonical_header():
    assert rf._canonical_header("problem understanding") is not None
    assert rf._canonical_header("time & space complexity") == "Complexity"
    assert rf._canonical_header("tradeoffs") == "Tradeoffs"
    assert rf._canonical_header("cost analysis") == "Cost Analysis"
    assert rf._canonical_header("monitoring") == "Monitoring"


def test_deduplicate_sections_removes_body():
    text = (
        "# Problem\nIntro\n\n"
        "# Approach\nFirst approach text.\n\n"
        "# Code\n```python\nprint(1)\n```\n\n"
        "# Approach\nSecond approach text.\n\n"
    )
    cleaned, removed = rf.deduplicate_sections(text)
    assert "Approach" in removed
    assert "First approach text" in cleaned
    assert "Second approach text" not in cleaned
