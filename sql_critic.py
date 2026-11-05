"""Deterministic SQL critic (Phase 4).

Runs BEFORE the LLM verifier for the SQL agent to cheaply and reliably catch the
failure modes that matter for large-scale optimization answers:

  1. Generic, non-actionable SQL ("add some indexes", no real query / no concrete
     CREATE INDEX statements).
  2. A partial optimization template (missing any of the 11 mandatory sections,
     especially the critical seven: Root Cause Analysis, Index Strategy, EXPLAIN /
     Execution Plan Analysis, Partitioning Strategy, Monitoring, Tradeoffs, Final
     Optimized Query).
  3. Ineffective / invalid recommendations on an otherwise complete answer:
       - invalid PostgreSQL partition syntax (e.g., MySQL `VALUES LESS THAN`),
       - duplicate / redundant left-prefix indexes,
       - indexes whose leading column matches no query predicate (validated against
         the actual query shape),
       - an EXPLAIN section that does not explain the core plan node types
         (Seq Scan, Index Scan, Bitmap Scan, Sort, Hash Aggregate),
       - missing cost/benefit weighing for the optimizations.

It is intentionally conservative so correct answers are NEVER rejected:

  * If the agent correctly ASKS for the missing query/schema (clarification), PASS.
  * If the query is a CONCEPTUAL SQL question (not an optimization request), PASS and
    let the lenient LLM verifier judge it — the strict template does not apply.
  * The correctness/quality checks (3) run ONLY on a complete optimization template,
    so an incomplete answer is told to finish the template first.
"""
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.DOTALL)
_SQL_KEYWORDS = re.compile(
    r"\b(select|insert|update|delete|create|with|alter|merge|explain)\b", re.IGNORECASE
)
_CREATE_INDEX = re.compile(r"create\s+(?:unique\s+)?index", re.IGNORECASE)
_NO_INDEX_JUSTIFIED = re.compile(
    r"(no\s+(?:additional|new|extra)\s+index|already\s+indexed|"
    r"covered\s+by\s+(?:an?\s+)?existing\s+index|existing\s+index\s+suffices)",
    re.IGNORECASE,
)

# An optimization request -> the strict template applies. These are ACTION/scale
# signals, not topic words: bare "index" is intentionally excluded so a conceptual
# question like "what is a covering index?" is NOT forced into the strict template.
_OPTIMIZATION_HINTS = (
    "optimize", "optimization", "slow", "speed up", "speed-up", "faster",
    "performance", "scale", "scaling", "billion", "million", "large table",
    "huge table", "execution plan", "explain analyze", "taking too long", "timeout",
    "bottleneck", "high latency", "p99", "p95",
)

# Clarification signals (asking the user for the query/schema).
_ASK_HINTS = ("provide", "share", "send", "need the", "could you", "please give",
              "i need", "paste")

# 11 mandatory sections. We match headers leniently via synonyms, but ALL of them
# must be present for an optimization answer to pass.
_SECTIONS = (
    ("Problem Understanding", ("problem understanding", "problem statement",
                                "workload summary", "context & constraints",
                                "context and constraints")),
    ("Root Cause Analysis", ("root cause", "bottleneck analysis", "why it is slow",
                              "why the query is slow")),
    ("Query Analysis", ("query analysis", "query shape", "current query", "plan overview")),
    ("Index Strategy", ("index strategy", "indexing strategy", "indexes", "indexing")),
    ("EXPLAIN / Execution Plan Analysis", ("explain plan", "execution plan", "explain analyze", "query plan")),
    ("Partitioning Strategy", ("partitioning", "partition", "sharding")),
    ("Read Replica Strategy", ("read replica", "replicas", "replication")),
    ("Redis Caching Strategy", ("redis", "caching", "cache")),
    ("Monitoring", ("monitoring", "observability", "metrics & alerting", "metrics and alerting")),
    ("Tradeoffs", ("tradeoff", "trade-off", "trade off", "trade-offs")),
    ("Final Optimized Query", ("final optimized query", "final query", "optimized query")),
)

