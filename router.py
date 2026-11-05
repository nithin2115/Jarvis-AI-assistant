import logging
import re
import time

logger = logging.getLogger(__name__)

# Timeout resiliency: per-attempt timeout shrinks on retries so a slow provider
# doesn't burn the entire budget; total deadline caps worst-case latency.
_FIRST_ATTEMPT_TIMEOUT = 60
_TIMEOUT_DECREMENT = 15
_MIN_ATTEMPT_TIMEOUT = 20
_TOTAL_ROUTER_TIMEOUT = 150  # hard ceiling for all generation attempts

# Define agent names
DSA_AGENT = "DSA_AGENT"
SQL_AGENT = "SQL_AGENT"
SYSTEM_DESIGN_AGENT = "SYSTEM_DESIGN_AGENT"
PROJECT_BUILDER_AGENT = "PROJECT_BUILDER_AGENT"
DEBUG_AGENT = "DEBUG_AGENT"
CODE_REVIEW_AGENT = "CODE_REVIEW_AGENT"
FULLSTACK_AGENT = "FULLSTACK_AGENT"
GENERAL_ASSISTANT_AGENT = "GENERAL_ASSISTANT_AGENT"

# Define routing keywords based on phase 3 specifications
ROUTER_CONFIG = {
    DEBUG_AGENT: [
        "error", "exception", "bug", "crash", "not working", "fix", "debug"
    ],
    PROJECT_BUILDER_AGENT: [
        "build", "create project", "create application", "generate application", 
        "spring boot", "react", "mern", "node", "express", "django", "flask"
    ],
    SYSTEM_DESIGN_AGENT: [
        "design", "architecture", "distributed", "scalable", "redis", "kafka", 
        "microservice", "load balancer", "whatsapp", "twitter", "uber", "netflix"
    ],
    SQL_AGENT: [
        "sql", "mysql", "postgresql", "oracle", "query", "join", "database", 
        "index", "execution plan", "aggregation", "schema"
    ],
    CODE_REVIEW_AGENT: [
        "review code", "refactor", "optimize code", "improve code", "analyze code"
    ],
    DSA_AGENT: [
        "leetcode", "array", "string", "tree", "graph", "dfs", "bfs", "heap", 
        "stack", "queue", "trie", "dp", "dynamic programming", "sliding window", 
        "binary search", "segment tree", "lru", "lfu", "median finder"
    ],
    FULLSTACK_AGENT: [
        "frontend", "backend", "rest api", "authentication", "react component", 
        "angular", "vue"
    ]
}

# The dictionary iteration order acts as our priority check in Python 3.7+
# The agents are ordered by priority (Phase 4):
# Priority: DEBUG_AGENT -> PROJECT_BUILDER_AGENT -> SYSTEM_DESIGN_AGENT -> SQL_AGENT -> CODE_REVIEW_AGENT -> DSA_AGENT -> FULLSTACK_AGENT -> GENERAL_ASSISTANT_AGENT

# Agent Prompts
import os
AGENT_PROMPTS = {
    GENERAL_ASSISTANT_AGENT: "You are a helpful, concise AI assistant. Answer general questions directly and conversationally."
}

