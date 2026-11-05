"""Deterministic System Design critic (Phase 5 + domain hardening).

Cheap, high-precision checks that run BEFORE the LLM verifier. They catch the
mistakes a deterministic check can flag safely, without ever rejecting a correct
answer:
  * Capacity consistency  — stated QPS must follow from requests/day (± order of
    magnitude); a Capacity section must contain real numbers, not hand-waving.
  * Realism               — a single node/server cannot serve absurd (≥1M) QPS.
  * Domain depth          — a recognised domain (social-feed, messaging, e-commerce)
    MUST cover its core challenges, not just generic Redis/Kafka/DB/LB boxes.
  * Capacity completeness — must quantify requests/sec, storage growth, bandwidth,
    and cache sizing.
  * Architecture diagram  — must show application SERVICES, not only infrastructure.

Design principles (never reject a correct answer):
  * The domain / completeness / diagram checks run ONLY on a full design document
    (one with an architecture diagram or several sections), so clarifying questions,
    conceptual answers, and numbers-free notes pass straight through to the LLM
    verifier untouched.
  * Tolerance bands are wide; only genuine, order-of-magnitude errors are flagged.
"""
import logging
import re

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86_400.0

_SUFFIX = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_SUF = r"(billion|million|thousand|trillion|bn|mn|[kmbt])?"

# "<n><suffix> qps" / "requests per second" / "req/s" ...
_QPS_RE = re.compile(
    _NUM + r"\s*" + _SUF + r"\s*"
    r"(?:qps|rps|req(?:uest)?s?\s*/\s*s(?:ec(?:ond)?)?|"
    r"(?:requests?|queries|reads?|writes?|ops|operations)\s+per\s+second)",
    re.IGNORECASE,
)
# "<n><suffix> requests per day" / "writes/day" ...
_PERDAY_RE = re.compile(
    _NUM + r"\s*" + _SUF + r"\s*"
    r"(?:requests?|queries|reads?|writes?|ops|operations|messages|events|lookups)\s*"
    r"(?:/\s*day|per\s+day|/\s*d(?:ay)?\b|daily)",
    re.IGNORECASE,
)

_CAPACITY_HEADER = re.compile(r"capacity", re.IGNORECASE)
_QUANT_TOKEN = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*"
    r"(?:k|m|b|bn|kb|mb|gb|tb|pb|bytes?|qps|rps|servers?|shards?|nodes?|replicas?|"
    r"requests?|/\s*day|/\s*s|per\s+(?:day|second))",
    re.IGNORECASE,
)

# Tolerance: a stated QPS is consistent with requests/day if it lands anywhere from
# 1/10 of the average up to 50x the average (covers sub-average to large peak factors).
_TOL_LOW = 10.0
_TOL_HIGH = 50.0

# ── Domain & completeness hardening ─────────────────────────────────────────
# A single node/server realistically tops out in the tens of thousands of QPS;
# only flag clearly absurd claims so a correct answer is never rejected.
_UNREAL_SINGLE_NODE_QPS = 1_000_000.0

_SCALE_HEADER = re.compile(
    r"scale estimat|capacity (?:estimat|planning)|traffic estimat", re.IGNORECASE)
_ARCH_HEADER = re.compile(
    r"architecture diagram|system architecture|high[\s-]?level (?:design|architecture)",
    re.IGNORECASE)

# Infrastructure-only tokens vs. application/service-tier tokens. A diagram that
# names ONLY infrastructure (≥2 infra tokens, no service tier) is rejected.
_INFRA_TOKENS = re.compile(
    r"\b(?:load\s*balancer|lb|redis|kafka|memcached?|cassandra|postgres\w*|mysql|"
    r"mongo\w*|dynamodb|elasticsearch|nginx|haproxy|zookeeper|rabbitmq|sqs|s3|cdn|"
    r"database|db|cache|message\s*queue|queue|object\s*store|blob\s*store)\b",
    re.IGNORECASE,
)
_SERVICE_TOKENS = re.compile(
    r"\b(?:\w+\s+service|services?|microservices?|gateway|api|worker|consumer|"
    r"producer|handler|processor|controller|app\s*server|application|feed|timeline|"
    r"ranking|notification|search|upload|media|order|payment|inventory|cart|"
    r"presence|messaging|auth|profile|recommendation|aggregator|orchestrat\w*|"
    r"ingest\w*)\b",
    re.IGNORECASE,
)