# EXPLAIN section must demonstrate literacy in the core plan node types.
_NODE_TYPES = (
    ("Seq Scan", re.compile(r"seq(?:uential)?\s+scan", re.IGNORECASE)),
    ("Index Scan", re.compile(r"index(?:[\s-]+only)?\s+scan", re.IGNORECASE)),
    ("Bitmap Scan", re.compile(r"bitmap(?:\s+(?:index|heap))?\s+scan", re.IGNORECASE)),
    ("Sort", re.compile(r"\bsort\b", re.IGNORECASE)),
    ("Hash Aggregate", re.compile(r"hash\s*aggregate", re.IGNORECASE)),
)
_EXPLAIN_SYNS = ("explain plan", "execution plan", "explain analyze", "query plan")
_TRADEOFF_SYNS = ("tradeoff", "trade-off", "trade off", "cost/benefit", "cost benefit")

# Parse `CREATE INDEX [name] ON table (cols) [INCLUDE (...)]`. The negative lookahead
# stops an omitted index name from swallowing the `ON` keyword.
_INDEX_DEF_RE = re.compile(
    r"create\s+(?:unique\s+)?index(?:\s+concurrently)?(?:\s+if\s+not\s+exists)?\s+"
    r"(?:(?!on\b)[a-z0-9_\"]+\s+)?"
    r"on\s+(?P<table>[a-z0-9_\".]+)\s*(?:using\s+\w+\s*)?"
    r"\(\s*(?P<cols>[^)]*?)\s*\)",
    re.IGNORECASE | re.DOTALL,
)

# Partition validity. Declarative PostgreSQL uses RANGE/LIST/HASH + FROM..TO / IN / WITH;
# `VALUES LESS THAN` is MySQL syntax and INVALID in PostgreSQL.
_PART_PRESENT_RE = re.compile(r"partition\s+by|partition\s+of", re.IGNORECASE)
_PART_METHOD_RE = re.compile(r"partition\s+by\s+([a-z]+)", re.IGNORECASE)
_MYSQL_PART_RE = re.compile(r"values\s+less\s+than", re.IGNORECASE)
_VALID_PART_METHODS = {"range", "list", "hash"}

# Cost/benefit weighing language (must co-occur in the Tradeoffs section).
_COST_CUE = re.compile(
    r"\bcost|storage|write\s+amplification|overhead|expensive|\blag\b|staleness|"
    r"maintenance|bloat", re.IGNORECASE)
_BENEFIT_CUE = re.compile(
    r"benefit|faster|speed\s*-?up|throughput|lower\s+latency|reduc|improv|"
    r"\bwin\b|cut(?:s|ting)?\b|fewer|avoid", re.IGNORECASE)

# Predicate / join / sort columns referenced by a query.
_PRED_OP_RE = re.compile(
    r"([a-z_][a-z0-9_]*)\s*(?:=|<|>|<=|>=|<>|!=|\blike\b|\bbetween\b|\bin\b|\bis\b)",
    re.IGNORECASE)
_ORDER_GROUP_RE = re.compile(
    r"(?:order|group)\s+by\s+(.+?)(?:\blimit\b|\boffset\b|\bhaving\b|\bwindow\b|;|$)",
    re.IGNORECASE | re.DOTALL)
_ORDER_STOPWORDS = {"asc", "desc", "nulls", "first", "last", "and", "or"}

# Sargability of the SHIPPED final query: a "fix" that still defeats its own index
# is not an optimization. We flag `func(col) <op> ...` and a leading-wildcard LIKE,
# unless a matching expression / trigram (GIN) index is also proposed.
_NONSARGABLE_FUNC_RE = re.compile(
    r"\b(?:lower|upper|year|month|day|date|date_trunc|trunc|to_char|substr|substring|"
    r"coalesce|cast|convert|abs|round|left|right|extract)\s*\([^()]*"
    r"\b[a-z_][a-z0-9_.]*\b[^()]*\)\s*(?:=|<|>|<=|>=|<>|!=|\blike\b|\bbetween\b|\bin\b)",
    re.IGNORECASE,
)
_LEADING_WILDCARD_RE = re.compile(r"\bi?like\b\s*'\s*%", re.IGNORECASE)
_TRIGRAM_INDEX_RE = re.compile(
    r"gin_trgm_ops|pg_trgm|using\s+gin|using\s+gist|to_tsvector|tsvector|@@",
    re.IGNORECASE,
)


