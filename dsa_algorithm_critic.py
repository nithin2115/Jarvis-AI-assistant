"""DSA Algorithm Critic (Phase 2 extension).

Deterministic, no-LLM gate for algorithm-specific DSA solutions that are NOT
already covered by lfu_critic.py or dsa_complexity.py. Handles:
  - Sliding Window Median
  - LRU Cache
  - Trie
  - Segment Tree
  - Fenwick Tree (Binary Indexed Tree)
  - Union Find (Disjoint Set Union)
  - Rate Limiter
  - Top-K / Kth-largest (optimality: heap / quickselect / bucket, not full sort)

Note: Dijkstra, A*, two-heap median stream, and topological sort optimality are
enforced separately by dsa_complexity.py (claimed-vs-actual complexity).

Gated: only fires when the user query matches the relevant algorithm AND the
response ships code (mirrors dsa_structure.is_solution_attempt).

Fail-safe: conceptual / non-targeted queries always pass. On exception, passes.
"""
import re
import logging

import dsa_structure as ds

logger = logging.getLogger(__name__)

_FENCE = ds._FENCE


# ── Query gating regexes ─────────────────────────────────────────────────────
_ALGO_GATES = {
    "sliding_window_median": re.compile(
        r"\bsliding\s+window\s+median\b|median\s+in\s+sliding\s+window|"
        r"\bsliding\s+window\s+.*median\b",
        re.IGNORECASE,
    ),
    "lru_cache": re.compile(
        r"\blru\s+cache\b|least\s+recently\s+used\s+cache|lru\b",
        re.IGNORECASE,
    ),
    "trie": re.compile(
        r"\btrie\b|prefix\s+tree|implement\s+trie",
        re.IGNORECASE,
    ),
    "segment_tree": re.compile(
        r"\bsegment\s+tree\b|range\s+query\s+.*segment|range\s+sum\s+.*mutable\b|"
        r"\blazy\s+propagation\b",
        re.IGNORECASE,
    ),
    "union_find": re.compile(
        r"\bunion\s+find\b|disjoint\s+set\b|dsu\b|union\s+by\s+rank\b|"
        r"path\s+compression\b",
        re.IGNORECASE,
    ),
    "fenwick": re.compile(
        r"\bfenwick\b|binary\s+indexed\s+tree|\bfenwick\s+tree\b",
        re.IGNORECASE,
    ),
    "top_k": re.compile(
        r"\bkth\s+largest\b|\bkth\s+smallest\b|\btop\s+k\b|\btop-k\b|"
        r"\bk\s+most\s+frequent\b|\bk\s+largest\b|\bk\s+smallest\b|"
        r"\bk\s+closest\b",
        re.IGNORECASE,
    ),
    "rate_limiter": re.compile(
        r"\brate\s+limiter\b|rate\s+limit\b|token\s+bucket\b|sliding\s+window\s+log\b|"
        r"fixed\s+window\s+rate\b|leaky\s+bucket\b",
        re.IGNORECASE,
    ),
}


# ── Sliding Window Median ──────────────────────────────────────────────────
_SW_MEDIAN_BAD_RE = re.compile(
    r"\bheap\.remove\s*\(|\bmaxheap\.remove\s*\(|\bminheap\.remove\s*\("
    r"|\bpriorityqueue\b.*\.remove\s*\(|\bheapify\s*\(|\bremove\s*\(.*heap",
    re.IGNORECASE,
)
_SW_MEDIAN_TWO_HEAPS_RE = re.compile(
    r"\btwo\s*heaps\b|\bmax\s*heap\b|\bmin\s*heap\b|"
    r"\bsmall\s*heap\b|\blarge\s*heap\b|"
    r"\blower\s*half\b|\bupper\s*half\b",
    re.IGNORECASE,
)
_SW_MEDIAN_LAZY_RE = re.compile(
    r"\b(?:delayed|lazy)\s*(?:map|dict|hash|set|deletion)|"
    r"\bdelayed\b.*\bmap\b|\blazy\s*deletion\b|"
    r"\bprune\b.*\bheap\b",
    re.IGNORECASE,
)
_SW_MEDIAN_HEAP_OPS_RE = re.compile(
    r"\b(?:offer|poll|peek|add\s*\(|push\s*\(|pop\s*\(|top\s*\()",
    re.IGNORECASE,
)


