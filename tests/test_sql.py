"""
Phase 4 — SQL critic / knowledge-base regression suite.

Deterministic tests for sql_critic plus verifier short-circuit behavior (no network
for the reject paths). The verifier PASS-through path stubs brain_manager. Run:
    python -m pytest tests/test_sql.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import sql_critic

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sql(code):
    return "```sql\n" + code + "\n```"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Building blocks so negative fixtures can swap exactly one part out.
_INDEX_DDL = _sql(
    "CREATE INDEX idx_orders_cust_created\n"
    "ON orders (customer_id, created_at DESC) INCLUDE (total);"
)
_PART_DDL = _sql(
    "CREATE TABLE orders (\n"
    "  id bigserial, customer_id bigint NOT NULL,\n"
    "  created_at timestamptz NOT NULL, total numeric\n"
    ") PARTITION BY RANGE (created_at);\n\n"
    "CREATE TABLE orders_2024_01 PARTITION OF orders\n"
    "  FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');"
)
_FINAL_DDL = _sql(
    "SELECT id, total FROM orders\n"
    "WHERE customer_id = $1 AND created_at >= $2\n"
    "ORDER BY created_at DESC LIMIT 50;"
)
_EXPLAIN_BODY = (
    "Before: EXPLAIN ANALYZE shows a Seq Scan on orders (100M rows) feeding a Sort for the "
    "ORDER BY, with most rows Removed by Filter. After the composite index the plan becomes an "
    "Index Scan (Index Only Scan because total is INCLUDEd) and the Sort node disappears because "
    "the index already returns rows in created_at order. For low-selectivity OR predicates "
    "Postgres would instead pick a Bitmap Index Scan + Bitmap Heap Scan. A Hash Aggregate would "
    "appear only with a GROUP BY; this query has none. Estimated vs actual rows now match."
)
_TRADE_BODY = (
    "Cost/benefit per optimization: the composite index costs ~2 GB storage and adds write "
    "amplification on every insert, but its benefit is converting a Seq Scan + Sort into an "
    "Index-Only Scan, cutting p95 from ~200ms to ~5ms — a clear win for this read-heavy path. "
    "The replica costs sub-second lag in exchange for ~3x read throughput; the Redis cache costs "
    "up to 60s staleness but removes ~90% of DB hits."
)

_S_INDEX = "### Index Strategy\n" + _INDEX_DDL + "\n\n"
_S_EXPLAIN = "### EXPLAIN / Execution Plan Analysis\n" + _EXPLAIN_BODY + "\n\n"
_S_PART = "### Partitioning Strategy\nRange-partition orders by created_at (monthly):\n" + _PART_DDL + "\n\n"
_S_TRADE = "### Tradeoffs\n" + _TRADE_BODY + "\n\n"

FULL_ANSWER = (
    "### Problem Understanding\n"
    "User fetches last 50 orders for a customer with time filter; SLA p95 < 200ms; orders table ~100M rows.\n\n"
    "### Root Cause Analysis\n"
    "Seq Scan on orders: no index supports the (customer_id, created_at) filter.\n\n"
    "### Query Analysis\n"
    "Filters on customer_id + created_at, orders by created_at DESC with LIMIT 50; one narrow range filter.\n\n"
    + _S_INDEX
    + _S_EXPLAIN
    + _S_PART
    + "### Read Replica Strategy\n"
    "Route this read-only query to a replica; tolerate sub-second replication lag.\n\n"
    "### Redis Caching Strategy\n"
    "Cache recent per-customer orders in Redis keyed by customer_id, TTL 60s, busting on new order insert.\n\n"
    "### Monitoring\n"
    "Track p99 latency, slow-query log > 200ms, buffer hit ratio, replication lag.\n\n"
    + _S_TRADE
    + "### Final Optimized Query\n" + _FINAL_DDL
)

NO_INDEX_JUSTIFIED = FULL_ANSWER.replace(
    _S_INDEX,
    "### Index Strategy\n"
    "No new index is required — the query is fully covered by an existing index "
    "on (customer_id, created_at).\n\n",
)

# Duplicate / redundant left-prefix index added alongside the composite one.
DUP_INDEX_ANSWER = FULL_ANSWER.replace(
    _INDEX_DDL,
    _sql(
        "CREATE INDEX idx_orders_cust_created\n"
        "ON orders (customer_id, created_at DESC) INCLUDE (total);\n"
        "CREATE INDEX idx_orders_cust ON orders (customer_id);"
    ),
)

# Index whose leading column is not used by any predicate in the query.
MISMATCH_INDEX_ANSWER = FULL_ANSWER.replace(
    _INDEX_DDL, _sql("CREATE INDEX idx_orders_status ON orders (status);")
)

# MySQL `VALUES LESS THAN` syntax, invalid in PostgreSQL.
INVALID_PARTITION_ANSWER = FULL_ANSWER.replace(
    _PART_DDL,
    _sql(
        "CREATE TABLE orders (\n"
        "  id bigint, customer_id bigint, created_at datetime\n"
        ")\n"
        "PARTITION BY RANGE (YEAR(created_at)) (\n"
        "  PARTITION p2023 VALUES LESS THAN (2024),\n"
        "  PARTITION p2024 VALUES LESS THAN (2025)\n"
        ");"
    ),
)

# EXPLAIN section that fails to explain the plan node types.
MISSING_NODE_TYPES_ANSWER = FULL_ANSWER.replace(
    _EXPLAIN_BODY, "After the index the Seq Scan becomes an Index Scan."
)

# Tradeoffs that list only costs, no benefit weighing.
MISSING_COST_BENEFIT_ANSWER = FULL_ANSWER.replace(
    _TRADE_BODY,
    "The index uses storage and adds write amplification. The replica adds replication "
    "lag. The cache adds staleness.",
)

# Final query keeps the index-matching predicates but adds a leading-wildcard LIKE
# (defeats a B-tree index). No trigram/GIN index is proposed -> reject.
LEADING_WILDCARD_ANSWER = FULL_ANSWER.replace(
    _FINAL_DDL,
    _sql(
        "SELECT id, total FROM orders\n"
        "WHERE customer_id = $1 AND created_at >= $2 AND notes LIKE '%urgent%'\n"
        "ORDER BY created_at DESC LIMIT 50;"
    ),
)

# Final query wraps an indexed column in a function (non-sargable); no expression
# index is proposed -> reject.
NONSARGABLE_FUNC_ANSWER = FULL_ANSWER.replace(
    _FINAL_DDL,
    _sql(
        "SELECT id, total FROM orders\n"
        "WHERE customer_id = $1 AND DATE(created_at) = $2\n"
        "ORDER BY created_at DESC LIMIT 50;"
    ),
)

# Same function predicate, but WITH a matching expression index -> sargable -> PASS.
EXPR_INDEX_ANSWER = FULL_ANSWER.replace(
    _INDEX_DDL,
    _sql(
        "CREATE INDEX idx_orders_cust_created\n"
        "ON orders (customer_id, created_at DESC) INCLUDE (total);\n"
        "CREATE INDEX idx_orders_day ON orders (DATE(created_at));"
    ),
).replace(
    _FINAL_DDL,
    _sql(
        "SELECT id, total FROM orders\n"
        "WHERE customer_id = $1 AND DATE(created_at) = $2\n"
        "ORDER BY created_at DESC LIMIT 50;"
    ),
)


# ---------------------------------------------------------------------------
# Clarification + conceptual (must PASS / defer)
# ---------------------------------------------------------------------------
def test_clarification_passes():
    text = ("I need the exact SQL query and the table schema to optimize this "
            "accurately. Please provide the query and schema; I won't invent tables.")
    assert sql_critic.critique("Optimize this", text)["verified"] is True


def test_conceptual_question_defers():
    # Not an optimization request -> strict template does not apply.
    text = ("An INNER JOIN returns only matching rows from both tables, while a "
            "LEFT JOIN returns all rows from the left table plus matches.")
    assert sql_critic.critique(
        "What is the difference between INNER JOIN and LEFT JOIN?", text
    )["verified"] is True


def test_conceptual_index_question_not_force_templated():
    # "what is a covering index" has no action word -> defers (no false reject).
    text = "A covering index includes all columns a query needs, enabling index-only scans."
    assert sql_critic.critique("What is a covering index?", text)["verified"] is True


# ---------------------------------------------------------------------------
# Generic / incomplete optimization answers (must REJECT)
# ---------------------------------------------------------------------------
def test_generic_prose_only_rejected():
    text = ("You should add indexes on the columns you filter by, avoid SELECT *, "
            "and make sure statistics are up to date.")
    r = sql_critic.critique("Optimize my slow query", text)
    assert r["verified"] is False
    assert "code block" in r["feedback"].lower()


def test_code_without_index_rejected_as_generic():
    text = ("### Code\n" + _sql("SELECT id FROM orders WHERE customer_id = 5;") +
            "\nJust rewrite it like that and it'll be faster.")
    r = sql_critic.critique("This query is slow, optimize it", text)
    assert r["verified"] is False
    assert "create index" in r["feedback"].lower()


def test_code_and_index_but_incomplete_template_rejected():
    text = ("### Index Strategy\n" + _sql("CREATE INDEX idx ON orders (customer_id);") +
            "\n### Code\n" + _sql("SELECT id FROM orders WHERE customer_id = 5;"))
    r = sql_critic.critique("optimize this slow query", text)
    assert r["verified"] is False
    assert "missing" in r["feedback"].lower()


def test_missing_final_optimized_query_section_rejected():
    text = FULL_ANSWER.replace("### Final Optimized Query\n", "### Code\n")
    r = sql_critic.critique("optimize this query", text)
    assert r["verified"] is False
    assert "final" in r["feedback"].lower()


def test_missing_problem_understanding_rejected():
    text = FULL_ANSWER.replace("### Problem Understanding\n", "### Context Removed\n", 1)
    r = sql_critic.critique("optimize this query", text)
    assert r["verified"] is False
    assert "problem understanding" in r["feedback"].lower()


# ---------------------------------------------------------------------------
# Complete optimization answers (must PASS)
# ---------------------------------------------------------------------------
def test_full_eleven_section_answer_passes():
    assert sql_critic.critique(
        "Optimize this slow PostgreSQL query at scale", FULL_ANSWER
    )["verified"] is True


def test_no_new_index_justified_passes():
    assert sql_critic.critique(
        "Optimize this slow query", NO_INDEX_JUSTIFIED
    )["verified"] is True


# ---------------------------------------------------------------------------
# Verifier integration (reject paths short-circuit BEFORE any LLM call)
# ---------------------------------------------------------------------------
def test_verifier_rejects_generic_sql_without_network():
    import verifier_agent
    r = verifier_agent.verify("SQL_AGENT", "optimize my slow query",
                              "Just add some indexes and avoid SELECT *.")
    assert r["verified"] is False


def test_verifier_rejects_foreign_section_in_sql():
    import verifier_agent
    text = ("### Index Strategy\n" + _sql("CREATE INDEX idx ON t (a);") +
            "\n### Edge Cases\n- empty input")
    r = verifier_agent.verify("SQL_AGENT", "optimize this slow query", text)
    assert r["verified"] is False
    assert "edge cases" in r["feedback"].lower()


def test_verifier_passes_full_sql_answer(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask",
                        lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("SQL_AGENT",
                              "Optimize this slow PostgreSQL query at scale", FULL_ANSWER)
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Knowledge base wiring
# ---------------------------------------------------------------------------
def test_sql_knowledge_base_file_exists():
    assert os.path.exists(os.path.join(BASE, "SQL_KNOWLEDGE_BASE.md"))


def test_sql_knowledge_base_injected_into_prompt():
    import router
    prompt = router.AGENT_PROMPTS[router.SQL_AGENT].lower()
    assert "leftmost-prefix" in prompt
    assert "sargable" in prompt


# ---------------------------------------------------------------------------
# Hardening v2 — ineffective/invalid recommendations on a COMPLETE template
# ---------------------------------------------------------------------------
def test_index_defs_parsing():
    defs = sql_critic._index_defs(
        _sql("CREATE INDEX i ON orders (customer_id, created_at DESC) INCLUDE (total);"))
    assert defs and defs[0]["table"] == "orders"
    assert defs[0]["cols"] == ["customer_id", "created_at"]


def test_predicate_columns_extraction():
    cols = sql_critic._predicate_columns(
        "SELECT id FROM orders WHERE customer_id = $1 AND created_at >= $2 ORDER BY created_at DESC")
    assert "customer_id" in cols and "created_at" in cols


def test_invalid_pg_partition_helper():
    assert sql_critic._invalid_pg_partition(
        "CREATE TABLE t PARTITION BY RANGE (d);\nPARTITION p VALUES LESS THAN (1)")
    assert sql_critic._invalid_pg_partition("CREATE TABLE t PARTITION BY HASH (id);") is None
    assert sql_critic._invalid_pg_partition("no partitioning here") is None


def test_node_type_coverage_helper():
    _, missing = sql_critic._node_type_coverage(_EXPLAIN_BODY)
    assert missing == []


def test_full_answer_passes_all_v2_checks():
    assert sql_critic.critique(
        "Optimize this slow PostgreSQL query at scale", FULL_ANSWER)["verified"] is True


def test_duplicate_index_rejected():
    r = sql_critic.critique("optimize this slow query at scale", DUP_INDEX_ANSWER)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "duplicate" in fb or "redundant" in fb


def test_mismatched_index_rejected():
    r = sql_critic.critique("optimize this slow query at scale", MISMATCH_INDEX_ANSWER)
    assert r["verified"] is False
    assert "match" in r["feedback"].lower()


def test_invalid_pg_partition_rejected():
    r = sql_critic.critique("optimize this slow query at scale", INVALID_PARTITION_ANSWER)
    assert r["verified"] is False
    assert "partition" in r["feedback"].lower()


def test_missing_plan_node_types_rejected():
    r = sql_critic.critique("optimize this slow query at scale", MISSING_NODE_TYPES_ANSWER)
    assert r["verified"] is False
    assert "bitmap scan" in r["feedback"].lower()


def test_missing_cost_benefit_rejected():
    r = sql_critic.critique("optimize this slow query at scale", MISSING_COST_BENEFIT_ANSWER)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "cost" in fb and "benefit" in fb


def test_leading_wildcard_final_query_rejected():
    r = sql_critic.critique("optimize this slow query at scale", LEADING_WILDCARD_ANSWER)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "wildcard" in fb or "sargable" in fb


def test_nonsargable_function_predicate_rejected():
    r = sql_critic.critique("optimize this slow query at scale", NONSARGABLE_FUNC_ANSWER)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "sargable" in fb or "function" in fb


def test_expression_index_makes_function_sargable_passes():
    r = sql_critic.critique("optimize this slow query at scale", EXPR_INDEX_ANSWER)
    assert r["verified"] is True, r["feedback"]


def test_verifier_rejects_mismatched_index_without_network():
    import verifier_agent
    r = verifier_agent.verify("SQL_AGENT", "optimize this slow query at scale", MISMATCH_INDEX_ANSWER)
    assert r["verified"] is False


def test_verifier_rejects_invalid_partition_without_network():
    import verifier_agent
    r = verifier_agent.verify("SQL_AGENT", "optimize this slow query at scale", INVALID_PARTITION_ANSWER)
    assert r["verified"] is False


def test_sql_prompt_carries_v2_hardening():
    import router
    low = router.AGENT_PROMPTS[router.SQL_AGENT].lower()
    for tok in ("execution plan", "seq scan", "index scan", "bitmap scan",
                "hash aggregate", "values less than", "duplicate", "cost/benefit"):
        assert tok in low, f"missing SQL hardening guidance: {tok!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