def _load_agent_prompts():
    agent_files = {
        DSA_AGENT: "DSA_AGENT.md",
        SQL_AGENT: "SQL_AGENT.md",
        SYSTEM_DESIGN_AGENT: "SYSTEM_DESIGN_AGENT.md",
        PROJECT_BUILDER_AGENT: "FULLSTACK_AGENT.md",
        DEBUG_AGENT: "DEBUG_AGENT.md",
        CODE_REVIEW_AGENT: "CODE_REVIEW_AGENT.md",
        FULLSTACK_AGENT: "FULLSTACK_AGENT.md"
    }

    # Optional per-agent knowledge bases. When present, the KB is appended to the
    # agent's system prompt so domain facts/patterns live in modular files that can
    # be iterated on independently of the prompt itself.
    knowledge_bases = {
        DSA_AGENT: "DSA_KNOWLEDGE_BASE.md",
        SQL_AGENT: "SQL_KNOWLEDGE_BASE.md",
        SYSTEM_DESIGN_AGENT: "SYSTEM_DESIGN_KNOWLEDGE_BASE.md",
        PROJECT_BUILDER_AGENT: "FULLSTACK_STANDARDS.md",
        FULLSTACK_AGENT: "FULLSTACK_STANDARDS.md",
        DEBUG_AGENT: "DEBUG_KNOWLEDGE_BASE.md",
        CODE_REVIEW_AGENT: "CODE_REVIEW_KNOWLEDGE_BASE.md",
    }

    base_dir = os.path.dirname(os.path.abspath(__file__))
    for agent, filename in agent_files.items():
        filepath = os.path.join(base_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                AGENT_PROMPTS[agent] = f.read()
        else:
            logger.warning(f"Agent prompt file missing: {filepath}")

        kb_name = knowledge_bases.get(agent)
        if kb_name:
            kb_path = os.path.join(base_dir, kb_name)
            if os.path.exists(kb_path):
                with open(kb_path, "r", encoding="utf-8") as f:
                    kb = f.read().strip()
                if kb and agent in AGENT_PROMPTS:
                    AGENT_PROMPTS[agent] += "\n\n---\n\n" + kb

_load_agent_prompts()


# ── Weighted, word-boundary keyword routing ─────────────────────────────────
# Naive substring matching caused false positives (bare "node" hijacked DSA
# queries, generic "design"/"build" beat data-structure terms). We now score
# every agent by summing the weights of matched keywords and pick the highest
# score. Ties break by the priority order of this dict.
_W_STRONG, _W_MED, _W_WEAK = 3, 2, 1
WEIGHTED_CONFIG = {
    DEBUG_AGENT: {
        _W_STRONG: ["nullpointerexception", "null pointer", "stack trace", "stacktrace",
                    "traceback", "segfault", "segmentation fault", "indexoutofbounds",
                    "indexoutofboundsexception", "arrayindexoutofboundsexception",
                    "classnotfound", "classnotfoundexception", "nosuchmethod",
                    "nosuchmethoderror", "stackoverflowerror", "illegalargumentexception",
                    "illegalstateexception", "concurrentmodificationexception",
                    "numberformatexception", "classcastexception"],
        _W_MED:    ["exception", "error", "crash", "crashes", "crashing", "crashed",
                    "bug", "not working", "debug", "throws", "fails with", "won't compile",
                    "failing", "fails", "hangs", "freezes", "deadlock", "race condition",
                    "memory leak", "infinite loop", "won't run", "wont run", "doesn't run",
                    "returns null", "not matching", "off by one", "off-by-one"],
        _W_WEAK:   ["fix", "unexpected", "unexpectedly"],
    },
    PROJECT_BUILDER_AGENT: {
        # STRONG = explicit build ACTIONS. A bare framework name only signals the
        # tech stack (MED), so it never outweighs a clear debug/error intent.
        _W_STRONG: ["create project", "create application", "generate application",
                    "mern", "scaffold", "boilerplate", "build app", "full stack app",
                    "todo app", "starter template", "starter kit"],
        _W_MED:    ["spring boot", "react", "express", "django", "flask", "node.js",
                    "nodejs", "next.js", "docker", "docker-compose", "dockerfile"],
        _W_WEAK:   ["build", "project"],
    },
    SYSTEM_DESIGN_AGENT: {
        _W_STRONG: ["whatsapp", "twitter", "uber", "netflix", "instagram", "amazon",
                    "youtube", "google drive", "dropbox", "tinyurl", "url shortener",
                    "rate limiter", "web crawler", "system design", "distributed",
                    "microservice", "microservices", "load balancer", "message queue",
                    "kafka", "billion users", "million users"],
        _W_MED:    ["architecture", "scalable", "scalability", "redis", "sharding",
                    "replication", "consistent hashing", "cdn", "high availability",
                    "fault tolerant", "fault tolerance"],
        _W_WEAK:   ["design"],
    },
    SQL_AGENT: {
        _W_STRONG: ["postgresql", "postgres", "mysql", "oracle", "execution plan",
                    "explain analyze", "query plan", "materialized view", "optimize query"],
        _W_MED:    ["sql", "query", "database", "schema", "index", "indexes", "join",
                    "aggregation", "partition", "partitioning", "shard", "cardinality",
                    "seq scan", "b-tree", "btree", "window function", "cte",
                    "group by", "upsert", "denormalize", "denormalization",
                    "stored procedure", "foreign key", "primary key"],
        _W_WEAK:   [],
    },
    CODE_REVIEW_AGENT: {
        _W_STRONG: ["review code", "code review", "review this", "refactor",
                    "analyze code", "improve code", "review my", "review my code",
                    "code smell", "code smells"],
        _W_MED:    ["idiomatic", "readability", "maintainability", "best practices",
                    "clean up", "cleanup", "critique", "code quality", "quality issues"],
        _W_WEAK:   ["review", "feedback", "improvements", "maintainable", "readable",
                    "audit"],
    },
    DSA_AGENT: {
        _W_STRONG: ["linked list", "binary tree", "binary search", "dynamic programming",
                    "sliding window", "segment tree", "fenwick", "two sum",
                    "two sorted arrays", "median", "lru", "lfu", "leetcode",
                    "time complexity", "space complexity", "big o", "quicksort",
                    "merge sort", "dijkstra", "bellman ford", "floyd warshall",
                    "topological sort", "union find", "kth largest", "kth smallest",
                    "top k", "monotonic", "knapsack", "longest common"],
        _W_MED:    ["array", "string", "tree", "graph", "heap", "stack", "queue",
                    "trie", "dfs", "bfs", "cache", "dp", "recursion", "backtracking",
                    "memoization", "greedy", "two pointers", "prefix sum",
                    "subarray", "substring", "palindrome", "palindromic", "fibonacci"],
        _W_WEAK:   ["sort", "complexity", "algorithm", "optimal", "memoized"],
    },
    FULLSTACK_AGENT: {
        _W_STRONG: ["rest api", "jwt", "authentication", "oauth", "oauth2"],
        _W_MED:    ["frontend", "backend", "react component", "angular", "vue",
                    "rbac", "nginx", "spring security", "role based access control",
                    "role-based access control", "access control"],
        _W_WEAK:   [],
    },
}


def _kw_present(token: str, q: str) -> bool:
    """Word-boundary match that also respects punctuation boundaries (so 'sql'
    does NOT match inside 'postgresql' and 'node' does NOT match 'node by node'
    unless the token is exactly 'node')."""
    pat = r'(?<![a-z0-9])' + re.escape(token) + r'(?![a-z0-9])'
    return re.search(pat, q) is not None


def _kw_matches(keyword: str, q: str) -> bool:
    """A multi-word keyword matches when every token is present (word-boundary)."""
    return all(_kw_present(tok, q) for tok in keyword.split())


def _score_query(user_query: str):
    """Score every configured agent for the query. Returns (scores, matched)."""
    ql = (user_query or "").lower()
    scores, matched = {}, {}
    for agent, tiers in WEIGHTED_CONFIG.items():
        total, hits = 0, []
        for weight, kws in tiers.items():
            for kw in kws:
                if _kw_matches(kw, ql):
                    total += weight
                    hits.append(kw)
        scores[agent] = total
        matched[agent] = hits
    return scores, matched


def _best_agent(scores: dict) -> str:
    """Highest score wins; ties resolved by the priority order of WEIGHTED_CONFIG."""
    best = max(scores.values()) if scores else 0
    if best <= 0:
        return GENERAL_ASSISTANT_AGENT
    for agent in WEIGHTED_CONFIG:
        if scores.get(agent, 0) == best:
            return agent
    return GENERAL_ASSISTANT_AGENT


def classify_intent(user_query: str) -> dict:
    """Weighted intent classification.

    Returns a structured verdict: the selected ``agent``, a normalized
    ``confidence`` in [0,1], the ``top_intents`` (up to 3 candidates with their
    score/confidence/matched keywords), the raw ``scores`` map, and a
    human-readable ``explanation``. ``route_agent`` shares the same scoring, so
    its result always equals ``top_intents[0].agent`` (or GENERAL when nothing
    matched)."""
    scores, matched = _score_query(user_query)
    selected = _best_agent(scores)

    # Rank by (score, earliest-priority) so ties follow the routing order.
    order = list(WEIGHTED_CONFIG.keys())
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1], -order.index(kv[0])),
        reverse=True,
    )
    positive_total = sum(s for _, s in ranked if s > 0)
    top = []
    for agent, score in ranked[:3]:
        conf = round(score / positive_total, 3) if positive_total > 0 else 0.0
        top.append({
            "agent": agent,
            "score": score,
            "confidence": conf,
            "matched": matched.get(agent, []),
        })

    best_score = ranked[0][1] if ranked else 0
    if best_score <= 0:
        selected = GENERAL_ASSISTANT_AGENT
        confidence = 0.0
        explanation = "No domain keywords matched; routed to the general assistant."
    else:
        confidence = top[0]["confidence"]
        runner_up = top[1] if len(top) > 1 and top[1]["score"] > 0 else None
        margin = best_score - (runner_up["score"] if runner_up else 0)
        explanation = (
            f"Matched {matched.get(selected, [])} (score {best_score}); won by "
            f"margin {margin} over "
            f"{runner_up['agent'] if runner_up else 'no other candidate'}."
        )

    return {
        "agent": selected,
        "confidence": confidence,
        "top_intents": top,
        "scores": scores,
        "matched": matched.get(selected, []),
        "explanation": explanation,
    }


