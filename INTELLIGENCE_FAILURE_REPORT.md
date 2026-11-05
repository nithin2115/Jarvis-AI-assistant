# INTELLIGENCE FAILURE REPORT
_Generated from a real offline run of `python -m bench` — no fabricated data. Reproducible: `python -m bench`._

## Method
Each adversarial case is a concrete answer containing ONE isolated failure mode, scored by Jarvis's own deterministic critics (no LLM, no network). A case that is correctly REJECTED proves the relevant validation exists; a case that ESCAPES (is wrongly accepted) is a real intelligence gap that would ship to users.

## Summary
- **Adversarial cases:** 27
- **Correctly rejected:** 27
- **Escapes (wrongly accepted):** 0 (0.0%)
- **Hallucination/fabrication catch rate:** 100.0%

## Baseline vs. current (Phase 3 reasoning gate)
The benchmark was also run with the Phase 3 contradiction gate disabled to measure the real gap it closes.
- **With reasoning gate disabled:** 3.7% escape rate (1 escape: dsa_contradictory_complexity)
- **With reasoning gate enabled:** 0.0% escape rate (0 escapes)
- **Gap closed:** the gate eliminated the only self-contradiction escape in the corpus, raising accuracy from 97.6% to 100.0%.

## Failure analysis (every adversarial case)
| Case | Failure mode | Root cause | Missing reasoning | Missing validation | Missing verification | Caught? | Stage |
|---|---|---|---|---|---|---|---|
| `dsa_lru_timestamp_scan` | on_scan | Claims O(1) but scans a whole map/list to find the eviction victim | Estimate complexity from the actual loop, not the intended one | Reject claimed-O(1) when an AST loop/min/max scans a collection | Re-derive Big-O from the code and compare to the claim | yes | dsa_complexity |
| `dsa_lfu_freq_scan` | on_scan | Claims O(1) but scans a whole map/list to find the eviction victim | Estimate complexity from the actual loop, not the intended one | Reject claimed-O(1) when an AST loop/min/max scans a collection | Re-derive Big-O from the code and compare to the claim | yes | dsa_output_quality |
| `dsa_swm_heap_remove` | arbitrary_heap_removal | Removes an arbitrary element from a heap (O(k)) | Recognise lazy-deletion is required for windowed heaps | Forbid heap.remove(x)/PriorityQueue.remove inside the window | Trace one window to confirm O(log k) per step | yes | dsa_complexity |
| `dsa_median_stream_sort` | sort_each_add | Sorts the whole stream on every insertion | Pick incremental structure (two heaps) for streaming median | Reject sort/insort per add when O(log n) is claimed | Dry-run addNum to confirm per-op cost | yes | dsa_complexity |
| `dsa_segtree_linear` | linear_scan | Linear range loop where a logarithmic structure is required | Choose a segment tree / BIT for range queries | Reject O(n) loop with an O(log n) claim | Verify query cost on a sample range | yes | dsa_complexity |
| `dsa_trie_wordlist_scan` | wordlist_scan | Stores words in a list and scans with startswith | Use a prefix tree with per-character nodes | Reject list+startswith for trie prefix queries | Confirm prefix lookup is O(L), not O(N·L) | yes | dsa_complexity |
| `dsa_dsu_no_compression` | no_path_compression | Union-Find without path compression / union by rank | Apply both optimisations for near-constant amortised cost | Reject DSU claiming alpha(n) without compression | Trace find() depth growth | yes | dsa_algorithm_critic |
| `dsa_dijkstra_no_heap` | no_heap | Dijkstra selecting the next node by linear scan (O(V^2)) | Use a priority queue keyed by tentative distance | Reject O(E log V) claim without a heap | Re-derive cost from the selection loop | yes | dsa_complexity |
| `dsa_duplicate_complexity` | duplicate_section | The same section is emitted twice (template artifact) | Plan one coherent answer, not stitched fragments | Reject repeated section headers (dsa_output_quality) | Scan the final answer for duplicate structure | yes | dsa_output_quality |
| `dsa_placeholder_stub` | placeholder | Method bodies are stubs (pass/TODO/NotImplementedError) | Finish every method before returning | Reject placeholder/stub bodies (dsa_structure) | Compile-check the code mentally | yes | dsa_structure |
| `dsa_contradictory_complexity` | contradiction | The solution states two different time complexities for itself | Re-read the final answer and ensure exactly one consistent Big-O claim | Reject multiple distinct stated complexities (dsa_reasoning) | State the actual asymptotic cost of the implementation and label any alternative as rejected | yes | dsa_reasoning |
| `dsa_all_o1_list_remove` | on_scan | Claims O(1) but scans a whole map/list to find the eviction victim | Estimate complexity from the actual loop, not the intended one | Reject claimed-O(1) when an AST loop/min/max scans a collection | Re-derive Big-O from the code and compare to the claim | yes | dsa_output_quality |
| `debug_fabricated_file` | fabricated_patch | Invents a full 'patched file' for code never seen | Ask for evidence before patching | Reject a fabricated file when no code/trace was given (debug_critic) | Confirm the user actually supplied the code | yes | debug_critic |
| `review_truncated_refactor` | truncated | Refactor/code trails off ('rest unchanged') | Emit the complete refactor | Reject truncation markers (codereview_critic) | Verify no omission markers remain | yes | response_quality |
| `sql_duplicate_index` | duplicate_index | Proposes a redundant left-prefix index | Check existing indexes before adding | Reject duplicate/redundant indexes (sql_critic) | Validate each index against the query shape | yes | sql_critic |
| `sql_mismatched_index` | mismatched_index | Index leading column unused by the query | Match index columns to WHERE/JOIN/ORDER BY | Reject indexes whose lead column has no predicate | Verify the planner would use the index | yes | sql_critic |
| `sql_invalid_partition` | invalid_pg_partition | Invalid PostgreSQL partition DDL (MySQL syntax) | Use dialect-correct DDL | Reject `VALUES LESS THAN` in Postgres | Validate DDL against the target engine | yes | sql_critic |
| `sql_missing_plan_nodes` | missing_explain_nodes | EXPLAIN section omits relevant plan node types | Explain Seq/Index/Bitmap Scan, Sort, Hash Aggregate | Require plan-node coverage (sql_critic) | Map the query to its expected plan | yes | sql_critic |
| `sql_missing_cost_benefit` | missing_tradeoffs | Optimizations lack cost/benefit justification | State the tradeoff of each change | Require cost/benefit per optimization | Confirm every change is justified | yes | sql_critic |
| `sql_nonsargable` | nonsargable_predicate | Non-sargable predicate defeats the index | Keep predicates sargable or add an expression index | Reject function-wrapped columns without expr index | Check index usability for each predicate | yes | sql_critic |
| `sd_inconsistent_qps` | capacity_order_of_magnitude | Capacity numbers off by orders of magnitude | Derive capacity from scale (QPS, storage, fleet) | Reject internally inconsistent capacity (sysdesign_critic) | Recompute requests/sec and storage from inputs | yes | sysdesign_critic |
| `sd_handwavy_capacity` | handwavy_capacity | Capacity is hand-wavy ('a large number of servers') | Show the back-of-envelope math | Reject capacity with no numbers | Quantify each capacity dimension | yes | sysdesign_critic |
| `sd_infra_only` | infra_namedrop_no_domain | Name-drops Redis/Kafka/DB without the domain | Address the system's core domain challenges | Reject infra-only designs (sysdesign_critic) | Map components to domain requirements | yes | sysdesign_critic |
| `sd_missing_sections` | missing_mandatory_sections | Design omits mandatory sections | Cover all required design sections | Require the mandatory section set | Checklist the sections before shipping | yes | sysdesign_critic |
| `sd_diagram_missing_tiers` | diagram_missing_tiers | Architecture diagram omits tiers (Queue/Storage) | Trace the request through all seven tiers | Require a full request-path diagram | Walk the diagram end to end | yes | sysdesign_critic |
| `sd_social_missing_deepdive` | missing_domain_deepdive | Recognised domain missing its deep-dives | Include domain-specific deep-dives (feed/fan-out, etc.) | Require domain deep-dives (sysdesign_critic) | Verify the domain checklist | yes | sysdesign_critic |
| `fs_missing_docker` | missing_docker_dir | Full-stack build omits the docker/ directory | Ship all four mandatory directories | Require frontend/backend/database/docker (fullstack_critic) | Verify the folder structure | yes | fullstack_critic |

## Escapes — prioritised fixes
No escapes in the current corpus: every adversarial failure mode is caught by an existing deterministic stage.

## False rejects (good answers wrongly blocked)
None: every golden answer is accepted by the deterministic gate.
