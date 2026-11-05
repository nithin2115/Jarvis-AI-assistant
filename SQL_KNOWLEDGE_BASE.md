# SQL Optimization Knowledge Base

Production facts and patterns for large-scale query optimization. Ground every
recommendation in the user's actual query/schema — never invent tables or columns.

## Diagnosis: read the plan first
- Always reason from `EXPLAIN` / `EXPLAIN ANALYZE` (Postgres) or the execution plan
  (`EXPLAIN FORMAT=JSON` in MySQL). Compare estimated vs actual rows to spot bad stats.
- Red flags: `Seq Scan` on a large table, `Nested Loop` over many rows, a `Sort` or
  `Hash` spilling to disk, large `Rows Removed by Filter`, or `Index Scan` that still
  reads most of the table (low selectivity index).
- Stale statistics cause bad plans — `ANALYZE` / `ANALYZE TABLE` after big loads.

## Plan node types (explain how each changes)
- **Seq Scan**: reads the whole table — fine for small tables, a red flag on large ones;
  the usual target an index removes.
- **Index Scan / Index-Only Scan**: walks a B-tree for selective predicates; Index-Only
  avoids heap fetches when the index covers all referenced columns (`INCLUDE`).
- **Bitmap Index Scan + Bitmap Heap Scan**: chosen for medium-selectivity predicates or to
  combine several indexes (`AND`/`OR`); builds a bitmap of matching pages then visits them.
- **Sort**: ordering for `ORDER BY` / merge joins / `DISTINCT`; a matching index can supply
  order and ELIMINATE the Sort (watch for sorts spilling to disk).
- **Hash Aggregate** (vs Group Aggregate): groups for `GROUP BY` / `DISTINCT`; Group
  Aggregate is used when input is already sorted by the grouping key.
- Always state which nodes your indexes REMOVE (e.g., Seq Scan + Sort) and which they
  INTRODUCE, and back it with estimated vs actual rows.

## Indexing
- A B-tree index helps equality and range predicates and `ORDER BY` on the leading
  column(s). The **leftmost-prefix rule**: a composite index `(a, b, c)` serves
  predicates on `a`, `a,b`, `a,b,c` — not `b` alone.
- **Covering / INCLUDE indexes** let the engine answer from the index alone (index-only
  scan), avoiding heap lookups: `CREATE INDEX ... ON t (filter_cols) INCLUDE (select_cols)`.
- **Partial indexes** for skewed predicates: `CREATE INDEX ... WHERE status = 'ACTIVE'`.
- Index **selectivity matters**: a column with few distinct values (e.g., boolean) is a
  poor standalone index. Order composite columns by selectivity / query shape.
- Each index adds write amplification and storage — justify every index you add.
- For text search use GIN/GiST (Postgres) or FULLTEXT (MySQL), not a B-tree `LIKE '%x%'`.
- **Match the query shape**: the index's leading column must be used by a WHERE / JOIN /
  ORDER BY / GROUP BY predicate. An index whose leading column the query never touches is
  useless and will not be chosen by the planner.
- **No duplicate / redundant indexes**: an index on `(a)` is redundant when `(a, b)` already
  exists (left-prefix rule). Redundant indexes only add write and storage cost — drop them.

## Query rewrites
- Avoid `SELECT *`; project only needed columns to enable index-only scans.
- Replace correlated subqueries with `JOIN`s or `LATERAL` / window functions.
- `EXISTS` is usually cheaper than `IN (subquery)` for semi-joins.
- Keep predicates **sargable**: `WHERE col = $1`, not `WHERE func(col) = $1` or
  `WHERE col + 0 = $1` (these defeat indexes). Use range bounds instead of `DATE(ts)=...`.
- Paginate with **keyset/seek pagination** (`WHERE id > $last ORDER BY id LIMIT n`),
  not large `OFFSET` which scans and discards rows.
- Batch writes; avoid row-by-row round trips.

## Scaling reads & writes
- **Partitioning**: range-by-date for time-series, hash-by-key for even distribution.
  Enables partition pruning and cheap old-data drops. State the partition key + scheme.
  Valid PostgreSQL declarative DDL: `CREATE TABLE t (...) PARTITION BY RANGE|LIST|HASH (col)`
  then children `CREATE TABLE t_p PARTITION OF t FOR VALUES FROM (a) TO (b)` (RANGE) /
  `FOR VALUES IN (...)` (LIST) / `WITH (MODULUS m, REMAINDER r)` (HASH). The MySQL form
  `PARTITION ... VALUES LESS THAN (...)` is INVALID in PostgreSQL.
- **Read replicas** offload read-heavy traffic; be explicit about replication lag and
  read-after-write consistency (route reads needing freshness to the primary).
- **Sharding** for write scale-out; pick a shard key that avoids hotspots; cross-shard
  joins/transactions are expensive — design to avoid them.
- **Materialized views** pre-compute expensive aggregates; define the refresh strategy
  (on-demand, scheduled, or incremental) and the staleness tolerance.

## Caching
- Cache hot, expensive, read-mostly results in Redis with a clear key scheme and TTL.
- Define invalidation: write-through, write-behind, or TTL + event-based busting.
- Beware cache stampede — use request coalescing / locks / jittered TTLs.

## Monitoring
- Track p95/p99 latency, slow-query log threshold, buffer cache hit ratio, lock waits,
  deadlocks, replication lag, and index bloat. Alert on plan regressions.

## Tradeoffs to always state
- Give an explicit cost/benefit for EVERY optimization — weigh the cost against the payoff
  so each recommendation is justified, not asserted.
- Index/materialized-view storage + write cost vs read speedup.
- Replication lag vs read scalability.
- Denormalization (faster reads) vs update anomalies and write cost.
- Caching freshness vs latency.