def route_agent(user_query: str) -> str:
    """Deterministically route a user query to the appropriate agent via weighted scoring."""
    scores, matched = _score_query(user_query)
    selected = _best_agent(scores)
    best = scores.get(selected, 0)
    if selected == GENERAL_ASSISTANT_AGENT and best <= 0:
        logger.info(f"[ROUTER]\nQuery: {user_query}\nSelected Agent: {GENERAL_ASSISTANT_AGENT}\nMatched: None")
    else:
        logger.info(f"[ROUTER]\nQuery: {user_query}\nSelected Agent: {selected}\nScore: {best} | Matched: {matched.get(selected, [])}")
    return selected

def _check_integrity(text: str) -> list:
    """Backend response-integrity stage. Returns a list of detected issues.

    Kept conservative so prose parentheses/braces do not raise false alarms —
    the only hard structural signal we trust on the backend is unbalanced code
    fences (a reliable truncation indicator)."""
    issues = []
    if not text:
        issues.append("empty response")
        return issues
    if text.count("```") % 2 != 0:
        issues.append("unbalanced code fences")
    return issues


# Short, user-safe message. Retained for backwards-compat, but the pipeline no
# longer returns this for valid technical queries (see best-effort delivery below).
# NEVER contains verifier/critic notes, requirement diagnostics, or internal reasoning.
_SAFE_FALLBACK_MESSAGE = (
    "I wasn't able to put together a complete answer for that just now. "
    "Could you rephrase or add a little more detail so I can help properly?"
)

