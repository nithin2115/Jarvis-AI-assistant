"""
Phase 12 — FINAL_RESPONSE_SANITIZER regression suite.

Pure-function tests (no network) for final_response_sanitizer.sanitize and
its individual detectors. Run:
    python -m pytest tests/test_final_response_sanitizer.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import final_response_sanitizer as san
import test_dsa as t  # reuse FULL_SOLUTION + _fence


def _f(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Clean responses must PASS (no false positives)
# ---------------------------------------------------------------------------
def test_clean_dsa_solution_passes():
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", t.FULL_SOLUTION)
    assert ok is True
    assert reason == ""
    assert cleaned == t.FULL_SOLUTION  # no-op


def test_empty_response_passes():
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve something", "")
    assert ok is True
    assert reason == ""


def test_non_dsa_clean_passes():
    text = "# Answer\n\nHere is the solution.\n\n```python\nprint('hello')\n```\n"
    ok, reason, cleaned = san.sanitize("GENERAL_ASSISTANT_AGENT", "hello", text)
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# 1. Duplicate major sections
# ---------------------------------------------------------------------------
def test_duplicate_complexity_section():
    text = (
        "# Problem Understanding\nFind two indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nTime: O(n)\n\n"
        "# Complexity\nSpace: O(n)\n"
    )
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "Complexity" in reason


def test_duplicate_code_section():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Code\n" + _f("def g(): pass") + "\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "Code" in reason


def test_duplicate_approach_section():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Approach\nAnother approach.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "Approach" in reason


def test_duplicate_edge_cases_section():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Edge Cases\nEmpty input.\n\n"
        "# Edge Cases\nLarge input.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "Edge Cases" in reason


# ---------------------------------------------------------------------------
# 2. Repeated headers (any ATX header, not just canonical)
# ---------------------------------------------------------------------------
def test_repeated_non_canonical_header():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Notes\nFirst note.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Notes\nSecond note.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "notes" in reason.lower()


# ---------------------------------------------------------------------------
# 3. Template fragments: orphan markdown, unfinished bullets, partial sections
# ---------------------------------------------------------------------------
def test_orphan_bold_label():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\n**Time Complexity\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "orphan" in reason.lower() or "template" in reason.lower()


def test_unfinished_bullet():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map approach.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\n"
        "- Use a hash map for O(1) lookups\n"
        "- Iterate through the array and\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "bullet" in reason.lower() or "template" in reason.lower()


def test_partial_section_no_body():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Notes\n\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "partial" in reason.lower() or "template" in reason.lower()


def test_template_placeholder_fragment():
    text = t.FULL_SOLUTION + "\n\n# Notes\n<explanation>\n"
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "template" in reason.lower()


# ---------------------------------------------------------------------------
# 4. Repeated paragraphs (similarity matching)
# ---------------------------------------------------------------------------
def test_verbatim_repeated_paragraph():
    text = (
        "# Problem Understanding\n"
        "We use a hash map to store each value and its index. "
        "This allows O(1) complement lookups.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\n"
        "We use a hash map to store each value and its index. "
        "This allows O(1) complement lookups.\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "paragraph" in reason.lower()


def test_similar_repeated_paragraph():
    text = (
        "# Problem Understanding\n"
        "We use a hash map to store each value and its index for fast lookups.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\n"
        "We use a hash map to store each value and its index for quick lookups.\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "paragraph" in reason.lower()


def test_distinct_paragraphs_not_flagged():
    text = (
        "# Problem Understanding\n"
        "We need to find two indices whose values sum to the target.\n\n"
        "# Optimal Algorithm\n"
        "A hash map gives O(1) complement lookups in a single pass.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\n"
        "Store each value's index as we iterate, checking the complement.\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True


# ---------------------------------------------------------------------------
# 5. Repeated code blocks
# ---------------------------------------------------------------------------
def test_repeated_code_block():
    code = "def two_sum(nums, target):\n    return [0, 1]\n"
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f(code) + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Test\n" + _f(code) + "\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "code block" in reason.lower()


def test_distinct_code_blocks_not_flagged():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Test\n" + _f("assert f() is None") + "\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True


# ---------------------------------------------------------------------------
# 6. Generator merge artifacts (repeated section sequences)
# ---------------------------------------------------------------------------
def test_merge_artifact_repeated_sequence():
    # Use non-canonical headers so duplicate_major_section doesn't fire first.
    # The sequence "# Notes -> # Details" appearing twice is a merge artifact.
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Notes\nFirst note.\n\n"
        "# Details\nFirst detail.\n\n"
        "# Notes\nSecond note.\n\n"
        "# Details\nSecond detail.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "merge" in reason.lower() or "sequence" in reason.lower()


def test_no_merge_artifact_in_normal_response():
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", t.FULL_SOLUTION)
    assert ok is True


# ---------------------------------------------------------------------------
# 7. DSA section order enforcement
# ---------------------------------------------------------------------------
def test_dsa_wrong_order_complexity_before_approach():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Complexity\nO(n)\n\n"
        "# Approach\nSingle pass.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "order" in reason.lower()


def test_dsa_correct_order_passes():
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True


def test_dsa_order_not_enforced_for_non_dsa():
    text = (
        "# Approach\nDo this first.\n\n"
        "# Problem Understanding\nWhat is this.\n\n"
        "Some answer.\n"
    )
    ok, reason, _ = san.sanitize("GENERAL_ASSISTANT_AGENT", "explain", text)
    assert ok is True


# ---------------------------------------------------------------------------
# 8. Auto-remove duplicated trailing sections
# ---------------------------------------------------------------------------
def test_auto_remove_duplicate_trailing_complexity():
    complexity_section = "# Complexity\n- Time: O(n)\n- Space: O(n)\n"
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        + complexity_section + "\n\n"
        + complexity_section
    )
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    # The trailing duplicate is removed, so it should pass
    assert ok is True
    assert cleaned.count("Complexity") == 1


def test_auto_remove_duplicate_trailing_code():
    code_section = "# Code\n" + _f("def f(): pass") + "\n"
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        + code_section + "\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        + code_section
    )
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True
    assert cleaned.count("# Code") == 1


def test_auto_remove_no_duplicate_trailing():
    text = t.FULL_SOLUTION
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True
    assert cleaned == text  # no-op


def test_auto_remove_multiple_trailing_duplicates():
    section = "# Complexity\nO(n)\n"
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        + section + "\n\n"
        + section + "\n\n"
        + section
    )
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is True
    assert cleaned.count("# Complexity") == 1


# ---------------------------------------------------------------------------
# Merged response / partial regeneration artifacts
# ---------------------------------------------------------------------------
def test_merged_response_two_full_solutions():
    text = t.FULL_SOLUTION + "\n\n" + t.FULL_SOLUTION
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "solve two sum", text)
    # Auto-cleanup should remove the trailing duplicate sections
    assert ok is True
    # The cleaned text should have each section header only once
    assert cleaned.count("### Problem Understanding") == 1
    assert cleaned.count("### Complexity") == 1


def test_partial_regeneration_artifact():
    """A response where regeneration appended a partial second copy."""
    text = (
        "# Problem Understanding\nFind indices.\n\n"
        "# Optimal Algorithm\nHash map.\n\n"
        "# Code\n" + _f("def f(): pass") + "\n\n"
        "# Approach\nSingle pass.\n\n"
        "# Complexity\nO(n)\n\n"
        "# Problem Understanding\nFind indices again.\n"
    )
    ok, reason, _ = san.sanitize("DSA_AGENT", "solve two sum", text)
    assert ok is False
    assert "Problem Understanding" in reason


# ---------------------------------------------------------------------------
# Fail-safe: exception never blocks a response
# ---------------------------------------------------------------------------
def test_fail_safe_on_exception():
    # Pass something that could cause issues — None
    ok, reason, cleaned = san.sanitize("DSA_AGENT", "query", None)
    assert ok is True
    assert cleaned is None or cleaned == ""


# ---------------------------------------------------------------------------
# Individual detector unit tests
# ---------------------------------------------------------------------------
def test_duplicate_major_section_detector():
    text = "# Complexity\nO(n)\n\n# Complexity\nO(n)\n"
    assert san.duplicate_major_section(text) == "Complexity"


def test_repeated_header_detector():
    text = "# Notes\nA\n\n# Notes\nB\n"
    assert san.repeated_header(text) == "notes"


def test_template_fragment_detector():
    text = "# Section\n<explanation>\n"
    assert san.template_fragment(text) is not None


def test_repeated_paragraph_detector():
    para = "This is a long enough paragraph with more than eight words in it."
    text = para + "\n\n" + para
    assert san.repeated_paragraph(text) is True


def test_repeated_code_block_detector():
    code = "def f():\n    return 1\n"
    text = _f(code) + "\n\n" + _f(code)
    assert san.repeated_code_block(text) is True


def test_merge_artifact_detector():
    text = (
        "# Complexity\nA\n\n# Code\nB\n\n"
        "# Complexity\nC\n\n# Code\nD\n"
    )
    assert san.merge_artifact(text) is not None


def test_dsa_section_order_ok():
    text = (
        "# Problem Understanding\nA\n\n"
        "# Optimal Algorithm\nB\n\n"
        "# Code\nC\n\n"
        "# Approach\nD\n\n"
        "# Complexity\nE\n"
    )
    ok, _ = san.dsa_section_order(text)
    assert ok is True


def test_dsa_section_order_violation():
    text = (
        "# Problem Understanding\nA\n\n"
        "# Code\nC\n\n"
        "# Optimal Algorithm\nB\n\n"
        "# Approach\nD\n\n"
        "# Complexity\nE\n"
    )
    ok, reason = san.dsa_section_order(text)
    assert ok is False
    assert "order" in reason.lower()


def test_remove_duplicate_trailing_sections_function():
    section = "# Complexity\nO(n)\n"
    text = section + "\n\n" + section
    result = san.remove_duplicate_trailing_sections(text)
    assert result.count("# Complexity") == 1
