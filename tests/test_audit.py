"""
End-to-end architecture audit harness. No network: brain_manager is monkeypatched
so we can deterministically exercise router / requirement_tracker / verifier / critic
logic and prove behaviour. Run: python -m pytest tests/test_audit.py -v  (or python tests/test_audit.py)
"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import router
import requirement_tracker
import verifier_agent
import dsa_critic
import dsa_complexity

# ---------------------------------------------------------------------------
# Fake brain_manager so no network calls happen. Tests set _NEXT_RESPONSE.
# ---------------------------------------------------------------------------
_NEXT = {"text": "VERIFIED"}

def _fake_ask(prompt="", context="", sys_prompt="", **kwargs):
    val = _NEXT["text"]
    if callable(val):
        val = val(prompt, sys_prompt)
    return val, "fake"

def _fake_ask_stream(prompt="", context="", sys_prompt="", on_chunk=None, **kwargs):
    val = _NEXT["text"]
    if callable(val):
        val = val(prompt, sys_prompt)
    if on_chunk and val:
        on_chunk(val)
    return val, "fake"

import brain_manager
brain_manager.ask = _fake_ask  # type: ignore
brain_manager.ask_stream = _fake_ask_stream  # type: ignore


def set_response(text):
    _NEXT["text"] = text


# ---------------------------------------------------------------------------
# Phase 2: Routing (correctness + false positives + fallback abuse)
# ---------------------------------------------------------------------------
ROUTING_CASES = [
    # (query, expected_agent)
    ("Design WhatsApp", "SYSTEM_DESIGN_AGENT"),
    ("Optimize PostgreSQL query", "SQL_AGENT"),
    ("Solve LRU Cache", "DSA_AGENT"),
    ("Build Spring Boot React App", "PROJECT_BUILDER_AGENT"),
    ("My app throws NullPointerException", "DEBUG_AGENT"),
    ("Review this Java code", "CODE_REVIEW_AGENT"),
    # False-positive guards
    ("Reverse a linked list node by node", "DSA_AGENT"),
    ("Design a stack that supports getMin in O(1)", "DSA_AGENT"),
    ("Build an in-memory LRU cache class", "DSA_AGENT"),
    ("Find the median of two sorted arrays", "DSA_AGENT"),
    ("What is the time complexity of quicksort", "DSA_AGENT"),
    ("Design Amazon", "SYSTEM_DESIGN_AGENT"),
    ("Optimize this 5 billion row Postgres query", "SQL_AGENT"),
    ("How do I fix a NullPointerException in my code", "DEBUG_AGENT"),
]

def test_routing():
    failures = []
    for q, exp in ROUTING_CASES:
        got = router.route_agent(q)
        if got != exp:
            failures.append(f"  {q!r} -> {got} (expected {exp})")
    assert not failures, "Routing failures:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Phase 3: Requirement extraction + matching
# ---------------------------------------------------------------------------
def test_requirement_extraction_explicit():
    q = "Design WhatsApp\n\nRequirements:\nRedis\nKafka\nMonitoring\nTradeoffs"
    reqs = requirement_tracker.extract_requirements(q)
    for k in ("redis", "kafka", "monitoring", "tradeoffs"):
        assert k in reqs, f"missing {k} in {reqs}"
        assert reqs[k] is False

def test_requirement_matching_variants():
    # "real-time" in text must satisfy requirement "realtime" (normalization)
    reqs = {"realtime": False, "redis": False}
    requirement_tracker.check_requirements_satisfied(
        "We use a real-time websocket layer and Redis cache.", reqs)
    assert reqs["realtime"] is True, "real-time should satisfy 'realtime'"
    assert reqs["redis"] is True

def test_no_implicit_requirements_hallucinated():
    # A bare problem statement (no "Requirements:" block) must yield NO hard
    # requirements — the old LLM extractor hallucinated 'data structures'/'algorithms'
    # which then failed substring matching and rejected valid drafts forever.
    set_response('["data structures", "algorithms"]')  # would be the old LLM output
    assert requirement_tracker.extract_requirements("Solve the LRU Cache problem") == {}

def test_requirement_rejection():
    reqs = {"redis": False, "kafka": False}
    requirement_tracker.check_requirements_satisfied("We only use redis.", reqs)
    missing = requirement_tracker.get_missing_requirements(reqs)
    assert missing == ["kafka"], missing


# ---------------------------------------------------------------------------
# Phase 5/6: Verifier + Critic verdict parsing robustness
# ---------------------------------------------------------------------------
def test_verifier_clean_verified():
    set_response("VERIFIED")
    r = verifier_agent.verify("SQL_AGENT", "q", "ans")
    assert r["verified"] is True

def test_verifier_rejected():
    set_response("REJECTED\nReason: missing Monitoring section.")
    r = verifier_agent.verify("SQL_AGENT", "q", "ans")
    assert r["verified"] is False
    assert "Monitoring" in r["feedback"]

def test_verifier_rambling_then_verified():
    # LLM rambles then concludes VERIFIED on its own line. Must be VERIFIED.
    set_response("Let me think about this.\nThe answer looks complete.\nVERIFIED")
    r = verifier_agent.verify("SQL_AGENT", "q", "ans")
    assert r["verified"] is True, "Trailing VERIFIED verdict must be honored"

def test_critic_rejected_treemap():
    set_response("REJECTED\nReason: O(k) median lookup.\nExpected: Two Heaps + Lazy Deletion")
    r = dsa_critic.critique("Sliding Window Median", "uses TreeMap")
    assert r["verified"] is False
    assert "Two Heaps" in r["feedback"]


def _dsa_compile_answer(code, lang="python"):
    return (
        "### Problem Understanding\nWe need to solve the problem.\n\n"
        "### Optimal Algorithm\nUse the right data structure.\n\n"
        "### Code\n```" + lang + "\n" + code + "\n```\n\n"
        "### Approach\nSingle pass.\n\n"
        "### Complexity\n- Time Complexity: O(n)\n- Space Complexity: O(n)\n"
    )


def test_verifier_rejects_dsa_missing_cpp_headers():
    # Even though the fake LLM would return VERIFIED, the deterministic compile
    # verifier must reject the draft before any network call.
    set_response("VERIFIED")
    ans = _dsa_compile_answer(
        "int main() {\n"
        "    vector<int> v = {1, 2};\n"
        "    cout << v[0] << endl;\n"
        "    return 0;\n"
        "}\n", "cpp"
    )
    r = verifier_agent.verify("DSA_AGENT", "reverse a linked list", ans)
    assert r["verified"] is False
    assert "header" in r["feedback"].lower()


def test_verifier_rejects_dsa_multiple_java_classes():
    set_response("VERIFIED")
    ans = _dsa_compile_answer(
        "public class TrieNode {}\n"
        "public class Trie {}\n", "java"
    )
    r = verifier_agent.verify("DSA_AGENT", "implement a trie", ans)
    assert r["verified"] is False
    assert "public class" in r["feedback"].lower() or "compile" in r["feedback"].lower()


def test_verifier_rejects_dsa_java_missing_import():
    set_response("VERIFIED")
    ans = _dsa_compile_answer(
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        ArrayList<Integer> list = new ArrayList<>();\n"
        "        System.out.println(list);\n"
        "    }\n"
        "}\n", "java"
    )
    r = verifier_agent.verify("DSA_AGENT", "merge k sorted lists", ans)
    assert r["verified"] is False
    assert "import" in r["feedback"].lower()


# ---------------------------------------------------------------------------
# Phase 7: Response integrity + 1000+ line stress (no truncation/corruption)
# ---------------------------------------------------------------------------
def test_integrity_detects_unbalanced_fence():
    assert "unbalanced code fences" in router._check_integrity("```python\nx=1\n")
    assert router._check_integrity("```py\nx=1\n```") == []

def _big_response(lines=1500):
    out = ["# Large Response\n"]
    out.append("```python")
    for i in range(lines):
        out.append(f"def func_{i}(x):  # line {i}")
        out.append(f"    return x + {i}")
    out.append("```")
    return "\n".join(out)

def test_stress_1000_lines_no_truncation():
    big = _big_response(1500)
    set_response(big)
    # Force verifier to pass so we exercise the integrity + streaming path.
    orig_verify = verifier_agent.verify
    verifier_agent.verify = lambda *a, **k: {"verified": True, "feedback": ""}
    try:
        collected = []
        result = router.run_agent("SYSTEM_DESIGN_AGENT", "Design something big",
                                  context="", on_chunk=collected.append)
    finally:
        verifier_agent.verify = orig_verify
    streamed = "".join(collected)
    assert streamed == result, "Streamed chunks must reassemble to the exact response"
    assert result.count("\n") >= 3000, f"Expected 3000+ lines, got {result.count(chr(10))}"
    assert result.count("```") % 2 == 0, "Code fences must be balanced after integrity stage"
    assert "func_1499" in result, "Tail of large response must not be truncated"

def test_dsa_pipeline_end_to_end():
    # Full specialist pipeline: generator -> DSA critic -> verifier -> integrity -> stream.
    # The critic/verifier get VERIFIED; the generator returns a complete LRU solution.
    solution = (
        "## Optimal Solution\n\n"
        "```python\n"
        "from collections import OrderedDict\n\n"
        "class LRUCache:\n"
        "    def __init__(self, capacity: int):\n"
        "        self.cache = OrderedDict()\n"
        "        self.capacity = capacity\n\n"
        "    def get(self, key: int) -> int:\n"
        "        if key not in self.cache:\n"
        "            return -1\n"
        "        self.cache.move_to_end(key)\n"
        "        return self.cache[key]\n\n"
        "    def put(self, key: int, value: int) -> None:\n"
        "        if key in self.cache:\n"
        "            self.cache.move_to_end(key)\n"
        "        self.cache[key] = value\n"
        "        if len(self.cache) > self.capacity:\n"
        "            self.cache.popitem(last=False)\n"
        "```\n\n"
        "**Time:** O(1) get/put. **Space:** O(capacity)."
    )
    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "dsa critic" in sp or "verifier agent" in sp:
            return "VERIFIED"
        return solution
    set_response(responder)
    try:
        collected = []
        result = router.run_agent("DSA_AGENT", "Solve the LRU Cache problem",
                                  context="", on_chunk=collected.append)
    finally:
        set_response("VERIFIED")
    assert "LRUCache" in result, "DSA pipeline must return a complete solution, not an apology"
    assert "I apologize" not in result
    assert result.count("```") % 2 == 0
    assert "".join(collected) == result

def test_general_agent_streams_directly():
    set_response("Hello boss, how can I help?")
    collected = []
    result = router.run_agent("GENERAL_ASSISTANT_AGENT", "hi", context="",
                              on_chunk=collected.append)
    assert result == "Hello boss, how can I help?"
    assert "".join(collected) == result


# ---------------------------------------------------------------------------
# Phase 1: Verifier leakage — internal QA output must NEVER reach the user
# ---------------------------------------------------------------------------
_LEAK_TOKENS = [
    "Final Verification Failure", "Missing requirements", "Verifier Notes",
    "VERIFIER FEEDBACK", "REJECTED", "Reason:", "Expected:", "critic",
]

def test_no_verifier_leakage_on_exhaustion():
    # Generator returns a usable draft; verifier ALWAYS rejects -> retries exhausted.
    # Self-healing behavior: deliver the BEST-EFFORT draft, never leak QA notes.
    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "verifier agent" in sp or "dsa critic" in sp:
            return "REJECTED\nReason: missing Monitoring and Disaster Recovery sections."
        return "## Draft answer\nSome partial content."
    set_response(responder)
    try:
        collected = []
        result = router.run_agent("SYSTEM_DESIGN_AGENT", "Design WhatsApp",
                                  context="", on_chunk=collected.append)
    finally:
        set_response("VERIFIED")
    streamed = "".join(collected)
    for tok in _LEAK_TOKENS:
        assert tok not in result, f"Leaked internal QA token to user (return): {tok!r}"
        assert tok not in streamed, f"Leaked internal QA token to user (stream): {tok!r}"
    # The generic apology must NOT be returned for a query that produced real content.
    assert result != router._SAFE_FALLBACK_MESSAGE
    assert "Draft answer" in result and "partial content" in result


# ---------------------------------------------------------------------------
# Deterministic end-to-end LFU run: bad draft -> reject -> regenerate -> ship good
# ---------------------------------------------------------------------------
def test_lfu_pipeline_regenerates_after_bad_draft():
    # First draft is a sentinel-eviction LFU that the DETERMINISTIC lfu_critic
    # rejects pre-LLM. After the verifier feedback is injected, the generator
    # returns a correct LFU which must be the answer that ships.
    from test_lfu_critic import LFU_GOOD as good
    bad = (
        "# Problem Understanding\nDesign an LFU cache.\n\n"
        "# Optimal Algorithm\nUse a sentinel node for eviction.\n\n"
        "# Code\n```python\n"
        "class LFUCache:\n"
        "    def evict(self):\n"
        "        node = self.dummy.next  # sentinel-based eviction\n"
        "        self.remove(node)\n"
        "```\n\n"
        "# Approach\nEvict using the dummy sentinel node.\n\n"
        "# Complexity\nO(1)\n"
    )

    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "dsa critic" in sp or "verifier agent" in sp:
            return "VERIFIED"
        # Generation path: once the verifier feedback has been injected (i.e. the
        # bad draft was rejected and we are regenerating), return the good answer.
        if "verifier feedback" in sp:
            return good
        return bad

    set_response(responder)
    try:
        collected = []
        result = router.run_agent("DSA_AGENT", "implement an lfu cache",
                                  context="", on_chunk=collected.append)
    finally:
        set_response("VERIFIED")

    # The bad sentinel draft must NOT ship — regeneration must have replaced it.
    assert "self.dummy.next" not in result, "Shipped the rejected sentinel draft"
    assert "sentinel" not in result.lower()
    # The correct LFU (keyToNode + freqToList + minFreq) must be delivered.
    assert "freqToList" in result and "minFreq" in result
    # Streaming integrity + no internal QA leakage.
    assert "".join(collected) == result
    assert result.count("```") % 2 == 0
    for tok in _LEAK_TOKENS:
        assert tok not in result, f"Leaked internal QA token: {tok!r}"


# ---------------------------------------------------------------------------
# Eliminate generic fallback: self-healing best-effort delivery
# ---------------------------------------------------------------------------
def test_best_effort_never_returns_generic_fallback():
    # Valid technical query; verifier ALWAYS rejects, but the generator produced a
    # complete solution -> ship it (best-effort), NEVER the generic apology.
    solution = "## Solution\n```java\nclass Solver { int f(int a){ return a*2; } }\n```\nWorks."
    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "verifier agent" in sp or "dsa critic" in sp:
            return "REJECTED\nReason: not optimal enough."
        return solution
    set_response(responder)
    try:
        result = router.run_agent("DSA_AGENT", "Implement a solver in Java", context="")
    finally:
        set_response("VERIFIED")
    assert result != router._SAFE_FALLBACK_MESSAGE
    assert "class Solver" in result, "best-effort must deliver the real draft"
    for tok in _LEAK_TOKENS:
        assert tok not in result

def test_clarification_when_no_usable_draft():
    # Generator produces NOTHING usable -> ask a context-tied clarification, not the
    # generic apology.
    set_response("")  # every generation + verification returns empty
    try:
        result = router.run_agent("DEBUG_AGENT", "fix it", context="")
    finally:
        set_response("VERIFIED")
    assert result != router._SAFE_FALLBACK_MESSAGE
    assert "stack trace" in result.lower(), "clarification must ask for the missing info"

def test_final_attempt_escalates_to_deepthink():
    # The final attempt must escalate: deepthink=True + recovery prompt. With Phase 6
    # self-consistency A/B, the first attempt generates two drafts (both deepthink=False),
    # then the remaining two attempts follow the original escalation pattern.
    seen_deepthink = []
    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "verifier agent" in sp or "dsa critic" in sp:
            return "REJECTED\nReason: incomplete."
        return "## partial\nnot enough yet"
    real_ask = brain_manager.ask
    def capture(prompt="", context="", sys_prompt="", **kw):
        sp = (sys_prompt or "").lower()
        if not ("verifier agent" in sp or "dsa critic" in sp):
            seen_deepthink.append(bool(kw.get("deepthink", False)))
        return real_ask(prompt, context, sys_prompt, **kw)
    set_response(responder)
    brain_manager.ask = capture
    try:
        router.run_agent("DSA_AGENT", "Implement a thing", context="")
    finally:
        brain_manager.ask = real_ask
        set_response("VERIFIED")
    assert seen_deepthink[-1] is True, f"final attempt must use deepthink: {seen_deepthink}"
    assert seen_deepthink.count(True) == 1, f"only the final attempt should use deepthink: {seen_deepthink}"
    assert all(d is False for d in seen_deepthink[:-1]), f"non-final attempts must not use deepthink: {seen_deepthink}"


# ---------------------------------------------------------------------------
# Phase 2: Requirement levels — MANDATORY fails, RECOMMENDED/OPTIONAL do not
# ---------------------------------------------------------------------------
def test_requirement_levels_classification():
    assert requirement_tracker.classify_requirement("JWT") == requirement_tracker.LEVEL_MANDATORY
    assert requirement_tracker.classify_requirement("Docker") == requirement_tracker.LEVEL_MANDATORY
    assert requirement_tracker.classify_requirement("Redis") == requirement_tracker.LEVEL_MANDATORY
    assert requirement_tracker.classify_requirement("Folder Structure") == requirement_tracker.LEVEL_MANDATORY
    assert requirement_tracker.classify_requirement("Monitoring") == requirement_tracker.LEVEL_RECOMMENDED
    assert requirement_tracker.classify_requirement("Tradeoffs") == requirement_tracker.LEVEL_RECOMMENDED
    assert requirement_tracker.classify_requirement("Security") == requirement_tracker.LEVEL_RECOMMENDED
    assert requirement_tracker.classify_requirement("Detailed Cost Analysis") == requirement_tracker.LEVEL_OPTIONAL
    assert requirement_tracker.classify_requirement("Detailed Redis Sizing") == requirement_tracker.LEVEL_OPTIONAL
    assert requirement_tracker.classify_requirement("Detailed Kafka Capacity Planning") == requirement_tracker.LEVEL_OPTIONAL

def test_missing_optional_never_fails():
    # Answer covers the mandatory item but omits an optional deep-dive.
    reqs = {"redis": False, "detailed cost analysis": False}
    requirement_tracker.check_requirements_satisfied("We use Redis for caching.", reqs)
    mand = requirement_tracker.get_missing_requirements(reqs, level=requirement_tracker.LEVEL_MANDATORY)
    opt = requirement_tracker.get_missing_requirements(reqs, level=requirement_tracker.LEVEL_OPTIONAL)
    assert mand == [], f"Mandatory satisfied, should not be missing: {mand}"
    assert opt == ["detailed cost analysis"], opt

def test_good_answer_not_rejected_for_optional():
    # Verifier passes; mandatory present; optional missing -> ships verified draft.
    answer = "## Design\nUses Redis and JWT. ```\ncode\n```"
    def responder(prompt, sys_prompt):
        sp = (sys_prompt or "").lower()
        if "verifier agent" in sp or "dsa critic" in sp:
            return "VERIFIED"
        return answer
    set_response(responder)
    try:
        result = router.run_agent("SYSTEM_DESIGN_AGENT",
                                  "Design X\nRequirements:\nRedis\nJWT\nDetailed Cost Analysis",
                                  context="")
    finally:
        set_response("VERIFIED")
    assert result == answer, "A verified answer must ship even if an OPTIONAL deep-dive is missing"


# ---------------------------------------------------------------------------
# Phase 3: Response isolation — no cross-request / cross-agent contamination
# ---------------------------------------------------------------------------
def test_stateless_generation_no_history_pollution():
    # Specialist generation + verifier must run brain_manager stateless so a
    # prior agent's draft cannot leak into the next request.
    seen = {"stateless_flags": []}
    real_ask = brain_manager.ask
    def spy_ask(prompt="", context="", sys_prompt="", **kwargs):
        seen["stateless_flags"].append(kwargs.get("stateless", False))
        return real_ask(prompt, context, sys_prompt, **kwargs)
    brain_manager.ask = spy_ask
    set_response(lambda p, sp: "VERIFIED" if ("verifier agent" in (sp or "").lower() or "dsa critic" in (sp or "").lower()) else "## Answer\nok")
    try:
        router.run_agent("SQL_AGENT", "Optimize a query", context="")
    finally:
        brain_manager.ask = real_ask
        set_response("VERIFIED")
    # Every brain call in the specialist path (generation + verifier) must be stateless.
    assert seen["stateless_flags"], "expected brain_manager.ask to be called"
    assert all(seen["stateless_flags"]), f"non-stateless calls leaked history: {seen['stateless_flags']}"

def test_unique_request_ids():
    # Two sequential requests must not share buffers (fresh request_id each time).
    ids = []
    real_info = router.logger.info
    def cap(msg, *a, **k):
        if isinstance(msg, str) and "PIPELINE_START" in msg:
            ids.append(msg)
        return real_info(msg, *a, **k)
    router.logger.info = cap
    set_response("VERIFIED")
    try:
        router.run_agent("GENERAL_ASSISTANT_AGENT", "hi", context="")
        router.run_agent("GENERAL_ASSISTANT_AGENT", "hello", context="")
    finally:
        router.logger.info = real_info
    assert len(ids) == 2 and ids[0] != ids[1], f"request_ids must be unique: {ids}"


# ---------------------------------------------------------------------------
# Phase 5: AST-aware DSA complexity verifier
# ---------------------------------------------------------------------------
def test_complexity_sliding_window_median_rejects_heap_remove():
    bad = (
        "### Complexity\nTime Complexity: O(n log k)\n"
        "```python\nimport heapq\n"
        "def medianSlidingWindow(nums, k):\n"
        "    heap = []\n"
        "    heap.remove(nums[i-k])  # remove leaving element\n```"
    )
    ok, reason = dsa_complexity.analyze("Sliding Window Median", bad)
    assert ok is False and "lazy deletion" in reason.lower()

def test_complexity_sliding_window_median_accepts_lazy_deletion():
    good = (
        "### Complexity\nTime Complexity: O(n log k)\n"
        "```python\nimport heapq\n"
        "# Two heaps with lazy deletion via to_delete counter\n"
        "to_delete = {}\nsmall, large = [], []\n```"
    )
    ok, _ = dsa_complexity.analyze("Sliding Window Median", good)
    assert ok is True

def test_complexity_lfu_rejects_min_scan():
    bad = (
        "### Complexity\nTime Complexity: O(1)\n"
        "```python\n"
        "def get(self, key):\n"
        "    lowest = min(self.freq.values())  # scan to find min freq\n```"
    )
    ok, reason = dsa_complexity.analyze("Implement LFU Cache", bad)
    assert ok is False and "minFreq" in reason

def test_complexity_lfu_accepts_incremental_minfreq():
    good = (
        "### Complexity\nTime Complexity: O(1)\n"
        "```python\n"
        "def put(self, key, value):\n"
        "    self.min_freq = 1  # maintained incrementally\n"
        "    self.freq[key] = 1\n```"
    )
    ok, _ = dsa_complexity.analyze("Implement LFU Cache", good)
    assert ok is True

def test_complexity_ignored_for_unrelated_problem():
    # A correct LRU using OrderedDict must never be flagged by the complexity checks.
    ok, _ = dsa_complexity.analyze(
        "Implement LRU Cache",
        "Time Complexity: O(1)\n```python\nfrom collections import OrderedDict\n```")
    assert ok is True

def test_complexity_java_naive_heap_remove_rejected():
    # Exact attempt-1 anti-pattern captured in the live trace: heap.remove(element).
    bad = ("### Complexity\nTime Complexity: O(n log k)\n```java\n"
           "PriorityQueue<Integer> maxHeap = new PriorityQueue<>();\n"
           "maxHeap.remove(num);\n```")
    ok, reason = dsa_complexity.analyze("Implement Sliding Window Median in Java", bad)
    assert ok is False and "lazy" in reason.lower()

def test_complexity_java_lazy_deletion_accepted():
    # Exact attempt-3 pattern that SHOULD ship: removal targets a HashMap, not the heap.
    good = ("### Complexity\nTime Complexity: O(n log k)\n```java\n"
            "PriorityQueue<Integer> maxHeap = new PriorityQueue<>();\n"
            "Map<Integer,Integer> delayedRemoval = new HashMap<>();\n"
            "delayedRemoval.remove(maxHeap.peek());\n"
            "maxHeap.poll();\n```")
    ok, _ = dsa_complexity.analyze("Implement Sliding Window Median in Java", good)
    assert ok is True

def test_complexity_lazy_without_keyword_accepted():
    # CASE B regression: lazy bookkeeping map with NO 'lazy/delayed' keyword in its name.
    good = ("Time Complexity: O(n log k)\n```java\n"
            "PriorityQueue<Integer> lo = new PriorityQueue<>();\n"
            "Map<Integer,Integer> hash = new HashMap<>();\n"
            "hash.remove(num);  // O(1) map removal\n```")
    ok, _ = dsa_complexity.analyze("Sliding Window Median", good)
    assert ok is True

def test_complexity_heap_remove_head_noarg_accepted():
    # heap.remove() with no argument removes the HEAD -> O(log n), must NOT be flagged.
    good = ("Time Complexity: O(n log k)\n```java\n"
            "PriorityQueue<Integer> maxHeap = new PriorityQueue<>();\n"
            "maxHeap.remove();\n```")
    ok, _ = dsa_complexity.analyze("Sliding Window Median", good)
    assert ok is True


# ---------------------------------------------------------------------------
# Phase 9: Template isolation — foreign sections rejected, native ones kept
# ---------------------------------------------------------------------------
def test_forbidden_section_system_design_full_code():
    assert verifier_agent._find_forbidden_section(
        "SYSTEM_DESIGN_AGENT", "### Architecture Diagram\n...\n### Full Code\n```\n...\n```") == "full code"

def test_forbidden_section_sql_edge_cases():
    assert verifier_agent._find_forbidden_section(
        "SQL_AGENT", "### Index Strategy\n...\n### Edge Cases\n- empty table") == "edge cases"

def test_forbidden_section_debug_complexity():
    assert verifier_agent._find_forbidden_section(
        "DEBUG_AGENT", "### Root Cause Analysis\n...\n### Complexity Analysis\nO(n)") == "complexity analysis"

def test_no_false_forbidden_native_sections():
    # A clean System Design response with only its own sections must NOT be flagged.
    sd = ("### Functional Requirements\n...\n### Architecture Diagram\nClient -> Gateway\n"
          "### Redis Strategy\n...\n### Kafka Strategy\n...\n### Tradeoffs\n...")
    assert verifier_agent._find_forbidden_section("SYSTEM_DESIGN_AGENT", sd) is None
    # Code review's own 'Architecture & Structure' must not trip 'architecture diagram'.
    cr = "### Architecture & Structure\n...\n### Refactored Code\n```\n...\n```"
    assert verifier_agent._find_forbidden_section("CODE_REVIEW_AGENT", cr) is None

def test_verifier_rejects_foreign_section_end_to_end():
    # Generator emits a SQL answer that wrongly contains an Edge Cases section;
    # verifier must reject it (regenerate), never ship it.
    leaky = "### Index Strategy\nCREATE INDEX ...\n### Edge Cases\n- empty result set"
    res = verifier_agent.verify("SQL_AGENT", "Optimize query", leaky)
    assert res["verified"] is False
    assert "edge cases" in res["feedback"].lower()


# ---------------------------------------------------------------------------
# Phase 4/6: Agent prompt contracts (loaded prompts enforce the right template)
# ---------------------------------------------------------------------------
def _prompt(agent):
    return router.AGENT_PROMPTS[agent]

def test_debug_prompt_contract():
    p = _prompt("DEBUG_AGENT")
    for s in ("Evidence Needed", "Likely Causes", "Investigation Steps", "Fix Suggestions"):
        assert s in p, f"DEBUG prompt missing section: {s}"
    # Must instruct asking for code/stack trace and forbid foreign sections.
    assert "stack trace" in p.lower()
    for forbidden in ("Kafka Strategy", "Architecture Diagram", "Complexity Analysis"):
        assert forbidden in p, f"DEBUG prompt should name forbidden section {forbidden}"

def test_fullstack_prompt_contract_no_corruption():
    p = _prompt("PROJECT_BUILDER_AGENT")
    assert all(ord(c) >= 32 or c in "\n\t" for c in p), "prompt contains control chars"
    for d in ("frontend/", "backend/", "database/", "docker/"):
        assert d in p, f"builder prompt missing dir: {d}"
    for s in ("Entities", "Repositories", "Services", "Controllers", "React Components",
              "Docker Files", "README"):
        assert s in p, f"builder prompt missing section: {s}"

def test_sql_prompt_has_execution_plan():
    p = _prompt("SQL_AGENT")
    assert "Execution Plan" in p and "Caching" in p

def test_system_design_prompt_has_capacity_and_tech_choices():
    p = _prompt("SYSTEM_DESIGN_AGENT")
    for s in ("Capacity Calculations", "Technology Choices", "Architecture Diagram"):
        assert s in p, f"system design prompt missing: {s}"


# ---------------------------------------------------------------------------
# Phase 7: Timeout resiliency — provider returns empty responses
# ---------------------------------------------------------------------------
def test_router_timeout_resiliency_falls_back():
    # Simulate a provider that times out (empty response) for every attempt.
    # BrainManager.ask will failover and eventually return an empty string.
    original = brain_manager.ask
    brain_manager.ask = lambda *a, **k: ("", "timeout")
    try:
        response = router.run_agent(router.DSA_AGENT, "Solve two sum")
        # Router must not crash and must return a non-empty clarification
        # because no usable draft was produced.
        assert response and response.strip(), "router returned empty response on timeout"
        assert "two sum" in response.lower() or "problem" in response.lower(), response
    finally:
        brain_manager.ask = original


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception:
            print(f"ERROR {t.__name__}:\n{traceback.format_exc()}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