def _code_blocks(text: str):
    return [m.group(1) for m in _FENCE.finditer(text or "")]


def _has_sql_code(text: str) -> bool:
    return any(_SQL_KEYWORDS.search(b) for b in _code_blocks(text))


def _header_lines(text: str):
    """Markdown/section headers only (so incidental prose mentions don't count)."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip().lower()
        if not s:
            continue
        if s.startswith("#") or s.startswith("**") or (s.endswith(":") and len(s) < 48):
            out.append(re.sub(r"[#*`:_]", "", s).strip())
    return out


def _count_sections(text: str):
    headers = _header_lines(text)
    present, missing = [], []
    for canonical, synonyms in _SECTIONS:
        if any(any(syn in h for syn in synonyms) for h in headers):
            present.append(canonical)
        else:
            missing.append(canonical)
    return present, missing


def _is_clarification(text: str) -> bool:
    """The agent asked for the query/schema instead of inventing one."""
    if _has_sql_code(text):
        return False
    low = (text or "").lower()
    asks = any(h in low for h in _ASK_HINTS)
    mentions = ("schema" in low or "query" in low or "table" in low)
    return asks and mentions and len(text or "") < 800


def _is_optimization_query(user_query: str) -> bool:
    q = (user_query or "").lower()
    return any(h in q for h in _OPTIMIZATION_HINTS)


def _markdown_sections(text: str):
    """Split into (cleaned_header, body) pairs using ONLY markdown headers as
    boundaries (so a short prose 'Label:' line never truncates a section body)."""
    sections, name, body = [], None, []
    for line in (text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("#") or low.startswith("**"):
            if name is not None:
                sections.append((name, "\n".join(body)))
            name = re.sub(r"[#*`:]", "", low).strip()
            body = []
        elif name is not None:
            body.append(line)
    if name is not None:
        sections.append((name, "\n".join(body)))
    return sections


def _section_body(text: str, synonyms):
    for name, body in _markdown_sections(text):
        if any(syn in name for syn in synonyms):
            return body
    return None


def _query_blocks(text: str):
    """Non-DDL code blocks — the actual queries, excluding CREATE/ALTER/etc DDL."""
    out = []
    for b in _code_blocks(text):
        if b.strip().lower().startswith(("create", "alter", "drop", "truncate")):
            continue
        out.append(b)
    return out


def _index_defs(text: str):
    """Parse CREATE INDEX statements -> [{table, cols|None, raw}]. cols is None for
    expression indexes we can't reliably validate by column name."""
    defs = []
    for m in _INDEX_DEF_RE.finditer(text or ""):
        cols_raw = m.group("cols") or ""
        if "(" in cols_raw:  # expression index — skip column validation
            key_cols = None
        else:
            key_cols = [c.strip().split()[0].strip('"').lower()
                        for c in cols_raw.split(",") if c.strip()]
            key_cols = [c for c in key_cols if c]
        table = (m.group("table") or "").split(".")[-1].strip('"').lower()
        defs.append({"table": table, "cols": key_cols, "raw": m.group(0)})
    return defs


def _predicate_columns(sql: str):
    """Columns used in WHERE / JOIN ON / GROUP BY / ORDER BY / HAVING predicates."""
    s = (sql or "").lower()
    cols = set()
    for m in _PRED_OP_RE.finditer(s):
        cols.add(m.group(1))
    for m in _ORDER_GROUP_RE.finditer(s):
        for tok in re.findall(r"[a-z_][a-z0-9_]*", m.group(1)):
            if tok not in _ORDER_STOPWORDS:
                cols.add(tok)
    cols.discard("")
    return cols


