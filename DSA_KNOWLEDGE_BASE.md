# DSA Knowledge Base

Canonical optimal patterns and complexity facts. Use these exact approaches for the
classic problems below; do NOT invent a slower variant. Every complexity you state
MUST match the code you wrote.

## Complexity Facts (non-negotiable)
- A comparison sort (`sorted()`, `list.sort()`, `Arrays.sort`, `Collections.sort`,
  `std::sort`) is **O(n log n)** — it can NEVER be described as O(n). Only
  counting / radix / bucket sort are O(n), and only under integer-key constraints.
- Membership test in a **list/array** is O(n); in a **hash set/map** it is O(1).
  Saying O(n) overall while doing `x in list` inside a loop is wrong (it is O(n^2)).
- Removing an **arbitrary** element from a binary heap / `PriorityQueue` is **O(k)**,
  not O(log k). Only the head pop/poll is O(log k). "Lazy deletion" means you NEVER call
  `heap.remove(element)` — you keep a `delayed`/`removed` count map and prune stale heads.
- A true **O(1)** operation does NOT hide a scan: `min(...)`/`max(...)` over a collection,
  `sorted(...)`, or a `for`/`while` loop over a whole map/list is at least O(n). Maintain the
  value incrementally (counter, auxiliary stack, `minFreq`) for genuine O(1).
- Building a heap with `heapify` is O(n); pushing n items one by one is O(n log n).
- A hash map gives **average** O(1) get/put — not guaranteed worst case.
- Recursion without memoization on overlapping subproblems is exponential, not
  polynomial. State O(2^n) unless you memoize.

## Arrays & Strings
- **Two Sum** -> hash map of value->index, single pass. O(n) time, O(n) space.
- **Three Sum** -> sort + two pointers. O(n^2) time, O(1) extra space.
- **Subarray sum equals K** -> prefix sum + hash map of counts. O(n).
- **Maximum subarray** -> Kadane's algorithm. O(n).
- **Product of array except self** -> prefix/suffix products. O(n) time, O(1) extra.
- **Longest substring without repeating chars** -> sliding window + last-seen map. O(n).
- **Anagram grouping** -> sort key or 26-count key + hash map. O(n·k) / O(n·k log k).

## Two Pointers / Sliding Window
- **Sliding Window Maximum** -> monotonic deque of indices. O(n) time, O(k) space.
- **Sliding Window Median** -> **Two Heaps + Lazy Deletion**. Max-heap (lower half),
  min-heap (upper half), balanced so size diff <= 1. Track a `delayed` count map for
  elements leaving the window and prune invalid heads lazily. **NEVER** call
  `heap.remove(element)` / `PriorityQueue.remove(x)` inside the window (that is O(k)
  and makes the solution O(n·k)). Target O(n log k) time, O(k) space.
- **Minimum window substring** -> sliding window + need/have counts. O(n).
- **Trapping rain water** -> two pointers with left/right max. O(n) time, O(1) space.

## Stacks / Queues / Monotonic
- **Valid parentheses** -> stack. O(n).
- **Next greater element** / **Daily temperatures** -> monotonic decreasing stack. O(n).
- **Largest rectangle in histogram** -> monotonic stack. O(n).
- **Min stack / getMin in O(1)** -> auxiliary stack of running minima. O(1) per op.

## Linked Lists
- **Reverse a linked list** -> iterative 3-pointer swap. O(n) time, O(1) space.
- **Detect cycle** -> Floyd's tortoise & hare. O(n) time, O(1) space.
- **Merge k sorted lists** -> min-heap of heads. O(n log k).
- **LRU Cache** -> HashMap + doubly linked list (or `OrderedDict`). O(1) get/put.
- **LFU Cache** -> HashMap of key->node, HashMap of freq->doubly linked list, and an
  incrementally maintained `minFreq`. O(1) get/put. NEVER scan the freq map for the min.

## Trees & Tries
- **Traversals** -> recursive or explicit stack; level order uses a queue (BFS). O(n).
- **Lowest common ancestor (binary tree)** -> single recursion. O(n).
- **Validate BST** -> in-order traversal must be strictly increasing, or min/max bounds. O(n).
- **Serialize/deserialize** -> pre-order with null markers. O(n).
- **Prefix search / autocomplete** -> Trie: each node has a children map (or `array[26]`) and
  an `is_end` flag. insert / search / startsWith are O(L). Scanning a word list with
  `startswith` is O(N·L) and is NOT a trie.
- **Range sum/min with point updates** -> **Segment Tree** (recurse children `2*node`,
  `2*node+1` at `mid`, combine) or a **Fenwick/BIT** (`i & -i`). Query and update are O(log n);
  a linear loop over the range is O(n) and wrong for the O(log n) claim.

## Graphs
- **Shortest path, unweighted** -> BFS. O(V+E).
- **Shortest path, non-negative weights** -> Dijkstra with a min-heap keyed by tentative
  distance. O(E log V). Without a heap it is a linear min-scan = O(V^2), so never claim a log
  factor for a heap-less Dijkstra.
- **Shortest path with a heuristic** -> **A\***: min-heap ordered by `f = g + h` with an
  admissible heuristic (Manhattan/Euclidean). No heuristic => it is just Dijkstra/BFS, not A*.
- **Shortest path, negative weights** -> Bellman-Ford. O(V·E).
- **All-pairs shortest path** -> Floyd-Warshall. O(V^3).
- **Connected components / cycle (undirected)** -> Union-Find or DFS. ~O(V+E).
- **Union-Find (DSU)** -> `find` with **path compression** (`parent[x] = find(parent[x])`)
  **and** union by rank/size give ~O(α(n)) amortized. Claiming O(1)/O(α) without path
  compression, or doing BFS/DFS per connectivity query, is wrong.
- **Topological sort** -> Kahn's (in-degree + queue) or DFS post-order with cycle detection.
  O(V+E). A comparison `sort()` never yields a valid topological order.
- **Minimum spanning tree** -> Kruskal (union-find) or Prim (heap). O(E log V).

## Heaps / Selection
- **K-th largest / Top-K** -> size-K min-heap. O(n log k) time, O(k) space.
- **Median from a data stream** -> two balanced heaps. O(log n) add, O(1) median.
- **Merge k sorted streams** -> min-heap. O(n log k).

## Dynamic Programming
- **0/1 Knapsack** -> 2D (or 1D rolling) DP over items × capacity. O(n·W).
- **Coin change (min coins)** -> 1D DP over amount. O(amount·coins).
- **Longest common subsequence** -> 2D DP. O(n·m).
- **Longest increasing subsequence** -> patience sorting + binary search. O(n log n).
- **Edit distance** -> 2D DP. O(n·m).
- Always state whether you used top-down memoization or bottom-up tabulation, and the
  exact dimensions of the DP table for the complexity.

## Intervals
- **Merge intervals / insert interval** -> sort by start, sweep. O(n log n).
- **Meeting rooms (min rooms)** -> min-heap of end times, or sweep line. O(n log n).

## Validation checklist before you answer
1. The code is complete and compiles (no `...`, no truncation, balanced braces/fences).
2. The stated time and space complexity exactly match the implementation.
3. You used the canonical optimal pattern above (no accidental brute force).
4. You did not claim O(n) while sorting, nor O(1) while scanning a whole map/list.
