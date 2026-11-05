"""AST-aware DSA complexity validator (Phase 5 + Phase 6).

Deterministically detects the classic "claimed complexity does not match the
implementation" anti-patterns BEFORE the LLM critic runs, so they are caught
reliably and cheaply. Covered canonical problems / anti-patterns:

  * Sliding Window Median claiming O(n log k) but removing an arbitrary element
    from a heap / PriorityQueue in O(k)  -> must use Two Heaps + Lazy Deletion.
  * Fake lazy deletion: claims lazy deletion yet calls heap.remove(element).
  * LFU Cache claiming O(1) but scanning the frequency map for the minimum.
  * LRU Cache claiming O(1) but scanning to find the least-recently-used entry.
  * Median from a data stream claiming O(log n) but sorting / insort each op.
  * Segment Tree claiming O(log n) query but doing a linear range aggregation.
  * Trie problem that scans a word list / uses startswith instead of a trie.
  * Union-Find claiming inverse-Ackermann/O(1) without path compression (or
    doing BFS/DFS for connectivity).
  * Dijkstra claiming O(E log V) with no priority queue (=> O(V^2)).
  * A* with no admissible heuristic (f = g + h).
  * Topological sort done with a comparison sort instead of Kahn's / DFS.
  * Generic: O(1) claimed while sorting / scanning a whole collection; and the
    universal O(n)-claim-with-a-comparison-sort check.

The checks are intentionally conservative: they only fire when the problem type,
the claimed complexity, AND the offending implementation pattern all line up, so
correct solutions are never rejected.
"""
import re
import logging

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.DOTALL)


def extract_code_blocks(text: str) -> list:
    """Return the contents of every fenced code block in the text."""
    return [m.group(1) for m in _FENCE.finditer(text or "")]


def _norm(c: str) -> str:
    return re.sub(r"\s+", "", (c or "")).lower()


def extract_time_complexities(text: str) -> list:
    """Return normalized complexity claims that are explicitly tied to TIME.

    Used by detectors that must not be confused by a space-complexity O(...) claim.
    """
    t = text or ""
    claims = []
    for m in re.finditer(r"time\s*complexity[^\n]*?O\(\s*([^)]*?)\s*\)", t, re.IGNORECASE):
        claims.append(_norm(m.group(1)))
    return claims


def extract_claimed_complexities(text: str) -> list:
    """Return normalized complexity claims, preferring those tied to 'time complexity'."""
    claims = extract_time_complexities(text)
    if not claims:
        for m in re.finditer(r"O\(\s*([^)]*?)\s*\)", text or ""):
            claims.append(_norm(m.group(1)))
    return claims


# A comparison-sort library call. Counting/radix/bucket sorts are O(n) and do NOT
# use these APIs, so matching here is a reliable "this is O(n log n)" signal.
_COMPARISON_SORT = re.compile(
    r"(?:\bsorted\s*\(|\.sort\s*\(|Arrays\.sort\b|Collections\.sort\b|"
    r"std::sort\b|\.sort_values\s*\(|\bqsort\s*\()",
    re.IGNORECASE,
)


def _uses_comparison_sort(code: str) -> bool:
    return bool(_COMPARISON_SORT.search(code or ""))


def _heap_var_names(code: str) -> set:
    """Best-effort set of identifiers that refer to a heap / priority queue, across
    Java and Python. Used so we only treat `.remove()` on a HEAP as the O(k)
    anti-pattern — `.remove()` on a HashMap/dict is O(1) and must NOT be flagged."""
    names = set()
    # Java: `PriorityQueue<...> name` and `name = new PriorityQueue<>()`
    for m in re.finditer(r"PriorityQueue\s*<[^>]*>\s+(\w+)", code):
        names.add(m.group(1))
    for m in re.finditer(r"(\w+)\s*=\s*new\s+PriorityQueue", code):
        names.add(m.group(1))
    # Python: `heapq.heappush(name, ...)` / `heappush(name, ...)`
    for m in re.finditer(r"heappush(?:pop)?\s*\(\s*(\w+)", code):
        names.add(m.group(1))
    # Any identifier whose name itself signals a heap/priority queue.
    for m in re.finditer(r"\b(\w*(?:heap|pq)\w*)\b", code, re.IGNORECASE):
        names.add(m.group(1))
    # Drop empties / language keywords that could sneak in.
    return {n for n in names if n and n.lower() not in ("priorityqueue",)}


