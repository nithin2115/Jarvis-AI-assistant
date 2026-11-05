"""
Phase 2 — DSA Algorithm Critic regression suite.

Pure-function tests for dsa_algorithm_critic.check covering Sliding Window Median,
LRU Cache, Trie, Segment Tree, Union Find, and Rate Limiter.
Run:
    python -m pytest tests/test_dsa_algorithm_critic.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import dsa_algorithm_critic as dac


def _f(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Sliding Window Median
# ---------------------------------------------------------------------------
def test_median_two_heaps_passes():
    text = (
        "# Approach\nUse two heaps (max heap for lower half, min heap for upper half) "
        "with a delayed map for lazy deletion.\n\n"
        "# Code\n" + _f(
            "class DualHeap:\n"
            "    def __init__(self):\n"
            "        self.small = []  # max heap (negated)\n"
            "        self.large = []  # min heap\n"
            "        self.delayed = {}\n"
            "    def prune(self, heap):\n"
            "        while heap and self.delayed.get(-heap[0]):\n"
            "            self.delayed[-heap[0]] -= 1\n"
            "            heapq.heappop(heap)\n"
            "    def offer(self, num):\n"
            "        heapq.heappush(self.small, -num)\n"
            "    def poll(self, num):\n"
            "        self.delayed[num] = self.delayed.get(num, 0) + 1\n"
            "    def peek(self):\n"
            "        return -self.small[0]"
        ) + "\n\n"
        "# Complexity\nO(log n) per operation.\n"
    )
    ok, reason = dac.check("sliding window median", text)
    assert ok is True, reason


def test_median_heap_remove_rejected():
    text = (
        "# Approach\nUse a priority queue.\n\n"
        "# Code\n" + _f(
            "class MedianFinder:\n"
            "    def remove(self, num):\n"
            "        self.maxHeap.remove(num)"
        ) + "\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason = dac.check("sliding window median", text)
    assert ok is False
    assert "heap" in reason.lower() or "remove" in reason.lower()


def test_median_missing_lazy_deletion_rejected():
    text = (
        "# Approach\nUse two heaps.\n\n"
        "# Code\n" + _f(
            "class MedianFinder:\n"
            "    def __init__(self):\n"
            "        self.small = []\n"
            "        self.large = []"
        ) + "\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason = dac.check("sliding window median", text)
    assert ok is False
    assert "lazy" in reason.lower() or "deletion" in reason.lower() or "heap" in reason.lower()


# ---------------------------------------------------------------------------
# LRU Cache
# ---------------------------------------------------------------------------
def test_lru_cache_good_passes():
    text = (
        "# Approach\nUse a HashMap from key to node and a doubly linked list. "
        "get and put are O(1). Move accessed node to front; evict from tail.\n\n"
        "# Code\n" + _f(
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.capacity = capacity\n"
            "        self.keyToNode = {}\n"
            "        self.head = Node(0,0)\n"
            "        self.tail = Node(0,0)\n"
            "        self.head.next = self.tail\n"
            "        self.tail.prev = self.head\n"
            "    def get(self, key):\n"
            "        if key not in self.keyToNode: return -1\n"
            "        node = self.keyToNode[key]\n"
            "        self._move_to_front(node)\n"
            "        return node.val\n"
            "    def put(self, key, val):\n"
            "        if key in self.keyToNode:\n"
            "            self._move_to_front(self.keyToNode[key])\n"
            "        if len(self.keyToNode) >= self.capacity:\n"
            "            evicted = self.tail.prev\n"
            "            self._remove(evicted)\n"
            "            del self.keyToNode[evicted.key]\n"
        ) + "\n\n"
        "# Complexity\nO(1) get and put.\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is True, reason


def test_lru_cache_sentinel_rejected():
    text = (
        "# Approach\nUse a sentinel node.\n\n"
        "# Code\n" + _f(
            "class LRUCache:\n"
            "    def evict(self):\n"
            "        node = self.dummy.next\n"
            "        self.remove(node)"
        ) + "\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is False
    assert "sentinel" in reason.lower() or "head" in reason.lower()


def test_lru_cache_heap_rejected():
    text = (
        "# Approach\nUse a priority queue keyed by last-access timestamp.\n\n"
        "# Code\n" + _f(
            "import heapq\n"
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.pq = []\n"
            "        self.keyToNode = {}\n"
            "    def get(self, key):\n"
            "        heapq.heappush(self.pq, (self.t, key))\n"
            "        return -1"
        ) + "\n\n"
        "# Complexity\nO(log n) per operation. doubly linked list not used.\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is False
    assert "heap" in reason.lower() or "priority" in reason.lower()


def test_lru_cache_missing_components_rejected():
    text = (
        "# Approach\nUse a list.\n\n"
        "# Code\n" + _f(
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.capacity = capacity\n"
            "        self.items = []"
        ) + "\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is False
    assert "keytonode" in reason.lower() or "linked" in reason.lower() or "o(1)" in reason.lower()


def test_lru_ordereddict_accepted():
    # A library-backed OrderedDict LRU is O(1) and MUST be accepted, even though it
    # carries no hand-rolled keyToNode map / doubly linked list.
    text = (
        "# Approach\nUse an OrderedDict; move the key to the most-recent end on "
        "access and pop the oldest on overflow. get and put are O(1).\n\n"
        "# Code\n" + _f(
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
        ) + "\n\n"
        "# Complexity\nO(1) get and put via OrderedDict.\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is True, reason


def test_lru_linkedhashmap_accepted():
    # A Java LinkedHashMap in access order with removeEldestEntry is an O(1) LRU.
    text = (
        "# Approach\nExtend LinkedHashMap in access order and override "
        "removeEldestEntry to evict the least recently used entry in O(1).\n\n"
        "# Code\n" + _f(
            "import java.util.LinkedHashMap;\n"
            "import java.util.Map;\n"
            "public class LRUCache<K, V> extends LinkedHashMap<K, V> {\n"
            "    private final int capacity;\n"
            "    public LRUCache(int capacity) {\n"
            "        super(capacity, 0.75f, true);\n"
            "        this.capacity = capacity;\n"
            "    }\n"
            "    @Override\n"
            "    protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {\n"
            "        return size() > capacity;\n"
            "    }\n"
            "}\n", "java"
        ) + "\n\n"
        "# Complexity\nO(1) get and put.\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is True, reason


def test_lru_timestamp_scan_rejected():
    # Scanning a timestamp map for the oldest key is O(n) — must be rejected.
    text = (
        "# Approach\nStore values in a dict and timestamps in another dict; on "
        "overflow, find the oldest by scanning the timestamps.\n\n"
        "# Code\n" + _f(
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        self.cap = capacity\n"
            "        self.store = {}\n"
            "        self.time = {}\n"
            "        self.clock = 0\n"
            "    def get(self, key):\n"
            "        if key not in self.store:\n"
            "            return -1\n"
            "        self.clock += 1\n"
            "        self.time[key] = self.clock\n"
            "        return self.store[key]\n"
            "    def put(self, key, value):\n"
            "        if len(self.store) >= self.cap and key not in self.store:\n"
            "            oldest = min(self.time, key=self.time.get)\n"
            "            del self.store[oldest]\n"
            "            del self.time[oldest]\n"
            "        self.store[key] = value\n"
            "        self.clock += 1\n"
            "        self.time[key] = self.clock\n"
        ) + "\n\n"
        "# Complexity\nClaimed O(1) get and put.\n"
    )
    ok, reason = dac.check("lru cache", text)
    assert ok is False
    assert "scan" in reason.lower() or "o(n)" in reason.lower()


# ---------------------------------------------------------------------------
# Trie
# ---------------------------------------------------------------------------
def test_trie_good_passes():
    text = (
        "# Approach\nTrie node with children map and isEnd flag.\n\n"
        "# Code\n" + _f(
            "class TrieNode:\n"
            "    def __init__(self):\n"
            "        self.children = {}\n"
            "        self.isEnd = False\n"
            "\n"
            "class Trie:\n"
            "    def insert(self, word):\n"
            "        node = self.root\n"
            "        for ch in word:\n"
            "            node = node.children.setdefault(ch, TrieNode())\n"
            "        node.isEnd = True\n"
            "    def search(self, word):\n"
            "        node = self._find(word)\n"
            "        return node is not None and node.isEnd\n"
            "    def startsWith(self, prefix):\n"
            "        return self._find(prefix) is not None"
        ) + "\n\n"
        "# Complexity\nO(m) per operation.\n"
    )
    ok, reason = dac.check("implement trie", text)
    assert ok is True, reason


def test_trie_missing_components_rejected():
    text = (
        "# Approach\nUse a set of words.\n\n"
        "# Code\n" + _f(
            "class Trie:\n"
            "    def __init__(self):\n"
            "        self.words = set()\n"
            "    def insert(self, word):\n"
            "        self.words.add(word)"
        ) + "\n\n"
        "# Complexity\nO(m)\n"
    )
    ok, reason = dac.check("implement trie", text)
    assert ok is False
    assert "children" in reason.lower() or "isend" in reason.lower() or "search" in reason.lower()


# ---------------------------------------------------------------------------
# Segment Tree
# ---------------------------------------------------------------------------
def test_segment_tree_good_passes():
    text = (
        "# Approach\nSegment tree with build, update, and query.\n\n"
        "# Code\n" + _f(
            "class SegmentTree:\n"
            "    def __init__(self, nums):\n"
            "        n = len(nums)\n"
            "        self.tree = [0] * (4 * n)\n"
            "        self.build(nums, 0, 0, n - 1)\n"
            "    def build(self, nums, node, l, r):\n"
            "        if l == r:\n"
            "            self.tree[node] = nums[l]\n"
            "            return\n"
            "        mid = (l + r) // 2\n"
            "        self.build(nums, 2 * node + 1, l, mid)\n"
            "        self.build(nums, 2 * node + 2, mid + 1, r)\n"
            "        self.tree[node] = self.tree[2*node+1] + self.tree[2*node+2]\n"
            "    def update(self, index, val):\n"
            "        self._update(0, 0, n - 1, index, val)\n"
            "    def query(self, left, right):\n"
            "        return self._query(0, 0, n - 1, left, right)"
        ) + "\n\n"
        "# Complexity\nO(log n) per operation.\n"
    )
    ok, reason = dac.check("segment tree", text)
    assert ok is True, reason


def test_segment_tree_missing_components_rejected():
    text = (
        "# Approach\nPrefix sums.\n\n"
        "# Code\n" + _f(
            "class NumArray:\n"
            "    def __init__(self, nums):\n"
            "        self.prefix = [0] * (len(nums) + 1)\n"
            "        for i, v in enumerate(nums):\n"
            "            self.prefix[i+1] = self.prefix[i] + v"
        ) + "\n\n"
        "# Complexity\nO(n) update, O(1) query.\n"
    )
    ok, reason = dac.check("segment tree", text)
    assert ok is False
    assert "build" in reason.lower() or "tree" in reason.lower() or "update" in reason.lower() or "query" in reason.lower()


# ---------------------------------------------------------------------------
# Union Find
# ---------------------------------------------------------------------------
def test_union_find_good_passes():
    text = (
        "# Approach\nUnion by rank with path compression.\n\n"
        "# Code\n" + _f(
            "class UnionFind:\n"
            "    def __init__(self, n):\n"
            "        self.parent = list(range(n))\n"
            "        self.rank = [0] * n\n"
            "    def find(self, x):\n"
            "        if self.parent[x] != x:\n"
            "            self.parent[x] = self.parent[self.parent[x]]\n"
            "            return self.find(self.parent[x])\n"
            "        return x\n"
            "    def union(self, x, y):\n"
            "        rx, ry = self.find(x), self.find(y)\n"
            "        if rx == ry: return\n"
            "        if self.rank[rx] < self.rank[ry]:\n"
            "            self.parent[rx] = ry\n"
            "        elif self.rank[rx] > self.rank[ry]:\n"
            "            self.parent[ry] = rx\n"
            "        else:\n"
            "            self.parent[ry] = rx\n"
            "            self.rank[rx] += 1"
        ) + "\n\n"
        "# Complexity\nO(alpha(n)) per operation.\n"
    )
    ok, reason = dac.check("union find", text)
    assert ok is True, reason


def test_union_find_missing_components_rejected():
    text = (
        "# Approach\nNaive union.\n\n"
        "# Code\n" + _f(
            "class UnionFind:\n"
            "    def __init__(self, n):\n"
            "        self.parent = list(range(n))\n"
            "    def union(self, x, y):\n"
            "        self.parent[self.find(x)] = self.find(y)\n"
            "    def find(self, x):\n"
            "        while self.parent[x] != x:\n"
            "            x = self.parent[x]\n"
            "        return x"
        ) + "\n\n"
        "# Complexity\nO(n)\n"
    )
    ok, reason = dac.check("union find", text)
    assert ok is False
    assert "rank" in reason.lower() or "path compression" in reason.lower()


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------
def test_rate_limiter_token_bucket_passes():
    text = (
        "# Approach\nToken bucket algorithm with capacity and refill rate.\n\n"
        "# Code\n" + _f(
            "class TokenBucket:\n"
            "    def __init__(self, capacity, fill_rate):\n"
            "        self.capacity = capacity\n"
            "        self.tokens = capacity\n"
            "        self.fill_rate = fill_rate\n"
            "        self.last_time = time.time()\n"
            "    def allow_request(self, tokens=1):\n"
            "        now = time.time()\n"
            "        self.tokens += (now - self.last_time) * self.fill_rate\n"
            "        self.tokens = min(self.tokens, self.capacity)\n"
            "        self.last_time = now\n"
            "        if self.tokens >= tokens:\n"
            "            self.tokens -= tokens\n"
            "            return True\n"
            "        return False"
        ) + "\n\n"
        "# Complexity\nO(1) per allow_request.\n"
    )
    ok, reason = dac.check("rate limiter", text)
    assert ok is True, reason


def test_rate_limiter_sleep_rejected():
    text = (
        "# Approach\nBlock requests until tokens available.\n\n"
        "# Code\n" + _f(
            "class RateLimiter:\n"
            "    def allow_request(self):\n"
            "        while self.tokens < 1:\n"
            "            time.sleep(0.1)\n"
            "        self.tokens -= 1"
        ) + "\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = dac.check("rate limiter", text)
    assert ok is False
    assert "sleep" in reason.lower()


def test_rate_limiter_missing_components_rejected():
    text = (
        "# Approach\nCount requests.\n\n"
        "# Code\n" + _f(
            "class RateLimiter:\n"
            "    def __init__(self):\n"
            "        self.count = 0\n"
            "    def allow_request(self):\n"
            "        self.count += 1"
        ) + "\n\n"
        "# Complexity\nO(1)\n"
    )
    ok, reason = dac.check("rate limiter", text)
    assert ok is False
    assert "capacity" in reason.lower() or "window" in reason.lower() or "token" in reason.lower()


# ---------------------------------------------------------------------------
# Fenwick Tree (Binary Indexed Tree)
# ---------------------------------------------------------------------------
def test_fenwick_good_passes():
    text = (
        "# Approach\nBinary indexed tree with lowbit walk for O(log n) update/query.\n\n"
        "# Code\n" + _f(
            "class Fenwick:\n"
            "    def __init__(self, n):\n"
            "        self.n = n\n"
            "        self.tree = [0] * (n + 1)\n"
            "    def update(self, i, delta):\n"
            "        while i <= self.n:\n"
            "            self.tree[i] += delta\n"
            "            i += i & -i\n"
            "    def query(self, i):\n"
            "        s = 0\n"
            "        while i > 0:\n"
            "            s += self.tree[i]\n"
            "            i -= i & -i\n"
            "        return s"
        ) + "\n\n"
        "# Complexity\nO(log n) per update and query.\n"
    )
    ok, reason = dac.check("fenwick tree for prefix sums", text)
    assert ok is True, reason


def test_fenwick_without_lowbit_rejected():
    text = (
        "# Approach\nUse a prefix-sum array.\n\n"
        "# Code\n" + _f(
            "class Fenwick:\n"
            "    def __init__(self, nums):\n"
            "        self.prefix = [0] * (len(nums) + 1)\n"
            "        for i, v in enumerate(nums):\n"
            "            self.prefix[i + 1] = self.prefix[i] + v\n"
            "    def query(self, i):\n"
            "        return self.prefix[i + 1]\n"
            "    def update(self, i, v):\n"
            "        for j in range(i + 1, len(self.prefix)):\n"
            "            self.prefix[j] += v"
        ) + "\n\n"
        "# Complexity\nO(n) update.\n"
    )
    ok, reason = dac.check("binary indexed tree", text)
    assert ok is False
    assert "lowbit" in reason.lower() or "i & -i" in reason.lower()


# ---------------------------------------------------------------------------
# Top-K / Kth-largest
# ---------------------------------------------------------------------------
def test_top_k_heap_passes():
    text = (
        "# Approach\nKeep a size-k min heap; the root is the kth largest.\n\n"
        "# Code\n" + _f(
            "import heapq\n"
            "def kth_largest(nums, k):\n"
            "    heap = []\n"
            "    for x in nums:\n"
            "        heapq.heappush(heap, x)\n"
            "        if len(heap) > k:\n"
            "            heapq.heappop(heap)\n"
            "    return heap[0]"
        ) + "\n\n"
        "# Complexity\nO(n log k).\n"
    )
    ok, reason = dac.check("find the kth largest element in an array", text)
    assert ok is True, reason


def test_top_k_quickselect_passes():
    text = (
        "# Approach\nQuickselect partitions around a pivot to find the kth largest in O(n) average.\n\n"
        "# Code\n" + _f(
            "def kth_largest(nums, k):\n"
            "    def partition(lo, hi):\n"
            "        pivot = nums[hi]; i = lo\n"
            "        for j in range(lo, hi):\n"
            "            if nums[j] > pivot:\n"
            "                nums[i], nums[j] = nums[j], nums[i]; i += 1\n"
            "        nums[i], nums[hi] = nums[hi], nums[i]; return i\n"
            "    lo, hi = 0, len(nums) - 1\n"
            "    while True:\n"
            "        p = partition(lo, hi)\n"
            "        if p == k - 1: return nums[p]\n"
            "        elif p < k - 1: lo = p + 1\n"
            "        else: hi = p - 1"
        ) + "\n\n"
        "# Complexity\nO(n) average.\n"
    )
    ok, reason = dac.check("kth largest element", text)
    assert ok is True, reason


def test_top_k_full_sort_rejected():
    text = (
        "# Approach\nSort the array and index it.\n\n"
        "# Code\n" + _f(
            "def kth_largest(nums, k):\n"
            "    nums.sort()\n"
            "    return nums[-k]"
        ) + "\n\n"
        "# Complexity\nO(n log n).\n"
    )
    ok, reason = dac.check("find the kth largest element in an array", text)
    assert ok is False
    assert "sort" in reason.lower() and ("heap" in reason.lower() or "quickselect" in reason.lower())


def test_top_k_frequent_count_then_sort_passes():
    """Counting + sorting a frequency map is a reasonable, accepted answer."""
    text = (
        "# Approach\nCount frequencies, then sort the distinct keys by count.\n\n"
        "# Code\n" + _f(
            "from collections import Counter\n"
            "def top_k_frequent(nums, k):\n"
            "    freq = Counter(nums)\n"
            "    return [x for x, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:k]]"
        ) + "\n\n"
        "# Complexity\nO(d log d) where d is the number of distinct values.\n"
    )
    ok, reason = dac.check("top k frequent elements", text)
    assert ok is True, reason


# ---------------------------------------------------------------------------
# Gate / conceptual safety
# ---------------------------------------------------------------------------
def test_conceptual_query_passes():
    ok, reason = dac.check("what is a trie", "A trie is a tree-like data structure.")
    assert ok is True


def test_non_algo_query_passes():
    ok, reason = dac.check("two sum", "# Code\n```python\ndef twoSum(): pass\n```\n")
    assert ok is True


def test_dsa_critic_wiring_no_llm():
    """dsa_critic.critique must reject a bad LRU cache without LLM call."""
    import dsa_critic
    import brain_manager
    original_ask = brain_manager.ask
    brain_manager.ask = lambda *a, **kw: ("VERIFIED", "fake")
    try:
        text = (
            "# Approach\nUse a sentinel node.\n\n"
            "# Code\n" + _f(
                "class LRUCache:\n"
                "    def evict(self):\n"
                "        node = self.dummy.next\n"
                "        self.remove(node)"
            ) + "\n\n"
            "# Complexity\nO(1)\n"
        )
        result = dsa_critic.critique("lru cache", text)
        assert result["verified"] is False
    finally:
        brain_manager.ask = original_ask
