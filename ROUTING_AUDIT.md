# ROUTING AUDIT — Specialist Selection

Measures how reliably `router.route_agent` (weighted keyword scoring over
`WEIGHTED_CONFIG`) sends a query to the correct specialist.

## Methodology (reproducible)
- **Corpus:** `tests/routing_corpus.py` — 185 hand-labeled prompts across all 7
  specialists + the general fallback. Labels are the agent a competent engineer
  would expect; the set deliberately includes paraphrases and cross-domain traps.
- **Harness:** `routing_corpus.evaluate(route_agent)` runs every prompt through the
  real router and reports overall accuracy, per-agent recall, and each misroute.
- **Gate:** `tests/test_routing_audit.py` (overall ≥ 0.97, per-agent ≥ 0.90).
- **Run:** `python -m pytest tests/test_routing_audit.py -v`

> Note: `PROJECT_BUILDER_AGENT` and `FULLSTACK_AGENT` load the **same** prompt
> (`FULLSTACK_AGENT.md`) and KB (`FULLSTACK_STANDARDS.md`), so a swap between those
> two is functionally a no-op; it is still scored strictly here.

## Results

| | Baseline | After fixes |
|---|---|---|
| **Overall accuracy** | **85.95%** (159/185) | **99.46%** (184/185) |

| Agent | Baseline recall | After fixes |
|-------|-----------------|-------------|
| DEBUG_AGENT | 0.70 (21/30) | **0.97** (29/30) |
| PROJECT_BUILDER_AGENT | 0.95 (19/20) | **1.00** (20/20) |
| SYSTEM_DESIGN_AGENT | 1.00 (25/25) | **1.00** (25/25) |
| SQL_AGENT | 0.92 (23/25) | **1.00** (25/25) |
| CODE_REVIEW_AGENT | 0.55 (11/20) | **1.00** (20/20) |
| DSA_AGENT | 0.91 (32/35) | **1.00** (35/35) |
| FULLSTACK_AGENT | 0.87 (13/15) | **1.00** (15/15) |
| GENERAL_ASSISTANT_AGENT | 1.00 (15/15) | **1.00** (15/15) |

## Root causes of the baseline misroutes
1. **CODE_REVIEW had only STRONG phrases, no MED/WEAK** (worst at 55%). Natural
   review asks ("is this idiomatic", "code smells", "critique my implementation",
   "give me feedback", "clean up this function", "make it more maintainable") matched
   nothing and fell through to GENERAL.
2. **DEBUG missed full exception class names.** `classnotfound` did not match
   `ClassNotFoundException` (the word-boundary guard rejects the trailing `exception`),
   and `nosuchmethod` did not match `NoSuchMethodError`.
3. **DEBUG missed behavioral-bug vocabulary:** "deadlock", "infinite loop", "race
   condition", "memory leak", "test is failing", "returns null", "won't run", "hangs".
4. **SQL missed analytic syntax:** "window function", "CTE", "group by", "upsert".
5. **DSA missed common problem nouns:** "subarray", "substring", "palindrome",
   "fibonacci", "memoized".
6. **FULLSTACK missed `oauth2`** (the trailing digit broke the `oauth` word boundary)
   **and spelled-out "role based access control"** (only `rbac` was present).
7. **PROJECT_BUILDER** lost "starter template for a Vue app" to FULLSTACK on the bare
   `vue` keyword.

## Fixes applied (`router.py` `WEIGHTED_CONFIG`)
- **CODE_REVIEW:** added STRONG `code smell(s)`, `review my code`; MED `idiomatic`,
  `readability`, `maintainability`, `best practices`, `clean up`, `critique`,
  `code quality`, `quality issues`; WEAK `review`, `feedback`, `improvements`,
  `maintainable`, `readable`, `audit`.
- **DEBUG:** added full exception names (`classnotfoundexception`,
  `nosuchmethoderror`, `indexoutofboundsexception`, `arrayindexoutofboundsexception`,
  `illegalargumentexception`, `illegalstateexception`,
  `concurrentmodificationexception`, `numberformatexception`, `classcastexception`)
  and behavioral terms (`failing`, `fails`, `hangs`, `freezes`, `deadlock`,
  `race condition`, `memory leak`, `infinite loop`, `won't run`, `returns null`,
  `not matching`, `off by one`).
- **SQL:** added `window function`, `cte`, `group by`, `upsert`, `denormalize`,
  `stored procedure`, `foreign key`, `primary key`.
- **DSA:** added `subarray`, `substring`, `palindrome`, `palindromic`, `fibonacci`,
  `memoized`.
- **FULLSTACK:** added STRONG `oauth2`; MED `role based access control`,
  `access control`.
- **PROJECT_BUILDER:** added STRONG `starter template`, `starter kit`.

All edits keep the existing tie-break priority order
(DEBUG → PROJECT_BUILDER → SYSTEM_DESIGN → SQL → CODE_REVIEW → DSA → FULLSTACK →
GENERAL). The pre-existing 159-case routing/router/audit suite still passes
(no regressions).

## Remaining known gap (honest)
- **1 miss:** *"The for loop is skipping the last element"* → GENERAL. It contains
  **no** error/debug vocabulary at all — it purely describes wrong behavior. Catching
  it reliably needs semantic understanding, not keywords (this is exactly finding
  **F1** in `ROOT_CAUSE_ANALYSIS.md`). Rather than overfit a brittle `skipping`
  keyword, it is left as a documented limitation. A future semantic/embedding
  fallback for sub-threshold scores would close it without false positives.

## How to extend
Add `(query, EXPECTED_AGENT)` rows to `CORPUS` in `tests/routing_corpus.py` and run
the gate. New misroutes print with their actual vs. expected agent for fast triage.
