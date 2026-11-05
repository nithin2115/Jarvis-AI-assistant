# SQL VALIDATION

How SQL optimization answers are validated **deterministically** before the LLM
verifier (`sql_critic.critique`, run from `verifier_agent.verify`). The critic is
conservative: clarifications and conceptual questions PASS; the strict template
applies only to genuine optimization requests.

## Validation stages (in order)

| # | Stage | Enforces |
|---|-------|----------|
| 0 | Clarification / conceptual pass-through | Asking for the missing query/schema, or a conceptual Q ("what is a covering index?"), is accepted — never forced into the template |
| 1 | SQL code present | An optimization answer must ship a fenced `sql` query, not prose-only advice |
| 2 | Concrete index | A real `CREATE INDEX` (cols + order, covering/partial) **or** explicit justification that no new index is needed |
| 3 | 11 mandatory sections | Problem Understanding, Root Cause, Query Analysis, Index Strategy, EXPLAIN/Execution Plan, Partitioning, Read Replica, Redis Caching, Monitoring, Tradeoffs, Final Optimized Query |
| 4a | Valid PG partition syntax | Rejects MySQL `VALUES LESS THAN`; requires RANGE/LIST/HASH declarative syntax |
| 4b | No duplicate/redundant index | Rejects a left-prefix duplicate of a composite index |
| 4c | Index matches the query | Every index's **leading column** must appear in a WHERE/JOIN/ORDER BY/GROUP BY predicate |
| 4d | EXPLAIN node-type literacy | Must discuss Seq Scan + Index/Bitmap Scan and ≥3 node types (Sort, Hash Aggregate) |
| 4e | Cost/benefit tradeoffs | Each optimization weighs COST (storage, write amplification, replica lag, staleness) vs BENEFIT (latency/throughput) |
| **4f** | **Sargability of the shipped query (NEW)** | **The Final Optimized Query must not defeat its own index** |
| 5 | LLM verifier | Final correctness/completeness judgement |

## What changed in this phase
The KB already teaches "sargable", but **no deterministic check enforced it**. A
"Final Optimized Query" could still:
- use a **leading-wildcard `LIKE '%...'`** (cannot use a B-tree index), or
- **wrap a predicate column in a function** (`WHERE DATE(created_at) = $2`,
  `WHERE LOWER(email) = $1`) — non-sargable, so the proposed index is unusable.

Stage **4f** now rejects both, with two deliberate exceptions to avoid false
positives:
- a **trigram/GIN/GiST or full-text** index (`pg_trgm`, `USING gin`, `to_tsvector`,
  `@@`) makes a wildcard/FTS predicate legitimate → pass;
- a **matching expression index** (`CREATE INDEX ... ON t (DATE(created_at))`) makes
  the function predicate sargable → pass.

The function check only fires on `func(col) <operator>` (the column on the indexed
side), so `col = LOWER($1)` (function on the parameter) is correctly **not** flagged.

## Test coverage (`tests/test_sql.py` — 31 tests)
New golden-pass + adversarial-reject:
- `test_leading_wildcard_final_query_rejected` — `LIKE '%urgent%'` in the fix → reject
- `test_nonsargable_function_predicate_rejected` — `DATE(created_at) = $2` → reject
- `test_expression_index_makes_function_sargable_passes` — same predicate **with** a
  matching expression index → pass

These fixtures keep the proposed index matching the query predicates, so they
exercise the new sargability stage specifically (not the pre-existing
index/predicate-mismatch stage). The full 11-section `FULL_ANSWER` still passes.

Run: `python -m pytest tests/test_sql.py -v` → **31 passed**.

## Coverage vs. the SQL mandate
Query optimization ✓, indexing strategy ✓, composite/redundant indexes ✓, covering
indexes (`INCLUDE`) ✓, execution plans / EXPLAIN literacy ✓, partitioning ✓, sharding
✓ (Partitioning Strategy synonyms), caching ✓ (Redis section), read replicas ✓,
tradeoffs ✓, **sargability of the shipped query ✓ (new)**.

## Known limitations (honest)
- The function-sargability regex covers the common scalar functions; an exotic or
  user-defined function wrapping a column may pass the deterministic gate and rely on
  the LLM verifier.
- Sargability is checked on the **Final Optimized Query** section only (the shipped
  fix); the "before" query shown in Query Analysis/EXPLAIN is intentionally exempt.