# Agent-specific RECOVERY prompts (Phase 5): appended on the FINAL attempt to force
# a complete, best-effort answer instead of yet another rejected fragment.
_RECOVERY_PROMPTS = {
    "DSA_AGENT": (
        "FINAL ATTEMPT — you MUST output a complete, optimal solution now: the full "
        "compilable code in one fenced block, the correct optimal algorithm, and accurate "
        "time/space complexity. Do NOT truncate or omit the code."
    ),
    "SQL_AGENT": (
        "FINAL ATTEMPT — provide the optimized query plus a concrete index strategy now. "
        "If the schema is unknown, state explicit reasonable assumptions and proceed; do not refuse."
    ),
    "SYSTEM_DESIGN_AGENT": (
        "FINAL ATTEMPT — deliver the full design now: functional requirements, an architecture "
        "diagram (Client -> Gateway -> Services -> Redis -> DB), data model, and scaling. "
        "Do not omit core sections."
    ),
    "PROJECT_BUILDER_AGENT": (
        "FINAL ATTEMPT — output the real project NOW: a folder structure containing frontend/, "
        "backend/, database/, and docker/, plus the key source files as code. Build it, don't explain."
    ),
    "DEBUG_AGENT": (
        "FINAL ATTEMPT — give a concrete root-cause analysis and specific fixes. If you genuinely "
        "need the user's code, ask exactly one focused question."
    ),
    "CODE_REVIEW_AGENT": (
        "FINAL ATTEMPT — deliver the review now with concrete issues and refactored code."
    ),
}


