# FINAL BENCHMARK REPORT
_Offline-deterministic run (2026-06-22 21:30:30). Reproducible: `python -m bench`._

## Corpus
- **Total cases:** 41 (golden 14, adversarial 27)
- **By agent:** DSA_AGENT 17, DEBUG_AGENT 2, CODE_REVIEW_AGENT 2, SQL_AGENT 9, SYSTEM_DESIGN_AGENT 9, FULLSTACK_AGENT 2

## Headline metrics (Jarvis deterministic critics)
| Metric | Value |
|---|---|
| Accuracy (verdict matches ground truth) | 100.0% |
| Compilation success (golden code) | 100.0% |
| Hallucination/escape rate (adversarial accepted) | 0.0% |
| Completeness (golden accepted) | 100.0% |
| Reasoning quality (golden DSA core-stage coverage) | 100.0% (avg 4.0 stages) |

## Before/after baseline (Phase 3 reasoning gate)
| Metric | Gate disabled | Gate enabled | Delta |
|---|---|---|---|
| Accuracy | 97.6% | 100.0% | +2.4 pp |
| Escape rate | 3.7% | 0.0% | -3.7 pp |
| Golden completeness | 100.0% | 100.0% | 0.0 pp |
| Compilation success | 100.0% | 100.0% | 0.0 pp |
| Escape cases | dsa_contradictory_complexity | none | closed |

## Per-agent accuracy
| Agent | Cases | Correct | Accuracy |
|---|---|---|---|
| DSA_AGENT | 17 | 17 | 100.0% |
| DEBUG_AGENT | 2 | 2 | 100.0% |
| CODE_REVIEW_AGENT | 2 | 2 | 100.0% |
| SQL_AGENT | 9 | 9 | 100.0% |
| SYSTEM_DESIGN_AGENT | 9 | 9 | 100.0% |
| FULLSTACK_AGENT | 2 | 2 | 100.0% |

## Success criteria
| Criterion | Probe case | Result |
|---|---|---|
| Solve LFU correctly | `dsa_lfu_freq_scan` | PASS |
| Solve LRU correctly | `dsa_lru_timestamp_scan` | PASS |
| Solve Sliding Window Median correctly | `dsa_swm_heap_remove` | PASS |
| Solve Median-from-Stream correctly | `dsa_median_stream_sort` | PASS |
| Reject non-repetitive failures (duplicate sections) | `dsa_duplicate_complexity` | PASS |
| Reject incomplete/placeholder answers | `dsa_placeholder_stub` | PASS |

## Head-to-head vs external models
_Not run in this pass._ External head-to-head needs API keys and budget. With keys set (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`), run:

```
python -m bench --live
```

This asks each model the golden queries with Jarvis's own agent prompts and scores their answers through the identical critics.