# A single node/server claimed to serve an absurd QPS (both word orders).
_SINGLE_NODE_A = re.compile(
    _NUM + r"\s*" + _SUF + r"\s*"
    r"(?:qps|rps|req(?:uest)?s?\s*/\s*s(?:ec(?:ond)?)?|(?:requests?|queries)\s+per\s+second)"
    r"[^.\n]{0,30}?(?:a\s+|one\s+)?single\s+(?:node|server|machine|instance|box|host)",
    re.IGNORECASE,
)
_SINGLE_NODE_B = re.compile(
    r"(?:a\s+)?(?:single|one)\s+(?:node|server|machine|instance|box|host)"
    r"[^.\n]{0,40}?(?:handles?|serves?|process(?:es)?|supports?|sustains?|does?)\s+"
    r"(?:up\s+to\s+)?" + _NUM + r"\s*" + _SUF + r"\s*"
    r"(?:qps|rps|req(?:uest)?s?\s*/\s*s(?:ec(?:ond)?)?|(?:requests?|queries)\s+per\s+second)",
    re.IGNORECASE,
)

# Capacity Calculations must quantify all four dimensions (full designs only).
_CAP_COMPONENTS = (
    ("requests/sec (QPS)",
     re.compile(r"\b(?:qps|rps)\b|requests?\s*/\s*s(?:ec(?:ond)?)?|req\s*/\s*s|"
                r"(?:requests?|queries|reads?|writes?)\s+per\s+second", re.IGNORECASE)),
    ("storage growth",
     re.compile(r"\d[\d,.]*\s*(?:gb|tb|pb)\b[\s\S]{0,80}?"
                r"(?:per\s+(?:day|month|year)|/\s*(?:day|month|year|yr|d|mo)|daily|annually)|"
                r"(?:storage|data|disk)[\s\S]{0,60}?"
                r"(?:per\s+(?:day|month|year)|/\s*(?:day|month|year))", re.IGNORECASE)),
    ("bandwidth",
     re.compile(r"bandwidth|throughput|\b\d[\d,.]*\s*(?:gbps|mbps|tbps|kbps|gb/s|mb/s|kb/s|tb/s)\b|"
                r"\b(?:bytes?|bits?)\s*(?:/|per)\s*s(?:ec(?:ond)?)?\b", re.IGNORECASE)),
    ("cache sizing",
     re.compile(r"(?:cache|redis|hot[\s-]?set|working[\s-]?set|hot\s+data|in[\s-]?memory)"
                r"[\s\S]{0,80}?\d[\d,.]*\s*(?:mb|gb|tb|pb)|"
                r"\d[\d,.]*\s*(?:mb|gb|tb|pb)[\s\S]{0,60}?"
                r"(?:cache|redis|hot[\s-]?set|working[\s-]?set|in[\s-]?memory)", re.IGNORECASE)),
)

# Domain detection — query first, then the response's title/headers as a fallback.
_DOMAIN_KEYWORDS = {
    "social": ("instagram", "facebook", "twitter", "linkedin", "tiktok", "reddit",
               "pinterest", "snapchat", "news feed", "newsfeed", "social network",
               "social media"),
    "messaging": ("whatsapp", "messenger", "telegram", "signal", "slack", "discord",
                  "imessage", "chat app", "chat system", "messaging app",
                  "messaging system"),
    "ecommerce": ("e-commerce", "ecommerce", "amazon", "flipkart", "shopify", "etsy",
                  "online store", "online shop", "shopping cart", "marketplace",
                  "checkout"),
}

