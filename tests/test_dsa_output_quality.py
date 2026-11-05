"""
Phase 11 — DSA output-quality critic regression suite.

Pure-function tests (no network) for dsa_output_quality.check / cleanup, plus the
wiring into dsa_critic.critique. Run:
    python -m pytest tests/test_dsa_output_quality.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import dsa_output_quality as q
import test_dsa as t  # reuse FULL_SOLUTION + _fence


def _f(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Clean solutions must PASS (no false positives)
# ---------------------------------------------------------------------------
def test_full_solution_passes():
    assert q.check("solve two sum optimally", t.FULL_SOLUTION) == (True, "")


def test_conceptual_no_code_defers():
    assert q.check("What is a hash map?", "A hash map stores key/value pairs.")[0] is True


def test_cpp_include_not_template_artifact():
    text = ("### Code\n" + _f("#include <algorithm>\n#include <vector>\nint main(){return 0;}", "cpp")
            + "\n### Complexity\n- Time Complexity: O(n)")
    assert q.template_artifact(text) is None


def test_bold_complexity_label_not_duplicate():
    text = ("### Approach\nWe scan once.\n\n### Complexity\n"
            "**Time Complexity:** O(n)\n**Space Complexity:** O(n)\n\n### Code\n" + _f("x = 1"))
    assert q.duplicate_section(text) is None


# ---------------------------------------------------------------------------
# 1. Duplicate sections
# ---------------------------------------------------------------------------
def test_duplicate_complexity_rejected():
    text = t.FULL_SOLUTION + "\n### Complexity\n- Time Complexity: O(n)\n"
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "complexity" in reason.lower()


def test_duplicate_code_rejected():
    text = t.FULL_SOLUTION + "\n### Code\n" + _f("def f(): return 1")
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "code" in reason.lower()


def test_duplicate_approach_rejected():
    text = t.FULL_SOLUTION + "\n### Approach\nWe do it again.\n"
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "approach" in reason.lower()


def test_distinct_sections_not_flagged():
    # "Approach" and "Explanation" are different sections, never conflated.
    text = t.FULL_SOLUTION + "\n### Explanation\nA longer narrative walkthrough here.\n"
    assert q.duplicate_section(text) is None


# ---------------------------------------------------------------------------
# 2. Template artifacts / unfinished / duplicated paragraphs
# ---------------------------------------------------------------------------
def test_template_artifact_prose_rejected():
    text = t.FULL_SOLUTION.replace("Hash map of value -> index, single pass.",
                                   "your explanation here")
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "artifact" in reason.lower()


def test_template_artifact_angle_token_rejected():
    text = t.FULL_SOLUTION.replace("Store each value's index; check the complement on the fly.",
                                   "<approach>")
    assert q.template_artifact(text) is not None


def test_empty_code_block_is_artifact():
    text = t.FULL_SOLUTION + "\n### Notes\n```python\n```\n"
    assert q.template_artifact(text) == "empty code block"


def test_unfinished_sentence_rejected():
    # Realistic truncation: the whole answer ends mid-clause.
    text = t.FULL_SOLUTION + "\n\n### Notes\nThe key insight here is that we"
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "unfinished" in reason.lower()


def test_duplicated_paragraph_rejected():
    para = "We iterate once over the array and use a hash map for constant time complement lookups."
    text = t.FULL_SOLUTION + "\n\n" + para + "\n\n" + para + "\n"
    ok, reason = q.check("solve two sum optimally", text)
    assert ok is False and "duplicat" in reason.lower()


# ---------------------------------------------------------------------------
# 3. LFU cache mandatory content
# ---------------------------------------------------------------------------
LFU_FULL = (
    "### Problem Understanding\nImplement an O(1) LFU cache.\n\n"
    "### Optimal Algorithm\nTwo hash maps plus per-frequency doubly linked lists.\n\n"
    "### Code\n" + _f(
        "class LFUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.cap = cap; self.keyToNode = {}; self.freqToList = {}; self.minFreq = 0\n"
        "    def get(self, key):\n"
        "        return -1\n")
    + "\n### Approach\n"
    "keyToNode maps each key to its node; freqToList maps each frequency to a doubly "
    "linked list of nodes; minFreq is maintained incrementally. On eviction we remove "
    "the least recently used node within the minimum-frequency list (LRU tie-break).\n\n"
    "### Complexity\n- Time Complexity: O(1) because hash-map lookups and linked-list "
    "splices are constant time per operation.\n- Space: O(capacity)\n"
)


def test_lfu_full_passes():
    assert q.check("implement an LFU cache", LFU_FULL) == (True, "")


def test_lfu_missing_minfreq_rejected():
    text = LFU_FULL.replace("minFreq is maintained incrementally", "we track the smallest count")
    text = text.replace("self.minFreq = 0", "self.smallest = 0")
    text = text.replace("minimum-frequency list", "smallest-count list")
    ok, reason = q.check("implement an LFU cache", text)
    assert ok is False and "minfreq" in reason.lower()


def test_lfu_missing_tiebreak_rejected():
    text = LFU_FULL.replace(
        "On eviction we remove the least recently used node within the minimum-frequency list (LRU tie-break).",
        "On eviction we remove some node from the minimum-frequency bucket.",
    )
    ok, reason = q.check("implement an LFU cache", text)
    assert ok is False and ("tie" in reason.lower() or "lru" in reason.lower())


def test_lfu_check_skipped_for_non_lfu():
    # The LFU content gate must not fire on a non-LFU problem.
    assert q.lfu_gaps("two sum", t.FULL_SOLUTION) == []


# ---------------------------------------------------------------------------
# 4. WHY O(1)
# ---------------------------------------------------------------------------
def test_o1_without_justification_rejected():
    # A bare O(1) claim with NO mechanism/reasoning anywhere must be rejected.
    text = ("### Optimal Algorithm\nUse a dictionary.\n\n### Code\n"
            + _f("d = {}\nd[1] = 2\nprint(d[1])")
            + "\n### Approach\nStore items and read them back directly.\n\n"
            "### Complexity\n- Time Complexity: O(1)\n")
    ok, reason = q.check("design an O(1) store", text)
    assert ok is False and "why" in reason.lower()


def test_o1_with_justification_passes():
    text = ("### Optimal Algorithm\nUse a hash map.\n\n### Code\n"
            + _f("d = {}\nd[1] = 2\nprint(d[1])")
            + "\n### Approach\nWe use a hash map so each lookup is constant time.\n\n"
            "### Complexity\n- Time Complexity: O(1) because hash-map access is constant time.\n")
    assert q.check("design an O(1) store", text)[0] is True


def test_non_o1_complexity_not_required_to_justify():
    assert q.missing_why_o1("### Complexity\n- Time Complexity: O(n log n)") is False


# ---------------------------------------------------------------------------
# 5. Production-grade requirements
# ---------------------------------------------------------------------------
PROD_FULL = (
    "### Problem Understanding\nA token-bucket rate limiter.\n\n"
    "### Data Structures Used\nAn integer token counter plus a refill timestamp.\n\n"
    "### Optimal Algorithm\nToken bucket refilled per second.\n\n"
    "### Code\n" + _f(
        "class RateLimiter:\n"
        "    def __init__(self, rate):\n"
        "        if rate <= 0:\n"
        "            raise ValueError('rate must be positive')\n"
        "        self.rate = rate\n"
        "    def allow(self):\n"
        "        return True\n"
        "\n"
        "# Example usage\n"
        "rl = RateLimiter(5)\n"
        "assert rl.allow() is True\n")
    + "\n### Approach\nEncapsulated bucket with input checks and a usage example.\n\n"
    "### Complexity\n- Time Complexity: O(1) because each call updates a counter.\n\n"
    "### Edge Cases\n- rate <= 0 raises ValueError.\n- Bursts are capped at the bucket size.\n"
)


def test_production_full_passes():
    assert q.check("Write production-grade code for a rate limiter", PROD_FULL) == (True, "")


def test_production_missing_test_rejected():
    text = PROD_FULL.replace("# Example usage\nrl = RateLimiter(5)\nassert rl.allow() is True\n", "")
    ok, reason = q.check("Write production-grade code for a rate limiter", text)
    assert ok is False and "test" in reason.lower()


def test_production_missing_validation_rejected():
    text = PROD_FULL.replace(
        "        if rate <= 0:\n            raise ValueError('rate must be positive')\n", "")
    ok, reason = q.check("Write production-grade code for a rate limiter", text)
    assert ok is False and "valid" in reason.lower()


def test_production_gate_skipped_for_normal_request():
    text = PROD_FULL.replace("# Example usage\nrl = RateLimiter(5)\nassert rl.allow() is True\n", "")
    assert q.production_gaps("write a rate limiter", text) == []


def test_production_missing_data_structures_section_rejected():
    text = PROD_FULL.replace(
        "### Data Structures Used\nAn integer token counter plus a refill timestamp.\n\n", "")
    ok, reason = q.check("Write production-grade code for a rate limiter", text)
    assert ok is False and "data structures used" in reason.lower()


def test_production_missing_edge_cases_section_rejected():
    text = PROD_FULL.replace(
        "\n\n### Edge Cases\n- rate <= 0 raises ValueError.\n- Bursts are capped at the bucket size.\n",
        "\n")
    ok, reason = q.check("Write production-grade code for a rate limiter", text)
    assert ok is False and "edge cases" in reason.lower()


def test_production_sections_gate_skipped_for_normal_request():
    text = PROD_FULL.replace(
        "### Data Structures Used\nAn integer token counter plus a refill timestamp.\n\n", "")
    assert q.production_sections("write a rate limiter", text) == []


def test_duplicate_edge_cases_section_rejected():
    text = (
        "### Problem Understanding\nP\n\n### Optimal Algorithm\nA\n\n"
        "### Code\n" + _f("def f():\n    return 1") + "\n\n"
        "### Approach\nW\n\n### Complexity\nO(1) because constant.\n\n"
        "### Edge Cases\n- empty input\n\n### Edge Cases\n- duplicate section\n"
    )
    ok, reason = q.check("solve it", text)
    assert ok is False and "edge cases" in reason.lower()


# ---------------------------------------------------------------------------
# 6. cleanup()
# ---------------------------------------------------------------------------
def test_cleanup_noop_on_clean_solution():
    assert q.cleanup(t.FULL_SOLUTION) == t.FULL_SOLUTION


def test_cleanup_removes_duplicate_section():
    text = t.FULL_SOLUTION + "\n### Complexity\n- Time Complexity: O(n)\n"
    cleaned = q.cleanup(text)
    assert cleaned.count("### Complexity") == 1
    assert "def two_sum" in cleaned
    assert cleaned.count("```") % 2 == 0


def test_cleanup_collapses_repeated_header():
    text = "### Code\n### Code\n" + _f("x = 1")
    cleaned = q.cleanup(text)
    assert cleaned.count("### Code") == 1


def test_cleanup_strips_template_artifact():
    text = t.FULL_SOLUTION.replace("Hash map of value -> index, single pass.",
                                   "We use a hash map. your explanation here")
    cleaned = q.cleanup(text)
    assert "your explanation here" not in cleaned
    assert "We use a hash map." in cleaned


# ---------------------------------------------------------------------------
# critique wrapper + dsa_critic wiring
# ---------------------------------------------------------------------------
def test_critique_wrapper_shape():
    r = q.critique("solve two sum optimally", t.FULL_SOLUTION)
    assert r == {"verified": True, "feedback": ""}
    bad = t.FULL_SOLUTION + "\n### Code\n" + _f("def g(): return 2")
    rb = q.critique("solve two sum optimally", bad)
    assert rb["verified"] is False and rb["feedback"]


def test_dsa_critic_rejects_duplicate_section_without_network():
    # Output-quality runs before the LLM, so a duplicate section is rejected with no
    # brain_manager.ask call.
    import dsa_critic
    text = t.FULL_SOLUTION + "\n### Complexity\n- Time Complexity: O(n)\n"
    r = dsa_critic.critique("solve two sum optimally", text)
    assert r["verified"] is False and "complexity" in r["feedback"].lower()


def test_dsa_critic_passes_clean_solution(monkeypatch):
    import brain_manager
    import dsa_critic
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = dsa_critic.critique("solve two sum optimally", t.FULL_SOLUTION)
    assert r["verified"] is True


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
