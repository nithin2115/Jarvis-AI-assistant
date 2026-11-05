# QUALITY FILTERS
_Deterministic output filters that reject low-quality answers before they ship, with the corpus evidence for each._

## Filter inventory
| Category (user spec) | Filter module | Caught in corpus |
|---|---|---|
| Duplicate sections (complexity/approach/code twice) | dsa_output_quality / response_quality_critic | 4 |
| Incomplete answers (missing imports/classes/methods) | compile_verifier / dsa_structure | 1 |
| Hallucinated production claims / fabricated code | debug_critic / domain critics | 1 |
| Wrong complexity | dsa_complexity | 6 |
| Suboptimal algorithm / data structure | dsa_algorithm_critic / lfu_critic | 1 |
| Foreign/templated sections | verifier_agent template isolation | 0 |
| Self-contradiction | dsa_reasoning | 1 |

## Rejecting-stage distribution (adversarial corpus)
| Stage | Cases rejected |
|---|---|
| `dsa_complexity` | 6 |
| `sql_critic` | 6 |
| `sysdesign_critic` | 6 |
| `dsa_output_quality` | 3 |
| `dsa_algorithm_critic` | 1 |
| `dsa_structure` | 1 |
| `dsa_reasoning` | 1 |
| `debug_critic` | 1 |
| `response_quality` | 1 |
| `fullstack_critic` | 1 |

## Uncovered categories (escapes -> filters to add)
None — every adversarial case in the corpus is filtered.

## Baseline (Phase 3 reasoning gate disabled)
With the self-contradiction filter disabled, the same corpus produced 3.7% escapes: dsa_contradictory_complexity. Re-enabling the gate closes this gap and returns the escape rate to 0.0%.