def _uses_linear_heap_removal(code: str) -> bool:
    """Detect the genuine anti-pattern: removing an ARBITRARY element from a heap /
    priority queue, e.g. `maxHeap.remove(num)` (O(k) in Java, O(k) on a Python list).

    Precise by design:
      * Only flags `.remove(<non-empty-arg>)` on a known HEAP variable.
      * `heap.remove()` with no argument removes the HEAD (O(log n)) -> NOT flagged.
      * `map.remove(key)` / `delayed.remove(x)` on non-heap vars -> NOT flagged
        (this is the legitimate lazy-deletion bookkeeping).
    """
    for name in _heap_var_names(code):
        # <heapvar> . remove ( <something other than just whitespace/')'> )
        if re.search(r"\b" + re.escape(name) + r"\s*\.\s*remove\s*\(\s*[^)\s]", code):
            return True
    return False


def _scans_for_min_freq(code: str) -> bool:
    low = code.lower()
    if "freq" not in low:
        return False
    flat = re.sub(r"\s+", "", low)
    # Correct LFU maintains a minFreq counter incrementally.
    incremental = bool(re.search(r"min_?freq\s*(=|\+=|-=)", low)) or "self.minfreq" in flat
    if incremental:
        return False
    # Anti-pattern: find the minimum frequency by scanning the whole map.
    scans = (
        bool(re.search(r"min\s*\(", low))
        or bool(re.search(r"sorted\s*\(", low))
        or bool(re.search(r"for\s+\w+\s+in\s+[^\n:]*freq", low))
    )
    return scans


# ── Shared detectors for the canonical-algorithm checks (Phase 6) ──────────
_HEAP_API = re.compile(
    r"heappush|heappop|heapify|heapq\.|PriorityQueue|priority[_\s]?queue|"
    r"make_heap|push_heap|pop_heap|\bheap\b",
    re.IGNORECASE,
)
# A min/max over a whole iterable: either `min(iterable)` (no comma => not the scalar
# min(a, b) form) or `min(iterable, key=...)` (the classic "scan for the smallest" idiom).
_ITER_MINMAX = re.compile(
    r"\b(?:min|max)\s*\(\s*[^,)]+\)|\b(?:min|max)\s*\(\s*[\w.]+\s*,\s*key\s*=")
_SORTED_CALL = re.compile(r"\bsorted\s*\(|\.sort\s*\(")


def _uses_heap(code: str) -> bool:
    return bool(_HEAP_API.search(code or ""))


def _uses_ordered_struct(code: str) -> bool:
    """True if the code uses an O(1)-recency structure: OrderedDict / LinkedHashMap /
    a doubly linked list (prev & next), or the classic move-to-head helpers."""
    c = code or ""
    if re.search(r"OrderedDict|LinkedHashMap", c):
        return True
    if re.search(r"doubly[\s_-]*linked", c, re.IGNORECASE):
        return True
    if re.search(r"move_to_end|move_to_front|moveToHead|addToHead|removeNode|_remove\b|_add\b", c):
        return True
    # Both prev and next pointers referenced => a doubly linked list.
    if re.search(r"\.prev\b|\bprev\s*=", c) and re.search(r"\.next\b|\bnext\s*=", c):
        return True
    return False


def _is_pure_log(c: str) -> bool:
    """True for a pure logarithmic claim (logn / logk / logv), NOT an n-log-n product."""
    if "log" not in c:
        return False
    return not re.search(r"[nkvem]\s*\*?\s*log|[nkvem]log", c)


def _scans_for_recency(code: str) -> bool:
    """A scan used to find the least-recently-used / oldest entry — incompatible with O(1)."""
    c = code or ""
    if _SORTED_CALL.search(c) or _ITER_MINMAX.search(c) or re.search(r"\.index\s*\(", c):
        return True
    return bool(re.search(r"for\s+\w+\s+in\s+[^\n:]*(?:time|stamp|count|order|lru|oldest|recent)",
                          c, re.IGNORECASE))


def _find_body_py(code: str) -> str:
    """Best-effort body of a Python `def find(...)` up to the next def / dedent."""
    m = re.search(r"def\s+find\s*\([^)]*\)\s*:(.*?)(?:\n\s*def\s|\Z)", code or "", re.DOTALL)
    return m.group(1) if m else ""