# Mandatory domain sections, each matched by accepted variants anywhere in the text.
_DOMAIN_SECTIONS = {
    "social": [
        ("Feed Generation", re.compile(r"feed generation|generat\w*\s+the\s+feed|timeline generation|feed (?:construction|assembly|service)", re.IGNORECASE)),
        ("Feed Ranking", re.compile(r"feed ranking|rank\w*\s+the\s+feed|ranking (?:algorithm|model|signal|service)|relevance ranking|edge\s*rank", re.IGNORECASE)),
        ("Fan-out on Write", re.compile(r"fan[\s-]?out[\s-]?on[\s-]?write|write[\s-]?fan[\s-]?out|push (?:model|fan)|precompute\w*\s+timeline", re.IGNORECASE)),
        ("Fan-out on Read", re.compile(r"fan[\s-]?out[\s-]?on[\s-]?read|read[\s-]?fan[\s-]?out|pull (?:model|fan)", re.IGNORECASE)),
        ("Celebrity Handling", re.compile(r"celebrit|hot user|high[\s-]?follower|hybrid (?:fan|push|pull|approach)|popular (?:user|account)", re.IGNORECASE)),
        ("Media Storage", re.compile(r"media storage|media pipeline|object stor|blob stor|store\s+media|\bs3\b", re.IGNORECASE)),
        ("CDN Strategy", re.compile(r"\bcdn\b|content delivery network|edge cach", re.IGNORECASE)),
        ("Search Architecture", re.compile(r"search architecture|inverted index|search service|elasticsearch|typeahead|search index", re.IGNORECASE)),
    ],
    "messaging": [
        ("Presence Service", re.compile(r"presence", re.IGNORECASE)),
        ("Message Ordering", re.compile(r"message ordering|order\w*\s+of\s+messages|ordering guarantee|sequence number|monotonic|lamport|vector clock|per[\s-]?conversation order", re.IGNORECASE)),
        ("End-to-End Encryption", re.compile(r"end[\s-]?to[\s-]?end encryption|\be2ee\b|e2e encryption|signal protocol|double ratchet", re.IGNORECASE)),
        ("Delivery Guarantees", re.compile(r"delivery guarantee|delivery receipt|at[\s-]?least[\s-]?once|exactly[\s-]?once|acknowledg|delivery (?:status|state)|read receipt", re.IGNORECASE)),
        ("Group Fan-out", re.compile(r"group fan[\s-]?out|group (?:message|chat)[\s\S]{0,30}?fan[\s-]?out|fan[\s-]?out[\s\S]{0,20}?group", re.IGNORECASE)),
        ("Media Pipeline", re.compile(r"media pipeline|media (?:upload|processing|handling)|transcod|thumbnail", re.IGNORECASE)),
        ("Multi Device Sync", re.compile(r"multi[\s-]?device|multidevice|device sync|cross[\s-]?device|companion device|linked device|sync across (?:devices|sessions)", re.IGNORECASE)),
    ],
    "ecommerce": [
        ("Inventory Consistency", re.compile(r"inventory", re.IGNORECASE)),
        ("Checkout Flow", re.compile(r"checkout", re.IGNORECASE)),
        ("Recommendation System", re.compile(r"recommendation|recommender|recommend\w*\s+(?:system|engine|service)", re.IGNORECASE)),
    ],
}

# ── Mandatory sections (full designs only) ──────────────────────────────────
# Each section is "present" if ANY response header matches its regex. Accepted
# variants are wide so a senior answer using slightly different names still passes.
_MANDATORY_SECTIONS = [
    ("Functional Requirements", re.compile(r"^(?!non[\s-]?functional).*\bfunctional requirement", re.IGNORECASE)),
    ("Non-Functional Requirements", re.compile(r"non[\s-]?functional|\bnfr\b", re.IGNORECASE)),
    ("Scale Estimation", re.compile(r"scale estimat|traffic estimat|back[\s-]?of[\s-]?(?:the[\s-]?)?envelope|scaling estimat|scale & ", re.IGNORECASE)),
    ("Capacity Calculations", re.compile(r"capacity", re.IGNORECASE)),
    ("API Design", re.compile(r"\bapi\b", re.IGNORECASE)),
    ("Database Design", re.compile(r"database|data model|schema|datastore|storage design|persistence", re.IGNORECASE)),
    ("Redis Strategy", re.compile(r"redis|cach(?:e|ing) (?:strategy|layer|design|tier)", re.IGNORECASE)),
    ("Kafka Strategy", re.compile(r"kafka|messaging|message queue|event (?:stream\w*|driven|bus)|pub[\s/-]?sub|queue strategy|streaming", re.IGNORECASE)),
    ("Data Flow", re.compile(r"data\s*flow|request flow|end[\s-]?to[\s-]?end flow|sequence (?:flow|diagram)|workflow|write path|read path", re.IGNORECASE)),
    ("Monitoring", re.compile(r"monitor|observability|metrics|alerting|telemetry", re.IGNORECASE)),
    ("Disaster Recovery", re.compile(r"disaster recovery|fault tolerance|fail[\s-]?over|high availability|resilien|backup|\bdr\b|\brpo\b|\brto\b", re.IGNORECASE)),
    ("Security", re.compile(r"security|authentication|authorization|\bauthn?\b|encryption|privacy", re.IGNORECASE)),
    ("Tradeoffs", re.compile(r"trade[\s-]?offs?|cap theorem|compromise|pros? (?:and|&) cons?", re.IGNORECASE)),
    ("Cost Considerations", re.compile(r"\bcost", re.IGNORECASE)),
    ("Architecture Diagram", re.compile(r"architecture diagram|system architecture|high[\s-]?level (?:design|architecture)|component diagram|\barchitecture\b", re.IGNORECASE)),
]