def sliding_window_median_check(text):
    """Return (ok, reason)."""
    if _SW_MEDIAN_BAD_RE.search(text):
        return False, (
            "Sliding Window Median rejected: removes from a heap directly "
            "(use lazy deletion with a delayed map + offer/poll/peek)."
        )
    has_two_heaps = _SW_MEDIAN_TWO_HEAPS_RE.search(text)
    has_lazy = _SW_MEDIAN_LAZY_RE.search(text)
    has_heap_ops = _SW_MEDIAN_HEAP_OPS_RE.search(text)
    if not (has_two_heaps and has_lazy and has_heap_ops):
        return False, (
            "Sliding Window Median rejected: requires two heaps, lazy deletion "
            "(delayed map), and offer/poll/peek operations."
        )
    return True, ""


# ── LRU Cache ──────────────────────────────────────────────────────────────
_LRU_BAD_RE = re.compile(
    r"\b(list\.head|list\.tail|dummy|sentinel)\b",
    re.IGNORECASE,
)
_LRU_GOOD_RE = re.compile(
    r"\b(head\.next|tail\.prev|move\s*to\s*front|remove\s*from\s*tail|"
    r"add\s*to\s*front|doubly\s*linked\s*list|dll\b)",
    re.IGNORECASE,
)
# An LRU cache must be O(1) via a hash map + doubly linked list, NEVER a heap.
_LRU_FORBIDDEN_RE = re.compile(
    r"\bpriorityqueue\b|\bheapq\b|\bheappush\b|\bheappop\b|\bheapify\b|"
    r"\bbinary\s*heap\b|\bmin\s*heap\b|\bmax\s*heap\b",
    re.IGNORECASE,
)
_LRU_COMPONENTS = {
    "keyToNode map": re.compile(
        r"keytonode|key\s*->\s*node|key\s*to\s*node|node\s*map|map.*node",
        re.IGNORECASE,
    ),
    "doubly linked list": re.compile(
        r"doubly\s*linked\s*list|dll\b|prev\b|next\b.*tail|head\.next|tail\.prev",
        re.IGNORECASE,
    ),
    "O(1) proof": re.compile(
        r"hash\s*map.*o\(1\)|o\(1\).*hash\s*map|o\(1\).*get|o\(1\).*put|"
        r"move\s*to\s*front.*o\(1\)|constant\s*time",
        re.IGNORECASE,
    ),
}
# A library-backed LRU — Python OrderedDict or Java LinkedHashMap used with the
# O(1) recency primitives — is optimal and MUST be accepted (the manual
# keyToNode + doubly-linked-list components are then not required).
_LRU_LIBRARY_RE = re.compile(
    r"\bordereddict\b|\bmove_to_end\b|popitem\s*\(\s*last\s*=\s*false\s*\)"
    r"|\blinkedhashmap\b|\bremoveeldestentry\b|access[\s_-]*order",
    re.IGNORECASE,
)
# Scanning a timestamp / recency / access map for the oldest key
# (e.g. `min(self.time, key=self.time.get)`) makes get/put O(n), not O(1).
_LRU_SCAN_RE = re.compile(
    r"(?:\bmin\b|\bmax\b|\bsorted\b)\s*\([^)]*"
    r"(?:time|timestamp|clock|recen|last[\s_-]*used|last[\s_-]*access|\baccess)",
    re.IGNORECASE,
)