def _duplicate_index(defs):
    """Return (kept, redundant) when one index's keys are an exact/left-prefix
    duplicate of another on the same table, else None."""
    seen = []
    for d in defs:
        if not d["cols"]:
            continue
        for prev in seen:
            if prev["table"] != d["table"]:
                continue
            a, b = prev["cols"], d["cols"]
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if longer[:len(shorter)] == shorter:
                kept = prev if longer is (prev["cols"]) else d
                redundant = d if kept is prev else prev
                return (kept, redundant)
        seen.append(d)
    return None


def _mismatched_index(defs, predicate_cols):
    """Return the first index whose LEADING column is not used by any predicate."""
    if not predicate_cols:
        return None
    for d in defs:
        if not d["cols"]:
            continue
        if d["cols"][0] not in predicate_cols:
            return d
    return None


def _invalid_pg_partition(text: str):
    """Return an error string for invalid PostgreSQL partition syntax, else None."""
    t = text or ""
    if not _PART_PRESENT_RE.search(t):
        return None
    low = t.lower()
    is_mysql = "mysql" in low and "postgres" not in low
    if not is_mysql and _MYSQL_PART_RE.search(t):
        return ("MySQL `VALUES LESS THAN` is invalid in PostgreSQL declarative "
                "partitioning — use `PARTITION OF parent FOR VALUES FROM (...) TO (...)` "
                "(RANGE), `FOR VALUES IN (...)` (LIST), or `WITH (MODULUS m, REMAINDER r)` (HASH).")
    m = _PART_METHOD_RE.search(t)
    if m and m.group(1).lower() not in _VALID_PART_METHODS:
        return (f"`PARTITION BY {m.group(1).upper()}` is not a valid method — "
                "use RANGE, LIST, or HASH.")
    return None


def _node_type_coverage(explain_body: str):
    present = [name for name, rx in _NODE_TYPES if rx.search(explain_body or "")]
    missing = [name for name, _ in _NODE_TYPES if name not in present]
    return present, missing