def _find_has_path_compression(code: str) -> bool:
    """True if find() reassigns a parent pointer (path compression / halving) or recurses
    with `parent[x] = find(...)`. Conservative: if we cannot isolate find(), assume True."""
    body = _find_body_py(code)
    if not body:
        return True  # cannot isolate -> never falsely flag
    # parent[x] ... = (incl. tuple/iterative compression) OR a recursive find() assignment.
    return bool(re.search(r"parent\s*\[\s*\w+\s*\][^\n=]*=|=\s*(?:self\.)?find\s*\(",
                          body, re.IGNORECASE))


_RANGE_LOOP = re.compile(r"for\s+\w+\s+in\s+range\s*\(", re.IGNORECASE)
_AGG_OP = re.compile(r"\+=|sum\s*\(|\btotal\b", re.IGNORECASE)
_SLICE_AGG = re.compile(r"sum\s*\(\s*\w+\s*\[[^\]]*:[^\]]*\]\s*\)")
_SEGTREE_HALLMARK = re.compile(r"2\s*\*\s*\w*node|\w*node\s*\*\s*2|<<\s*1|\bmid\b\s*=", re.IGNORECASE)


def _linear_range_aggregation(code: str) -> bool:
    """A linear range loop/slice that aggregates (the O(n) anti-pattern for a segment tree)."""
    c = code or ""
    if _SLICE_AGG.search(c):
        return True
    return bool(_RANGE_LOOP.search(c) and _AGG_OP.search(c))


def _detect_sliding_window_median(q, code, claims, response_text):
    """SWM claiming logarithmic time but removing an arbitrary element from a heap."""
    if "median" in q and ("sliding" in q or "window" in q):
        if any("log" in c for c in claims) and _uses_linear_heap_removal(code):
            return False, (
                "The code calls PriorityQueue/heap.remove(element) inside the sliding "
                "window, which is O(k) per step -> O(n*k) overall, NOT the claimed "
                "O(n log k). Rewrite using TWO HEAPS + LAZY DELETION: keep a max-heap "
                "for the lower half and a min-heap for the upper half; maintain a "
                "HashMap<Integer,Integer> of 'delayed' (to-be-removed) elements; only "
                "offer/poll/peek the heaps and prune invalid heads lazily; rebalance so "
                "the size difference is <= 1. NEVER call heap.remove(element). "
                "Target: O(n log k) time, O(k) space."
            )
    return True, ""


def _detect_lfu_scan(q, code, claims, response_text):
    """LFU cache claiming O(1) but scanning the frequency map for the minimum."""
    if "lfu" in q:
        if any(c == "1" for c in claims) and _scans_for_min_freq(code):
            return False, (
                "Claims O(1) but scans the frequency map to find the minimum "
                "frequency. Maintain `minFreq` incrementally (update it on get/put) "
                "for true O(1) get and put."
            )
    return True, ""


def _detect_sort_vs_linear(q, code, claims, response_text):
    """Universal: the ONLY stated time complexity is O(n), yet the code uses a
    comparison sort (which is O(n log n)). Conservative — fires only when the time
    claim set is exactly {n}, so a correctly stated O(n log n) is never flagged."""
    time_claims = set(extract_time_complexities(response_text))
    if time_claims == {"n"} and _uses_comparison_sort(code):
        return False, (
            "Claims O(n) time but the code performs a comparison sort "
            "(sorted()/sort()/Arrays.sort), which is O(n log n). Either state the "
            "correct O(n log n), or replace the sort with an O(n) technique "
            "(hashing, counting/bucket sort, or two pointers)."
        )
    return True, ""


def _detect_fake_lazy_deletion(q, code, claims, response_text):
    """Claims lazy deletion but actually calls heap.remove(element) — the very O(k)
    operation lazy deletion exists to avoid."""
    low = (response_text or "").lower()
    mentions_lazy = ("lazy deletion" in low or "lazy delete" in low
                     or ("lazil" in low and "delet" in low))
    if mentions_lazy and _uses_linear_heap_removal(code):
        return False, (
            "The solution claims LAZY DELETION but actually calls heap.remove(element) / "
            "PriorityQueue.remove(x) — the O(k) operation lazy deletion exists to avoid. Real "
            "lazy deletion NEVER removes an arbitrary element: keep a `delayed`/`removed` count "
            "map, only offer/poll/peek the heaps, and discard stale heads when they surface."
        )
    return True, ""