def _draft_quality(text: str) -> float:
    """Cheap completeness score used to pick the best-effort draft (Phase 7)."""
    if not text or not text.strip():
        return 0.0
    score = float(len(text.strip()))
    if "```" in text and text.count("```") % 2 == 0:
        score += 2000.0  # a complete, balanced code block is a strong completeness signal
    return score


def _clarification_message(agent: str, user_query: str) -> str:
    """Context-tied clarification, used ONLY when NO usable draft was produced at all
    (Category A: unintelligible request, or Category B: missing information). This is
    NOT a generic apology — it asks for the specific missing piece so the user can
    immediately retry productively."""
    asks = {
        "DSA_AGENT": "which problem should I solve, plus any constraints (language, input size)?",
        "SQL_AGENT": "share the query (and table schema if you have it) you want optimized.",
        "DEBUG_AGENT": "share the code and the full error / stack trace so I can pinpoint the cause.",
        "CODE_REVIEW_AGENT": "paste the code you'd like me to review.",
        "SYSTEM_DESIGN_AGENT": "which system should I design, and any scale or feature constraints?",
        "PROJECT_BUILDER_AGENT": "what should I build? Tell me the stack and the core features.",
    }
    ask = asks.get(agent, "could you add a bit more detail about exactly what you need?")
    return f"I can help with this — {ask}"


