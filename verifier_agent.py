import logging
import re
import brain_manager
import dsa_critic
import sql_critic
import sysdesign_critic
import fullstack_critic
import debug_critic
import codereview_critic
import response_quality_critic
import verdict_utils

logger = logging.getLogger(__name__)

# ── Template isolation (Phase 9) ────────────────────────────────────────────
# Section headers that must NEVER appear in a given agent's output because they
# belong to a different specialist. Detected as markdown/section HEADERS only
# (not prose) so legitimate incidental mentions are not flagged.
_FORBIDDEN_SECTIONS = {
    "SYSTEM_DESIGN_AGENT": ["full code", "edge cases", "complexity analysis",
                             "patched code", "refactored code", "problem understanding"],
    "DEBUG_AGENT": ["complexity analysis", "architecture diagram", "kafka strategy",
                     "redis strategy", "database design", "project structure",
                     "scale estimation", "index strategy"],
    "SQL_AGENT": ["edge cases", "complexity analysis", "architecture diagram",
                   "project structure"],
    "DSA_AGENT": ["architecture diagram", "kafka strategy", "redis strategy",
                   "index strategy", "project structure", "scale estimation",
                   "disaster recovery"],
    "CODE_REVIEW_AGENT": ["architecture diagram", "kafka strategy", "scale estimation",
                           "edge cases", "complexity analysis"],
    "PROJECT_BUILDER_AGENT": ["complexity analysis", "edge cases", "architecture diagram",
                               "scale estimation"],
    "FULLSTACK_AGENT": ["complexity analysis", "edge cases", "architecture diagram",
                         "scale estimation"],
}


def _find_forbidden_section(agent_type: str, text: str):
    """Return the name of the first foreign section header found, else None."""
    forbidden = _FORBIDDEN_SECTIONS.get(agent_type)
    if not forbidden:
        return None
    for line in (text or "").splitlines():
        s = line.strip().lower()
        if not s:
            continue
        # Only treat markdown headers / bold headings / "Label:" lines as sections.
        is_header = s.startswith("#") or s.startswith("**") or (s.endswith(":") and len(s) < 40)
        if not is_header:
            continue
        cleaned = re.sub(r"[#*`:_]", "", s).strip()
        for f in forbidden:
            if cleaned == f or cleaned.startswith(f + " ") or cleaned.startswith(f):
                return f
    return None