# ── Architecture-diagram components (scoped to the diagram section) ──────────
# The diagram MUST trace a request through all seven tiers.
_DIAGRAM_COMPONENTS = [
    ("Client", re.compile(r"\bclient\b|\bbrowser\b|mobile\s*app|\bweb\s*app\b|\buser\b|frontend|\bapp\b", re.IGNORECASE)),
    ("API Gateway", re.compile(r"api\s*gateway|\bgateway\b|load\s*balancer|\blb\b|reverse\s*proxy|\bedge\b", re.IGNORECASE)),
    ("Services", re.compile(r"\w+\s+service|services?\b|microservice|\bworker\b|handler|processor|controller|app\s*server", re.IGNORECASE)),
    ("Cache", re.compile(r"\bcache\b|redis|memcached?", re.IGNORECASE)),
    ("Queue", re.compile(r"\bqueue\b|kafka|rabbitmq|\bsqs\b|kinesis|pub[\s/-]?sub|message\s*broker|event\s*bus|\bstream\b", re.IGNORECASE)),
    ("Database", re.compile(r"database|\bdb\b|postgres|mysql|cassandra|dynamo|mongo|\bsql\b|nosql|spanner|cockroach|bigtable", re.IGNORECASE)),
    ("Storage", re.compile(r"\bstorage\b|\bs3\b|object\s*stor|blob\s*stor|\bcdn\b|file\s*stor|\bbucket\b|\bgcs\b", re.IGNORECASE)),
]

# ── Redis / Kafka / cache sizing guards ─────────────────────────────────────
_REDIS_HEADER = re.compile(r"redis\s*(?:strategy|caching|cache|tier)|cach(?:e|ing)\s*(?:strategy|layer|tier)", re.IGNORECASE)
_KAFKA_HEADER = re.compile(r"kafka|messaging|message\s*queue|event\s*stream|queue\s*strategy", re.IGNORECASE)
_DB_HEADER = re.compile(r"database|data\s*model|schema|datastore|storage\s*design", re.IGNORECASE)

# API Design must list CONCRETE endpoints, not just prose ("we expose REST APIs").
_API_HEADER = re.compile(r"\bapi\b(?!\s*gateway)", re.IGNORECASE)
_API_ENDPOINT_RE = re.compile(
    r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/"            # REST: POST /posts
    r"|(?:^|\s)/(?:v\d+|api|users?|posts?|orders?|feed|messages?|"  # a path literal
    r"products?|events?|graphql|search|sessions?|payments?)\b"
    r"|\brpc\s+\w+\s*\("                                            # gRPC: rpc Method(
    r"|\b(?:query|mutation)\s+\w+\s*[({]"                           # GraphQL
    r"|\bgraphql\b",
    re.IGNORECASE,
)

# Redis Strategy section must show memory size, eviction policy, and cluster mode.
_REDIS_SIZE_RE = re.compile(
    r"\d[\d,.]*\s*(?:mb|gb|tb|pb)\b|memory\s*(?:limit|size|footprint)|"
    r"\b(?:maxmemory|ram|gb)\b", re.IGNORECASE)
_REDIS_EVICTION_RE = re.compile(
    r"eviction|lru|lfu|ttl|expire|allkeys|volatile|maxmemory-policy", re.IGNORECASE)
_REDIS_CLUSTER_RE = re.compile(
    r"cluster|replica|sentinel|shard|partition|redis\s*cluster|primary|secondary", re.IGNORECASE)

# Kafka Strategy section must show partition count, retention, throughput.
_KAFKA_PARTITION_RE = re.compile(
    r"partition\s*(?:count|=?)|num\s*partitions|\d+\s*partition|topic\s*partition", re.IGNORECASE)
_KAFKA_RETENTION_RE = re.compile(
    r"retention|\d+\s*(?:day|hour|week|month)[\s\S]{0,20}?retention|retention[\s\S]{0,20}?\d+\s*(?:day|hour|week|month)", re.IGNORECASE)
_KAFKA_THROUGHPUT_RE = re.compile(
    r"throughput|\d+\s*(?:mb/s|gb/s|messages/s|msg/s)|producer\s*rate|consumer\s*rate", re.IGNORECASE)

# Cache sizing must show hit ratio and/or hot-set size.
_CACHE_HIT_RATIO_RE = re.compile(
    r"hit\s*ratio|cache\s*hit|hit\s*rate|miss\s*rate|80%|90%|95%|99%", re.IGNORECASE)
_CACHE_HOTSET_RE = re.compile(
    r"hot\s*set|working\s*set|hot\s*data|top\s*\d+|pareto|20%|80/20|cache\s*size", re.IGNORECASE)

# Replication assumptions must be stated in Database/Storage.
_REPLICATION_RE = re.compile(
    r"replication\s*factor|\brf\s*=\s*\d+|replica\s*\d+|3\s*copies|\b3x\b|durability|\braft\b|paxos", re.IGNORECASE)

