"""
Phase 5 — System Design critic / knowledge-base regression suite.

Deterministic tests for the derived-numbers capacity check plus verifier
short-circuit behavior (reject paths need no network). Run:
    python -m pytest tests/test_sysdesign.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import sysdesign_critic as sd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------
def test_to_number_suffixes():
    assert sd._to_number("1", "billion") == 1e9
    assert sd._to_number("100", "k") == 1e5
    assert sd._to_number("2.5", "million") == 2.5e6
    assert sd._to_number("1,000", "") == 1000.0


def test_extract_qps_and_per_day():
    text = "We expect 1 billion requests per day and about 12,000 QPS on average."
    assert max(sd._values(sd._PERDAY_RE, text)) == 1e9
    assert 12000 in sd._values(sd._QPS_RE, text)


# ---------------------------------------------------------------------------
# Derived-numbers consistency
# ---------------------------------------------------------------------------
CONSISTENT = (
    "### Scale Estimation\n"
    "1 billion requests per day; read-heavy 100:1.\n\n"
    "### Capacity Calculations\n"
    "1 billion requests per day / 86,400 = 11,574 QPS average; at 5x peak = 58,000 QPS. "
    "Storage: 10M writes/day x 1 KB = 10 GB/day, x365 = 3.65 TB/year.\n"
)

INCONSISTENT_LOW = (
    "### Scale Estimation\n"
    "1 billion requests per day.\n\n"
    "### Capacity Calculations\n"
    "We can comfortably serve this with about 100 QPS on a single node.\n"
)

INCONSISTENT_HIGH = (
    "### Scale Estimation\n"
    "1 million requests per day.\n\n"
    "### Capacity Calculations\n"
    "This needs 5 million QPS of capacity.\n"
)

PEAK_OK = (
    "### Scale Estimation\n10 million requests per day.\n\n"
    "### Capacity Calculations\n"
    "10 million requests per day / 86,400 = 116 QPS average, with 600 QPS at peak.\n"
)

HANDWAVY = (
    "### Capacity Calculations\n"
    "We will need significant storage and a large number of servers to handle the load.\n"
)

CAP_WITH_MATH = (
    "### Capacity Calculations\n"
    "Storage/day = 10M writes/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year; x3 replicas.\n"
)


def test_consistent_capacity_passes():
    assert sd.critique("Design Twitter", CONSISTENT)["verified"] is True


def test_inconsistent_low_qps_rejected():
    r = sd.critique("Design Twitter", INCONSISTENT_LOW)
    assert r["verified"] is False
    assert "order of magnitude" in r["feedback"].lower()


def test_inconsistent_high_qps_rejected():
    r = sd.critique("Design a counter", INCONSISTENT_HIGH)
    assert r["verified"] is False


def test_peak_factor_within_tolerance_passes():
    assert sd.critique("Design a feed", PEAK_OK)["verified"] is True


def test_handwavy_capacity_rejected():
    r = sd.critique("Design Instagram", HANDWAVY)
    assert r["verified"] is False
    assert "hand-wavy" in r["feedback"].lower() or "show the" in r["feedback"].lower()


def test_capacity_with_real_math_passes():
    assert sd.critique("Design Dropbox", CAP_WITH_MATH)["verified"] is True


def test_no_numbers_defers():
    text = "I'd put a gateway in front of stateless services, with Redis and Kafka."
    assert sd.critique("Design something", text)["verified"] is True


def test_clarification_defers():
    text = "Which system should I design, and what scale/feature constraints?"
    assert sd.critique("design", text)["verified"] is True


# ---------------------------------------------------------------------------
# Verifier integration (reject paths short-circuit BEFORE any LLM call)
# ---------------------------------------------------------------------------
def test_verifier_rejects_inconsistent_capacity_without_network():
    import verifier_agent
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design Twitter", INCONSISTENT_LOW)
    assert r["verified"] is False


def test_verifier_rejects_full_code_section_in_design():
    import verifier_agent
    text = "### Architecture Diagram\nClient -> Gateway\n### Full Code\n```\nx=1\n```"
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design X", text)
    assert r["verified"] is False
    assert "full code" in r["feedback"].lower()


def test_verifier_passes_consistent_design(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design Twitter", CONSISTENT)
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Knowledge base wiring
# ---------------------------------------------------------------------------
def test_sysdesign_knowledge_base_file_exists():
    assert os.path.exists(os.path.join(BASE, "SYSTEM_DESIGN_KNOWLEDGE_BASE.md"))


def test_sysdesign_knowledge_base_injected_into_prompt():
    import router
    prompt = router.AGENT_PROMPTS[router.SYSTEM_DESIGN_AGENT].lower()
    assert "back-of-envelope" in prompt
    assert "fan-out on write" in prompt


def test_agent_prompt_carries_domain_and_capacity_hardening():
    """The generator template + KB must teach the domain deep-dives and the four
    capacity dimensions, so attempt #1 can satisfy the hardened critic."""
    import router
    prompt = router.AGENT_PROMPTS[router.SYSTEM_DESIGN_AGENT].lower()
    for token in ("celebrity handling", "presence service", "inventory consistency",
                  "cdn strategy", "cache sizing", "bandwidth"):
        assert token in prompt, f"missing domain/capacity guidance: {token!r}"