def _detect_lru_scan(q, code, claims, response_text):
    """LRU cache claiming O(1) but scanning to find the least-recently-used entry."""
    if "lru" in q or "least recently used" in q:
        if any(c == "1" for c in claims) and not _uses_ordered_struct(code) and _scans_for_recency(code):
            return False, (
                "Claims O(1) get/put for an LRU cache but uses no O(1) recency structure and "
                "scans to find the LRU entry. Use a HashMap + doubly linked list (move the "
                "accessed node to the head, evict the tail) or an OrderedDict with move_to_end — "
                "both give true O(1) get and put."
            )
    return True, ""


def _detect_median_stream(q, code, claims, response_text):
    """Streaming-median claiming O(log n) add but sorting / insort-ing each operation."""
    is_stream = "median" in q and ("stream" in q or "median finder" in q or "medianfinder" in q)
    if is_stream and not ("sliding" in q or "window" in q):
        log_or_const = any(_is_pure_log(c) or c == "1" for c in claims)
        sorts = _uses_comparison_sort(code) or bool(re.search(r"\binsort\b|bisect\.insort", code))
        if log_or_const and sorts:
            return False, (
                "Claims O(log n) addNum / O(1) findMedian for a streaming median but sorts or "
                "inserts into a sorted list each operation (O(n) or O(n log n)). Use TWO HEAPS: a "
                "max-heap for the lower half and a min-heap for the upper half, balanced so their "
                "sizes differ by <= 1 -> O(log n) addNum, O(1) findMedian."
            )
    return True, ""


def _detect_segment_tree_linear(q, code, claims, response_text):
    """Segment-tree claiming O(log n) query but doing a linear range aggregation."""
    if "segment tree" in q or "segtree" in q:
        if any("log" in c for c in claims) and _linear_range_aggregation(code) \
                and not _SEGTREE_HALLMARK.search(code):
            return False, (
                "Claims O(log n) range query for a segment tree but aggregates the range with a "
                "linear loop / slice (O(n)). Build a real segment tree: recurse over node "
                "children (2*node, 2*node+1) splitting at mid, combining child results — query "
                "and update are O(log n)."
            )
    return True, ""


def _detect_trie_scan(q, code, claims, response_text):
    """Trie problem that actually scans a word list / uses startswith instead of a trie."""
    if "trie" in q or "prefix tree" in q:
        has_node = bool(re.search(
            r"children|child\b|TrieNode|defaultdict\s*\(|\blinks\b|next\s*\[|\bis_end\b|isEnd",
            code, re.IGNORECASE))
        # Iterating a WORD LIST (plural) or using startswith == scanning, not a trie.
        # `for ch in word` (singular, iterating characters) is normal and must NOT match.
        scans = bool(re.search(r"\.startswith\s*\(", code)) or bool(re.search(
            r"for\s+\w+\s+in\s+(?:\w*\.)?(?:words|word_list|wordlist|wordList|dictionary|word_set)\b",
            code, re.IGNORECASE))
        if not has_node and scans:
            return False, (
                "This does not implement a Trie: it scans a word list / uses startswith, which is "
                "O(N*L) per query. Build a real Trie — each node holds a children map (or "
                "array[26]) and an is_end flag; insert and prefix-search are O(L) in the word length."
            )
    return True, ""


def _detect_union_find_naive(q, code, claims, response_text):
    """Union-Find claiming inverse-Ackermann/O(1) without path compression, or doing
    BFS/DFS for connectivity."""
    if any(k in q for k in ("union find", "union-find", "disjoint set", "dsu")):
        near_const = any((("\u03b1" in c) or ("alpha" in c) or ("ackermann" in c) or c == "1")
                         for c in claims)
        if not near_const:
            return True, ""
        has_dsu = bool(re.search(r"\bparent\b|\bunion\s*\(|\bfind\s*\(", code, re.IGNORECASE))
        traversal = bool(re.search(r"\bbfs\b|\bdfs\b|deque\s*\(|collections\.deque|\.popleft\s*\(",
                                   code, re.IGNORECASE))
        if traversal and not has_dsu:
            return False, (
                "Claims near-O(1)/inverse-Ackermann but implements connectivity with BFS/DFS "
                "(O(V+E) per query). Use a real Union-Find (DSU): path compression in find() and "
                "union by rank/size give ~O(alpha(n)) amortized per operation."
            )
        if re.search(r"def\s+find\s*\(", code) and not _find_has_path_compression(code):
            return False, (
                "Claims O(1)/inverse-Ackermann for Union-Find but find() has no PATH COMPRESSION, "
                "so it is not amortized near-constant. Compress on the way up "
                "(parent[x] = find(parent[x])) and use union by rank/size."
            )
    return True, ""