def lru_cache_check(text):
    """Return (ok, reason)."""
    if _LRU_FORBIDDEN_RE.search(text):
        return False, (
            "LRU Cache rejected: uses a heap / priority queue. An LRU cache must be "
            "O(1) via a hash map + doubly linked list (or OrderedDict / LinkedHashMap), "
            "not a heap (which is O(log n))."
        )
    if _LRU_SCAN_RE.search(text):
        return False, (
            "LRU Cache rejected: scans a timestamp/recency map (min/max/sorted) to find "
            "the least-recently-used key, which is O(n) per operation. Use a doubly linked "
            "list (move-to-front on access, evict the tail) or an OrderedDict/LinkedHashMap."
        )
    # A correct library-backed LRU (OrderedDict / LinkedHashMap) is O(1): accept it
    # without demanding the hand-rolled keyToNode + DLL components.
    if _LRU_LIBRARY_RE.search(text):
        return True, ""
    if _LRU_BAD_RE.search(text) and not _LRU_GOOD_RE.search(text):
        return False, (
            "LRU Cache rejected: eviction uses list.head / list.tail / dummy / "
            "sentinel; use head.next / tail.prev / move-to-front."
        )
    missing = [label for label, rx in _LRU_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"LRU Cache rejected: missing {', '.join(missing)}."
    return True, ""


# ── Trie ─────────────────────────────────────────────────────────────────────
_TRIE_COMPONENTS = {
    "TrieNode class": re.compile(
        r"class\s+trie\s*node|class\s+trienode|struct\s+trie\s*node|"
        r"\bchildren\s*\[\s*\]|\bchildren\s*=\s*\{|trie\s*node\b",
        re.IGNORECASE,
    ),
    "children array/map": re.compile(
        r"children\s*\[\s*26\s*\]|children\s*=\s*\[\s*None\s*\]\s*\*\s*26|"
        r"children\s*=\s*\{\s*\}|children\s*=\s*dict\s*\(|\bchildren\b",
        re.IGNORECASE,
    ),
    "isEnd flag": re.compile(
        r"isend|is_end|isword|is_word|end\s*of\s*word|word_end|eow\b",
        re.IGNORECASE,
    ),
    "insert/search/startsWith": re.compile(
        r"\binsert\b.*\bsearch\b|\bsearch\b.*\bstartsWith\b|"
        r"\bstartsWith\b.*\binsert\b|\binsert\b|\bsearch\b|\bstartsWith\b",
        re.IGNORECASE,
    ),
}


def trie_check(text):
    """Return (ok, reason)."""
    missing = [label for label, rx in _TRIE_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"Trie rejected: missing {', '.join(missing)}."
    return True, ""


# ── Segment Tree ───────────────────────────────────────────────────────────
_SEGTREE_COMPONENTS = {
    "build tree": re.compile(
        r"\bbuild\s*(?:tree|segment)|\bbuild\s*\(|\bsegmenttree\b|"
        r"\bsegment_tree\b",
        re.IGNORECASE,
    ),
    "update operation": re.compile(
        r"\bupdate\s*(?:tree|segment)|\bupdate\s*\(|\bpoint\s*update\b",
        re.IGNORECASE,
    ),
    "query operation": re.compile(
        r"\bquery\s*(?:range|segment)|\bquery\s*\(|\brange\s*query\b|"
        r"\bsumrange\b|\bsum_range\b",
        re.IGNORECASE,
    ),
    "tree representation": re.compile(
        r"\btree\s*\[\s*4\s*\*\s*n\b|tree\s*=\s*\[\s*0\s*\]\s*\*\s*\(?4\s*\*\s*n\)?|"
        r"\bnode\s*class\b.*\b(left|right|sum|val)\b|"
        r"\bleft\s*=\s*2\s*\*\s*i\s*\+\s*1\b",
        re.IGNORECASE,
    ),
}


def segment_tree_check(text):
    """Return (ok, reason)."""
    missing = [label for label, rx in _SEGTREE_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"Segment Tree rejected: missing {', '.join(missing)}."
    return True, ""


# ── Union Find (DSU) ───────────────────────────────────────────────────────
_UF_COMPONENTS = {
    "parent array": re.compile(
        r"parent\s*\[\s*\]|parent\s*=\s*\[\s*\]|self\.parent\b|\bparent\b",
        re.IGNORECASE,
    ),
    "rank/size array": re.compile(
        r"rank\s*\[\s*\]|size\s*\[\s*\]|self\.rank\b|self\.size\b|"
        r"union\s*by\s*rank|union\s*by\s*size",
        re.IGNORECASE,
    ),
    "path compression": re.compile(
        r"path\s*compression|self\.parent\[\s*x\s*\]\s*=\s*self\.parent\[\s*self\.parent\[\s*x\s*\]\s*\]|"
        r"parent\[\s*find\s*\(|parent\[\s*root\s*\]|recursion.*find",
        re.IGNORECASE,
    ),
    "find + union methods": re.compile(
        r"\bdef\s+find\b|\bdef\s+union\b|\bpublic\s+.*\bfind\b|\bpublic\s+.*\bunion\b|"
        r"\bfind\s*\(.*\bunion\s*\(",
        re.IGNORECASE,
    ),
}


def union_find_check(text):
    """Return (ok, reason)."""
    missing = [label for label, rx in _UF_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"Union Find rejected: missing {', '.join(missing)}."
    return True, ""


# ── Rate Limiter ───────────────────────────────────────────────────────────
_RL_BAD_RE = re.compile(
    r"\bthread\.sleep\b|\bsleep\s*\(|\bwhile\s*true\s*\{|\bspin\s*lock\b|"
    r"\bbusy\s*wait\b|\bsynchronized\s*\(.*\).*\bsleep\b",
    re.IGNORECASE,
)
_RL_COMPONENTS = {
    "capacity/burst": re.compile(
        r"\bcapacity\b|\bburst\b|\bmax\s*request|\bthreshold\b|\blimit\b",
        re.IGNORECASE,
    ),
    "window/timestamp tracking": re.compile(
        r"\btimestamp\b|\btime\s*\(\)|\bwindow\b|\bcurrent\s*time\b|"
        r"\bcurrent\s*window\b|\bexpire\b|\bprune\b",
        re.IGNORECASE,
    ),
    "request count/tokens": re.compile(
        r"\btokens\b|\btoken\s*bucket\b|\bcount\b|\brequests\b|\brefill\b|"
        r"\ballow\s*request\b|\bacquire\b",
        re.IGNORECASE,
    ),
    "algorithm": re.compile(
        r"\btoken\s*bucket\b|\bfixed\s*window\b|\bsliding\s*window\b|"
        r"\bleaky\s*bucket\b",
        re.IGNORECASE,
    ),
}


def rate_limiter_check(text):
    """Return (ok, reason)."""
    if _RL_BAD_RE.search(text):
        return False, (
            "Rate Limiter rejected: uses sleep / busy-wait / spin-lock; use a "
            "token bucket, sliding window, or fixed-window counter with timestamps."
        )
    missing = [label for label, rx in _RL_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"Rate Limiter rejected: missing {', '.join(missing)}."
    return True, ""


# ── Fenwick Tree (Binary Indexed Tree) ─────────────────────────────────────
# The DEFINING operation is the lowbit walk `i & -i`. A plain prefix-sum array
# (O(n) update) is NOT a Fenwick tree, so the lowbit signature is mandatory.
_FENWICK_LOWBIT_RE = re.compile(
    r"&\s*\(?\s*-\s*\w+|\blowbit\b|\blow\s*bit\b|i\s*&\s*\(\s*-\s*i\s*\)",
    re.IGNORECASE,
)
_FENWICK_COMPONENTS = {
    "update (point update)": re.compile(
        r"\bdef\s+update\b|void\s+update|\bupdate\s*\(|\bdef\s+add\b|\badd\s*\(",
        re.IGNORECASE,
    ),
    "prefix-sum query": re.compile(
        r"\bdef\s+query\b|\bdef\s+prefix\w*\b|prefix\s*sum|prefixsum|\bquery\s*\(|"
        r"get\s*sum|getsum|\bdef\s+sum\b",
        re.IGNORECASE,
    ),
    "1-indexed tree array": re.compile(
        r"self\.tree\b|self\.bit\b|\btree\s*=\s*\[\s*0\s*\]|\bbit\s*=\s*\[\s*0\s*\]|"
        r"\bn\s*\+\s*1\b|len\s*\([^)]*\)\s*\+\s*1",
        re.IGNORECASE,
    ),
}


def fenwick_check(text):
    """Return (ok, reason)."""
    if not _FENWICK_LOWBIT_RE.search(text):
        return False, (
            "Fenwick/BIT rejected: missing the lowbit operation (i & -i) used to walk "
            "the tree in O(log n). A linear prefix-sum array is not a Fenwick tree."
        )
    missing = [label for label, rx in _FENWICK_COMPONENTS.items() if not rx.search(text)]
    if missing:
        return False, f"Fenwick/BIT rejected: missing {', '.join(missing)}."
    return True, ""


# ── Top-K / Kth-largest ────────────────────────────────────────────────────
# Optimal approaches: a size-K heap (O(n log k)), quickselect (O(n) avg), or a
# bucket/counting sort for top-K-frequent (O(n)). The rejected anti-pattern is
# fully sorting the raw input just to pick K. A "count then sort" over a frequency
# map is tolerated (a common, reasonable answer), so we only reject a full sort
# when neither an optimal structure NOR a frequency map is present.
_TOPK_HEAP_RE = re.compile(
    r"\bheapq\b|heappush|heappop|nlargest|nsmallest|priorityqueue|priority\s+queue|"
    r"\bmin\s*heap\b|\bmax\s*heap\b|\bheap\b",
    re.IGNORECASE,
)
_TOPK_SELECT_RE = re.compile(
    r"quickselect|quick\s+select|\bpartition\b|lomuto|hoare",
    re.IGNORECASE,
)
_TOPK_BUCKET_RE = re.compile(r"\bbucket\b|counting\s+sort", re.IGNORECASE)
_TOPK_FREQ_RE = re.compile(
    r"\bcounter\b|collections\.counter|\bfreq\w*\b|\bfrequency\b|count\s*\[|"
    r"most_common|hash\s*map|hashmap",
    re.IGNORECASE,
)
_TOPK_FULLSORT_RE = re.compile(
    r"\.sort\s*\(|sorted\s*\(|arrays\.sort|collections\.sort",
    re.IGNORECASE,
)


def top_k_check(text):
    """Return (ok, reason)."""
    optimal = (_TOPK_HEAP_RE.search(text) or _TOPK_SELECT_RE.search(text)
               or _TOPK_BUCKET_RE.search(text))
    if optimal:
        return True, ""
    if _TOPK_FULLSORT_RE.search(text) and not _TOPK_FREQ_RE.search(text):
        return False, (
            "Top-K rejected: it fully sorts the input (O(n log n)) just to select K. "
            "Use a size-K heap (O(n log k)) or quickselect (O(n) average); for "
            "top-K-frequent, a bucket/counting sort is O(n)."
        )
    return True, ""


# ── Dispatch ─────────────────────────────────────────────────────────────────

def check(user_query: str, response_text: str):
    """Run the algorithm-specific deterministic critic.

    Returns (ok, reason). Always passes if the query is not a targeted algorithm
    or if no solution attempt is present. Fail-safe on exception.
    """
    try:
        if not ds.is_solution_attempt(user_query, response_text):
            return True, ""

        for algo, gate in _ALGO_GATES.items():
            if gate.search(user_query):
                checker = globals()[f"{algo}_check"]
                ok, reason = checker(response_text)
                if not ok:
                    logger.warning(f"[DSA_ALGORITHM_CRITIC] {algo} REJECTED: {reason}")
                    return False, reason
        return True, ""
    except Exception as e:
        logger.warning(f"[DSA_ALGORITHM_CRITIC] fail-safe passthrough: {e}")
        return True, ""


def critique(user_query: str, response_text: str) -> dict:
    """Convenience wrapper returning {'verified': bool, 'feedback': str}."""
    ok, reason = check(user_query, response_text)
    return {"verified": ok, "feedback": "" if ok else reason}