# ===========================================================================
# Domain hardening — mandatory domain sections, capacity completeness,
# services-in-diagram, and realism. All reject paths are deterministic (no LLM).
# ===========================================================================
INSTAGRAM_FULL = (
    "# Designing Instagram\n\n"
    "### Functional Requirements\n"
    "Post photos, follow users, view a home feed, and search.\n\n"
    "### Non Functional Requirements\n"
    "Availability 99.99%, read p99 < 200 ms, eventual consistency for feeds, durable media.\n\n"
    "### Scale Estimation\n"
    "500M DAU; 100M posts/day; 1 billion requests/day; read-heavy 100:1.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion requests/day / 86,400 = 11,574 QPS average; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 100M posts/day x 1 MB = 100 TB/day; x365 = 36.5 PB/year; x3 replication.\n"
    "- Bandwidth: 58,000 QPS x 1 MB ~= 58 GB/s egress served via CDN.\n"
    "- Cache sizing: hot set ~20% of timelines ~= 730 GB held in Redis.\n"
    "- Fleet: 58,000 peak QPS / 20,000 QPS per server = 3 app servers, x2 for HA.\n\n"
    "### API Design\n"
    "POST /posts, GET /feed?cursor=, GET /users/{id}, POST /follow/{id} (REST + cursor pagination).\n\n"
    "### Database Design\n"
    "Posts and the social graph in Cassandra (wide-column); media metadata keyed by post id. "
    "Replication factor = 3; multi-region consistency model.\n\n"
    "### Redis Strategy\n"
    "Cache hot timelines and counters; write-through on fan-out; TTL + explicit invalidation. "
    "Redis Cluster with 3 replicas; 730 GB working set; allkeys-lru eviction; expected 90% hit ratio.\n\n"
    "### Kafka Strategy\n"
    "post-created events to a 64-partition topic; 7-day retention; fan-out and indexing consumers "
    "in consumer groups; ~10 MB/s peak throughput.\n\n"
    "### Data Flow\n"
    "A post hits the gateway -> Post Service -> Kafka -> fan-out workers append to follower timelines in Redis.\n\n"
    "### Monitoring\n"
    "Track QPS, p99 latency, fan-out lag, and cache hit-rate; alert on error budgets via Prometheus/Grafana.\n\n"
    "### Disaster Recovery\n"
    "Multi-region active-passive; RPO 5 min, RTO 30 min; cross-region backups and automated failover.\n\n"
    "### Security\n"
    "OAuth2 tokens, TLS everywhere, signed media URLs, per-endpoint authz and rate limiting.\n\n"
    "### Tradeoffs\n"
    "Fan-out on write favors read latency over write cost; eventual consistency over strong (CAP: AP).\n\n"
    "### Cost Considerations\n"
    "Compute ~= 3 app servers x $0.10/hr x 730 hr/mo ~= $220/mo; storage 36.5 PB x $0.021/GB-mo; egress via CDN at $0.02/GB.\n\n"
    "### Architecture Diagram\n"
    "Client -> API Gateway -> Feed Service -> Ranking Service -> Redis (cache) -> Cassandra (database)\n"
    "Write path: Post Service -> Kafka (queue) -> Fan-out Workers -> Redis\n"
    "Media: Client -> Media Service -> S3 (object storage) -> CDN\n\n"
    "### Feed Generation\n"
    "The Feed Service assembles each home timeline from the posts of followees.\n\n"
    "### Feed Ranking\n"
    "A ranking model scores posts by recency, affinity, and engagement signals.\n\n"
    "### Fan-out on Write\n"
    "On a new post we push the post id into each follower's timeline cache (Redis list).\n\n"
    "### Fan-out on Read\n"
    "For very large accounts we use fan-out on read and merge recent posts at read time.\n\n"
    "### Celebrity Handling\n"
    "Celebrity posts are not fanned out on write; we use a hybrid pull at read time, async via Kafka.\n\n"
    "### Media Storage\n"
    "Photos and videos go to object storage (S3); only metadata lives in the database.\n\n"
    "### CDN Strategy\n"
    "Media is served from an edge CDN with signed URLs and long cache-control.\n\n"
    "### Search Architecture\n"
    "Users and hashtags are indexed in an inverted index (Elasticsearch) with a typeahead prefix index.\n"
)

