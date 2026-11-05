# DSA VALIDATION

How DSA answers are validated **deterministically** (no LLM) before the LLM critic
ever runs. Order is defined by `dsa_critic.critique` (`dsa_critic.py:13`).

## Validation stack (in execution order)

| # | Stage | Module | What it enforces |
|---|-------|--------|------------------|
| 1 | Complexity | `dsa_complexity.analyze` | Claimed Big-O vs. actual implementation (AST-aware): rejects "sorted() claimed O(n)", Dijkstra/A* without a heap, single-heap median streams, "topological sort = sorted()", fake O(1) scans |
| 2 | Structure | `dsa_structure.check` | Mandatory sections for solve requests; rejects placeholder/stub bodies; logical-compile sanity |
| 3 | Compile | `compile_verifier.check` | Language-specific compile (syntax, missing imports/headers, invalid decls, multiple mains) for solution attempts |
| 4 | Output quality | `dsa_output_quality.check` | Duplicate sections, template artifacts, unfinished sentences, unexplained O(1), production-grade gaps (validation/encapsulation/tests) |
| 5 | LFU | `lfu_critic.check` | LFU eviction correctness, LRU tie-break, required structures (freq map + DLL/buckets), O(1) proof |
| 6 | Algorithm-specific | `dsa_algorithm_critic.check` | Per-algorithm structural correctness (table below) |
| 7 | LLM critic | `dsa_critic` (LLM) | Final optimality/correctness judgement |

## Algorithm-specific coverage (`dsa_algorithm_critic.py`)

| Algorithm | Defining check | Rejected anti-pattern |
|-----------|----------------|-----------------------|
| Sliding Window Median | two heaps + lazy deletion (delayed map) + offer/poll/peek | `heap.remove()` direct removal |
| LRU Cache | hash map + doubly linked list, O(1) | heap/priority-queue (O(log n)), sentinel-only eviction, missing components |
| Trie | TrieNode + children map + isEnd + insert/search/startsWith | set-of-words masquerading as a trie |
| Segment Tree | build + update + query + tree representation | prefix-sum array masquerading as segment tree |
| **Fenwick Tree (NEW)** | **lowbit walk `i & -i`** + update + prefix-sum query + 1-indexed array | **linear prefix-sum array with no lowbit** |
| Union Find | parent + rank/size + path compression + find/union | naive union without rank/path compression |
| Rate Limiter | capacity + window/timestamp + tokens + named algorithm | `sleep`/busy-wait/spin-lock |
| **Top-K / Kth-largest (NEW)** | **size-K heap / quickselect / bucket** | **full `sort()` of the raw input to pick K** (when no heap/quickselect and no frequency map) |

> Dijkstra, A*, two-heap median stream, and topological-sort optimality are enforced
> by `dsa_complexity.py` (stage 1), not the algorithm critic — verified by
> `test_dijkstra_no_heap_rejected`, `test_dijkstra_with_heap_accepted`,
> `test_dijkstra_custom_heap_class_accepted`, and the `MEDIAN_STREAM_*` cases.

## What changed in this phase
Two genuinely-missing validators were added (no prior coverage existed anywhere in
the codebase — confirmed by search):
- **Fenwick Tree** — the lowbit operation `i & -i` is mandatory; a plain prefix-sum
  array (O(n) update) is correctly rejected as "not a Fenwick tree".
- **Top-K / Kth-largest** — rejects the classic "sort the whole array to grab one
  element" anti-pattern, steering to a size-K heap (O(n log k)) or quickselect
  (O(n) avg). A "count-then-sort over a frequency map" answer for top-K-frequent is
  deliberately **tolerated** (a common, reasonable solution) to avoid false rejects.

Both are **conservative**: they only fire when the query matches the algorithm AND a
code solution is present (`dsa_structure.is_solution_attempt`); conceptual questions
and unrelated queries always pass; any exception fails open.

## Test coverage
- `tests/test_dsa_algorithm_critic.py` — **25 tests**, including new golden-pass +
  adversarial-reject pairs:
  - `test_fenwick_good_passes`, `test_fenwick_without_lowbit_rejected`
  - `test_top_k_heap_passes`, `test_top_k_quickselect_passes`,
    `test_top_k_full_sort_rejected`, `test_top_k_frequent_count_then_sort_passes`
- `tests/test_dsa.py` + `tests/test_dsa_output_quality.py` — complexity/structure/
  output-quality coverage.
- **Full DSA suite: 118 passed** (`pytest tests/test_dsa.py tests/test_dsa_algorithm_critic.py tests/test_dsa_output_quality.py`).

## Known limitations (honest)
- A generic "implement a min heap" has **no** dedicated structural validator (only
  the complexity check) — deterministic validation of an arbitrary heap is low-value
  and error-prone, so it defers to the LLM critic.
- The Top-K full-sort guard is intentionally lenient for frequency-map solutions, so a
  genuinely suboptimal `sorted(Counter(...))` for very large distinct sets passes the
  deterministic gate and relies on stage 1 / the LLM critic.