# Storage consistency: object size * count = total (rough check).
_STORAGE_OBJECT_RE = re.compile(
    r"(?:photo|image|video|tweet|post|message|order|user|record).*?\d[\d,.]*\s*(?:kb|mb|gb|bytes)", re.IGNORECASE)
_STORAGE_TOTAL_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:gb|tb|pb|mb)\b[\s\S]{0,40}?(?:storage|data|disk|total|per\s*day)", re.IGNORECASE)

# ── Hallucinated-number guards ──────────────────────────────────────────────
# An arbitrary server/node count: a provisioning verb + a literal count + a node
# noun, with NO derivation shown on that line (servers must follow from QPS).
_SERVER_COUNT_RE = re.compile(
    r"(?:need|needs|requir\w*|use[sd]?|provision\w*|deploy\w*|spin\s*up|allocat\w*|"
    r"add|run|running|estimat\w*|scale\s+to|have|pick|choose|select)\s+"
    r"(?:about\s+|approximately\s+|roughly\s+|around\s+|~\s*)?"
    r"(\d[\d,]*)\s+"
    r"(?:app\s+|web\s+|application\s+|backend\s+|api\s+|database\s+|db\s+|cache\s+|frontend\s+|edge\s+)?"
    r"(?:servers?|nodes?|instances?|machines?|hosts?|boxes|vms?)\b",
    re.IGNORECASE,
)
# Signals that a server count was actually DERIVED (relate it to throughput/QPS).
_DERIV_CUE = re.compile(
    r"÷|=|\bper\s+(?:server|node|instance|box|machine|host)\b|\bqps\b|\brps\b|"
    r"throughput|\beach\b|\bhandl\w+|\bserv(?:es|ing)\b|capacity\s+of",
    re.IGNORECASE,
)
_COST_HEADER = re.compile(r"\bcost", re.IGNORECASE)
# A dollar amount appearing in the Cost section.
_COST_AMOUNT_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:k|m|bn|b|mn|million|billion|thousand)?", re.IGNORECASE)
# Signals the cost was DERIVED: a multiplication, a computed total, or a per-RESOURCE
# unit rate (period rates like $/month alone do NOT count as a derivation).
_COST_DERIV_CUE = re.compile(
    r"×|÷|\*|\bx\b|=\s*\$|"
    r"\bper\s+(?:hour|hr|gb|tb|pb|request|req|instance|server|node|core|vcpu|user|million)\b|"
    r"\$\s?\d[\d.]*\s*/\s*(?:hr|hour|gb|tb|pb|request|req|instance|core|vcpu)|"
    r"instance[\s-]?hour|unit (?:price|cost)|\brate\b",
    re.IGNORECASE,
)


def _to_number(num_str: str, suffix: str) -> float:
    val = float(num_str.replace(",", ""))
    if suffix:
        val *= _SUFFIX.get(suffix.lower(), 1.0)
    return val


def _values(regex, text):
    return [_to_number(m.group(1), m.group(2)) for m in regex.finditer(text or "")]


def _section_body(text: str, header_re) -> str:
    """Return the body of the first section whose header matches ``header_re`` (until
    the next header). Headers are markdown ``#`` lines or ``**bold**`` lines."""
    body, capturing = [], False
    for line in (text or "").splitlines():
        stripped = line.strip()
        is_header = stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**"))
        if is_header:
            if capturing:
                break  # reached the next section
            if header_re.search(stripped):
                capturing = True
            continue
        if capturing:
            body.append(line)
    return "\n".join(body)


def _capacity_section(text: str) -> str:
    """Return the body of the Capacity Calculations section (until the next header)."""
    return _section_body(text, _CAPACITY_HEADER)


