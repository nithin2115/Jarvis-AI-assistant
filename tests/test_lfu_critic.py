"""
Phase 13 — LFU Cache Critic regression suite.

Pure-function tests (no network) for lfu_critic.check / critique, plus the
wiring into dsa_critic.critique. Run:
    python -m pytest tests/test_lfu_critic.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import lfu_critic as lc
import test_dsa as t  # reuse _fence


def _f(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# A correct, complete LFU solution that must PASS all checks
# ---------------------------------------------------------------------------
LFU_GOOD = (
    "# Problem Understanding\n"
    "Design an O(1) LFU cache with get and put operations.\n\n"
    "# Optimal Algorithm\n"
    "Use a keyToNode map, a freqToList map, and minFreq tracking. "
    "Each frequency bucket is a DLL where head.next is the oldest (LRU) "
    "and tail.prev is the newest. Eviction removes head.next from the "
    "minFreq bucket (LRU tie-break).\n\n"
    "# Code\n" + _f(
        "class LFUCache:\n"
        "    def __init__(self, capacity):\n"
        "        self.cap = capacity\n"
        "        self.keyToNode = {}      # key -> Node\n"
        "        self.freqToList = {}     # freq -> DLL\n"
        "        self.minFreq = 0\n"
        "\n"
        "    def get(self, key):\n"
        "        if key not in self.keyToNode:\n"
        "            return -1\n"
        "        node = self.keyToNode[key]\n"
        "        self._update_freq(node)\n"
        "        return node.val\n"
        "\n"
        "    def put(self, key, val):\n"
        "        if self.cap == 0:\n"
        "            return\n"
        "        if key in self.keyToNode:\n"
        "            node = self.keyToNode[key]\n"
        "            node.val = val\n"
        "            self._update_freq(node)\n"
        "            return\n"
        "        if len(self.keyToNode) >= self.cap:\n"
        "            # Evict LRU from minFreq bucket: head.next is oldest\n"
        "            dll = self.freqToList[self.minFreq]\n"
        "            evicted = dll.head.next  # oldest node\n"
        "            dll.remove(evicted)\n"
        "            del self.keyToNode[evicted.key]\n"
        "        node = Node(key, val)\n"
        "        self.keyToNode[key] = node\n"
        "        self.freqToList.setdefault(1, DLL()).append(node)\n"
        "        self.minFreq = 1\n"
        "\n"
        "    def _update_freq(self, node):\n"
        "        old_freq = node.freq\n"
        "        dll = self.freqToList[old_freq]\n"
        "        dll.remove(node)  # DLL remove: O(1)\n"
        "        if dll.empty() and old_freq == self.minFreq:\n"
        "            self.minFreq += 1  # frequency update\n"
        "        node.freq += 1\n"
        "        self.freqToList.setdefault(node.freq, DLL()).append(node)\n"
    ) + "\n\n"
    "# Approach\n"
    "HashMap lookup gives O(1) key access via keyToNode. DLL insert appends "
    "to tail.prev in O(1). DLL remove unlinks a node in O(1) using its "
    "prev/next pointers. Frequency update moves the node to the next bucket "
    "and increments minFreq when the old bucket is empty. The LRU tie-break "
    "evicts head.next (oldest) from the minFreq list.\n\n"
    "# Complexity\n"
    "- Time: O(1) per operation — HashMap lookup, DLL insert, DLL remove, "
    "and frequency update are all O(1).\n"
    "- Space: O(n) for the maps and nodes.\n\n"
    "# Edge Cases\n"
    "- capacity=0: put is a no-op, get always returns -1.\n"
    "- Frequency tie: LRU tie-break evicts the oldest node in minFreq.\n"
)


# ---------------------------------------------------------------------------
# Clean LFU solution must PASS (no false positives)
# ---------------------------------------------------------------------------
def test_good_lfu_passes():
    ok, reason = lc.check("implement an lfu cache", LFU_GOOD)
    assert ok is True, reason


def test_non_lfu_query_passes():
    ok, reason = lc.check("solve two sum", LFU_GOOD)
    assert ok is True


def test_conceptual_lfu_question_passes():
    ok, reason = lc.check("what is an lfu cache?", "An LFU cache evicts the least frequently used entry.")
    assert ok is True


def test_fail_safe_on_exception():
    ok, reason = lc.check("implement an lfu cache", None)
    assert ok is True


# ---------------------------------------------------------------------------
# 1. Sentinel/dummy eviction bug
# ---------------------------------------------------------------------------
def test_sentinel_eviction_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse sentinel node for eviction.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def evict(self):\n"
            "        node = self.dummy.next  # sentinel-based eviction\n"
            "        self.remove(node)\n"
        ) + "\n\n"
        "# Approach\nEvict using dummy sentinel node.\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "dummy" in reason.lower() or "sentinel" in reason.lower()


def test_list_head_eviction_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse list.head for eviction.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def evict(self):\n"
            "        node = self.list.head  # wrong pattern\n"
            "        self.remove(node)\n"
        ) + "\n\n"
        "# Approach\nEvict from list.head.\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "list.head" in reason.lower() or "list.head" in reason


def test_list_tail_eviction_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse list.tail for eviction.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def evict(self):\n"
            "        node = self.list.tail  # wrong pattern\n"
            "        self.remove(node)\n"
        ) + "\n\n"
        "# Approach\nEvict from list.tail.\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "list.tail" in reason.lower() or "list.tail" in reason


def test_head_next_tail_prev_accepted():
    """A response using head.next / tail.prev must not be flagged for eviction."""
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse head.next and tail.prev for eviction.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def evict(self):\n"
            "        node = self.dll.head.next  # oldest = LRU\n"
            "        self.dll.remove(node)\n"
        ) + "\n\n"
        "# Approach\nhead.next is oldest, tail.prev is newest. LRU tie-break "
        "evicts head.next from minFreq bucket. keyToNode map, freqToList map, "
        "minFreq tracking are all maintained.\n\n"
        "# Complexity\n"
        "O(1): HashMap lookup, DLL insert, DLL remove, frequency update.\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    # May fail on other checks but must NOT fail on eviction pattern
    if not ok:
        assert "head" not in reason.lower() or "list.head" not in reason.lower()


# ---------------------------------------------------------------------------
# 2. Missing LRU tie-break rule
# ---------------------------------------------------------------------------
def test_missing_lru_tiebreak_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode, freqToList, minFreq.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.freqToList = {}\n"
            "        self.minFreq = 0\n"
            "    def evict(self):\n"
            "        dll = self.freqToList[self.minFreq]\n"
            "        node = dll.head.next\n"
            "        dll.remove(node)\n"
        ) + "\n\n"
        "# Approach\n"
        "HashMap lookup gives O(1). DLL insert and DLL remove are O(1). "
        "Frequency update increments minFreq. No ordering within a frequency bucket.\n\n"
        "# Complexity\nO(1) per operation.\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "tie" in reason.lower() or "lru" in reason.lower() or "recently" in reason.lower()


# ---------------------------------------------------------------------------
# 3. Missing keyToNode / freqToList / minFreq
# ---------------------------------------------------------------------------
def test_missing_keytonode_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse freqToList and minFreq.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.freqToList = {}\n"
            "        self.minFreq = 0\n"
        ) + "\n\n"
        "# Approach\nLRU tie-break via head.next. DLL insert, DLL remove, "
        "frequency update, HashMap lookup all O(1).\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "keytonode" in reason.lower() or "key->node" in reason.lower()


def test_missing_freqtolist_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode and minFreq.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.minFreq = 0\n"
        ) + "\n\n"
        "# Approach\nLRU tie-break via head.next. DLL insert, DLL remove, "
        "frequency update, HashMap lookup all O(1).\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "freqtolist" in reason.lower() or "freq->list" in reason.lower()


def test_missing_minfreq_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode and freqToList.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.freqToList = {}\n"
        ) + "\n\n"
        "# Approach\nLRU tie-break via head.next. DLL insert, DLL remove, "
        "frequency update, HashMap lookup all O(1).\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "minfreq" in reason.lower() or "min freq" in reason.lower()


# ---------------------------------------------------------------------------
# 4. Missing O(1) proof components
# ---------------------------------------------------------------------------
def test_missing_o1_proof_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode, freqToList, minFreq. "
        "LRU tie-break via head.next.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.freqToList = {}\n"
            "        self.minFreq = 0\n"
        ) + "\n\n"
        "# Approach\nAll operations are O(1).\n\n"
        "# Complexity\nO(1) per operation.\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "o(1)" in reason.lower() or "proof" in reason.lower()


def test_missing_dll_insert_proof_rejected():
    text = (
        "# Problem Understanding\nDesign LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode, freqToList, minFreq. "
        "LRU tie-break via head.next.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.freqToList = {}\n"
            "        self.minFreq = 0\n"
        ) + "\n\n"
        "# Approach\nHashMap lookup is O(1). DLL remove via unlink is O(1). "
        "Frequency update moves node to next bucket.\n\n"
        "# Complexity\nO(1): HashMap lookup, DLL remove, frequency update.\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "insert" in reason.lower()


# ---------------------------------------------------------------------------
# 5. Duplicate sections
# ---------------------------------------------------------------------------
def test_duplicate_complexity_section_rejected():
    text = LFU_GOOD + "\n\n# Complexity\n- Time: O(1)\n"
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "complexity" in reason.lower()


def test_duplicate_code_section_rejected():
    text = LFU_GOOD + "\n\n# Code\n" + _f("def foo(): pass") + "\n"
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "code" in reason.lower()


def test_duplicate_edge_cases_section_rejected():
    text = LFU_GOOD + "\n\n# Edge Cases\n- Another edge case.\n"
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "edge" in reason.lower()


# ---------------------------------------------------------------------------
# 6. Template fragments
# ---------------------------------------------------------------------------
def test_template_fragment_rejected():
    text = LFU_GOOD + "\n\n# Notes\n<explanation>\n"
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "template" in reason.lower()


def test_placeholder_fragment_rejected():
    text = LFU_GOOD.replace(
        "Design an O(1) LFU cache with get and put operations.",
        "Design an O(1) LFU cache. [insert your explanation here]",
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "template" in reason.lower()


# ---------------------------------------------------------------------------
# 7. Specific LFU test scenarios
# ---------------------------------------------------------------------------
def test_capacity_zero_handling():
    """capacity=0 must be handled — the good solution handles it."""
    # LFU_GOOD already handles capacity=0 in put()
    assert "cap == 0" in LFU_GOOD or "capacity == 0" in LFU_GOOD


def test_frequency_tie_scenario():
    """When two keys have the same frequency, LRU tie-break must be mentioned."""
    # LFU_GOOD mentions LRU tie-break and head.next
    ok, reason = lc.check("implement an lfu cache", LFU_GOOD)
    assert ok is True
    assert "tie" in LFU_GOOD.lower() or "lru" in LFU_GOOD.lower()


def test_lru_tiebreak_eviction_scenario():
    """The good solution evicts head.next (oldest) from minFreq bucket."""
    ok, reason = lc.check("implement an lfu cache", LFU_GOOD)
    assert ok is True
    assert "head.next" in LFU_GOOD


def test_sentinel_eviction_bug_scenario():
    """A solution using dummy/sentinel for eviction must be rejected."""
    text = LFU_GOOD.replace(
        "evicted = dll.head.next  # oldest node",
        "evicted = self.dummy.next  # sentinel-based bug",
    ).replace(
        "head.next is the oldest (LRU)",
        "dummy.next is the oldest",
    ).replace(
        "and tail.prev is the newest.",
        "",
    ).replace(
        "head.next is oldest, tail.prev is newest",
        "dummy.next is oldest",
    ).replace(
        "to tail.prev in O(1)",
        "to the list in O(1)",
    ).replace(
        "evicts head.next (oldest)",
        "evicts dummy.next (oldest)",
    ).replace(
        "Eviction removes head.next from the",
        "Eviction removes dummy.next from the",
    ).replace(
        "Evict LRU from minFreq bucket: head.next is oldest",
        "Evict from minFreq bucket: dummy.next is oldest",
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "dummy" in reason.lower() or "sentinel" in reason.lower()


def test_duplicate_response_assembly_scenario():
    """A response that duplicates the entire LFU solution must be rejected."""
    text = LFU_GOOD + "\n\n" + LFU_GOOD
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "duplicate" in reason.lower()


# ---------------------------------------------------------------------------
# 8. Node field / structure / scan / bucket-deletion hardening (Phase: LFU v2)
# ---------------------------------------------------------------------------
# A node that omits the DLL pointers (prev/next) entirely — passes the earlier
# eviction / tie-break / component / O(1)-proof checks so node-fields is what fires.
NODE_NO_PTRS = (
    "# Problem Understanding\nDesign an O(1) LFU cache.\n\n"
    "# Optimal Algorithm\nUse keyToNode map, freqToList map, minFreq.\n\n"
    "# Code\n" + _f(
        "class Node:\n"
        "    def __init__(self, key, value):\n"
        "        self.key = key\n"
        "        self.value = value\n"
        "        self.freq = 1\n"
        "class LFUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.keyToNode = {}\n"
        "        self.freqToList = {}\n"
        "        self.minFreq = 0\n"
        "    def evict(self):\n"
        "        bucket = self.freqToList[self.minFreq]\n"
        "        victim = bucket.pop_front()\n"
        "        del self.keyToNode[victim.key]\n"
    ) + "\n\n"
    "# Approach\n"
    "HashMap lookup gives O(1) via keyToNode. DLL insert and DLL remove are O(1). "
    "Frequency update moves a node to the following bucket. When several keys share "
    "the minimum frequency we evict the least recently used (LRU tie-break).\n\n"
    "# Complexity\nO(1): HashMap lookup, DLL insert, DLL remove, frequency update.\n"
)


def test_node_missing_prev_next_rejected():
    ok, reason = lc.check("implement an lfu cache", NODE_NO_PTRS)
    assert ok is False
    assert "prev" in reason.lower() and "next" in reason.lower()


def test_priorityqueue_rejected():
    text = LFU_GOOD.replace(
        "        self.minFreq = 0\n",
        "        self.minFreq = 0\n"
        "        import heapq\n"
        "        self.heap = []  # PriorityQueue of freqs\n",
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "priorityqueue" in reason.lower() or "heap" in reason.lower()


def test_treemap_rejected():
    text = LFU_GOOD.replace(
        "        self.minFreq = 0\n",
        "        self.minFreq = 0\n"
        "        self.buckets = TreeMap()  # sorted by frequency\n",
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "treemap" in reason.lower()


def test_frequency_scan_rejected():
    text = LFU_GOOD.replace(
        "            dll = self.freqToList[self.minFreq]\n",
        "            self.minFreq = min(self.freqToList.keys())\n"
        "            dll = self.freqToList[self.minFreq]\n",
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "scan" in reason.lower() or "o(n)" in reason.lower()


# Deletes a frequency bucket unconditionally (no emptiness guard). Carries full
# node fields so node-fields/structure/scan all pass and bucket-delete fires.
BUCKET_DEL_BAD = (
    "# Problem Understanding\nDesign an O(1) LFU cache.\n\n"
    "# Optimal Algorithm\nUse keyToNode, freqToList, minFreq with DLL buckets.\n\n"
    "# Code\n" + _f(
        "class Node:\n"
        "    def __init__(self, key, value):\n"
        "        self.key = key\n"
        "        self.value = value\n"
        "        self.freq = 1\n"
        "        self.prev = None\n"
        "        self.next = None\n"
        "class LFUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.keyToNode = {}\n"
        "        self.freqToList = {}\n"
        "        self.minFreq = 0\n"
        "    def _bump(self, node):\n"
        "        old = node.freq\n"
        "        self.freqToList[old].remove(node)\n"
        "        del self.freqToList[old]            # drop bucket unconditionally\n"
        "        node.freq = node.freq + 1\n"
        "        self.freqToList.setdefault(node.freq, DLL()).append(node)\n"
    ) + "\n\n"
    "# Approach\n"
    "HashMap lookup via keyToNode is O(1). DLL insert appends at tail.prev. DLL remove "
    "unlinks via prev/next pointers. Frequency update moves the node to the next bucket. "
    "We evict the least recently used (LRU tie-break) at head.next when frequencies tie.\n\n"
    "# Complexity\nO(1): HashMap lookup, DLL insert, DLL remove, frequency update.\n"
)


def test_bucket_delete_non_empty_rejected():
    ok, reason = lc.check("implement an lfu cache", BUCKET_DEL_BAD)
    assert ok is False
    assert "bucket" in reason.lower() and "empty" in reason.lower()


def test_duplicate_template_rejected():
    # Exact corruption from the report: Optimal Algorithm + Code appear twice.
    text = LFU_GOOD + (
        "\n\n# Optimal Algorithm\nUse keyToNode, freqToList, minFreq again.\n\n"
        "# Code\n" + _f("def extra():\n    return None") + "\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "duplicate" in reason.lower()


def test_lru_tiebreak_absent_rejected():
    # No LRU tie-break anywhere: full data structures but no tie-break rule.
    text = (
        "# Problem Understanding\nDesign an O(1) LFU cache.\n\n"
        "# Optimal Algorithm\nUse keyToNode, freqToList, minFreq.\n\n"
        "# Code\n" + _f(
            "class LFUCache:\n"
            "    def __init__(self, cap):\n"
            "        self.keyToNode = {}\n"
            "        self.freqToList = {}\n"
            "        self.minFreq = 0\n"
        ) + "\n\n"
        "# Approach\n"
        "HashMap lookup is O(1). DLL insert and DLL remove are O(1). Frequency update "
        "increments minFreq incrementally.\n\n"
        "# Complexity\nO(1) per operation.\n"
    )
    ok, reason = lc.check("implement an lfu cache", text)
    assert ok is False
    assert "tie" in reason.lower() or "recently" in reason.lower() or "lru" in reason.lower()


def test_dsa_critic_rejects_java_lfu_compile_error():
    """A Java LFU whose Node lacks prev/next must be rejected before any LLM call."""
    import dsa_critic
    import brain_manager
    original_ask = brain_manager.ask
    called = {"llm": False}

    def _spy_ask(*a, **kw):
        called["llm"] = True
        return "VERIFIED", "fake"

    brain_manager.ask = _spy_ask
    try:
        code = (
            "import java.util.HashMap;\n"
            "import java.util.Map;\n"
            "public class LFUCache {\n"
            "    class Node {\n"
            "        int key;\n"
            "        int value;\n"
            "        int freq;\n"
            "    }\n"
            "    Map<Integer, Node> keyToNode = new HashMap<>();\n"
            "    int minFreq;\n"
            "    void evict() {\n"
            "        Node node = keyToNode.get(minFreq);\n"
            "        node.prev.next = node.next;\n"
            "    }\n"
            "}"
        )
        answer = (
            "# Problem Understanding\nDesign an O(1) LFU cache.\n\n"
            "# Optimal Algorithm\nkeyToNode, freqToList, minFreq with DLL buckets.\n\n"
            "# Code\n" + _f(code, "java") + "\n\n"
            "# Approach\nLRU tie-break at head.next. HashMap lookup, DLL insert, "
            "DLL remove, frequency update are O(1).\n\n"
            "# Complexity\nO(1) per operation.\n"
        )
        result = dsa_critic.critique("implement an lfu cache in java", answer)
        assert result["verified"] is False
        assert not called["llm"]
        fb = result["feedback"].lower()
        assert "prev" in fb or "next" in fb or "compile" in fb
    finally:
        brain_manager.ask = original_ask


# ---------------------------------------------------------------------------
# Individual detector unit tests
# ---------------------------------------------------------------------------
def test_bad_eviction_detector_sentinel():
    text = "# Code\n" + _f("node = self.dummy.next\n")
    bad, good = lc.bad_eviction_pattern(text)
    assert bad is not None
    assert "dummy" in bad.lower()
    assert good is False


def test_bad_eviction_detector_good_pattern():
    text = "# Code\n" + _f("node = dll.head.next\n")
    bad, good = lc.bad_eviction_pattern(text)
    assert good is True


def test_missing_lru_tiebreak_detector():
    text = "# Code\n" + _f("pass") + "\n# Complexity\nO(1)\n"
    assert lc.missing_lru_tiebreak(text) is True


def test_missing_lfu_components_detector():
    text = "# Code\n" + _f("pass") + "\n"
    missing = lc.missing_lfu_components(text)
    assert "keyToNode map" in missing
    assert "freqToList map" in missing
    assert "minFreq tracking" in missing


def test_missing_o1_proof_detector():
    text = "# Complexity\nO(1)\n"
    missing = lc.missing_o1_proof(text)
    assert len(missing) == 4


def test_duplicate_major_section_detector():
    text = "# Complexity\nA\n\n# Complexity\nB\n"
    assert lc.duplicate_major_section(text) == "Complexity"


def test_template_fragment_detector():
    text = "# Section\n<explanation>\n"
    assert lc.template_fragment(text) is not None


# ---------------------------------------------------------------------------
# Wiring test: dsa_critic.critique calls lfu_critic
# ---------------------------------------------------------------------------
def test_dsa_critic_wiring_rejects_bad_lfu():
    """dsa_critic.critique must reject a bad LFU solution without LLM call."""
    import dsa_critic
    import brain_manager
    original_ask = brain_manager.ask
    called = {"llm": False}

    def _spy_ask(*a, **kw):
        called["llm"] = True
        return "VERIFIED", "fake"

    brain_manager.ask = _spy_ask
    try:
        text = (
            "# Problem Understanding\nDesign LFU cache.\n\n"
            "# Optimal Algorithm\nUse sentinel for eviction.\n\n"
            "# Code\n" + _f(
                "class LFUCache:\n"
                "    def evict(self):\n"
                "        node = self.dummy.next\n"
                "        self.remove(node)\n"
            ) + "\n\n"
            "# Approach\nSentinel-based eviction.\n\n"
            "# Complexity\nO(1)\n"
        )
        result = dsa_critic.critique("implement an lfu cache", text)
        assert result["verified"] is False
        assert not called["llm"]  # must be rejected before LLM
    finally:
        brain_manager.ask = original_ask


def test_dsa_critic_wiring_accepts_good_lfu():
    """dsa_critic.critique must accept a good LFU solution (LLM call happens)."""
    import dsa_critic
    import brain_manager
    original_ask = brain_manager.ask
    brain_manager.ask = lambda *a, **kw: ("VERIFIED", "fake")
    try:
        result = dsa_critic.critique("implement an lfu cache", LFU_GOOD)
        assert result["verified"] is True
    finally:
        brain_manager.ask = original_ask
