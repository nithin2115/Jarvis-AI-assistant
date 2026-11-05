"""
Phase 6 — Self-consistency Draft A/B comparison tests.

Unit tests for self_consistency.py; no network calls. Run:
    python -m pytest tests/test_self_consistency.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import self_consistency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_ask_sequence(answers):
    """Factory returning a fake ask_fn that yields answers in order."""
    calls = {"idx": 0}
    def ask_fn(prompt, context, sys_prompt, **kwargs):
        i = calls["idx"]
        calls["idx"] += 1
        return answers[i % len(answers)], "fake"
    return ask_fn, calls


# ---------------------------------------------------------------------------
# compare_drafts
# ---------------------------------------------------------------------------
def test_compare_drafts_prefers_verified():
    # A is an incomplete solution attempt (missing required sections), B is complete.
    a = (
        "### Code\n"
        "```python\n"
        "def two_sum(nums, target):\n"
        "    return []\n"
        "```\n\n"
        "### Complexity\n"
        "Time: O(n)\n"
    )
    b = (
        "### Problem Understanding\n"
        "Find two indices whose values sum to target.\n\n"
        "### Optimal Algorithm\n"
        "Hash map of value -> index, single pass.\n\n"
        "### Code\n"
        "```python\n"
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return []\n"
        "```\n\n"
        "### Approach\n"
        "Store each value's index; check the complement on the fly.\n\n"
        "### Complexity\n"
        "- Time Complexity: O(n)\n"
        "- Space Complexity: O(n)\n"
    )
    best, score_a, score_b, tie = self_consistency.compare_drafts(
        "DSA_AGENT", "Solve two sum optimally", a, b)
    assert best is b
    assert not tie
    # score[0] == not verified; A fails -> True, B passes -> False.
    assert score_a[0] is True
    assert score_b[0] is False


def test_compare_drafts_tie_breaks_to_a():
    a = "### Approach\nUse deque.\n```python\nprint(1)\n```"
    b = "### Approach\nUse deque.\n```python\nprint(2)\n```"
    best, _, _, tie = self_consistency.compare_drafts(
        "DSA_AGENT", "Solve sliding window maximum", a, b)
    assert best is a
    assert tie is True


def test_compare_drafts_sql_picks_concrete_index():
    import test_sql
    concrete = test_sql.FULL_ANSWER
    generic = test_sql.FULL_ANSWER.replace(
        test_sql._S_INDEX,
        "### Index Strategy\nAdd some indexes on the columns you filter by.\n\n"
    )
    best, score_a, score_b, _ = self_consistency.compare_drafts(
        "SQL_AGENT", "Optimize this slow query at scale", generic, concrete)
    assert best is concrete
    assert score_a[0] is True   # generic fails
    assert score_b[0] is False  # concrete passes


def test_generate_best_draft_skips_casual_agent():
    ask_fn, calls = _make_ask_sequence(["hello"])
    text, provider, score = self_consistency.generate_best_draft(
        "GENERAL_ASSISTANT_AGENT", "hi", "", "prompt", ask_fn, n=2)
    assert text == "hello"
    assert provider == "fake"
    assert calls["idx"] == 1   # only one generation


def test_generate_best_draft_generates_two_for_dsa():
    bad = "Use a good algorithm."
    good = (
        "### Problem Understanding\n"
        "Find two indices whose values sum to target.\n\n"
        "### Optimal Algorithm\n"
        "Hash map of value -> index, single pass.\n\n"
        "### Code\n"
        "```python\n"
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return []\n"
        "```\n\n"
        "### Approach\n"
        "Store each value's index; check the complement on the fly.\n\n"
        "### Complexity\n"
        "- Time Complexity: O(n)\n"
        "- Space Complexity: O(n)\n"
    )
    ask_fn, calls = _make_ask_sequence([bad, good])
    text, provider, score = self_consistency.generate_best_draft(
        "DSA_AGENT", "Solve two sum optimally", "", "prompt", ask_fn, n=2)
    assert text is good
    assert provider == "fake"
    assert calls["idx"] == 2
    assert score[0] is False  # verified


def test_generate_best_draft_handles_generation_failure():
    def ask_fn(prompt, context, sys_prompt, **kwargs):
        if ask_fn.calls == 0:
            ask_fn.calls += 1
            return "partial", "fake"
        raise RuntimeError("boom")
    ask_fn.calls = 0
    text, provider, score = self_consistency.generate_best_draft(
        "DSA_AGENT", "Solve sliding window maximum", "", "prompt", ask_fn, n=2)
    assert text == "partial"
    # partial is non-empty and therefore wins over the empty draft from the failed call.


def test_enabled_for_specialist_agents():
    for agent in ("DSA_AGENT", "SYSTEM_DESIGN_AGENT", "SQL_AGENT", "FULLSTACK_AGENT", "PROJECT_BUILDER_AGENT"):
        assert self_consistency.enabled_for(agent)
    assert not self_consistency.enabled_for("GENERAL_ASSISTANT_AGENT")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
