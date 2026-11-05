"""Phase 3 — DSA reasoning/consistency gate regression suite.

Pure-function tests (no network) for dsa_reasoning.check / stages_present /
stated_time_complexities, plus the wiring into dsa_critic.critique (the
contradiction path rejects deterministically, before any LLM call). Run:
    python -m pytest tests/test_dsa_reasoning.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import dsa_reasoning as dr


def _answer(complexity_block, code="def f(x):\n    return x", approach="One pass."):
    return (
        "### Problem Understanding\nRestate.\n\n"
        "### Optimal Algorithm\nHash map.\n\n"
        f"### Code\n```python\n{code}\n```\n\n"
        f"### Approach\n{approach}\n\n"
        f"### Complexity\n{complexity_block}\n"
    )


# ---------------------------------------------------------------------------
# stated_time_complexities
# ---------------------------------------------------------------------------
def test_single_time_complexity_one_value():
    text = _answer("- **Time Complexity:** O(n)\n- **Space Complexity:** O(n)\n")
    assert dr.stated_time_complexities(text) == ["o(n)"]


def test_two_distinct_time_complexities_detected():
    text = _answer("- **Time Complexity:** O(n)\n"
                   "- **Time Complexity:** O(n log n)\n"
                   "- **Space Complexity:** O(n)\n")
    vals = dr.stated_time_complexities(text)
    assert "o(n)" in vals and "o(nlogn)" in vals
    assert len(vals) == 2


def test_same_value_twice_is_one():
    text = _answer("- **Time Complexity:** O(1)\n- **Time Complexity:** O(1)\n")
    assert dr.stated_time_complexities(text) == ["o(1)"]


def test_complexity_in_code_comment_ignored():
    code = "def f(x):\n    # Time Complexity: O(n^2) naive\n    return x"
    text = _answer("- **Time Complexity:** O(n)\n- **Space Complexity:** O(1)\n", code=code)
    # The O(n^2) lives inside the code fence and must not count as a second claim.
    assert dr.stated_time_complexities(text) == ["o(n)"]


# ---------------------------------------------------------------------------
# check — reject contradictions, never reject good answers
# ---------------------------------------------------------------------------
def test_contradiction_rejected():
    text = _answer("- **Time Complexity:** O(n)\n"
                   "- **Time Complexity:** O(n log n)\n"
                   "- **Space Complexity:** O(n)\n")
    ok, reason = dr.check("solve two sum optimally", text)
    assert ok is False
    assert "time complexit" in reason.lower()


def test_consistent_answer_passes():
    text = _answer("- **Time Complexity:** O(n)\n- **Space Complexity:** O(n)\n")
    ok, _ = dr.check("solve two sum optimally", text)
    assert ok is True


def test_naive_comparison_in_prose_not_flagged():
    # A good answer may mention a naive alternative in prose without a SECOND
    # labelled time-complexity claim -> must not be rejected.
    text = (
        "### Problem Understanding\nRestate.\n\n"
        "### Optimal Algorithm\nHash map. A brute-force nested loop would be O(n^2), "
        "but we avoid it.\n\n"
        "### Code\n```python\ndef f(x):\n    return x\n```\n\n"
        "### Approach\nOne pass.\n\n"
        "### Complexity\n- **Time Complexity:** O(n)\n- **Space Complexity:** O(n)\n"
    )
    ok, _ = dr.check("solve two sum optimally", text)
    assert ok is True


def test_conceptual_question_not_gated():
    ok, _ = dr.check("what is the time complexity of mergesort? O(n log n) vs O(n)",
                     "Mergesort is O(n log n). A linear scan is O(n).")
    assert ok is True


# ---------------------------------------------------------------------------
# stages_present
# ---------------------------------------------------------------------------
def test_stages_present_core():
    text = _answer("- **Time Complexity:** O(n)\n- **Space Complexity:** O(n)\n")
    stages = dr.stages_present(text)
    assert {"problem_understanding", "optimal_algorithm", "complexity", "code"} <= stages


def test_stages_present_full_workflow():
    text = (
        "### Problem Understanding\nRestate.\n"
        "### Optimal Algorithm\nHeap.\n"
        "### Dry Run\nWalk through [1,2,3].\n"
        "### Edge Cases\nEmpty input, single element.\n"
        "### Code\n```python\ndef f():\n    return 1\n```\n"
        "### Sample Tests\nassert f() == 1\n"
        "### Complexity\n- Time Complexity: O(n)\n"
        "We re-derive and verify the complexity from the final code.\n"
    )
    stages = dr.stages_present(text)
    assert {"simulation", "edge_cases", "sample_tests", "verify_complexity"} <= stages


# ---------------------------------------------------------------------------
# Wiring into dsa_critic — contradiction rejected deterministically (no LLM)
# ---------------------------------------------------------------------------
def test_dsa_critic_rejects_contradiction_without_network():
    import dsa_critic
    text = _answer("- **Time Complexity:** O(n)\n"
                   "- **Time Complexity:** O(n log n)\n"
                   "- **Space Complexity:** O(n)\n",
                   code="def two_sum(nums, target):\n"
                        "    seen = {}\n"
                        "    for i, x in enumerate(nums):\n"
                        "        if target - x in seen:\n"
                        "            return [seen[target - x], i]\n"
                        "        seen[x] = i\n"
                        "    return []")
    res = dsa_critic.critique("solve two sum optimally", text)
    assert res["verified"] is False
    assert "time complexit" in res["feedback"].lower()