def _headers(text: str) -> list:
    """Lower-cased section header names (markdown ``#`` or ``**bold**``)."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#") or (s.startswith("**") and s.endswith("**")):
            cleaned = re.sub(r"[#*`_]", "", s).strip().lower()
            if cleaned:
                out.append(cleaned)
    return out


def _is_full_design(text: str) -> bool:
    """True when the response is a substantive design document (architecture diagram
    or several sections) — NOT a clarifying question or a short note. The domain /
    completeness / diagram checks apply ONLY to full designs so clarifications and
    conceptual answers are never wrongly rejected."""
    hdrs = _headers(text)
    if any(_ARCH_HEADER.search(h) for h in hdrs):
        return True
    return len(hdrs) >= 4


def _detect_domain(user_query: str, response_text: str):
    """Detect the design domain from the query first, then the response title/headers."""
    q = (user_query or "").lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(k in q for k in kws):
            return domain
    head = "\n".join(_headers(response_text)[:3]) + "\n" + (response_text or "")[:200].lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(k in head for k in kws):
            return domain
    return None


def _missing_domain_sections(domain: str, text: str) -> list:
    return [name for name, pat in _DOMAIN_SECTIONS.get(domain, []) if not pat.search(text or "")]


def _missing_capacity_components(text: str) -> list:
    """Components absent from the Capacity (or, as a fallback, Scale) section."""
    scope = _capacity_section(text) + "\n" + _section_body(text, _SCALE_HEADER)
    return [name for name, pat in _CAP_COMPONENTS if not pat.search(scope)]


def _arch_is_infra_only(text: str) -> bool:
    """True when the architecture diagram names only infrastructure (no service tier)."""
    body = _section_body(text, _ARCH_HEADER)
    if not body.strip():
        return False
    infra = {m.group(0).lower() for m in _INFRA_TOKENS.finditer(body)}
    if len(infra) < 2:
        return False
    return not _SERVICE_TOKENS.search(body)


def _unrealistic_single_node(text: str):
    """Return the offending QPS value if a single node/server is claimed to serve an
    absurd request rate, else None."""
    for rx in (_SINGLE_NODE_A, _SINGLE_NODE_B):
        for m in rx.finditer(text or ""):
            val = _to_number(m.group(1), m.group(2))
            if val >= _UNREAL_SINGLE_NODE_QPS:
                return val
    return None


def _missing_mandatory_sections(text: str) -> list:
    """Mandatory top-level sections whose header is absent from the document."""
    hdrs = _headers(text)
    return [name for name, pat in _MANDATORY_SECTIONS if not any(pat.search(h) for h in hdrs)]


def _missing_diagram_components(text: str) -> list:
    """Required tiers absent from the Architecture Diagram section. Returns [] when
    there is no diagram section (that gap is reported by the mandatory-section check)."""
    body = _section_body(text, _ARCH_HEADER)
    if not body.strip():
        return []
    return [name for name, pat in _DIAGRAM_COMPONENTS if not pat.search(body)]


def _arbitrary_server_count(text: str):
    """Return the offending phrase if a server/node count is asserted in the Capacity
    or Scale section WITHOUT a derivation (servers must follow from QPS ÷ throughput)."""
    scope = _capacity_section(text) + "\n" + _section_body(text, _SCALE_HEADER)
    for line in scope.splitlines():
        m = _SERVER_COUNT_RE.search(line)
        if m and not _DERIV_CUE.search(line):
            return m.group(0).strip()
    return None


def _invented_cost(text: str) -> bool:
    """True when the Cost section states a dollar figure with NO derivation (no unit
    rate x quantity), i.e. an invented infrastructure cost."""
    body = _section_body(text, _COST_HEADER)
    if not body.strip():
        return False
    return bool(_COST_AMOUNT_RE.search(body)) and not _COST_DERIV_CUE.search(body)


def _redis_strategy_check(text: str):
    """Return a list of missing Redis strategy components if the section exists."""
    body = _section_body(text, _REDIS_HEADER)
    if not body.strip():
        return []
    missing = []
    if not _REDIS_SIZE_RE.search(body):
        missing.append("memory size (e.g., GB)")
    if not _REDIS_EVICTION_RE.search(body):
        missing.append("eviction policy (e.g., LRU/LFU/TTL)")
    if not _REDIS_CLUSTER_RE.search(body):
        missing.append("cluster/replication topology")
    return missing


def _kafka_strategy_check(text: str):
    """Return a list of missing Kafka strategy components if the section exists."""
    body = _section_body(text, _KAFKA_HEADER)
    if not body.strip():
        return []
    missing = []
    if not _KAFKA_PARTITION_RE.search(body):
        missing.append("partition count")
    if not _KAFKA_RETENTION_RE.search(body):
        missing.append("retention window")
    if not _KAFKA_THROUGHPUT_RE.search(body):
        missing.append("throughput (MB/s or messages/s)")
    return missing


def _cache_sizing_check(text: str):
    """Return a list of missing cache sizing components if Redis Strategy exists."""
    body = _section_body(text, _REDIS_HEADER)
    if not body.strip():
        return []
    missing = []
    if not _CACHE_HIT_RATIO_RE.search(body):
        missing.append("hit ratio")
    if not _CACHE_HOTSET_RE.search(body):
        missing.append("hot-set / working-set size")
    return missing


def _replication_check(text: str):
    """Return True if Database/Storage sections exist but never state replication."""
    db_body = _section_body(text, _DB_HEADER)
    if not db_body.strip():
        return False
    return not _REPLICATION_RE.search(db_body)


def _api_missing_endpoints(text: str) -> bool:
    """True if an API Design section exists but lists NO concrete endpoint (HTTP
    method + path, or an RPC/GraphQL signature)."""
    body = _section_body(text, _API_HEADER)
    if not body.strip():
        return False
    return not _API_ENDPOINT_RE.search(body)


def critique(user_query: str, response_text: str) -> dict:
    """Return {"verified": bool, "feedback": str}. Deterministic only."""
    text = response_text or ""

    per_day = _values(_PERDAY_RE, text)
    qps = _values(_QPS_RE, text)

    # 1. Derived-numbers consistency: avg QPS must follow from requests/day.
    if per_day and qps:
        max_per_day = max(per_day)
        avg_qps = max_per_day / _SECONDS_PER_DAY
        low, high = avg_qps / _TOL_LOW, avg_qps * _TOL_HIGH
        if not any(low <= q <= high for q in qps):
            closest = min(qps, key=lambda q: abs(q - avg_qps))
            logger.warning(
                f"[SYSDESIGN_CRITIC] QPS {qps} inconsistent with {max_per_day:.0f}/day "
                f"(avg≈{avg_qps:.0f} QPS)"
            )
            return {"verified": False, "feedback": (
                f"Capacity numbers are inconsistent: {max_per_day:.0f} requests/day implies "
                f"an average of ~{avg_qps:.0f} QPS (÷86,400), but the stated QPS (~{closest:.0f}) "
                f"is off by an order of magnitude. Recompute QPS = requests-per-day ÷ 86,400 "
                f"and state your peak factor (e.g., 2–10× average)."
            )}

    # 2. Unrealistic estimate: a single node/server cannot serve mega-QPS.
    unreal = _unrealistic_single_node(text)
    if unreal is not None:
        logger.warning(f"[SYSDESIGN_CRITIC] Unrealistic single-node QPS: {unreal:.0f}")
        return {"verified": False, "feedback": (
            f"Unrealistic capacity estimate: a single node/server cannot serve ~{unreal:.0f} "
            f"QPS (real servers handle ~10k–100k QPS). Size a fleet instead: "
            f"servers = peak QPS ÷ per-server throughput, then shard/replicate."
        )}

    # 3. Hand-wavy capacity: a Capacity section exists but contains NO quantitative content.
    cap_body = _capacity_section(text)
    if cap_body.strip() and not _QUANT_TOKEN.search(cap_body):
        logger.warning("[SYSDESIGN_CRITIC] Capacity section has no derived numbers")
        return {"verified": False, "feedback": (
            "The Capacity Calculations section is hand-wavy — show the actual math with "
            "numbers and units (e.g., requests/day ÷ 86,400 = QPS; writes/day × bytes = "
            "storage/day × 365 = storage/year; × replication factor)."
        )}

    # 4. Arbitrary server/node count: a count asserted with no derivation from QPS.
    bad_servers = _arbitrary_server_count(text)
    if bad_servers is not None:
        logger.warning(f"[SYSDESIGN_CRITIC] Arbitrary server count: {bad_servers!r}")
        return {"verified": False, "feedback": (
            f'Arbitrary server count ("{bad_servers}") — derive it, don\'t invent it: '
            f"servers = peak QPS ÷ per-server throughput (~10k–100k QPS/server), then add "
            f"replication/headroom. Show the division."
        )}

    # 5. Invented infrastructure cost: a dollar figure with no unit-rate × quantity math.
    if _invented_cost(text):
        logger.warning("[SYSDESIGN_CRITIC] Invented infrastructure cost (no derivation)")
        return {"verified": False, "feedback": (
            "Cost Considerations states a dollar figure that is not derived. Compute it from the "
            "capacity: resource quantity × unit price (e.g., instance-hours × $/hr, GB-months × "
            "$/GB, egress GB × $/GB) — never invent a round monthly/annual total."
        )}

    # 6. Domain depth & completeness — only on a full design document, so clarifying
    #    questions and conceptual answers pass straight through to the LLM verifier.
    if _is_full_design(text):
        domain = _detect_domain(user_query, text)
        if domain:
            missing = _missing_domain_sections(domain, text)
            if missing:
                logger.warning(f"[SYSDESIGN_CRITIC] {domain} design missing core sections: {missing}")
                return {"verified": False, "feedback": (
                    f"This {domain} design is missing mandatory domain sections: "
                    f"{', '.join(missing)}. A senior {domain} design MUST address these core "
                    f"challenges — generic Redis/Kafka/Database/Load-Balancer boxes are not enough."
                )}

        if cap_body.strip() and _QUANT_TOKEN.search(cap_body):
            missing_cap = _missing_capacity_components(text)
            if missing_cap:
                logger.warning(f"[SYSDESIGN_CRITIC] Capacity missing dimensions: {missing_cap}")
                return {"verified": False, "feedback": (
                    f"Capacity Calculations is incomplete — it must quantify all of: "
                    f"{', '.join(missing_cap)}. Show the math (QPS = requests/day ÷ 86,400; "
                    f"storage/day × 365; bandwidth = QPS × payload; cache = hot-set × dataset)."
                )}

        if _arch_is_infra_only(text):
            logger.warning("[SYSDESIGN_CRITIC] Architecture diagram is infrastructure-only")
            return {"verified": False, "feedback": (
                "The architecture diagram names only infrastructure (Load Balancer / Redis / "
                "Kafka / Database). Show the application SERVICES and how a request flows "
                "through them, e.g., Client → API Gateway → Feed/Timeline/Ranking Services → "
                "Cache → DB, with Kafka where relevant."
            )}

        missing_components = _missing_diagram_components(text)
        if missing_components:
            logger.warning(f"[SYSDESIGN_CRITIC] Architecture diagram missing tiers: {missing_components}")
            return {"verified": False, "feedback": (
                f"The architecture diagram is missing required tiers: "
                f"{', '.join(missing_components)}. A complete diagram traces a request through all "
                f"seven: Client → API Gateway → Services → Cache → Queue → Database → Storage."
            )}

        missing_sections = _missing_mandatory_sections(text)
        if missing_sections:
            logger.warning(f"[SYSDESIGN_CRITIC] Design missing mandatory sections: {missing_sections}")
            return {"verified": False, "feedback": (
                f"This design is missing mandatory sections: {', '.join(missing_sections)}. Every "
                f"system design MUST include all of: Functional Requirements, Non-Functional "
                f"Requirements, Scale Estimation, Capacity Calculations, API Design, Database Design, "
                f"Redis Strategy, Kafka Strategy, Data Flow, Monitoring, Disaster Recovery, Security, "
                f"Tradeoffs, Cost Considerations, and an Architecture Diagram."
            )}

        # 7. Redis Strategy sizing: memory, eviction policy, and topology.
        redis_missing = _redis_strategy_check(text)
        if redis_missing:
            logger.warning(f"[SYSDESIGN_CRITIC] Redis Strategy missing: {redis_missing}")
            return {"verified": False, "feedback": (
                f"Redis Strategy is incomplete: missing {', '.join(redis_missing)}. "
                "State the cache size in GB, the eviction policy (LRU/LFU/TTL), and the "
                "cluster/replication topology (e.g., Redis Cluster, Sentinel, replicas)."
            )}

        # 8. Kafka Strategy sizing: partition count, retention, and throughput.
        kafka_missing = _kafka_strategy_check(text)
        if kafka_missing:
            logger.warning(f"[SYSDESIGN_CRITIC] Kafka Strategy missing: {kafka_missing}")
            return {"verified": False, "feedback": (
                f"Kafka Strategy is incomplete: missing {', '.join(kafka_missing)}. "
                "State the number of partitions, the retention window, and the expected "
                "throughput (MB/s or messages/s)."
            )}

        # 9. Cache sizing: hot-set / hit-ratio reasoning.
        cache_missing = _cache_sizing_check(text)
        if cache_missing:
            logger.warning(f"[SYSDESIGN_CRITIC] Cache sizing missing: {cache_missing}")
            return {"verified": False, "feedback": (
                f"Cache sizing is incomplete: missing {', '.join(cache_missing)}. "
                "Show the hot-set / working-set size and an estimated hit ratio (e.g., Pareto 80/20)."
            )}

        # 10. Replication assumptions: must be stated in the database/storage section.
        if _replication_check(text):
            logger.warning("[SYSDESIGN_CRITIC] Database/Storage missing replication factor")
            return {"verified": False, "feedback": (
                "Database Design / Storage section does not state the replication factor or "
                "durability model (e.g., replication factor = 3, Raft, multi-AZ). Always "
                "quantify how many copies of each piece of data are kept."
            )}

        # 11. API Design must list concrete endpoints, not just prose.
        if _api_missing_endpoints(text):
            logger.warning("[SYSDESIGN_CRITIC] API Design lists no concrete endpoints")
            return {"verified": False, "feedback": (
                "API Design is too vague — list concrete endpoints (HTTP method + path such as "
                "POST /posts, GET /feed, or RPC/GraphQL signatures) with request/response shapes, "
                "not just a statement that you 'expose REST APIs'."
            )}

    return {"verified": True, "feedback": ""}