# Full design identical to INSTAGRAM_FULL but the API Design section is prose-only
# (no HTTP method + path), so it must be rejected for lacking concrete endpoints.
VAGUE_API = INSTAGRAM_FULL.replace(
    "POST /posts, GET /feed?cursor=, GET /users/{id}, POST /follow/{id} (REST + cursor pagination).",
    "We expose a clean set of RESTful APIs for posting, reading the home timeline, and following accounts.",
)

SOCIAL_MISSING = (
    "# Instagram Design\n\n"
    "### Functional Requirements\nPost photos and view a feed.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Feed Service -> Redis -> Cassandra\n\n"
    "### Feed Generation\nWe build the home timeline from followees.\n\n"
    "### Redis Strategy\nCache hot timelines.\n"
)

WHATSAPP_MISSING = (
    "# WhatsApp Design\n\n"
    "### Functional Requirements\n1:1 and group chat.\n\n"
    "### Architecture Diagram\nClient -> WebSocket Gateway -> Chat Service -> Kafka -> Cassandra\n\n"
    "### Presence Service\nTrack online status with Redis TTL keys.\n\n"
    "### Redis Strategy\nPresence and session cache.\n"
)

ECOMMERCE_MISSING = (
    "# Amazon Design\n\n"
    "### Functional Requirements\nBrowse products and buy.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Catalog Service -> Redis -> DynamoDB\n\n"
    "### Checkout Flow\nCart -> payment -> order.\n\n"
    "### Redis Strategy\nCache the product catalog.\n"
)

INFRA_ONLY = (
    "# A Scalable System\n\n"
    "### Functional Requirements\nServe requests reliably.\n\n"
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion requests/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M writes/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year; x3 replicas.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### Architecture Diagram\nClient -> Load Balancer -> Redis -> Kafka -> Database\n"
)

CAP_INCOMPLETE = (
    "# A Scalable System\n\n"
    "### Functional Requirements\nServe requests.\n\n"
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion requests/day / 86,400 = 11,574 QPS; 5x peak 58,000 QPS.\n"
    "- Storage growth: 10M writes/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Worker Service -> Redis -> Database\n"
)

UNREAL_SINGLE_NODE = (
    "### Capacity Calculations\n"
    "A single server can handle 5 million QPS, so one box is enough.\n"
)

# Full design, complete capacity, has services, but the diagram omits Queue + Storage.
DIAGRAM_MISSING_TIERS = (
    "# A Scalable Web Service\n\n"
    "### Functional Requirements\nServe API requests.\n\n"
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M writes/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year; x3 replicas.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### Architecture Diagram\n"
    "Client -> API Gateway -> Order Service -> Redis -> PostgreSQL\n"
)

# Full 7-tier diagram + complete capacity, but most mandatory sections are absent.
SECTIONS_MISSING = (
    "# A Scalable System Design\n\n"
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M writes/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year; x3 replicas.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### Architecture Diagram\n"
    "Client -> API Gateway -> Order Service -> Redis (cache) -> Kafka (queue) -> PostgreSQL (database) -> S3 (storage)\n"
)

# A server count stated on its own line with NO derivation from QPS.
SERVERS_ARBITRARY = (
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Capacity Calculations\n"
    "- QPS: 1 billion requests/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- We will need 500 servers for the workload.\n"
)

