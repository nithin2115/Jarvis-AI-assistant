# CODE REVIEW VALIDATION

How Code Review answers are validated **deterministically** (`codereview_critic.critique`,
run from `verifier_agent.verify`). A real review must critique BEFORE the code, cover
multiple dimensions, and ship a COMPLETE refactor.

## Validation logic

| # | Check | Behavior |
|---|-------|----------|
| 0 | Is it a review? | A clarification ("paste your code") defers → PASS |
| 1 | No truncation | Rejects `// TODO`, "rest unchanged", "omitted for brevity" in the refactor |
| 2 | Refactor present | A review must end with the complete refactored code in a fenced block |
| 3 | Critique present | A critique section must precede the code (no code-dump-only) |
| **4** | **Dimension breadth (NEW)** | **Must address ≥ 3 distinct review dimensions** |
| 5 | LLM verifier | Final judgement |

## What changed in this phase
`_has_critique` accepted **any single** critique term, so a one-note review ("rename
`x` for readability") passed. A senior review examines multiple facets. The critic now
requires coverage of at least **3 of 7** dimensions, detected leniently anywhere in the
prose (`_DIMENSIONS`):

- **correctness** (logic errors, edge cases, wrong output)
- **bugs** (null/NPE, exceptions, races, leaks, error handling, boundaries)
- **security** (injection, XSS/CSRF/SSRF, auth, secrets, sanitization, encryption)
- **performance** (slow paths, N+1, latency, memory, throughput)
- **complexity** (Big-O, time/space complexity, algorithmic cost)
- **maintainability** (readability, naming, duplication/DRY, cohesion, nesting)
- **design** (architecture, separation of concerns, layering, patterns, SOLID)

The threshold is **3** (not 7 literal headers) on purpose: the canonical template
groups facets into combined headers (e.g. "Performance & Security",
"Readability & Maintainability"), so demanding 7 separate headings would reject the
intended format. Breadth-of-coverage captures the real requirement without false
rejects — `FULL_REVIEW` covers 4 areas and passes.

## Test coverage (`tests/test_codereview.py` — 14 tests)
New:
- `test_shallow_single_dimension_review_rejected` — readability-only review → reject
- `test_three_dimension_review_passes` — security + performance + maintainability → pass
- `test_full_review_covers_multiple_dimensions` — asserts `FULL_REVIEW` ≥ `MIN_DIMENSIONS`

Pre-existing (still green): is-review detection, has-critique detection, full review
passes, truncated refactor rejected, review-without-code rejected, code-without-critique
rejected, clarification defers, verifier short-circuit, KB wiring.

Run: `python -m pytest tests/test_codereview.py -v` → **14 passed**.
End-to-end regression check (`test_audit.py` + `test_response_quality.py`) → **81 passed**.

## Coverage vs. the Code Review mandate
Correctness ✓, complexity ✓, bugs ✓, security ✓, maintainability ✓, performance ✓
(all as breadth dimensions), complete refactored code ✓ (no truncation/TODO),
critique-before-code ordering ✓, foreign-section isolation ✓ (verifier blocks
System-Design/DSA sections from leaking into a review).

## Known limitations (honest)
- Breadth is measured by keyword coverage, so a review could mention a dimension
  shallowly and still count it. Depth-of-analysis per dimension is judged by the LLM
  verifier and the universal quality scorer (`response_quality_critic`).
- The critic does not execute the refactored code; correctness of the refactor itself
  is the LLM verifier's responsibility.