def verify(agent_type: str, user_query: str, response_text: str) -> dict:
    # ── Template isolation guard (Phase 9): reject foreign sections ──
    foreign = _find_forbidden_section(agent_type, response_text)
    if foreign:
        logger.warning(f"[VERIFIER] {agent_type}: forbidden section '{foreign}' present — rejecting")
        return {"verified": False,
                "feedback": (f"Remove the '{foreign}' section. It does not belong in a "
                             f"{agent_type} response — stay strictly within this agent's template.")}

    # ── Universal response-quality gate (Phase 10): deterministic, no LLM ──
    # Catches placeholders/TODOs, truncated/unbalanced code, boilerplate repetition,
    # generic filler, and deflections for free, before any network call.
    q_ok, q_reason = response_quality_critic.deterministic_check(agent_type, user_query, response_text)
    if not q_ok:
        logger.warning(f"[VERIFIER] {agent_type}: response-quality issue — {q_reason}")
        return {"verified": False, "feedback": q_reason}

    if agent_type == "DSA_AGENT":
        # Run specialized DSA Critic first
        dsa_result = dsa_critic.critique(user_query, response_text)
        if not dsa_result["verified"]:
            return dsa_result

    if agent_type == "SQL_AGENT":
        # Deterministic SQL critic first: rejects generic SQL and incomplete
        # optimization templates; passes clarifications and conceptual questions.
        sql_result = sql_critic.critique(user_query, response_text)
        if not sql_result["verified"]:
            return sql_result

    if agent_type == "SYSTEM_DESIGN_AGENT":
        # Deterministic derived-numbers check: catches order-of-magnitude capacity
        # errors and hand-wavy capacity sections before the LLM verifier.
        sd_result = sysdesign_critic.critique(user_query, response_text)
        if not sd_result["verified"]:
            return sd_result

    if agent_type in ("PROJECT_BUILDER_AGENT", "FULLSTACK_AGENT"):
        # Deterministic project-build check: enforce the four mandatory directories
        # and reject truncated/placeholder code before the LLM verifier.
        fs_result = fullstack_critic.critique(user_query, response_text)
        if not fs_result["verified"]:
            return fs_result

    if agent_type == "DEBUG_AGENT":
        # Deterministic anti-fabrication check: no invented patched file when the user
        # supplied no code/stack trace.
        dbg_result = debug_critic.critique(user_query, response_text)
        if not dbg_result["verified"]:
            return dbg_result

    if agent_type == "CODE_REVIEW_AGENT":
        # Deterministic review check: critique present, refactored code present and
        # not truncated.
        cr_result = codereview_critic.critique(user_query, response_text)
        if not cr_result["verified"]:
            return cr_result

    sys_prompt = (
        "You are the Verifier Agent. You judge whether a specialist answer is CORRECT and "
        "COMPLETE enough to ship. Be fair, not pedantic: a solid, correct, complete answer "
        "must PASS. Only block genuine quality failures.\n\n"
        "Domain checks (verify the CORE of each — accept reasonable section-name variants):\n"
        "- DSA: correct & optimal algorithm, complete (non-truncated) code, accurate complexity.\n"
        "- SQL: NO hallucinated schema/tables; ALL mandatory sections must be present: Root Cause "
        "Analysis, Query Analysis, Index Strategy, EXPLAIN / Execution Plan Analysis, Partitioning "
        "Strategy, Read Replica Strategy, Redis Caching Strategy, Monitoring, Tradeoffs, Final "
        "Optimized Query (as fenced ```sql). The Index Strategy must be concrete (real CREATE INDEX "
        "or explicit justification) AND validated against the query shape: reject useless indexes, "
        "duplicate/redundant left-prefix indexes, and any index whose leading column is not used by "
        "a WHERE/JOIN/ORDER BY/GROUP BY predicate. The EXPLAIN / Execution Plan section must explain "
        "the relevant plan node types (Seq Scan, Index Scan, Bitmap Scan, Sort, Hash Aggregate). "
        "Partitioning DDL must be valid PostgreSQL (reject MySQL `VALUES LESS THAN`). Each "
        "optimization needs a cost/benefit justification. **CRITICAL EXCEPTION:** If the user gave "
        "no query/schema and the agent correctly asks for it without inventing tables, output "
        "VERIFIED immediately.\n"
        "- System Design: it MUST include all mandatory sections (Functional & Non-Functional "
        "Requirements, Scale Estimation, Capacity Calculations, API Design, Database Design, Redis "
        "Strategy, Kafka Strategy, Data Flow, Monitoring, Disaster Recovery, Security, Tradeoffs, "
        "Cost Considerations, Architecture Diagram). The Architecture Diagram MUST trace the request "
        "through all seven tiers (Client -> API Gateway -> named Services -> Cache -> Queue -> "
        "Database -> Storage) -- NOT a diagram of only infrastructure boxes (Load Balancer / Redis / "
        "Kafka / DB). Capacity Calculations must quantify requests/sec, storage growth, bandwidth, "
        "cache sizing AND fleet size with realistic, internally-consistent, DERIVED numbers: server "
        "counts must follow from peak QPS / per-server throughput (reject arbitrary counts and absurd "
        "estimates such as one server serving millions of QPS), and any cost must be derived from "
        "quantity x unit price (reject invented round totals). REJECT a design that only "
        "name-drops generic Redis / Kafka / Database / Load Balancer without addressing the "
        "system's core DOMAIN challenges. For a recognised domain the relevant deep-dives are "
        "MANDATORY:\n"
        "    * social feed (Instagram / Facebook / Twitter / LinkedIn): Feed Generation, Feed "
        "Ranking, Fan-out on Write, Fan-out on Read, Celebrity Handling, Media Storage, CDN "
        "Strategy, Search Architecture.\n"
        "    * messaging (WhatsApp / chat): Presence Service, Message Ordering, Delivery "
        "Guarantees, Multi Device Sync, End-to-End Encryption, Group Fan-out, Media Pipeline.\n"
        "    * e-commerce (Amazon / shop): Inventory Consistency, Checkout Flow, Recommendation "
        "System.\n"
        "  Technology Choices further enrich a design. There must be NO full application source dump.\n"
        "- Full Stack / Project Builder: real, COMPLETE, runnable CODE (not a tutorial, no "
        "dependency-only stubs, no placeholders/pseudo-code), and a Folder Structure that "
        "explicitly contains frontend/, backend/, database/, and docker/. The layers "
        "(Entities/Repositories/Services/Controllers/React Components/Docker Files) must contain "
        "actual code. If a technology is NAMED it must be fully implemented: JWT -> JwtFilter + "
        "JwtUtil + token validation + Authorization/Bearer header; Redis -> RedisConfig + "
        "RedisTemplate + cache usage + invalidation; Kafka -> producer + @KafkaListener consumer + "
        "topic + event flow. E-commerce -> Cart, CartItem, OrderItem, Payment, Inventory. Use a "
        "SecurityFilterChain bean (NEVER WebSecurityConfigurerAdapter). Docker -> a real Dockerfile "
        "AND docker-compose. React -> pages, components, an API service layer, routing, and live "
        "API integration. If API docs are advertised, Swagger/OpenAPI config must exist. Every "
        "build needs a DTO layer, a GlobalExceptionHandler, validation annotations, and logging. "
        "Do not reject solely for a missing README.\n\n"
        "Reject ONLY if one of these is clearly true:\n"
        "- The code is incomplete or stops midway.\n"
        "- A feature the user EXPLICITLY demanded is entirely absent.\n"
        "- The stated complexity/analysis is factually wrong.\n"
        "- The answer hallucinated schema/data, or is off-topic for the agent.\n"
        "- A SQL optimization is missing a mandatory section, proposes a useless / duplicate / "
        "mismatched index, uses invalid PostgreSQL partition syntax, fails to explain the plan "
        "node types (Seq Scan / Index Scan / Bitmap Scan / Sort / Hash Aggregate), or omits the "
        "cost/benefit of its optimizations.\n"
        "- A System Design only name-drops generic infrastructure (Redis / Kafka / DB / Load "
        "Balancer) without its core domain challenges, omits a mandatory section (e.g., Security, "
        "Monitoring, Cost) or a MANDATORY domain deep-dive, ships an architecture diagram that is "
        "infrastructure-only or omits any of the seven tiers, asserts arbitrary server counts or "
        "invented infrastructure costs, or gives unrealistic / incomplete capacity numbers (missing "
        "requests/sec, storage growth, bandwidth, cache sizing, or fleet size).\n\n"
        "Do NOT reject for: exhaustive vendor benchmarks, minor section "
        "renaming, or stylistic preferences. (For System Design, the mandatory sections, capacity "
        "sizing, derived server/cost numbers, and the core domain deep-dives are NOT optional.)\n\n"
        "If it passes, output EXACTLY AND ONLY the word: VERIFIED\n"
        "If it genuinely fails, output: REJECTED\n"
        "followed by a concise explanation of what must be fixed."
    )

    prompt = f"User Query:\n{user_query}\n\nProposed Response:\n{response_text}"

    logger.info(f"[VERIFIER] Verifying response for {agent_type}...")

    response, _ = brain_manager.ask(
        prompt=prompt,
        context="",
        sys_prompt=sys_prompt,
        max_tokens=500,
        deepthink=False,
        stateless=True,  # QA call — never pollutes/reads shared conversation history
    )

    verified, feedback = verdict_utils.parse_verdict(response, default_verified=False)
    if verified:
        # ── Universal response-quality bar (Phase 10): ChatGPT/Claude/DeepSeek-grade ──
        # Runs only on otherwise-acceptable answers; scores 5 dimensions and regenerates
        # if any is below the bar. Fails OPEN so a good answer is never blocked.
        q_ok, q_reason = response_quality_critic.score(agent_type, user_query, response_text)
        if not q_ok:
            logger.warning(f"[VERIFIER] {agent_type}: below quality bar — {q_reason}")
            return {"verified": False, "feedback": q_reason}
        logger.info(f"[VERIFIER] Status: VERIFIED")
        return {"verified": True, "feedback": ""}
    logger.warning(f"[VERIFIER] Status: REJECTED. Reason: {feedback}")
    return {"verified": False, "feedback": feedback}
