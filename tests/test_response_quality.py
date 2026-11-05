"""
Phase 10 — Response Quality Critic regression suite.

Deterministic tests for the universal quality gate (placeholders, truncation,
unbalanced fences, boilerplate repetition, filler, deflection) plus the LLM
scorer's parsing / threshold / fail-open behavior and its wiring into
verifier_agent.verify. The deterministic reject paths need NO network; the scorer
paths stub brain_manager. Run:
    python -m pytest tests/test_response_quality.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import response_quality_critic as rq

AG = "DSA_AGENT"  # any specialist; the deterministic layer is domain-agnostic


def _block(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Clean answers + legitimate clarifications must PASS the deterministic gate
# ---------------------------------------------------------------------------
CLEAN_SIMPLE = "Binary search is O(log n) time and O(1) space."

CLEAN_CODE = (
    "## Optimal Solution\n"
    "Use a hash map for O(1) lookups.\n"
    + _block("def two_sum(nums, target):\n"
             "    seen = {}\n"
             "    for i, n in enumerate(nums):\n"
             "        if target - n in seen:\n"
             "            return [seen[target - n], i]\n"
             "        seen[n] = i\n"
             "    return []")
    + "\n**Complexity:** O(n) time, O(n) space."
)

CLARIFICATION = (
    "A NullPointerException dereferences null; I can't pinpoint it without your code. "
    "Please share the full stack trace and the failing method."
)


def test_clean_simple_answer_passes():
    assert rq.deterministic_check(AG, "complexity of binary search?", CLEAN_SIMPLE)[0] is True


def test_clean_code_answer_passes():
    assert rq.deterministic_check(AG, "two sum", CLEAN_CODE)[0] is True


def test_clarification_not_flagged():
    # "I can't pinpoint it without your code" is a clarification, NOT a refusal.
    assert rq.deterministic_check("DEBUG_AGENT", "my app NPEs", CLARIFICATION)[0] is True


# ---------------------------------------------------------------------------
# Placeholders / stubs
# ---------------------------------------------------------------------------
def test_todo_comment_rejected():
    text = "## Solution\n" + _block("def solve():\n    # TODO: implement\n    return 0")
    ok, reason = rq.deterministic_check(AG, "solve it", text)
    assert ok is False and "placeholder" in reason.lower()


def test_your_code_here_rejected():
    text = "## Solution\n" + _block("def solve():\n    # your code here\n    pass")
    assert rq.deterministic_check(AG, "solve it", text)[0] is False


def test_bracket_placeholder_rejected():
    text = "Set the key to [insert your API key here] and call the endpoint."
    assert rq.deterministic_check(AG, "how to call api", text)[0] is False


def test_not_implemented_error_rejected():
    text = "## Solution\n" + _block("def solve():\n    raise NotImplementedError")
    assert rq.deterministic_check(AG, "solve it", text)[0] is False


# ---------------------------------------------------------------------------
# Truncation / unbalanced fences
# ---------------------------------------------------------------------------
def test_rest_of_code_truncation_rejected():
    text = "## Solution\n" + _block("def solve():\n    # ... rest of the code\n    return 0")
    ok, reason = rq.deterministic_check(AG, "solve it", text)
    assert ok is False and "truncat" in reason.lower()


def test_omitted_for_brevity_rejected():
    text = "Here is the class; the remaining methods are omitted for brevity."
    assert rq.deterministic_check(AG, "write a class", text)[0] is False


def test_unbalanced_fence_rejected():
    text = "## Answer\n```python\nprint('hello')"  # never closed
    ok, reason = rq.deterministic_check(AG, "print hello", text)
    assert ok is False and "fence" in reason.lower()


# ---------------------------------------------------------------------------
# Boilerplate repetition
# ---------------------------------------------------------------------------
def test_repeated_header_rejected():
    text = "## Overview\nA\n## Overview\nB\n## Overview\nC\n"
    ok, reason = rq.deterministic_check(AG, "explain", text)
    assert ok is False and "repeated" in reason.lower()


def test_repeated_paragraph_rejected():
    para = "This approach uses a hash map to achieve constant time average lookups for each element.\n\n"
    text = para + "Some other text here.\n\n" + para
    ok, reason = rq.deterministic_check(AG, "explain", text)
    assert ok is False and "repeat" in reason.lower()


# ---------------------------------------------------------------------------
# Filler + deflection
# ---------------------------------------------------------------------------
def test_filler_rejected():
    text = "As an AI language model, the time complexity is O(n). I hope this helps!"
    assert rq.deterministic_check(AG, "complexity?", text)[0] is False


def test_deflection_rejected():
    text = "I'm sorry, but I can't help with that request."
    ok, reason = rq.deterministic_check(AG, "reverse a linked list", text)
    assert ok is False and "deflect" in reason.lower()


def test_refusal_to_help_rejected():
    text = "Unfortunately, I cannot provide that. Please try another assistant."
    assert rq.deterministic_check(AG, "sort an array", text)[0] is False


# ---------------------------------------------------------------------------
# False-positive regressions (correct answers must NEVER be rejected)
# ---------------------------------------------------------------------------
def test_html_placeholder_attribute_not_flagged():
    # The HTML/JSX `placeholder` attribute is legitimate, not a stub.
    text = "## Form\n" + _block('<input type="email" placeholder="Email" />', "jsx")
    assert rq.deterministic_check("FULLSTACK_AGENT", "make a form", text)[0] is True


def test_react_component_names_not_flagged():
    # `<Todo />` / `<TodoList>` are component names, not TODO markers.
    text = "## App\n" + _block("export default function App(){ return <TodoList items={todos} />; }", "jsx")
    assert rq.deterministic_check("FULLSTACK_AGENT", "render todos", text)[0] is True


def test_rest_of_the_team_not_flagged():
    # "rest of the team" must not trip the "rest of the code/implementation" marker.
    text = "Document the design and share it with the rest of the team for review."
    assert rq.deterministic_check(AG, "process advice", text)[0] is True


def test_legitimate_apology_without_refusal_not_flagged():
    # An apology that still answers is not a refusal/fallback.
    text = "Sorry for the earlier confusion — the correct complexity is O(n log n)."
    assert rq.deterministic_check(AG, "complexity?", text)[0] is True


def test_todo_prefixed_folder_name_not_flagged():
    # "todo-app/" is a folder name, not a TODO marker.
    text = "## Structure\n" + _block("todo-app/\n  frontend/\n  backend/", "text")
    assert rq.deterministic_check("FULLSTACK_AGENT", "scaffold", text)[0] is True


def test_react_state_destructuring_not_flagged():
    # "[todos, setTodos]" must not match the "[todo ...]" placeholder form.
    text = "## Hook\n" + _block("const [todos, setTodos] = useState([]);", "jsx")
    assert rq.deterministic_check("FULLSTACK_AGENT", "state", text)[0] is True


def test_real_todo_line_still_rejected():
    assert rq.deterministic_check(AG, "q", "TODO: implement the parser")[0] is False


# ---------------------------------------------------------------------------
# Scorer: parsing + threshold + fail-open
# ---------------------------------------------------------------------------
_FULL_BLOCK = (
    "CORRECTNESS: 9\nCOMPLETENESS: 8\nDEPTH: 9\nCLARITY: 9\n"
    "PRODUCTION_READINESS: 8\nISSUES: none"
)
_LOW_BLOCK = (
    "CORRECTNESS: 9\nCOMPLETENESS: 6\nDEPTH: 9\nCLARITY: 9\n"
    "PRODUCTION_READINESS: 9\nISSUES: missing error handling"
)


def test_parse_scores_full():
    scores = rq._parse_scores(_FULL_BLOCK)
    assert scores == {"Correctness": 9, "Completeness": 8, "Depth": 9,
                      "Clarity": 9, "Production Readiness": 8}


def test_parse_scores_clamped():
    assert rq._parse_scores("CORRECTNESS: 99")["Correctness"] == 10


def test_extract_issues():
    assert rq._extract_issues(_LOW_BLOCK) == "missing error handling"
    assert rq._extract_issues(_FULL_BLOCK) == ""


def test_score_passes_when_all_high(monkeypatch):
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: (_FULL_BLOCK, "x"))
    ok, fb = rq.score(AG, "q", "a solid answer")
    assert ok is True and fb == ""


def test_score_rejects_when_any_low(monkeypatch):
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: (_LOW_BLOCK, "x"))
    ok, fb = rq.score(AG, "q", "an incomplete answer")
    assert ok is False
    assert "completeness 6/10" in fb.lower()
    assert "missing error handling" in fb.lower()


def test_score_fails_open_on_unparseable(monkeypatch):
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "x"))
    assert rq.score(AG, "q", "answer")[0] is True


def test_score_fails_open_on_partial(monkeypatch):
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask",
                        lambda *a, **k: ("CORRECTNESS: 9\nCLARITY: 8", "x"))
    assert rq.score(AG, "q", "answer")[0] is True


def test_score_fails_open_on_exception(monkeypatch):
    import brain_manager
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(brain_manager, "ask", boom)
    assert rq.score(AG, "q", "answer")[0] is True


def test_score_skips_empty_response():
    assert rq.score(AG, "q", "   ")[0] is True


# ---------------------------------------------------------------------------
# Verifier integration
# ---------------------------------------------------------------------------
def test_verifier_rejects_placeholder_without_network():
    # The universal deterministic gate fires before any LLM call.
    import verifier_agent
    text = "## Optimal Solution\n" + _block("def solve():\n    # TODO: implement\n    return 0")
    r = verifier_agent.verify(AG, "Solve the two-sum problem", text)
    assert r["verified"] is False
    assert "placeholder" in r["feedback"].lower()


def test_verifier_rejects_unbalanced_fence_without_network():
    import verifier_agent
    text = "## Answer\n```python\nprint('hi')"  # open fence, no network needed
    r = verifier_agent.verify(AG, "print hi", text)
    assert r["verified"] is False


def test_verifier_rejects_below_quality_bar(monkeypatch):
    # Conceptual DSA Q: domain critic + main verifier PASS (VERIFIED); the scorer
    # then rejects because a category is below the bar -> regenerate.
    import brain_manager
    import verifier_agent

    def fake(prompt="", context="", sys_prompt="", **k):
        if "response quality critic" in (sys_prompt or "").lower():
            return (_LOW_BLOCK, "x")
        return ("VERIFIED", "x")

    monkeypatch.setattr(brain_manager, "ask", fake)
    r = verifier_agent.verify(AG, "What is a hash map?",
                              "A hash map stores key-value pairs with O(1) average lookup.")
    assert r["verified"] is False
    assert "quality" in r["feedback"].lower()


def test_verifier_passes_when_quality_high(monkeypatch):
    import brain_manager
    import verifier_agent

    def fake(prompt="", context="", sys_prompt="", **k):
        if "response quality critic" in (sys_prompt or "").lower():
            return (_FULL_BLOCK, "x")
        return ("VERIFIED", "x")

    monkeypatch.setattr(brain_manager, "ask", fake)
    r = verifier_agent.verify(AG, "What is a hash map?",
                              "A hash map stores key-value pairs with O(1) average lookup.")
    assert r["verified"] is True


def test_verifier_scorer_fails_open(monkeypatch):
    # If the scorer output is unparseable, a verified answer must still ship.
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "x"))
    r = verifier_agent.verify(AG, "What is a hash map?",
                              "A hash map stores key-value pairs with O(1) average lookup.")
    assert r["verified"] is True


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
