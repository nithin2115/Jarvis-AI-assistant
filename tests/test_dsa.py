"""
Phase 3 — DSA complexity / knowledge-base regression suite.

Pure-function tests (no network) for dsa_complexity detectors plus a check that the
DSA knowledge base is loaded into the agent prompt. Run:
    python -m pytest tests/test_dsa.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import dsa_complexity as dc
import dsa_structure as ds

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fence(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------
def test_extract_code_blocks():
    text = "intro\n" + _fence("x = 1") + "\nmid\n" + _fence("y = 2", "java")
    blocks = dc.extract_code_blocks(text)
    assert len(blocks) == 2
    assert "x = 1" in blocks[0] and "y = 2" in blocks[1]


def test_extract_time_complexities_ignores_space():
    text = "- Time Complexity: O(n log k)\n- Space Complexity: O(k)"
    assert dc.extract_time_complexities(text) == ["nlogk"]


def test_extract_claimed_falls_back_to_any_o():
    # No "time complexity" label -> falls back to any O(...) it can find.
    assert dc.extract_claimed_complexities("runs in O(n) overall") == ["n"]


# ---------------------------------------------------------------------------
# Sliding Window Median
# ---------------------------------------------------------------------------
SWM_BAD = (
    "### Code\n"
    + _fence(
        "PriorityQueue<Integer> maxHeap = new PriorityQueue<>((a,b)->b-a);\n"
        "PriorityQueue<Integer> minHeap = new PriorityQueue<>();\n"
        "maxHeap.add(nums[i]);\n"
        "maxHeap.remove(nums[i - k]);  // O(k) arbitrary removal\n",
        "java",
    )
    + "\n### Complexity\n- Time Complexity: O(n log k)\n- Space Complexity: O(k)"
)

SWM_GOOD = (
    "### Code\n"
    + _fence(
        "PriorityQueue<Integer> maxHeap = new PriorityQueue<>((a,b)->b-a);\n"
        "PriorityQueue<Integer> minHeap = new PriorityQueue<>();\n"
        "Map<Integer,Integer> delayed = new HashMap<>();\n"
        "maxHeap.offer(nums[i]);\n"
        "int top = maxHeap.peek();\n"
        "delayed.merge(outgoing, 1, Integer::sum);  // lazy deletion bookkeeping\n"
        "while (!maxHeap.isEmpty() && delayed.getOrDefault(maxHeap.peek(),0)>0) {\n"
        "    delayed.merge(maxHeap.poll(), -1, Integer::sum);\n"
        "}\n",
        "java",
    )
    + "\n### Complexity\n- Time Complexity: O(n log k)\n- Space Complexity: O(k)"
)


def test_swm_arbitrary_heap_removal_rejected():
    ok, reason = dc.analyze("sliding window median", SWM_BAD)
    assert ok is False
    assert "lazy deletion" in reason.lower()


def test_swm_two_heaps_lazy_deletion_accepted():
    ok, _ = dc.analyze("sliding window median of size k", SWM_GOOD)
    assert ok is True


def test_swm_detector_does_not_fire_on_map_remove():
    # map.remove(key) is O(1) and must NOT be treated as the heap anti-pattern.
    assert dc._uses_linear_heap_removal(
        "Map<Integer,Integer> delayed = new HashMap<>();\ndelayed.remove(x);"
    ) is False


# ---------------------------------------------------------------------------
# LFU Cache
# ---------------------------------------------------------------------------
LFU_BAD = (
    "### Code\n"
    + _fence(
        "Map<Integer,Integer> freq = new HashMap<>();\n"
        "int minF = Integer.MAX_VALUE;\n"
        "for (int f : freq.values()) minF = Math.min(minF, f);  // scan for min\n",
        "java",
    )
    + "\n### Complexity\n- Time Complexity: O(1)"
)

LFU_GOOD = (
    "### Code\n"
    + _fence(
        "Map<Integer,Node> freq = new HashMap<>();\n"
        "this.minFreq = 1;            // maintained incrementally\n"
        "minFreq += 1;                // updated on get/put\n",
        "java",
    )
    + "\n### Complexity\n- Time Complexity: O(1)"
)


def test_lfu_freq_scan_rejected():
    ok, reason = dc.analyze("implement an lfu cache", LFU_BAD)
    assert ok is False
    assert "minfreq" in reason.lower()


def test_lfu_incremental_minfreq_accepted():
    ok, _ = dc.analyze("implement an lfu cache", LFU_GOOD)
    assert ok is True


# ---------------------------------------------------------------------------
# Sort vs. linear (universal)
# ---------------------------------------------------------------------------
def test_sort_claiming_linear_rejected():
    text = "### Code\n" + _fence("nums = sorted(nums)\nreturn nums") + \
           "\n### Complexity\n- Time Complexity: O(n)"
    ok, reason = dc.analyze("group the data", text)
    assert ok is False
    assert "sort" in reason.lower()


def test_sort_correctly_stated_nlogn_accepted():
    text = "### Code\n" + _fence("nums = sorted(nums)\nreturn nums") + \
           "\n### Complexity\n- Time Complexity: O(n log n)"
    ok, _ = dc.analyze("group the data", text)
    assert ok is True


def test_counting_sort_linear_accepted():
    # No comparison-sort API call -> O(n) claim stands.
    text = (
        "### Code\n"
        + _fence(
            "count = [0]*100001\n"
            "for x in nums: count[x]+=1\n"
            "out=[]\n"
            "for v in range(len(count)):\n"
            "    out += [v]*count[v]\n"
        )
        + "\n### Complexity\n- Time Complexity: O(n)"
    )
    ok, _ = dc.analyze("sort small integers", text)
    assert ok is True


def test_sort_with_two_time_claims_not_flagged():
    # When O(n log n) is also stated, the {n}-only guard prevents a false positive.
    text = (
        "### Code\n" + _fence("aux = sorted(small)\nreturn aux") +
        "\n- Time Complexity: O(n log n)\n- (the merge pass alone is Time Complexity: O(n))"
    )
    ok, _ = dc.analyze("merge step", text)
    assert ok is True


# ---------------------------------------------------------------------------
# No-code / safety
# ---------------------------------------------------------------------------
def test_no_code_is_ok():
    ok, reason = dc.analyze("sliding window median", "Here is the idea, no code yet.")
    assert ok is True and reason == ""


# ---------------------------------------------------------------------------
# Knowledge base wiring
# ---------------------------------------------------------------------------
def test_dsa_knowledge_base_file_exists():
    assert os.path.exists(os.path.join(BASE, "DSA_KNOWLEDGE_BASE.md"))


def test_dsa_knowledge_base_injected_into_prompt():
    import router
    prompt = router.AGENT_PROMPTS[router.DSA_AGENT]
    # A distinctive line from the KB must be present in the assembled system prompt.
    assert "comparison sort" in prompt.lower()
    assert "two heaps + lazy deletion" in prompt.lower()


# ===========================================================================
# Phase 6 — canonical-algorithm detectors (LRU, median stream, segment tree,
# trie, union-find, Dijkstra, A*, topo sort, fake lazy deletion, O(1) scans).
# ===========================================================================
def _complexity(t):
    return "\n### Complexity\n- Time Complexity: " + t


# ── Fake lazy deletion ──────────────────────────────────────────────────────
def test_fake_lazy_deletion_rejected():
    text = (
        "We use lazy deletion to keep it O(n log k).\n### Code\n"
        + _fence(
            "PriorityQueue<Integer> maxHeap = new PriorityQueue<>();\n"
            "maxHeap.remove(nums[i - k]);  // 'lazy' but really O(k)\n", "java")
        + _complexity("O(n log k)")
    )
    ok, reason = dc.analyze("sliding window median", text)
    assert ok is False
    assert "lazy deletion" in reason.lower()


# ── LRU Cache ───────────────────────────────────────────────────────────────
LRU_BAD = (
    "### Code\n" + _fence(
        "class LRUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.cap = cap; self.store = {}; self.time = {}; self.clock = 0\n"
        "    def get(self, key):\n"
        "        if key in self.store:\n"
        "            self.clock += 1; self.time[key] = self.clock\n"
        "            return self.store[key]\n"
        "        return -1\n"
        "    def put(self, key, val):\n"
        "        if len(self.store) >= self.cap and key not in self.store:\n"
        "            oldest = min(self.time, key=self.time.get)\n"
        "            del self.store[oldest]; del self.time[oldest]\n"
        "        self.store[key] = val; self.clock += 1; self.time[key] = self.clock\n")
    + _complexity("O(1)")
)

LRU_GOOD = (
    "### Code\n" + _fence(
        "from collections import OrderedDict\n"
        "class LRUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.cap = cap; self.d = OrderedDict()\n"
        "    def get(self, key):\n"
        "        if key not in self.d: return -1\n"
        "        self.d.move_to_end(key); return self.d[key]\n"
        "    def put(self, key, val):\n"
        "        if key in self.d: self.d.move_to_end(key)\n"
        "        self.d[key] = val\n"
        "        if len(self.d) > self.cap: self.d.popitem(last=False)\n")
    + _complexity("O(1)")
)


def test_lru_scan_rejected():
    ok, reason = dc.analyze("implement an lru cache", LRU_BAD)
    assert ok is False
    assert "lru" in reason.lower()


def test_lru_ordereddict_accepted():
    ok, _ = dc.analyze("implement an lru cache", LRU_GOOD)
    assert ok is True


# ── Median from a data stream ───────────────────────────────────────────────
MEDIAN_STREAM_BAD = (
    "### Code\n" + _fence(
        "class MedianFinder:\n"
        "    def __init__(self): self.nums = []\n"
        "    def addNum(self, num):\n"
        "        self.nums.append(num); self.nums.sort()\n"
        "    def findMedian(self):\n"
        "        n = len(self.nums); return self.nums[n//2]\n")
    + _complexity("O(log n)")
)

MEDIAN_STREAM_GOOD = (
    "### Code\n" + _fence(
        "import heapq\n"
        "class MedianFinder:\n"
        "    def __init__(self): self.lo = []; self.hi = []\n"
        "    def addNum(self, num):\n"
        "        heapq.heappush(self.lo, -num)\n"
        "        heapq.heappush(self.hi, -heapq.heappop(self.lo))\n"
        "        if len(self.hi) > len(self.lo):\n"
        "            heapq.heappush(self.lo, -heapq.heappop(self.hi))\n"
        "    def findMedian(self):\n"
        "        if len(self.lo) > len(self.hi): return -self.lo[0]\n"
        "        return (-self.lo[0] + self.hi[0]) / 2\n")
    + _complexity("O(log n)")
)


def test_median_stream_sort_rejected():
    ok, reason = dc.analyze("find median from a data stream", MEDIAN_STREAM_BAD)
    assert ok is False
    assert "two heaps" in reason.lower()


def test_median_stream_two_heaps_accepted():
    ok, _ = dc.analyze("find median from a data stream", MEDIAN_STREAM_GOOD)
    assert ok is True


# ── Segment Tree ────────────────────────────────────────────────────────────
SEGTREE_BAD = (
    "### Code\n" + _fence(
        "class SegTree:\n"
        "    def __init__(self, arr): self.arr = arr\n"
        "    def query(self, l, r):\n"
        "        res = 0\n"
        "        for i in range(l, r + 1):\n"
        "            res += self.arr[i]\n"
        "        return res\n")
    + _complexity("O(log n)")
)

SEGTREE_GOOD = (
    "### Code\n" + _fence(
        "class SegTree:\n"
        "    def build(self, arr, node, lo, hi):\n"
        "        if lo == hi: self.tree[node] = arr[lo]; return\n"
        "        mid = (lo + hi) // 2\n"
        "        self.build(arr, 2*node, lo, mid)\n"
        "        self.build(arr, 2*node+1, mid+1, hi)\n"
        "        self.tree[node] = self.tree[2*node] + self.tree[2*node+1]\n")
    + _complexity("O(log n)")
)


def test_segment_tree_linear_query_rejected():
    ok, reason = dc.analyze("implement a segment tree for range sum", SEGTREE_BAD)
    assert ok is False
    assert "segment tree" in reason.lower()


def test_segment_tree_recursive_accepted():
    ok, _ = dc.analyze("implement a segment tree for range sum", SEGTREE_GOOD)
    assert ok is True


# ── Trie ────────────────────────────────────────────────────────────────────
TRIE_BAD = (
    "### Code\n" + _fence(
        "class Trie:\n"
        "    def __init__(self): self.words = []\n"
        "    def insert(self, w): self.words.append(w)\n"
        "    def startsWith(self, prefix):\n"
        "        for w in self.words:\n"
        "            if w.startswith(prefix): return True\n"
        "        return False\n")
    + _complexity("O(L)")
)

TRIE_GOOD = (
    "### Code\n" + _fence(
        "class TrieNode:\n"
        "    def __init__(self): self.children = {}; self.is_end = False\n"
        "class Trie:\n"
        "    def __init__(self): self.root = TrieNode()\n"
        "    def insert(self, w):\n"
        "        node = self.root\n"
        "        for ch in w: node = node.children.setdefault(ch, TrieNode())\n"
        "        node.is_end = True\n")
    + _complexity("O(L)")
)


def test_trie_wordlist_scan_rejected():
    ok, reason = dc.analyze("implement a trie", TRIE_BAD)
    assert ok is False
    assert "trie" in reason.lower()


def test_trie_real_node_accepted():
    ok, _ = dc.analyze("implement a trie", TRIE_GOOD)
    assert ok is True


# ── Union-Find ──────────────────────────────────────────────────────────────
DSU_BAD = (
    "### Code\n" + _fence(
        "class DSU:\n"
        "    def __init__(self, n): self.parent = list(range(n))\n"
        "    def find(self, x):\n"
        "        while x != self.parent[x]:\n"
        "            x = self.parent[x]\n"
        "        return x\n"
        "    def union(self, a, b):\n"
        "        self.parent[self.find(a)] = self.find(b)\n")
    + _complexity("O(alpha(n))")
)

DSU_GOOD = (
    "### Code\n" + _fence(
        "class DSU:\n"
        "    def __init__(self, n):\n"
        "        self.parent = list(range(n)); self.rank = [0]*n\n"
        "    def find(self, x):\n"
        "        if self.parent[x] != x:\n"
        "            self.parent[x] = self.find(self.parent[x])\n"
        "        return self.parent[x]\n"
        "    def union(self, a, b):\n"
        "        ra, rb = self.find(a), self.find(b)\n"
        "        if ra != rb: self.parent[rb] = ra\n")
    + _complexity("O(alpha(n))")
)


def test_union_find_no_compression_rejected():
    ok, reason = dc.analyze("implement union find / disjoint set", DSU_BAD)
    assert ok is False
    assert "compression" in reason.lower()


def test_union_find_with_compression_accepted():
    ok, _ = dc.analyze("implement union find / disjoint set", DSU_GOOD)
    assert ok is True


# ── Dijkstra ────────────────────────────────────────────────────────────────
DIJKSTRA_BAD = (
    "### Code\n" + _fence(
        "def dijkstra(graph, src, n):\n"
        "    dist = [float('inf')]*n; dist[src] = 0; visited = [False]*n\n"
        "    for _ in range(n):\n"
        "        u = -1\n"
        "        for v in range(n):\n"
        "            if not visited[v] and (u == -1 or dist[v] < dist[u]): u = v\n"
        "        visited[u] = True\n"
        "        for v, w in graph[u]:\n"
        "            if dist[u] + w < dist[v]: dist[v] = dist[u] + w\n"
        "    return dist\n")
    + _complexity("O(E log V)")
)

DIJKSTRA_GOOD = (
    "### Code\n" + _fence(
        "import heapq\n"
        "def dijkstra(graph, src, n):\n"
        "    dist = [float('inf')]*n; dist[src] = 0; pq = [(0, src)]\n"
        "    while pq:\n"
        "        d, u = heapq.heappop(pq)\n"
        "        if d > dist[u]: continue\n"
        "        for v, w in graph[u]:\n"
        "            if d + w < dist[v]:\n"
        "                dist[v] = d + w; heapq.heappush(pq, (d + w, v))\n"
        "    return dist\n")
    + _complexity("O(E log V)")
)


def test_dijkstra_no_heap_rejected():
    ok, reason = dc.analyze("dijkstra shortest path", DIJKSTRA_BAD)
    assert ok is False
    assert "heap" in reason.lower()


def test_dijkstra_with_heap_accepted():
    ok, _ = dc.analyze("dijkstra shortest path", DIJKSTRA_GOOD)
    assert ok is True


# ── A* ──────────────────────────────────────────────────────────────────────
ASTAR_BAD = (
    "### Code\n" + _fence(
        "import heapq\n"
        "def a_star(graph, src, goal, n):\n"
        "    dist = [float('inf')]*n; dist[src] = 0; pq = [(0, src)]\n"
        "    while pq:\n"
        "        d, u = heapq.heappop(pq)\n"
        "        if u == goal: return d\n"
        "        for v, w in graph[u]:\n"
        "            if d + w < dist[v]:\n"
        "                dist[v] = d + w; heapq.heappush(pq, (d + w, v))\n"
        "    return -1\n")
    + _complexity("O(E log V)")
)

ASTAR_GOOD = (
    "### Code\n" + _fence(
        "import heapq\n"
        "def a_star(start, goal, neighbors):\n"
        "    def h(p):  # Manhattan heuristic\n"
        "        return abs(p[0]-goal[0]) + abs(p[1]-goal[1])\n"
        "    pq = [(h(start), 0, start)]; seen = set()\n"
        "    while pq:\n"
        "        f, g, u = heapq.heappop(pq)\n"
        "        if u == goal: return g\n"
        "        if u in seen: continue\n"
        "        seen.add(u)\n"
        "        for v, w in neighbors(u):\n"
        "            heapq.heappush(pq, (g + w + h(v), g + w, v))\n"
        "    return -1\n")
    + _complexity("O(E log V)")
)


def test_astar_no_heuristic_rejected():
    ok, reason = dc.analyze("implement a* pathfinding", ASTAR_BAD)
    assert ok is False
    assert "heuristic" in reason.lower()


def test_astar_with_heuristic_accepted():
    ok, _ = dc.analyze("implement a* pathfinding", ASTAR_GOOD)
    assert ok is True


# ── Topological sort ────────────────────────────────────────────────────────
TOPO_BAD = (
    "### Code\n" + _fence(
        "def topo_sort(graph, n):\n"
        "    return sorted(range(n))  # sorting is NOT a topological order\n")
    + _complexity("O(V + E)")
)

TOPO_GOOD = (
    "### Code\n" + _fence(
        "from collections import deque\n"
        "def topo_sort(graph, n):\n"
        "    indegree = [0]*n\n"
        "    for u in range(n):\n"
        "        for v in graph[u]: indegree[v] += 1\n"
        "    q = deque([u for u in range(n) if indegree[u] == 0]); order = []\n"
        "    while q:\n"
        "        u = q.popleft(); order.append(u)\n"
        "        for v in graph[u]:\n"
        "            indegree[v] -= 1\n"
        "            if indegree[v] == 0: q.append(v)\n"
        "    return order if len(order) == n else []\n")
    + _complexity("O(V + E)")
)


def test_toposort_sorted_rejected():
    ok, reason = dc.analyze("topological sort of a dag", TOPO_BAD)
    assert ok is False
    assert "topological" in reason.lower()


def test_toposort_kahn_accepted():
    ok, _ = dc.analyze("topological sort of a dag", TOPO_GOOD)
    assert ok is True


# ── Generic O(1) hidden scan ────────────────────────────────────────────────
def test_o1_hidden_scan_rejected():
    text = ("### Code\n" + _fence(
        "class Bad:\n"
        "    def __init__(self): self.data = []\n"
        "    def add(self, x): self.data.append(x)\n"
        "    def getMax(self): return max(self.data)\n")
        + _complexity("O(1)"))
    ok, reason = dc.analyze("design a structure with O(1) getMax", text)
    assert ok is False
    assert "o(1)" in reason.lower()


def test_o1_minstack_with_scalar_min_accepted():
    text = ("### Code\n" + _fence(
        "class MinStack:\n"
        "    def __init__(self): self.s = []; self.mins = []\n"
        "    def push(self, x):\n"
        "        self.s.append(x)\n"
        "        self.mins.append(x if not self.mins else min(x, self.mins[-1]))\n"
        "    def getMin(self): return self.mins[-1]\n")
        + _complexity("O(1)"))
    ok, _ = dc.analyze("min stack with O(1) getMin", text)
    assert ok is True


# ===========================================================================
# Phase 6 — structural checks (sections, placeholder, logical compile).
# ===========================================================================
FULL_SOLUTION = (
    "### Problem Understanding\n"
    "Find two indices whose values sum to target.\n\n"
    "### Optimal Algorithm\n"
    "Hash map of value -> index, single pass.\n\n"
    "### Code\n" + _fence(
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return []\n")
    + "\n\n### Approach\n"
    "Store each value's index; check the complement on the fly.\n\n"
    "### Complexity\n- Time Complexity: O(n)\n- Space Complexity: O(n)\n"
)


def test_full_solution_passes_structure():
    ok, reason = ds.check("solve two sum optimally", FULL_SOLUTION)
    assert ok is True, reason


def test_missing_section_rejected():
    text = FULL_SOLUTION.replace("### Complexity\n", "### Notes\n", 1)
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False
    assert "complexity" in reason.lower()


def test_conceptual_question_skips_structure():
    # Has a snippet but it's an explanation, not a solve request.
    text = "A trie stores characters per node.\n" + _fence("node.children = {}")
    ok, _ = ds.check("What is a trie?", text)
    assert ok is True


def test_placeholder_pass_body_rejected():
    text = FULL_SOLUTION.replace(
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return []\n",
        "def two_sum(nums, target):\n    pass\n",
    )
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False
    assert "placeholder" in reason.lower() or "implementation" in reason.lower()


def test_placeholder_todo_marker_rejected():
    text = FULL_SOLUTION.replace("    return []\n", "    # TODO: implement this\n    return []\n")
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False


def test_unbalanced_delimiters_rejected():
    text = FULL_SOLUTION.replace("    return []\n", "    return (len(seen)\n")
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False
    assert "compile" in reason.lower() or "parse" in reason.lower()


def test_python_syntax_error_rejected():
    text = FULL_SOLUTION.replace("def two_sum(nums, target):", "def two_sum(nums, target)")
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False
    assert "parse" in reason.lower() or "syntax" in reason.lower()


def test_truncated_code_rejected():
    text = FULL_SOLUTION.replace("    return []\n", "    # ... rest of the code\n    return []\n")
    ok, reason = ds.check("solve two sum optimally", text)
    assert ok is False
    assert "truncat" in reason.lower()


def test_balanced_helper_ignores_brackets_in_strings():
    assert ds._balanced_delimiters('s = "a(b[c"  # ) ] balanced only in string\n', "python") is True


# ===========================================================================
# Phase 6 — false-positive hardening (correct-but-unconventional solutions
# must NOT be rejected).
# ===========================================================================
def test_dict_based_trie_iterating_chars_accepted():
    # No children/is_end keyword, dict-based, iterates `for ch in word` (singular).
    text = ("### Code\n" + _fence(
        "class Trie:\n"
        "    def __init__(self): self.root = {}\n"
        "    def insert(self, word):\n"
        "        node = self.root\n"
        "        for ch in word: node = node.setdefault(ch, {})\n"
        "        node['#'] = True\n"
        "    def search(self, word):\n"
        "        node = self.root\n"
        "        for ch in word:\n"
        "            if ch not in node: return False\n"
        "            node = node[ch]\n"
        "        return '#' in node\n")
        + _complexity("O(L)"))
    ok, _ = dc.analyze("implement a trie", text)
    assert ok is True


def test_union_find_iterative_compression_accepted():
    text = ("### Code\n" + _fence(
        "class DSU:\n"
        "    def __init__(self, n): self.parent = list(range(n))\n"
        "    def find(self, x):\n"
        "        root = x\n"
        "        while root != self.parent[root]: root = self.parent[root]\n"
        "        while x != root:\n"
        "            self.parent[x], x = root, self.parent[x]\n"
        "        return root\n")
        + _complexity("O(alpha(n))"))
    ok, _ = dc.analyze("implement union find / disjoint set", text)
    assert ok is True


def test_dijkstra_custom_heap_class_accepted():
    text = ("### Code\n" + _fence(
        "def dijkstra(graph, src, n):\n"
        "    dist = [float('inf')]*n; dist[src] = 0\n"
        "    heap = MinHeap(); heap.push((0, src))\n"
        "    while not heap.empty():\n"
        "        d, u = heap.pop()\n"
        "        for v, w in graph[u]:\n"
        "            if d + w < dist[v]:\n"
        "                dist[v] = d + w; heap.push((d + w, v))\n"
        "    return dist\n")
        + _complexity("O(E log V)"))
    ok, _ = dc.analyze("dijkstra shortest path", text)
    assert ok is True


# ===========================================================================
# Prompt wiring for the expanded algorithm coverage.
# ===========================================================================
def test_dsa_prompt_carries_phase6_patterns():
    import router
    low = router.AGENT_PROMPTS[router.DSA_AGENT].lower()
    for token in ("segment tree", "trie", "union-find", "dijkstra", "heuristic", "topological",
                  "path compression", "placeholder"):
        assert token in low, f"missing DSA pattern guidance: {token!r}"


# ---------------------------------------------------------------------------
# Compile verifier integration (Phase 1 hardening)
# ---------------------------------------------------------------------------
def _dsa_answer(code, lang="python"):
    return (
        "### Problem Understanding\nWe need to solve the problem.\n\n"
        "### Optimal Algorithm\nUse the right data structure.\n\n"
        "### Code\n" + _fence(code, lang) + "\n\n"
        "### Approach\nSingle pass with hash map.\n\n"
        "### Complexity\n- Time Complexity: O(n)\n- Space Complexity: O(n)\n"
    )


def test_dsa_critic_rejects_multiple_public_classes():
    import dsa_critic
    code = (
        "public class TrieNode {}\n"
        "public class Trie {}\n"
    )
    r = dsa_critic.critique("implement a trie", _dsa_answer(code, "java"))
    assert r["verified"] is False
    assert "public class" in r["feedback"].lower() or "compile" in r["feedback"].lower()


def test_dsa_critic_rejects_missing_cpp_headers():
    import dsa_critic
    code = (
        "int main() {\n"
        "    vector<int> v = {1, 2};\n"
        "    cout << v[0] << endl;\n"
        "    return 0;\n"
        "}\n"
    )
    r = dsa_critic.critique("reverse a linked list", _dsa_answer(code, "cpp"))
    assert r["verified"] is False
    assert "header" in r["feedback"].lower()


def test_dsa_critic_rejects_java_missing_import():
    import dsa_critic
    code = (
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        ArrayList<Integer> list = new ArrayList<>();\n"
        "        System.out.println(list);\n"
        "    }\n"
        "}\n"
    )
    r = dsa_critic.critique("merge k sorted lists", _dsa_answer(code, "java"))
    assert r["verified"] is False
    assert "import" in r["feedback"].lower()


def test_dsa_critic_accepts_valid_java_solution(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "import java.util.ArrayList;\n"
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        ArrayList<Integer> list = new ArrayList<>();\n"
        "        System.out.println(list);\n"
        "    }\n"
        "}\n"
    )
    r = dsa_critic.critique("merge k sorted lists", _dsa_answer(code, "java"))
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Golden DSA solutions — must pass the full dsa_critic pipeline
# ---------------------------------------------------------------------------
def _golden_answer(code, lang="python"):
    return (
        "### Problem Understanding\nFind the required result efficiently.\n\n"
        "### Optimal Algorithm\nUse the optimal data structure.\n\n"
        "### Code\n" + _fence(code, lang) + "\n\n"
        "### Approach\nExplain the single-pass logic.\n\n"
        "### Complexity\n- Time Complexity: O(n)\n- Space Complexity: O(n)\n"
    )


def test_golden_python_two_sum_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n"
        "            return [seen[target - x], i]\n"
        "        seen[x] = i\n"
        "    return []\n"
    )
    r = dsa_critic.critique("two sum", _golden_answer(code, "python"))
    assert r["verified"] is True


def test_golden_java_two_sum_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "import java.util.HashMap;\n"
        "public class Solution {\n"
        "    public int[] twoSum(int[] nums, int target) {\n"
        "        HashMap<Integer, Integer> seen = new HashMap<>();\n"
        "        for (int i = 0; i < nums.length; i++) {\n"
        "            int complement = target - nums[i];\n"
        "            if (seen.containsKey(complement)) {\n"
        "                return new int[]{seen.get(complement), i};\n"
        "            }\n"
        "            seen.put(nums[i], i);\n"
        "        }\n"
        "        return new int[]{};\n"
        "    }\n"
        "}\n"
    )
    r = dsa_critic.critique("two sum", _golden_answer(code, "java"))
    assert r["verified"] is True


def test_golden_cpp_two_sum_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "#include <vector>\n"
        "#include <unordered_map>\n"
        "using namespace std;\n"
        "class Solution {\n"
        "public:\n"
        "    vector<int> twoSum(vector<int>& nums, int target) {\n"
        "        unordered_map<int, int> seen;\n"
        "        for (int i = 0; i < nums.size(); i++) {\n"
        "            int complement = target - nums[i];\n"
        "            if (seen.count(complement)) {\n"
        "                return {seen[complement], i};\n"
        "            }\n"
        "            seen[nums[i]] = i;\n"
        "        }\n"
        "        return {};\n"
        "    }\n"
        "};\n"
    )
    r = dsa_critic.critique("two sum", _golden_answer(code, "cpp"))
    assert r["verified"] is True


def test_golden_python_lru_cache_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "class Node:\n"
        "    def __init__(self, key=0, val=0):\n"
        "        self.key = key\n"
        "        self.val = val\n"
        "        self.prev = None\n"
        "        self.next = None\n\n"
        "class LRUCache:\n"
        "    def __init__(self, capacity):\n"
        "        self.cap = capacity\n"
        "        self.keyToNode = {}\n"
        "        self.head = Node()\n"
        "        self.tail = Node()\n"
        "        self.head.next = self.tail\n"
        "        self.tail.prev = self.head\n"
        "\n"
        "    def get(self, key):\n"
        "        if key not in self.keyToNode:\n"
        "            return -1\n"
        "        node = self.keyToNode[key]\n"
        "        self._move_to_head(node)\n"
        "        return node.val\n"
        "\n"
        "    def put(self, key, value):\n"
        "        if key in self.keyToNode:\n"
        "            self.keyToNode[key].val = value\n"
        "            self._move_to_head(self.keyToNode[key])\n"
        "        else:\n"
        "            node = Node(key, value)\n"
        "            self.keyToNode[key] = node\n"
        "            self._add_to_head(node)\n"
        "            if len(self.keyToNode) > self.cap:\n"
        "                removed = self._remove_tail()\n"
        "                del self.keyToNode[removed.key]\n"
        "\n"
        "    def _add_to_head(self, node):\n"
        "        node.prev = self.head\n"
        "        node.next = self.head.next\n"
        "        self.head.next.prev = node\n"
        "        self.head.next = node\n"
        "\n"
        "    def _remove_node(self, node):\n"
        "        node.prev.next = node.next\n"
        "        node.next.prev = node.prev\n"
        "\n"
        "    def _move_to_head(self, node):\n"
        "        self._remove_node(node)\n"
        "        self._add_to_head(node)\n"
        "\n"
        "    def _remove_tail(self):\n"
        "        node = self.tail.prev\n"
        "        self._remove_node(node)\n"
        "        return node\n"
    )
    answer = (
        "### Problem Understanding\nImplement get and put in O(1) time.\n\n"
        "### Optimal Algorithm\nHash map gives key lookup, doubly linked list gives O(1) move and evict.\n\n"
        "### Code\n" + _fence(code, "python") + "\n\n"
        "### Approach\nUse keyToNode map for O(1) access. Move touched nodes to head. "
        "Evict tail.prev (LRU). All operations are O(1).\n\n"
        "### Complexity\n- Time Complexity: O(1) per get/put\n- Space Complexity: O(capacity)\n"
    )
    r = dsa_critic.critique("implement lru cache", answer)
    assert r["verified"] is True


def test_golden_java_lru_cache_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "import java.util.HashMap;\n"
        "import java.util.Map;\n"
        "class Node {\n"
        "    int key, val;\n"
        "    Node prev, next;\n"
        "    Node(int k, int v) { key = k; val = v; }\n"
        "}\n"
        "public class LRUCache {\n"
        "    private Map<Integer, Node> keyToNode = new HashMap<>();\n"
        "    private Node head = new Node(0, 0);\n"
        "    private Node tail = new Node(0, 0);\n"
        "    private int cap;\n"
        "    public LRUCache(int capacity) {\n"
        "        cap = capacity;\n"
        "        head.next = tail;\n"
        "        tail.prev = head;\n"
        "    }\n"
        "    public int get(int key) {\n"
        "        if (!keyToNode.containsKey(key)) return -1;\n"
        "        Node node = keyToNode.get(key);\n"
        "        moveToHead(node);\n"
        "        return node.val;\n"
        "    }\n"
        "    public void put(int key, int value) {\n"
        "        if (keyToNode.containsKey(key)) {\n"
        "            Node node = keyToNode.get(key);\n"
        "            node.val = value;\n"
        "            moveToHead(node);\n"
        "            return;\n"
        "        }\n"
        "        Node node = new Node(key, value);\n"
        "        keyToNode.put(key, node);\n"
        "        addToHead(node);\n"
        "        if (keyToNode.size() > cap) {\n"
        "            Node lru = tail.prev;\n"
        "            removeNode(lru);\n"
        "            keyToNode.remove(lru.key);\n"
        "        }\n"
        "    }\n"
        "    private void addToHead(Node node) {\n"
        "        node.prev = head;\n"
        "        node.next = head.next;\n"
        "        head.next.prev = node;\n"
        "        head.next = node;\n"
        "    }\n"
        "    private void removeNode(Node node) {\n"
        "        node.prev.next = node.next;\n"
        "        node.next.prev = node.prev;\n"
        "    }\n"
        "    private void moveToHead(Node node) {\n"
        "        removeNode(node);\n"
        "        addToHead(node);\n"
        "    }\n"
        "}\n"
    )
    answer = (
        "### Problem Understanding\nImplement get and put in O(1) time.\n\n"
        "### Optimal Algorithm\nHash map gives key lookup, doubly linked list gives O(1) move and evict.\n\n"
        "### Code\n" + _fence(code, "java") + "\n\n"
        "### Approach\nUse a keyToNode map for O(1) access. Move touched nodes to head. "
        "Evict tail.prev (LRU). All operations are O(1).\n\n"
        "### Complexity\n- Time Complexity: O(1) per get/put\n- Space Complexity: O(capacity)\n"
    )
    r = dsa_critic.critique("implement lru cache", answer)
    assert r["verified"] is True, r["feedback"]


def test_golden_cpp_lru_cache_passes(monkeypatch):
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
        "#include <unordered_map>\n"
        "using namespace std;\n"
        "struct Node {\n"
        "    int key;\n"
        "    int val;\n"
        "    Node* prev;\n"
        "    Node* next;\n"
        "    Node(int k, int v) : key(k), val(v), prev(nullptr), next(nullptr) {}\n"
        "};\n"
        "class LRUCache {\n"
        "    unordered_map<int, Node*> keyToNode;\n"
        "    Node* head;\n"
        "    Node* tail;\n"
        "    int cap;\n"
        "public:\n"
        "    LRUCache(int capacity) {\n"
        "        cap = capacity;\n"
        "        head = new Node(0, 0);\n"
        "        tail = new Node(0, 0);\n"
        "        head->next = tail;\n"
        "        tail->prev = head;\n"
        "    }\n"
        "    int get(int key) {\n"
        "        if (keyToNode.find(key) == keyToNode.end()) return -1;\n"
        "        Node* node = keyToNode[key];\n"
        "        moveToHead(node);\n"
        "        return node->val;\n"
        "    }\n"
        "    void put(int key, int value) {\n"
        "        if (keyToNode.find(key) != keyToNode.end()) {\n"
        "            Node* node = keyToNode[key];\n"
        "            node->val = value;\n"
        "            moveToHead(node);\n"
        "            return;\n"
        "        }\n"
        "        Node* node = new Node(key, value);\n"
        "        keyToNode[key] = node;\n"
        "        addToHead(node);\n"
        "        if ((int)keyToNode.size() > cap) {\n"
        "            Node* lru = tail->prev;\n"
        "            removeNode(lru);\n"
        "            keyToNode.erase(lru->key);\n"
        "        }\n"
        "    }\n"
        "    void addToHead(Node* node) {\n"
        "        node->prev = head;\n"
        "        node->next = head->next;\n"
        "        head->next->prev = node;\n"
        "        head->next = node;\n"
        "    }\n"
        "    void removeNode(Node* node) {\n"
        "        node->prev->next = node->next;\n"
        "        node->next->prev = node->prev;\n"
        "    }\n"
        "    void moveToHead(Node* node) {\n"
        "        removeNode(node);\n"
        "        addToHead(node);\n"
        "    }\n"
        "};\n"
    )
    answer = (
        "### Problem Understanding\nImplement get and put in O(1) time.\n\n"
        "### Optimal Algorithm\nHash map gives key lookup, doubly linked list gives O(1) move and evict.\n\n"
        "### Code\n" + _fence(code, "cpp") + "\n\n"
        "### Approach\nUse a keyToNode map for O(1) access. Move touched nodes to head. "
        "Evict tail->prev (LRU). All operations are O(1).\n\n"
        "### Complexity\n- Time Complexity: O(1) per get/put\n- Space Complexity: O(capacity)\n"
    )
    r = dsa_critic.critique("implement lru cache", answer)
    assert r["verified"] is True, r["feedback"]


def test_golden_python_lru_ordereddict_passes(monkeypatch):
    # A library-backed OrderedDict LRU is O(1) and must flow through the full critic
    # stack as VERIFIED. Regression: the algorithm critic used to reject it for lacking
    # a hand-rolled keyToNode map + doubly linked list.
    import dsa_critic
    import brain_manager
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    code = (
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
        "            self.cache.popitem(last=False)\n"
    )
    answer = (
        "### Problem Understanding\nImplement get and put in O(1) time.\n\n"
        "### Optimal Algorithm\nUse an OrderedDict: move_to_end on access keeps recency "
        "order; popitem(last=False) evicts the least recently used in O(1).\n\n"
        "### Code\n" + _fence(code, "python") + "\n\n"
        "### Approach\nEach access moves the key to the most-recent end; eviction removes "
        "the oldest entry. All operations are O(1).\n\n"
        "### Complexity\n- Time Complexity: O(1) per get/put\n- Space Complexity: O(capacity)\n"
    )
    r = dsa_critic.critique("implement lru cache", answer)
    assert r["verified"] is True, r["feedback"]


def test_java_public_constructor_no_return_passes():
    # Regression: a public constructor must NOT be flagged for 'no return statement'.
    import compile_verifier
    text = _fence(
        "public class Counter {\n"
        "    private int count;\n"
        "    public Counter(int start) {\n"
        "        count = start;\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("counter", text)
    assert ok is True, reason


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