# A dollar figure with no unit-rate x quantity derivation.
COST_INVENTED = (
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Cost Considerations\n"
    "Infrastructure will cost about $2 million per year.\n"
)

# A messaging design that derives its cost properly (rate x quantity) — must pass cost check.
COST_DERIVED = (
    "### Scale Estimation\n1 billion requests/day.\n\n"
    "### Cost Considerations\n"
    "Compute: 3 instances x $0.10/hr x 730 hr/mo = $219/mo; storage 3.65 TB x $0.021/GB-mo.\n"
)


# ── helper-level checks ─────────────────────────────────────────────────────
def test_is_full_design_detects_documents_not_clarifications():
    assert sd._is_full_design(INSTAGRAM_FULL) is True
    assert sd._is_full_design("Which system should I design, and at what scale?") is False


def test_detect_domain_from_query():
    assert sd._detect_domain("Design Instagram", "") == "social"
    assert sd._detect_domain("Design a Twitter feed", "") == "social"
    assert sd._detect_domain("Design WhatsApp", "") == "messaging"
    assert sd._detect_domain("Design Amazon", "") == "ecommerce"
    assert sd._detect_domain("Design a rate limiter", "") is None


def test_arch_infra_only_flags_infrastructure_diagram():
    assert sd._arch_is_infra_only(INFRA_ONLY) is True
    assert sd._arch_is_infra_only(INSTAGRAM_FULL) is False


def test_missing_capacity_components():
    assert sd._missing_capacity_components(INSTAGRAM_FULL) == []
    missing = sd._missing_capacity_components(CAP_INCOMPLETE)
    assert "bandwidth" in missing and "cache sizing" in missing


def test_missing_domain_sections():
    missing = sd._missing_domain_sections("social", SOCIAL_MISSING)
    assert "Feed Ranking" in missing and "Celebrity Handling" in missing
    assert sd._missing_domain_sections("social", INSTAGRAM_FULL) == []


# ── critique() reject / pass paths ──────────────────────────────────────────
def test_full_instagram_design_passes_critic():
    assert sd.critique("Design Instagram", INSTAGRAM_FULL)["verified"] is True


def test_api_endpoint_detection_helper():
    assert sd._api_missing_endpoints(INSTAGRAM_FULL) is False
    assert sd._api_missing_endpoints(VAGUE_API) is True


def test_vague_api_design_rejected():
    r = sd.critique("Design Instagram", VAGUE_API)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "api" in fb and ("endpoint" in fb or "vague" in fb)


def test_social_design_missing_core_sections_rejected():
    r = sd.critique("Design Instagram", SOCIAL_MISSING)
    assert r["verified"] is False
    assert "domain sections" in r["feedback"].lower()


def test_messaging_design_missing_core_sections_rejected():
    r = sd.critique("Design WhatsApp", WHATSAPP_MISSING)
    assert r["verified"] is False
    assert "message ordering" in r["feedback"].lower() or "encryption" in r["feedback"].lower()


def test_ecommerce_design_missing_core_sections_rejected():
    r = sd.critique("Design Amazon", ECOMMERCE_MISSING)
    assert r["verified"] is False
    assert "inventory consistency" in r["feedback"].lower()


def test_infra_only_architecture_rejected():
    r = sd.critique("Design a scalable system", INFRA_ONLY)
    assert r["verified"] is False
    assert "infrastructure" in r["feedback"].lower() or "services" in r["feedback"].lower()


def test_incomplete_capacity_components_rejected():
    r = sd.critique("Design a scalable system", CAP_INCOMPLETE)
    assert r["verified"] is False
    assert "bandwidth" in r["feedback"].lower() and "cache sizing" in r["feedback"].lower()


def test_unrealistic_single_node_qps_rejected():
    r = sd.critique("Design a counter", UNREAL_SINGLE_NODE)
    assert r["verified"] is False
    assert "unrealistic" in r["feedback"].lower()


def test_domain_query_short_answer_defers():
    # A clarification for a domain query must NOT be rejected for missing sections.
    text = "Instagram is a photo-sharing app; can you confirm the scale and key features?"
    assert sd.critique("Design Instagram", text)["verified"] is True


# ── verifier integration (reject paths short-circuit BEFORE any LLM call) ────
def test_verifier_rejects_infra_only_diagram_without_network():
    import verifier_agent
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design a scalable system", INFRA_ONLY)
    assert r["verified"] is False