def _detect_dijkstra_no_heap(q, code, claims, response_text):
    """Dijkstra claiming a log factor but using no priority queue (=> O(V^2))."""
    if "dijkstra" in q:
        if any("log" in c for c in claims) and not _uses_heap(code):
            return False, (
                "Claims O(E log V) for Dijkstra but uses no priority queue/heap — a linear "
                "min-distance scan makes it O(V^2). Use a min-heap (heapq / PriorityQueue) keyed "
                "by tentative distance, popping the closest unsettled vertex."
            )
    return True, ""


def _detect_astar_no_heuristic(q, code, claims, response_text):
    """A* with no heuristic (f = g + h) is just Dijkstra/BFS, not A*."""
    if re.search(r"\ba\*|a[-\s]?star\b|\bastar\b", q):
        has_heuristic = bool(re.search(
            r"heuristic|admissible|g\s*\+\s*h|f\s*=\s*g\s*\+\s*h|manhattan|euclidean|"
            r"f_?score|h_?score|\bh\s*\(|estimate|priority\s*=\s*[^\n]*\+",
            code, re.IGNORECASE))
        if not has_heuristic:
            return False, (
                "This is not A*: there is no admissible heuristic. A* prioritizes nodes by "
                "f = g + h (cost so far + heuristic estimate to the goal) using a min-heap. Add a "
                "heuristic (e.g., Manhattan/Euclidean) and push f-scores onto the priority queue."
            )
    return True, ""


def _detect_toposort_sorted(q, code, claims, response_text):
    """A comparison sort does not produce a valid topological order."""
    if "topolog" in q or "topo sort" in q:
        kahn = bool(re.search(r"indegree|in_degree|in-degree", code, re.IGNORECASE))
        if _uses_comparison_sort(code) and not kahn:
            return False, (
                "A comparison sort does NOT produce a valid topological order. Use Kahn's "
                "algorithm (compute in-degrees, repeatedly dequeue zero-indegree nodes) or DFS "
                "post-order with a visited set and cycle detection. Target O(V+E)."
            )
    return True, ""


def _detect_o1_hidden_scan(q, code, claims, response_text):
    """Generic: the ONLY stated time is O(1), yet the code sorts or does min/max over a
    whole collection (both > O(1))."""
    time_claims = set(extract_time_complexities(response_text))
    if time_claims == {"1"} and (_SORTED_CALL.search(code) or _ITER_MINMAX.search(code)):
        return False, (
            "Claims O(1) time but the code sorts or scans a whole collection (sorted()/min()/"
            "max() over an iterable), which is at least O(n). Either maintain the value "
            "incrementally (e.g., a counter / auxiliary structure) or correct the complexity."
        )
    return True, ""


# Ordered list of deterministic detectors. Each returns (ok, reason); the first
# failure wins. New checks can be appended without touching `analyze`. More specific
# detectors run before the generic ones so their feedback wins.
_DETECTORS = (
    _detect_sliding_window_median,
    _detect_lfu_scan,
    _detect_fake_lazy_deletion,
    _detect_lru_scan,
    _detect_median_stream,
    _detect_segment_tree_linear,
    _detect_trie_scan,
    _detect_union_find_naive,
    _detect_dijkstra_no_heap,
    _detect_astar_no_heuristic,
    _detect_toposort_sorted,
    _detect_o1_hidden_scan,
    _detect_sort_vs_linear,
)


def analyze(user_query: str, response_text: str):
    """Return (ok: bool, reason: str). ok=False => claimed complexity mismatches code."""
    q = (user_query or "").lower()
    code = "\n\n".join(extract_code_blocks(response_text))
    if not code:
        return True, ""

    claims = extract_claimed_complexities(response_text)
    for detector in _DETECTORS:
        ok, reason = detector(q, code, claims, response_text)
        if not ok:
            logger.warning(f"[DSA_COMPLEXITY] {detector.__name__}: {reason}")
            return False, reason

    return True, ""