def critique(user_query: str, response_text: str) -> dict:
    """Return {"verified": bool, "feedback": str}. Deterministic only."""
    text = response_text or ""

    # 1) Correctly asking for the missing query/schema is always acceptable.
    if _is_clarification(text):
        return {"verified": True, "feedback": ""}

    # 2) Conceptual SQL questions don't follow the optimization template — defer.
    if not _is_optimization_query(user_query):
        return {"verified": True, "feedback": ""}

    # 3) Genuine optimization request with an attempted answer -> enforce substance.
    if not _has_sql_code(text):
        logger.warning("[SQL_CRITIC] No SQL code block in an optimization answer")
        return {"verified": False, "feedback": (
            "Provide the Final Optimized Query in a fenced ```sql code block based on the "
            "user's actual schema — do not answer with prose-only generic advice."
        )}

    if not _CREATE_INDEX.search(text) and not _NO_INDEX_JUSTIFIED.search(text):
        logger.warning("[SQL_CRITIC] Generic answer: no concrete CREATE INDEX / justification")
        return {"verified": False, "feedback": (
            "Replace generic advice with a concrete Index Strategy: give the exact "
            "CREATE INDEX statement(s) (columns + order, covering/partial as needed), "
            "or explicitly justify why no new index is required."
        )}

    present, missing = _count_sections(text)
    if missing:
        logger.warning(f"[SQL_CRITIC] Incomplete template, missing: {missing}")
        return {"verified": False, "feedback": (
            "The SQL optimization answer is partial. Include ALL mandatory sections: "
            "Problem Understanding, Root Cause Analysis, Query Analysis, Index Strategy, "
            "EXPLAIN / Execution Plan Analysis, Partitioning Strategy, Read Replica Strategy, "
            "Redis Caching Strategy, Monitoring, Tradeoffs, and Final Optimized Query. "
            f"Missing: {', '.join(missing)}."
        )}

    # 4) Complete template -> scrutinize correctness/quality of the recommendations.

    # 4a) PostgreSQL partition syntax must be valid.
    part_err = _invalid_pg_partition(text)
    if part_err:
        logger.warning("[SQL_CRITIC] Invalid partition syntax")
        return {"verified": False, "feedback": "Fix the Partitioning Strategy: " + part_err}

    defs = _index_defs(text)

    # 4b) No duplicate / redundant left-prefix indexes.
    dup = _duplicate_index(defs)
    if dup:
        kept, redundant = ", ".join(dup[0]["cols"]), ", ".join(dup[1]["cols"])
        logger.warning("[SQL_CRITIC] Duplicate/redundant index")
        return {"verified": False, "feedback": (
            f"Remove the duplicate/redundant index ({redundant}): it is already covered by "
            f"the leftmost prefix of ({kept}). Keep only the more selective composite index."
        )}

    # 4c) Every index must match the query's predicates/joins/sort (not invented).
    pred_cols = _predicate_columns("\n".join(_query_blocks(text)))
    bad = _mismatched_index(defs, pred_cols)
    if bad:
        logger.warning("[SQL_CRITIC] Index does not match query predicates")
        return {"verified": False, "feedback": (
            f"The index on ({', '.join(bad['cols'])}) does not match the query shape: its "
            "leading column is not used in any WHERE / JOIN / ORDER BY / GROUP BY predicate. "
            "Index the columns the query actually filters, joins, or sorts on."
        )}

    # 4d) EXPLAIN section must demonstrate plan-node literacy.
    explain_body = _section_body(text, _EXPLAIN_SYNS)
    if explain_body is not None:
        present_nodes, missing_nodes = _node_type_coverage(explain_body)
        has_index_access = bool({"Index Scan", "Bitmap Scan"} & set(present_nodes))
        if "Seq Scan" not in present_nodes or not has_index_access or len(present_nodes) < 3:
            logger.warning(f"[SQL_CRITIC] EXPLAIN missing node-type analysis: {missing_nodes}")
            return {"verified": False, "feedback": (
                "Deepen the EXPLAIN / Execution Plan Analysis: explain the relevant plan node "
                "types and how the optimization changes them — Seq Scan, Index Scan, Bitmap "
                "Scan, Sort, and Hash Aggregate. Missing: " + ", ".join(missing_nodes) + "."
            )}

    # 4e) Cost/benefit weighing for the optimizations.
    tradeoff_body = _section_body(text, _TRADEOFF_SYNS)
    cb_scope = tradeoff_body if tradeoff_body is not None else text
    if not (_COST_CUE.search(cb_scope) and _BENEFIT_CUE.search(cb_scope)):
        logger.warning("[SQL_CRITIC] Missing cost/benefit weighing")
        return {"verified": False, "feedback": (
            "State the cost/benefit of each optimization in Tradeoffs: weigh the COST (index "
            "storage + write amplification, replica lag, cache staleness) against the BENEFIT "
            "(latency / throughput improvement) so each recommendation is justified."
        )}

    # 4f) The shipped Final Optimized Query must itself be sargable — a "fix" that
    #     still defeats its own index is not an optimization.
    final_body = _section_body(text, ("final optimized query", "final query", "optimized query"))
    if final_body:
        final_sql = "\n".join(_code_blocks(final_body)) or final_body
        if _LEADING_WILDCARD_RE.search(final_sql) and not _TRIGRAM_INDEX_RE.search(text):
            logger.warning("[SQL_CRITIC] Final query has a leading-wildcard LIKE")
            return {"verified": False, "feedback": (
                "The Final Optimized Query uses a leading-wildcard LIKE ('%...'), which cannot use "
                "a B-tree index and forces a scan. Use a trigram GIN index (pg_trgm), full-text "
                "search, or restructure the predicate to be sargable."
            )}
        has_expr_index = any(d["cols"] is None for d in defs)
        if not has_expr_index and _NONSARGABLE_FUNC_RE.search(final_sql):
            logger.warning("[SQL_CRITIC] Final query wraps a predicate column in a function")
            return {"verified": False, "feedback": (
                "The Final Optimized Query wraps a column in a function inside a WHERE/JOIN "
                "predicate (non-sargable), so the proposed index cannot be used. Compare the bare "
                "column instead (e.g. created_at >= '2024-01-01' rather than "
                "YEAR(created_at) = 2024), or add a matching expression index."
            )}

    return {"verified": True, "feedback": ""}