def run_agent(agent: str, user_query: str, **kwargs) -> str:
    """
    Executes the selected agent through the full pipeline with strict per-request
    isolation:
      Generator -> Requirement Tracker -> Critic/Verifier -> Integrity Check -> Stream.

    Each invocation owns a unique request_id and its own isolated buffers, so agent
    outputs can never mix across sequential or concurrent requests. Internal QA
    output (verifier/critic notes) is NEVER streamed or returned to the user.
    """
    import brain_manager
    import requirement_tracker
    import verifier_agent
    import uuid

    sys_prompt = AGENT_PROMPTS.get(agent, AGENT_PROMPTS[GENERAL_ASSISTANT_AGENT])

    on_chunk = kwargs.pop('on_chunk', None)
    context = kwargs.pop('context', "")

    # ── Per-request isolation context (Phase 3) ──────────────────────────────
    req = {
        "request_id": uuid.uuid4().hex[:12],
        "agent_id": agent,
        "generation_buffer": "",   # latest draft from the generator (overwritten per attempt)
        "verifier_buffer": "",     # internal QA feedback — NEVER streamed to the user
        "stream_buffer": "",       # exact text emitted to the user
        "renderer_buffer": "",     # final text handed to the renderer
    }
    rid = req["request_id"]

    def _emit_status(msg, is_active=True):
        try:
            from app import socketio
            socketio.emit("search_status", {"searching": is_active, "query": msg, "category": "Agent Pipeline"}, namespace="/")
        except Exception:
            pass

    def _stream_out(text: str):
        """Stream ONLY this request's buffer to the user (no cross-request reuse)."""
        if not text:
            return
        req["stream_buffer"] += text
        if on_chunk:
            on_chunk(text)

    logger.info(f"[PIPELINE_START] request_id={rid} agent={agent}")

    # ── Fast path: casual / general chat streams live (best TTFB, no verifier
    #    overhead). Verification only matters for the specialist agents. ──
    if agent == GENERAL_ASSISTANT_AGENT:
        logger.info(f"[STREAM_START] request_id={rid} direct")
        full, provider = brain_manager.ask_stream(
            user_query, context, sys_prompt, on_chunk=on_chunk, **kwargs
        )
        logger.info(f"[STREAM_END] request_id={rid} direct ({len(full)} chars via {provider})")
        logger.info(f"[PIPELINE_END] request_id={rid}")
        return full

    # ── Specialist path: buffer -> requirements -> critic/verifier -> integrity ──
    requirements = requirement_tracker.extract_requirements(user_query)

    # Specialist answers are long (full code + multiple structured sections), so the
    # default 600-token cap truncates them mid-code and the verifier rejects the
    # fragment forever. Give generation a real budget unless the caller overrides.
    # Generation is STATELESS at the brain layer: it must not read or write the
    # shared conversation history (continuity comes from the curated `context`).
    gen_kwargs = dict(kwargs)
    gen_kwargs.setdefault('max_tokens', 4096)
    # Default first-attempt timeout; it will be decremented on retries.
    gen_kwargs.setdefault('timeout', _FIRST_ATTEMPT_TIMEOUT)
    gen_kwargs['stateless'] = True

    max_attempts = 3
    final_response = ""
    verified_ok = False
    current_sys_prompt = sys_prompt

    # Best-effort tracking (Phase 7): remember the strongest draft we ever produce so
    # a valid query is NEVER answered with a generic apology.
    best_draft = ""
    best_q = 0.0
    best_missing = 10 ** 9
    last_reason = ""

    total_deadline = time.time() + _TOTAL_ROUTER_TIMEOUT

    for attempt in range(max_attempts):
        is_final = attempt == max_attempts - 1
        attempt_kwargs = dict(gen_kwargs)
        # Shrink timeout on retries so we don't keep waiting for a struggling provider.
        attempt_kwargs['timeout'] = max(
            _MIN_ATTEMPT_TIMEOUT,
            gen_kwargs['timeout'] - attempt * _TIMEOUT_DECREMENT
        )

        # If the overall budget is nearly exhausted, stop generating and fall back.
        if time.time() >= total_deadline - _MIN_ATTEMPT_TIMEOUT:
            logger.warning(
                f"[TIMEOUT] request_id={rid} total router budget exhausted; "
                f"skipping remaining attempts"
            )
            last_reason = "router timeout: total generation budget exhausted"
            break

        # ── Self-healing escalation (Phase 3/5): on the final attempt, switch to
        #    stronger reasoning and inject an agent-specific recovery prompt. ──
        if is_final:
            recovery = _RECOVERY_PROMPTS.get(agent)
            if recovery and recovery not in current_sys_prompt:
                current_sys_prompt += f"\n\n{recovery}"
            attempt_kwargs["deepthink"] = True
            logger.info(f"[ESCALATE] request_id={rid} final attempt — deepthink + recovery prompt")

        logger.info(f"[GENERATE_START] request_id={rid} attempt {attempt + 1}/{max_attempts}")
        _emit_status(f"Drafting response (attempt {attempt + 1})...")

        # Buffer the response, DO NOT stream to user yet — only verified text ships.
        # Phase 6: self-consistency A/B comparison on the first attempt.
        if attempt == 0:
            import self_consistency
            draft_response, provider, _ = self_consistency.generate_best_draft(
                agent, user_query, context, current_sys_prompt, brain_manager.ask, n=2, **attempt_kwargs
            )
        else:
            draft_response, provider = brain_manager.ask(
                user_query, context, current_sys_prompt, **attempt_kwargs
            )
        req["generation_buffer"] = draft_response
        logger.info(f"[GENERATE_END] request_id={rid} attempt {attempt + 1} ({len(draft_response)} chars via {provider})")

        # Requirement tracking with severity levels (Phase 2): only MANDATORY
        # omissions block the answer. RECOMMENDED -> warning. OPTIONAL -> ignored.
        missing = []
        if requirements:
            current_reqs = {k: False for k in requirements.keys()}
            requirement_tracker.check_requirements_satisfied(draft_response, current_reqs)
            missing = requirement_tracker.get_missing_requirements(current_reqs, level=requirement_tracker.LEVEL_MANDATORY)
            missing_recommended = requirement_tracker.get_missing_requirements(current_reqs, level=requirement_tracker.LEVEL_RECOMMENDED)
            if missing_recommended:
                logger.warning(f"[REQUIREMENTS] request_id={rid} Missing RECOMMENDED (warning, not blocking): {missing_recommended}")

        # Remember the best-effort draft (Phase 7): prefer the fewest missing MANDATORY
        # requirements, then the most complete content. Guarantees a real answer ships.
        q = _draft_quality(draft_response)
        if best_draft == "" or (len(missing), -q) < (best_missing, -best_q):
            best_draft, best_q, best_missing = draft_response, q, len(missing)

        if missing:
            last_reason = f"missing mandatory requirements: {missing}"
            logger.warning(f"[REQUIREMENTS] request_id={rid} Missing MANDATORY: {missing}. Regenerating.")
            current_sys_prompt += (
                f"\n\nIMPORTANT FEEDBACK: You completely missed the following mandatory requirements: "
                f"{', '.join(missing)}. You MUST include them in your response."
            )
            if attempt < max_attempts - 1:
                _emit_status("Refining response...")
                continue

        # Critic + Verifier
        logger.info(f"[VERIFY_START] request_id={rid}")
        _emit_status("Verifying response...")
        verification = verifier_agent.verify(agent, user_query, draft_response)
        req["verifier_buffer"] = verification.get("feedback", "")  # internal only — never streamed
        logger.info(f"[VERIFY_END] request_id={rid} verified={verification['verified']}")

        if verification["verified"] and not missing:
            final_response = draft_response
            verified_ok = True
            break

        # Verification failed → feed feedback back into the prompt and regenerate.
        feedback = verification["feedback"]
        if not missing:
            last_reason = feedback or "verifier rejected the draft"
        if missing:
            feedback = f"Missing requirements: {', '.join(missing)}. " + feedback
        current_sys_prompt += f"\n\nIMPORTANT VERIFIER FEEDBACK: {feedback}. Fix these issues."

    # ── No VERIFIED answer after all attempts ────────────────────────────────
    # Phase 2: log the FULL root cause (never shown to the user). Phase 3/7: a query
    # that produced real content is NEVER answered with a generic apology — we ship
    # the best-effort draft (self-healing). Only a query that produced NOTHING usable
    # gets a context-tied clarification (Category A/B).
    delivery_mode = "verified"
    if not verified_ok:
        logger.warning(
            f"[FALLBACK_ROOT_CAUSE] request_id={rid} agent={agent} "
            f"regeneration_count={max_attempts} best_draft_len={len(best_draft)} "
            f"best_missing_mandatory={best_missing} "
            f"failure_reason={(last_reason or 'unknown')[:300]!r}"
        )
        if best_draft.strip():
            logger.info(f"[BEST_EFFORT] request_id={rid} delivering best-effort draft (no generic fallback)")
            final_response = best_draft
            delivery_mode = "best_effort"
        else:
            logger.info(f"[CLARIFY] request_id={rid} no usable draft produced — asking a context-tied clarification")
            final_response = _clarification_message(agent, user_query)
            delivery_mode = "clarification"

    # ── Response Integrity stage ──
    logger.info(f"[INTEGRITY_START] request_id={rid}")

    # DSA cleanup pass (Phase 11): strip duplicate sections, repeated headers, and
    # template artifacts before delivery. No-op when the answer is already clean.
    if agent == DSA_AGENT:
        try:
            import dsa_output_quality
            cleaned = dsa_output_quality.cleanup(final_response)
            if cleaned != final_response:
                logger.info(f"[INTEGRITY] request_id={rid} DSA cleanup removed duplicate/artifact content")
                final_response = cleaned
        except Exception as e:
            logger.warning(f"[INTEGRITY] request_id={rid} DSA cleanup skipped ({e})")

    # LFU critic check (Phase 13): deterministic validation of LFU cache
    # implementations — eviction patterns, LRU tie-break, required data
    # structures, O(1) proof, duplicate sections, template fragments.
    if agent == DSA_AGENT:
        try:
            import lfu_critic
            ok, reason = lfu_critic.check(user_query, final_response)
            if not ok:
                logger.warning(f"[INTEGRITY] request_id={rid} LFU critic REJECTED: {reason}")
                if best_draft.strip():
                    final_response = best_draft
                    delivery_mode = "best_effort"
                else:
                    final_response = _clarification_message(agent, user_query)
                    delivery_mode = "clarification"
        except Exception as e:
            logger.warning(f"[INTEGRITY] request_id={rid} LFU critic skipped ({e})")

    # ResponseFinalizer (Phase 1): unified finalization stage. Runs after
    # generation, critic, and verifier but before streaming. Deduplicates canonical
    # sections, strips critic/verifier/regeneration artifacts, validates markdown
    # and code fences, and runs the Phase 12 sanitizer checks. On rejection, fall
    # back to the best-effort draft (or clarification if none available).
    try:
        import response_finalizer
        ok, reason, cleaned = response_finalizer.finalize(agent, user_query, final_response)
        if cleaned != final_response:
            logger.info(f"[INTEGRITY] request_id={rid} ResponseFinalizer cleaned response")
            final_response = cleaned
        if not ok:
            logger.warning(f"[INTEGRITY] request_id={rid} ResponseFinalizer REJECTED: {reason}")
            if best_draft.strip():
                logger.info(f"[INTEGRITY] request_id={rid} falling back to best-effort draft")
                final_response = best_draft
                delivery_mode = "best_effort"
            else:
                final_response = _clarification_message(agent, user_query)
                delivery_mode = "clarification"
    except Exception as e:
        logger.warning(f"[INTEGRITY] request_id={rid} ResponseFinalizer skipped ({e})")

    issues = _check_integrity(final_response)
    if issues:
        logger.warning(f"[INTEGRITY] request_id={rid} Issues detected: {issues}")
        if "unbalanced code fences" in issues:
            final_response += "\n```"
            logger.info(f"[INTEGRITY] request_id={rid} Repaired unbalanced code fence")
    logger.info(f"[INTEGRITY_END] request_id={rid} issues={len(issues)}")

    req["renderer_buffer"] = final_response
    _emit_status("Done", False)

    # ── Stream the verified response (no artificial per-chunk delay) ──
    if on_chunk and final_response:
        logger.info(f"[STREAM_START] request_id={rid}")
        chunk_size = 400
        for i in range(0, len(final_response), chunk_size):
            _stream_out(final_response[i:i + chunk_size])
        logger.info(f"[STREAM_END] request_id={rid} ({len(req['stream_buffer'])} chars)")

    logger.info(f"[PIPELINE_END] request_id={rid} agent={agent} verified={verified_ok} delivery={delivery_mode}")
    return final_response

