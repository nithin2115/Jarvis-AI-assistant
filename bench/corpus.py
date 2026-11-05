"""Curated, focused benchmark corpus — REAL golden + adversarial cases.

Every case is concrete and labelled with the verdict the deterministic pipeline
SHOULD produce. Golden cases must be ACCEPTED; adversarial cases must be REJECTED.
Adversarial cases each isolate a single, named failure mode (the `tags`) so the
benchmark pinpoints *why* an answer fails — or, when a flaw slips through, exposes
a real gap in Jarvis's critics.

No fabricated data: DSA cases are authored from validated patterns; SQL / System
Design / Full Stack cases reuse fixtures already asserted in the test-suite.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

# Router agent identifiers (kept as plain strings to avoid importing router here).
DSA = "DSA_AGENT"
SQL = "SQL_AGENT"
SYSDESIGN = "SYSTEM_DESIGN_AGENT"
FULLSTACK = "FULLSTACK_AGENT"
DEBUG = "DEBUG_AGENT"
REVIEW = "CODE_REVIEW_AGENT"

ACCEPT = "accept"
REJECT = "reject"


@dataclass(frozen=True)
class Case:
    id: str
    agent: str
    query: str
    kind: str           # "golden" | "adversarial"
    expect: str         # ACCEPT | REJECT
    tags: tuple         # failure-mode / category labels
    solution: str       # the answer text scored by the critics
    note: str = ""


# ---------------------------------------------------------------------------
# DSA answer builder
# ---------------------------------------------------------------------------
def _dsa(pu: str, oa: str, code: str, approach: str, complexity: str,
         lang: str = "python", extra: str = "") -> str:
    return (
        f"### Problem Understanding\n{pu}\n\n"
        f"### Optimal Algorithm\n{oa}\n\n"
        f"### Code\n```{lang}\n{code}\n```\n\n"
        f"### Approach\n{approach}\n\n"
        f"### Complexity\n{complexity}\n" + extra
    )


_O1 = "- **Time Complexity:** O(1) per operation\n- **Space Complexity:** O(capacity)\n"


# ── DSA golden answers (must be ACCEPTED) ──────────────────────────────────
_LRU_ORDEREDDICT = _dsa(
    "Implement an LRU cache with O(1) get and put.",
    "OrderedDict: move_to_end on access keeps recency order; popitem(last=False) "
    "evicts the least recently used entry in O(1).",
    "from collections import OrderedDict\n"
    "class LRUCache:\n"
    "    def __init__(self, capacity):\n"
    "        self.cap = capacity\n"
    "        self.cache = OrderedDict()\n"
    "    def get(self, key):\n"
    "        if key not in self.cache:\n"
    "            return -1\n"
    "        self.cache.move_to_end(key)\n"
    "        return self.cache[key]\n"
    "    def put(self, key, value):\n"
    "        if key in self.cache:\n"
    "            self.cache.move_to_end(key)\n"
    "        self.cache[key] = value\n"
    "        if len(self.cache) > self.cap:\n"
    "            self.cache.popitem(last=False)",
    "Each access moves the key to the most-recent end; eviction removes the oldest.",
    _O1,
)

_LRU_MANUAL = _dsa(
    "Implement an LRU cache with O(1) get and put.",
    "Hash map (keyToNode) for O(1) lookup plus a doubly linked list; move touched "
    "nodes to the head and evict the tail.",
    "class Node:\n"
    "    def __init__(self, key=0, val=0):\n"
    "        self.key, self.val, self.prev, self.next = key, val, None, None\n"
    "class LRUCache:\n"
    "    def __init__(self, capacity):\n"
    "        self.cap = capacity\n"
    "        self.keyToNode = {}\n"
    "        self.head = Node(); self.tail = Node()\n"
    "        self.head.next = self.tail; self.tail.prev = self.head\n"
    "    def _add(self, node):\n"
    "        node.prev = self.head; node.next = self.head.next\n"
    "        self.head.next.prev = node; self.head.next = node\n"
    "    def _remove(self, node):\n"
    "        node.prev.next = node.next; node.next.prev = node.prev\n"
    "    def get(self, key):\n"
    "        if key not in self.keyToNode:\n"
    "            return -1\n"
    "        node = self.keyToNode[key]; self._remove(node); self._add(node)\n"
    "        return node.val\n"
    "    def put(self, key, value):\n"
    "        if key in self.keyToNode:\n"
    "            self._remove(self.keyToNode[key])\n"
    "        node = Node(key, value); self.keyToNode[key] = node; self._add(node)\n"
    "        if len(self.keyToNode) > self.cap:\n"
    "            lru = self.tail.prev; self._remove(lru); del self.keyToNode[lru.key]",
    "keyToNode gives O(1) access; the doubly linked list gives O(1) move and evict.",
    _O1,
)

_TWO_SUM = _dsa(
    "Find two indices whose values sum to target.",
    "Single-pass hash map of value -> index.",
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, x in enumerate(nums):\n"
    "        if target - x in seen:\n"
    "            return [seen[target - x], i]\n"
    "        seen[x] = i\n"
    "    return []",
    "For each element check whether its complement was already seen.",
    "- **Time Complexity:** O(n)\n- **Space Complexity:** O(n)\n",
)

_DIJKSTRA_GOOD = _dsa(
    "Single-source shortest paths with non-negative edge weights.",
    "Dijkstra with a binary min-heap keyed by tentative distance.",
    "import heapq\n"
    "def dijkstra(graph, src):\n"
    "    dist = {src: 0}\n"
    "    pq = [(0, src)]\n"
    "    while pq:\n"
    "        d, u = heapq.heappop(pq)\n"
    "        if d > dist.get(u, float('inf')):\n"
    "            continue\n"
    "        for v, w in graph[u]:\n"
    "            nd = d + w\n"
    "            if nd < dist.get(v, float('inf')):\n"
    "                dist[v] = nd\n"
    "                heapq.heappush(pq, (nd, v))\n"
    "    return dist",
    "Pop the closest unsettled node, relax its edges, push improved distances.",
    "- **Time Complexity:** O(E log V)\n- **Space Complexity:** O(V)\n",
)

_DSU_GOOD = _dsa(
    "Maintain disjoint sets with union and connectivity queries.",
    "Union-Find with path compression in find and union by rank.",
    "class DSU:\n"
    "    def __init__(self, n):\n"
    "        self.parent = list(range(n)); self.rank = [0] * n\n"
    "    def find(self, x):\n"
    "        if self.parent[x] != x:\n"
    "            self.parent[x] = self.find(self.parent[x])\n"
    "        return self.parent[x]\n"
    "    def union(self, a, b):\n"
    "        ra, rb = self.find(a), self.find(b)\n"
    "        if ra == rb:\n"
    "            return\n"
    "        if self.rank[ra] < self.rank[rb]:\n"
    "            ra, rb = rb, ra\n"
    "        self.parent[rb] = ra\n"
    "        if self.rank[ra] == self.rank[rb]:\n"
    "            self.rank[ra] += 1",
    "Path compression flattens trees; union by rank keeps them shallow.",
    "- **Time Complexity:** O(alpha(n)) amortized per op\n- **Space Complexity:** O(n)\n",
)


# ── DSA adversarial answers (must be REJECTED — one isolated flaw each) ─────
_LRU_TIMESTAMP_SCAN = _dsa(
    "Implement an LRU cache with O(1) get and put.",
    "Keep a value dict and a timestamp dict; evict the oldest by scanning timestamps.",
    "class LRUCache:\n"
    "    def __init__(self, capacity):\n"
    "        self.cap = capacity; self.store = {}; self.time = {}; self.clock = 0\n"
    "    def get(self, key):\n"
    "        if key not in self.store:\n"
    "            return -1\n"
    "        self.clock += 1; self.time[key] = self.clock\n"
    "        return self.store[key]\n"
    "    def put(self, key, value):\n"
    "        if len(self.store) >= self.cap and key not in self.store:\n"
    "            oldest = min(self.time, key=self.time.get)\n"
    "            del self.store[oldest]; del self.time[oldest]\n"
    "        self.store[key] = value; self.clock += 1; self.time[key] = self.clock",
    "On overflow scan the timestamp map for the oldest key and remove it.",
    _O1,
)

_LFU_FREQ_SCAN = _dsa(
    "Implement an LFU cache with O(1) get and put.",
    "Store values and per-key frequencies; on eviction scan the frequency map for "
    "the minimum.",
    "import java.util.HashMap;\n"
    "import java.util.Map;\n"
    "class LFUCache {\n"
    "    Map<Integer,Integer> vals = new HashMap<>();\n"
    "    Map<Integer,Integer> freq = new HashMap<>();\n"
    "    int cap;\n"
    "    LFUCache(int capacity) { cap = capacity; }\n"
    "    int get(int key) {\n"
    "        if (!vals.containsKey(key)) return -1;\n"
    "        freq.put(key, freq.get(key) + 1);\n"
    "        return vals.get(key);\n"
    "    }\n"
    "    void put(int key, int value) {\n"
    "        if (cap == 0) return;\n"
    "        if (!vals.containsKey(key) && vals.size() >= cap) {\n"
    "            int evict = -1, min = Integer.MAX_VALUE;\n"
    "            for (Map.Entry<Integer,Integer> e : freq.entrySet())\n"
    "                if (e.getValue() < min) { min = e.getValue(); evict = e.getKey(); }\n"
    "            vals.remove(evict); freq.remove(evict);\n"
    "        }\n"
    "        vals.put(key, value); freq.put(key, freq.getOrDefault(key, 0) + 1);\n"
    "    }\n"
    "}",
    "On overflow loop the frequency map to find the least-frequently-used key.",
    _O1, lang="java",
)

_SWM_HEAP_REMOVE = _dsa(
    "Return the median of every window of size k as it slides over the array.",
    "Two heaps for the window, removing the outgoing element directly from the heap.",
    "import heapq\n"
    "def medianSlidingWindow(nums, k):\n"
    "    lo, hi, res = [], [], []\n"
    "    for i, x in enumerate(nums):\n"
    "        heapq.heappush(lo, -heapq.heappushpop(hi, x))\n"
    "        if len(lo) > len(hi):\n"
    "            heapq.heappush(hi, -heapq.heappop(lo))\n"
    "        if i >= k:\n"
    "            out = nums[i - k]\n"
    "            if out <= hi[0]:\n"
    "                lo.remove(-out)\n"
    "            else:\n"
    "                hi.remove(out)\n"
    "            heapq.heapify(lo); heapq.heapify(hi)\n"
    "        if i >= k - 1:\n"
    "            res.append(hi[0] if k % 2 else (hi[0] - lo[0]) / 2)\n"
    "    return res",
    "Maintain two heaps and call heap.remove on the element leaving the window.",
    "- **Time Complexity:** O(n log k)\n- **Space Complexity:** O(k)\n",
)

_MEDIAN_STREAM_SORT = _dsa(
    "Design a data structure supporting addNum and findMedian on a stream.",
    "Keep a sorted list; insert each number in order and read the middle.",
    "class MedianFinder:\n"
    "    def __init__(self):\n"
    "        self.data = []\n"
    "    def addNum(self, num):\n"
    "        self.data.append(num)\n"
    "        self.data.sort()\n"
    "    def findMedian(self):\n"
    "        n = len(self.data); m = n // 2\n"
    "        return self.data[m] if n % 2 else (self.data[m - 1] + self.data[m]) / 2",
    "Sort on every insertion, then index the middle element.",
    "- **Time Complexity:** O(log n) per addNum\n- **Space Complexity:** O(n)\n",
)

_SEGTREE_LINEAR = _dsa(
    "Support range-sum queries and point updates.",
    "Store the array and sum the range on every query.",
    "class NumArray:\n"
    "    def __init__(self, nums):\n"
    "        self.nums = list(nums)\n"
    "    def update(self, i, val):\n"
    "        self.nums[i] = val\n"
    "    def sumRange(self, i, j):\n"
    "        total = 0\n"
    "        for k in range(i, j + 1):\n"
    "            total += self.nums[k]\n"
    "        return total",
    "Loop from i to j adding each element to compute the range sum.",
    "- **Time Complexity:** O(log n) per query\n- **Space Complexity:** O(n)\n",
)

_TRIE_WORDLIST_SCAN = _dsa(
    "Implement a trie with insert, search and startsWith.",
    "Store inserted words in a list and scan with startswith for prefixes.",
    "class Trie:\n"
    "    def __init__(self):\n"
    "        self.words = []\n"
    "    def insert(self, word):\n"
    "        self.words.append(word)\n"
    "    def search(self, word):\n"
    "        return word in self.words\n"
    "    def startsWith(self, prefix):\n"
    "        return any(w.startswith(prefix) for w in self.words)",
    "Keep every word in a list; prefix queries scan all stored words.",
    "- **Time Complexity:** O(L) per operation\n- **Space Complexity:** O(N)\n",
)

_DSU_NO_COMPRESSION = _dsa(
    "Maintain disjoint sets with union and connectivity queries.",
    "Union-Find walking parent pointers without path compression.",
    "class DSU:\n"
    "    def __init__(self, n):\n"
    "        self.parent = list(range(n))\n"
    "    def find(self, x):\n"
    "        while self.parent[x] != x:\n"
    "            x = self.parent[x]\n"
    "        return x\n"
    "    def union(self, a, b):\n"
    "        self.parent[self.find(a)] = self.find(b)",
    "find walks to the root; union links one root under the other.",
    "- **Time Complexity:** O(alpha(n)) amortized per op\n- **Space Complexity:** O(n)\n",
)

_DIJKSTRA_NO_HEAP = _dsa(
    "Single-source shortest paths with non-negative edge weights.",
    "Dijkstra selecting the next node by scanning all distances.",
    "def dijkstra(graph, src, n):\n"
    "    dist = [float('inf')] * n; dist[src] = 0\n"
    "    visited = [False] * n\n"
    "    for _ in range(n):\n"
    "        u = -1\n"
    "        for v in range(n):\n"
    "            if not visited[v] and (u == -1 or dist[v] < dist[u]):\n"
    "                u = v\n"
    "        visited[u] = True\n"
    "        for v, w in graph[u]:\n"
    "            if dist[u] + w < dist[v]:\n"
    "                dist[v] = dist[u] + w\n"
    "    return dist",
    "Each step linearly scans for the closest unvisited node, then relaxes edges.",
    "- **Time Complexity:** O(E log V)\n- **Space Complexity:** O(V)\n",
)

_DSA_DUPLICATE_SECTION = (
    _LRU_ORDEREDDICT + "\n\n### Complexity\n"
    "- **Time Complexity:** O(1) per operation\n- **Space Complexity:** O(capacity)\n"
)

# Self-contradiction: the code is genuinely O(n) and the first claim matches it, so
# the AST complexity validator passes — but two DIFFERENT time complexities are stated
# as the solution's cost. No current critic compares claim-vs-claim => this ESCAPES
# until the Phase-3 reasoning/contradiction gate is added.
_DSA_CONTRADICTION = _dsa(
    "Return the indices of the two numbers that add up to target.",
    "Single-pass hash map of complement -> index.",
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, x in enumerate(nums):\n"
    "        if target - x in seen:\n"
    "            return [seen[target - x], i]\n"
    "        seen[x] = i\n"
    "    return []",
    "Each element is checked against previously seen complements in one pass.",
    "- **Time Complexity:** O(n)\n"
    "- **Time Complexity:** O(n log n)\n"
    "- **Space Complexity:** O(n)\n",
)

# All-O(1) data structure (RandomizedSet) whose remove is actually O(n) (list scan)
# while claiming O(1) — the named "All O(1)" problem.
_DSA_ALL_O1_LIST_REMOVE = _dsa(
    "Design RandomizedSet with O(1) insert, remove and getRandom.",
    "Array for getRandom plus a set for membership.",
    "import random\n"
    "class RandomizedSet:\n"
    "    def __init__(self):\n"
    "        self.data = []\n"
    "    def insert(self, val):\n"
    "        if val in self.data:\n"
    "            return False\n"
    "        self.data.append(val)\n"
    "        return True\n"
    "    def remove(self, val):\n"
    "        if val not in self.data:\n"
    "            return False\n"
    "        self.data.remove(val)\n"
    "        return True\n"
    "    def getRandom(self):\n"
    "        return random.choice(self.data)",
    "Append on insert, list.remove on delete, random.choice for getRandom.",
    "- **Time Complexity:** O(1) per operation\n- **Space Complexity:** O(n)\n",
)

_DSA_PLACEHOLDER = _dsa(
    "Implement a stack that returns the minimum in O(1).",
    "Auxiliary min-stack tracking the running minimum.",
    "class MinStack:\n"
    "    def __init__(self):\n"
    "        self.stack = []\n"
    "    def push(self, x):\n"
    "        pass\n"
    "    def pop(self):\n"
    "        pass\n"
    "    def getMin(self):\n"
    "        pass",
    "Maintain a parallel stack of minima.",
    _O1,
)


_DSA_CASES = [
    Case("dsa_lru_ordereddict", DSA, "implement an lru cache", "golden", ACCEPT,
         ("lru", "library_optimal"), _LRU_ORDEREDDICT),
    Case("dsa_lru_manual_dll", DSA, "implement an lru cache", "golden", ACCEPT,
         ("lru", "hashmap_dll"), _LRU_MANUAL),
    Case("dsa_two_sum", DSA, "solve two sum optimally", "golden", ACCEPT,
         ("hashmap",), _TWO_SUM),
    Case("dsa_dijkstra_heap", DSA, "implement dijkstra shortest path", "golden", ACCEPT,
         ("graph", "heap"), _DIJKSTRA_GOOD),
    Case("dsa_dsu_compression", DSA, "implement union find", "golden", ACCEPT,
         ("dsu", "path_compression"), _DSU_GOOD),

    Case("dsa_lru_timestamp_scan", DSA, "implement an lru cache", "adversarial", REJECT,
         ("lru", "on_scan", "false_complexity"), _LRU_TIMESTAMP_SCAN),
    Case("dsa_lfu_freq_scan", DSA, "implement an lfu cache", "adversarial", REJECT,
         ("lfu", "on_scan", "false_complexity"), _LFU_FREQ_SCAN),
    Case("dsa_swm_heap_remove", DSA, "sliding window median", "adversarial", REJECT,
         ("sliding_window_median", "arbitrary_heap_removal"), _SWM_HEAP_REMOVE),
    Case("dsa_median_stream_sort", DSA, "find median from data stream", "adversarial", REJECT,
         ("median_stream", "sort_each_add", "false_complexity"), _MEDIAN_STREAM_SORT),
    Case("dsa_segtree_linear", DSA, "range sum query mutable segment tree", "adversarial",
         REJECT, ("segment_tree", "linear_scan", "false_complexity"), _SEGTREE_LINEAR),
    Case("dsa_trie_wordlist_scan", DSA, "implement a trie prefix tree", "adversarial", REJECT,
         ("trie", "wordlist_scan"), _TRIE_WORDLIST_SCAN),
    Case("dsa_dsu_no_compression", DSA, "implement union find", "adversarial", REJECT,
         ("dsu", "no_path_compression", "false_complexity"), _DSU_NO_COMPRESSION),
    Case("dsa_dijkstra_no_heap", DSA, "implement dijkstra shortest path", "adversarial", REJECT,
         ("graph", "no_heap", "false_complexity"), _DIJKSTRA_NO_HEAP),
    Case("dsa_duplicate_complexity", DSA, "implement an lru cache", "adversarial", REJECT,
         ("duplicate_section", "quality"), _DSA_DUPLICATE_SECTION),
    Case("dsa_placeholder_stub", DSA, "implement a min stack", "adversarial", REJECT,
         ("placeholder", "incomplete"), _DSA_PLACEHOLDER),
    Case("dsa_contradictory_complexity", DSA, "solve two sum optimally", "adversarial",
         REJECT, ("contradiction", "self_inconsistent"), _DSA_CONTRADICTION),
    Case("dsa_all_o1_list_remove", DSA, "design all o(1) randomizedset", "adversarial",
         REJECT, ("all_o1", "on_scan", "false_complexity"), _DSA_ALL_O1_LIST_REMOVE),
]


# ---------------------------------------------------------------------------
# Debug + Code Review cases (authored from the deterministic critic contracts)
# ---------------------------------------------------------------------------
_DEBUG_GOLDEN = (
    "### Likely Cause\n"
    "The NullPointerException at `OrderService.java:42` means `customer` is null when "
    "`customer.getId()` runs — the repository lookup returned no row.\n\n"
    "### Fix\n"
    "Guard the lookup and fail fast with a clear error:\n"
    "```java\n"
    "Customer customer = repo.findById(id)\n"
    "    .orElseThrow(() -> new NotFoundException(\"customer \" + id));\n"
    "```\n"
)
_DEBUG_GOLDEN_QUERY = (
    "My service throws this:\n"
    "Exception in thread \"main\" java.lang.NullPointerException\n"
    "    at com.shop.OrderService.place(OrderService.java:42)\n"
    "How do I fix it?"
)

_DEBUG_FABRICATED = (
    "### Patched Code\n"
    "Here is your corrected file:\n"
    "```java\n"
    "public class OrderService {\n"
    "    private final OrderRepository repo;\n"
    "    private final PaymentGateway gateway;\n"
    "    public OrderService(OrderRepository repo, PaymentGateway gateway) {\n"
    "        this.repo = repo;\n"
    "        this.gateway = gateway;\n"
    "    }\n"
    "    public Order place(Long id, Cart cart) {\n"
    "        Customer customer = repo.findById(id).get();\n"
    "        Order order = new Order(customer, cart);\n"
    "        gateway.charge(order.total());\n"
    "        return repo.save(order);\n"
    "    }\n"
    "    public void cancel(Long orderId) {\n"
    "        repo.deleteById(orderId);\n"
    "    }\n"
    "}\n"
    "```\n"
)

_REVIEW_GOLDEN = (
    "### Architecture & Design\n"
    "The controller talks to the database directly; introduce a service layer to "
    "separate concerns.\n\n"
    "### Correctness & Bugs\n"
    "`findById(id).get()` throws on a missing row (an unhandled exception / NPE risk) "
    "and there is no null/edge-case handling.\n\n"
    "### Security\n"
    "The SQL is built by string concatenation — an injection vulnerability; use "
    "parameterized queries.\n\n"
    "### Performance & Complexity\n"
    "Loading all orders then filtering in memory is O(n); push the filter into the "
    "query and add an index.\n\n"
    "### Refactored Code\n"
    "```java\n"
    "public List<Order> recent(Long customerId) {\n"
    "    return repo.findByCustomerIdOrderByCreatedAtDesc(customerId, PageRequest.of(0, 50));\n"
    "}\n"
    "```\n"
)

_REVIEW_TRUNCATED = (
    "### Performance & Security\n"
    "Looks mostly fine; a couple of naming nits for readability.\n\n"
    "### Refactored Code\n"
    "```java\n"
    "public List<Order> recent(Long id) {\n"
    "    // ... rest of the code unchanged\n"
    "}\n"
    "```\n"
)

_DEBUG_REVIEW_CASES = [
    Case("debug_evidence_fix", DEBUG, _DEBUG_GOLDEN_QUERY, "golden", ACCEPT,
         ("debug", "has_evidence"), _DEBUG_GOLDEN),
    Case("debug_fabricated_file", DEBUG, "my app keeps crashing, fix it", "adversarial",
         REJECT, ("debug", "fabricated_patch", "hallucination"), _DEBUG_FABRICATED),
    Case("review_multidimension", REVIEW, "review this OrderService class", "golden", ACCEPT,
         ("code_review", "multi_dimension"), _REVIEW_GOLDEN),
    Case("review_truncated_refactor", REVIEW, "review this OrderService class", "adversarial",
         REJECT, ("code_review", "truncated", "shallow"), _REVIEW_TRUNCATED),
]


# ---------------------------------------------------------------------------
# Harvested fixtures (already asserted in the test-suite) for SQL / SysDesign /
# Full Stack. Imported so the corpus reuses validated ground truth instead of
# duplicating large answers. Guarded: a missing fixture is skipped, never fatal.
# ---------------------------------------------------------------------------
def _harvest() -> list:
    cases: list[Case] = []
    tests_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)

    def pull(module, names):
        out = {}
        for n in names:
            try:
                out[n] = getattr(module, n)
            except AttributeError:
                pass
        return out

    # SQL
    try:
        import test_sql as ts
        f = pull(ts, ["FULL_ANSWER", "NO_INDEX_JUSTIFIED", "EXPR_INDEX_ANSWER",
                      "DUP_INDEX_ANSWER", "MISMATCH_INDEX_ANSWER", "INVALID_PARTITION_ANSWER",
                      "MISSING_NODE_TYPES_ANSWER", "MISSING_COST_BENEFIT_ANSWER",
                      "NONSARGABLE_FUNC_ANSWER"])
        q = "optimize this slow postgresql query at scale"
        if "FULL_ANSWER" in f:
            cases.append(Case("sql_full_answer", SQL, q, "golden", ACCEPT,
                              ("sql", "complete_optimization"), f["FULL_ANSWER"]))
        if "NO_INDEX_JUSTIFIED" in f:
            cases.append(Case("sql_no_index_justified", SQL, q, "golden", ACCEPT,
                              ("sql", "justified_no_index"), f["NO_INDEX_JUSTIFIED"]))
        if "EXPR_INDEX_ANSWER" in f:
            cases.append(Case("sql_expression_index", SQL, q, "golden", ACCEPT,
                              ("sql", "expression_index"), f["EXPR_INDEX_ANSWER"]))
        for name, cid, tag in [
            ("DUP_INDEX_ANSWER", "sql_duplicate_index", "duplicate_index"),
            ("MISMATCH_INDEX_ANSWER", "sql_mismatched_index", "mismatched_index"),
            ("INVALID_PARTITION_ANSWER", "sql_invalid_partition", "invalid_pg_partition"),
            ("MISSING_NODE_TYPES_ANSWER", "sql_missing_plan_nodes", "missing_explain_nodes"),
            ("MISSING_COST_BENEFIT_ANSWER", "sql_missing_cost_benefit", "missing_tradeoffs"),
            ("NONSARGABLE_FUNC_ANSWER", "sql_nonsargable", "nonsargable_predicate"),
        ]:
            if name in f:
                cases.append(Case(cid, SQL, q, "adversarial", REJECT, ("sql", tag), f[name]))
    except Exception:
        pass

    # System Design
    try:
        import test_sysdesign as td
        f = pull(td, ["CONSISTENT", "INSTAGRAM_FULL", "CAP_WITH_MATH", "PEAK_OK",
                      "INCONSISTENT_LOW", "HANDWAVY", "INFRA_ONLY", "SECTIONS_MISSING",
                      "DIAGRAM_MISSING_TIERS", "SOCIAL_MISSING"])
        if "CONSISTENT" in f:
            cases.append(Case("sd_consistent_capacity", SYSDESIGN, "design twitter", "golden",
                              ACCEPT, ("system_design", "derived_capacity"), f["CONSISTENT"]))
        if "INSTAGRAM_FULL" in f:
            cases.append(Case("sd_instagram_full", SYSDESIGN, "design instagram", "golden",
                              ACCEPT, ("system_design", "domain_deepdive"), f["INSTAGRAM_FULL"]))
        if "CAP_WITH_MATH" in f:
            cases.append(Case("sd_capacity_math", SYSDESIGN, "design dropbox", "golden", ACCEPT,
                              ("system_design", "capacity_math"), f["CAP_WITH_MATH"]))
        for name, cid, tag in [
            ("INCONSISTENT_LOW", "sd_inconsistent_qps", "capacity_order_of_magnitude"),
            ("HANDWAVY", "sd_handwavy_capacity", "handwavy_capacity"),
            ("INFRA_ONLY", "sd_infra_only", "infra_namedrop_no_domain"),
            ("SECTIONS_MISSING", "sd_missing_sections", "missing_mandatory_sections"),
            ("DIAGRAM_MISSING_TIERS", "sd_diagram_missing_tiers", "diagram_missing_tiers"),
            ("SOCIAL_MISSING", "sd_social_missing_deepdive", "missing_domain_deepdive"),
        ]:
            if name in f:
                cases.append(Case(cid, SYSDESIGN, "design a large-scale system", "adversarial",
                                  REJECT, ("system_design", tag), f[name]))
    except Exception:
        pass

    # Full Stack
    try:
        import test_fullstack as tf
        f = pull(tf, ["COMPLETE_PROJECT", "MISSING_DOCKER"])
        if "COMPLETE_PROJECT" in f:
            cases.append(Case("fs_complete_project", FULLSTACK, "build a full stack todo app",
                              "golden", ACCEPT, ("fullstack", "complete_build"),
                              f["COMPLETE_PROJECT"]))
        if "MISSING_DOCKER" in f:
            cases.append(Case("fs_missing_docker", FULLSTACK, "build a full stack todo app",
                              "adversarial", REJECT, ("fullstack", "missing_docker_dir"),
                              f["MISSING_DOCKER"]))
    except Exception:
        pass

    return cases


CASES: list = _DSA_CASES + _DEBUG_REVIEW_CASES + _harvest()


def by_agent() -> dict:
    out: dict = {}
    for c in CASES:
        out.setdefault(c.agent, []).append(c)
    return out


def counts() -> dict:
    return {
        "total": len(CASES),
        "golden": sum(1 for c in CASES if c.kind == "golden"),
        "adversarial": sum(1 for c in CASES if c.kind == "adversarial"),
        "by_agent": {a: len(v) for a, v in by_agent().items()},
    }