def test_verifier_rejects_missing_domain_sections_without_network():
    import verifier_agent
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design Instagram", SOCIAL_MISSING)
    assert r["verified"] is False


def test_verifier_passes_full_instagram(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design Instagram", INSTAGRAM_FULL)
    assert r["verified"] is True


# ===========================================================================
# Hardening v2 — 15 mandatory sections, 7 diagram tiers, derived server counts
# and infrastructure costs, Multi Device Sync (messaging).
# ===========================================================================
def test_full_instagram_has_all_mandatory_sections():
    assert sd._missing_mandatory_sections(INSTAGRAM_FULL) == []


def test_missing_mandatory_sections_detected():
    missing = sd._missing_mandatory_sections(SECTIONS_MISSING)
    assert "Security" in missing and "Monitoring" in missing and "API Design" in missing


def test_full_instagram_has_all_diagram_tiers():
    assert sd._missing_diagram_components(INSTAGRAM_FULL) == []


def test_missing_diagram_tiers_detected():
    missing = sd._missing_diagram_components(DIAGRAM_MISSING_TIERS)
    assert "Queue" in missing and "Storage" in missing


def test_arbitrary_server_count_detected():
    assert sd._arbitrary_server_count(SERVERS_ARBITRARY) is not None
    assert sd._arbitrary_server_count(INSTAGRAM_FULL) is None  # derived fleet line is fine


def test_invented_cost_detected():
    assert sd._invented_cost(COST_INVENTED) is True
    assert sd._invented_cost(COST_DERIVED) is False
    assert sd._invented_cost(INSTAGRAM_FULL) is False


def test_messaging_requires_multi_device_sync():
    missing = sd._missing_domain_sections("messaging", WHATSAPP_MISSING)
    assert "Multi Device Sync" in missing


# ── critique() reject paths for the new checks ──────────────────────────────
def test_diagram_missing_tiers_rejected():
    r = sd.critique("Design a scalable web service", DIAGRAM_MISSING_TIERS)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "queue" in fb and "storage" in fb


def test_missing_mandatory_sections_rejected():
    r = sd.critique("Design a scalable system", SECTIONS_MISSING)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "mandatory sections" in fb and "security" in fb


def test_arbitrary_server_count_rejected():
    r = sd.critique("Design a scalable system", SERVERS_ARBITRARY)
    assert r["verified"] is False
    assert "server" in r["feedback"].lower() and "derive" in r["feedback"].lower()


def test_invented_cost_rejected():
    r = sd.critique("Design a scalable system", COST_INVENTED)
    assert r["verified"] is False
    assert "cost" in r["feedback"].lower() and "derived" in r["feedback"].lower()


def test_derived_cost_passes():
    assert sd.critique("Design a chat app", COST_DERIVED)["verified"] is True


# ── verifier integration (deterministic reject, no network) ─────────────────
def test_verifier_rejects_missing_mandatory_sections_without_network():
    import verifier_agent
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design a scalable system", SECTIONS_MISSING)
    assert r["verified"] is False


def test_verifier_rejects_arbitrary_server_count_without_network():
    import verifier_agent
    r = verifier_agent.verify("SYSTEM_DESIGN_AGENT", "Design a scalable system", SERVERS_ARBITRARY)
    assert r["verified"] is False


def test_agent_prompt_carries_v2_hardening():
    """Template + KB must teach the 7-tier diagram, Security, derived servers/costs,
    and Multi Device Sync so attempt #1 can satisfy the hardened critic."""
    import router
    prompt = router.AGENT_PROMPTS[router.SYSTEM_DESIGN_AGENT].lower()
    for token in ("multi device sync", "security", "queue", "storage",
                  "per-server throughput", "unit price"):
        assert token in prompt, f"missing v2 guidance: {token!r}"


# ===========================================================================
# Phase 3 hardening — Redis/Kafka/cache sizing and replication assumptions.
# ===========================================================================
REDIS_MISSING = (
    "# Analytics Pipeline\n\n"
    "### Functional Requirements\nIngest events and serve dashboards.\n\n"
    "### Non-Functional Requirements\nLow latency, high throughput.\n\n"
    "### Scale Estimation\n1 billion events/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M events/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### API Design\nPOST /events\n\n"
    "### Database Design\nClickHouse with replication factor 3.\n\n"
    "### Redis Strategy\nCache hot dashboards.\n\n"  # missing size, eviction, cluster
    "### Kafka Strategy\nevents to a 64-partition topic; 7-day retention; ~10 MB/s.\n\n"
    "### Data Flow\nClient -> Gateway -> Ingestion Service -> Kafka -> Workers -> Redis -> DB.\n\n"
    "### Monitoring\nMetrics.\n\n"
    "### Disaster Recovery\nBackups.\n\n"
    "### Security\nTLS.\n\n"
    "### Tradeoffs\nStreaming vs batch.\n\n"
    "### Cost Considerations\n3 servers x $0.10/hr x 730 hr = $219/mo.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Ingestion Service -> Redis -> Kafka -> PostgreSQL -> S3\n"
)

KAFKA_MISSING = (
    "# Analytics Pipeline\n\n"
    "### Functional Requirements\nIngest events and serve dashboards.\n\n"
    "### Non-Functional Requirements\nLow latency, high throughput.\n\n"
    "### Scale Estimation\n1 billion events/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M events/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### API Design\nPOST /events\n\n"
    "### Database Design\nPostgreSQL with replication factor 3.\n\n"
    "### Redis Strategy\nRedis Cluster, 730 GB, allkeys-lru, 90% hit ratio.\n\n"
    "### Kafka Strategy\nUse Kafka for events.\n\n"  # missing partitions, retention, throughput
    "### Data Flow\nClient -> Gateway -> Ingestion Service -> Kafka -> Workers -> Redis -> DB.\n\n"
    "### Monitoring\nMetrics.\n\n"
    "### Disaster Recovery\nBackups.\n\n"
    "### Security\nTLS.\n\n"
    "### Tradeoffs\nStreaming vs batch.\n\n"
    "### Cost Considerations\n3 servers x $0.10/hr x 730 hr = $219/mo.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Ingestion Service -> Redis -> Kafka -> PostgreSQL -> S3\n"
)

REPLICATION_MISSING = (
    "# Analytics Pipeline\n\n"
    "### Functional Requirements\nIngest events and serve dashboards.\n\n"
    "### Non-Functional Requirements\nLow latency, high throughput.\n\n"
    "### Scale Estimation\n1 billion events/day.\n\n"
    "### Capacity Calculations\n"
    "- Requests/sec: 1 billion/day / 86,400 = 11,574 QPS; 5x peak = 58,000 QPS.\n"
    "- Storage growth: 10M events/day x 1 KB = 10 GB/day; x365 = 3.65 TB/year.\n"
    "- Bandwidth: 58,000 QPS x 2 KB = 116 MB/s.\n"
    "- Cache sizing: 20% hot set = 730 GB in Redis.\n\n"
    "### API Design\nPOST /events\n\n"
    "### Database Design\nSingle-node PostgreSQL.\n\n"  # no replication
    "### Redis Strategy\nRedis Cluster; 20% hot set = 730 GB; allkeys-lru eviction; 90% hit ratio.\n\n"
    "### Kafka Strategy\n64 partitions, 7-day retention, ~10 MB/s.\n\n"
    "### Data Flow\nClient -> Gateway -> Ingestion Service -> Kafka -> Workers -> Redis -> DB.\n\n"
    "### Monitoring\nMetrics.\n\n"
    "### Disaster Recovery\nBackups.\n\n"
    "### Security\nTLS.\n\n"
    "### Tradeoffs\nStreaming vs batch.\n\n"
    "### Cost Considerations\n3 servers x $0.10/hr x 730 hr = $219/mo.\n\n"
    "### Architecture Diagram\nClient -> API Gateway -> Ingestion Service -> Redis -> Kafka -> PostgreSQL -> S3\n"
)


def test_redis_strategy_sizing_rejected():
    r = sd.critique("Design an analytics pipeline", REDIS_MISSING)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "redis" in fb
    assert "memory" in fb or "eviction" in fb or "cluster" in fb


def test_kafka_strategy_sizing_rejected():
    r = sd.critique("Design an analytics pipeline", KAFKA_MISSING)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "kafka" in fb
    assert "partition" in fb or "retention" in fb or "throughput" in fb


def test_replication_assumption_rejected():
    r = sd.critique("Design an analytics pipeline", REPLICATION_MISSING)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "replication" in fb


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
