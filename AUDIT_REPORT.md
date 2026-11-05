# JARVIS — Architecture Audit Report

_Phase 1 deliverable. Traced from the live code, not assumptions._

## Request lifecycle (as implemented)

```
User
 -> app.ask_ai()                      # app.py: routing + context build + memory
 -> router.route_agent()              # weighted keyword scoring -> agent id
 -> router.run_agent()                # the specialist pipeline:
      -> requirement_tracker.extract_requirements()
      -> LOOP (max 3 attempts):
           -> brain_manager.ask()                 # generator (stateless, 4096 tok)
           -> requirement_tracker.check_*()        # MANDATORY gate only
           -> verifier_agent.verify()              # forbidden-section + DSA critic + LLM
                -> dsa_critic.critique()           # DSA only: dsa_complexity + LLM
           -> on final attempt: deepthink + recovery prompt (escalation)
      -> best-effort delivery (ship strongest draft; never a generic apology)
      -> _check_integrity()                        # fence-balance repair
      -> stream to user
```

Provider layer: `brain_manager` fails over Gemini -> Groq -> OpenRouter, then a local
non-API fallback for total outages.

## Stage-by-stage findings

### 1. Router (`router.py`)
- **Strengths:** Already weighted (STRONG/MED/WEAK tiers), word-boundary matching
  (`_kw_present`) prevents the classic false positives (`sql` inside `postgresql`,
  `node` inside "node by node"). Deterministic, fast, no LLM cost.
- **Weaknesses:** Returns only a bare agent string — **no confidence, no top-3
  candidates, no explanation**. Keyword coverage has gaps vs. the target spec
  (`dp`, `partition`, `shard`, `optimize query`, `dijkstra`, `top k`, `billion users`).
- **Risk:** Low routing risk today; main gap is observability/extensibility.

### 2. Requirement Tracker (`requirement_tracker.py`)
- **Strengths:** Extracts only **explicit** `Requirements:` blocks; deliberately does
  NOT hallucinate implicit requirements (a prior bug). Severity levels
  (MANDATORY/RECOMMENDED/OPTIONAL) mean only hard omissions block shipping.
- **Weakness:** Substring matching can over-credit a requirement mentioned in prose.
- **Hallucination risk:** Low (the dangerous LLM-guess path was removed).

### 3. Generator (agent prompts `*_AGENT.md`)
- **Strengths:** Strict per-agent templates with section specs and validation rules.
  DSA prompt already encodes Known Optimal Patterns (Two Heaps + Lazy Deletion, etc.).
- **Weaknesses:** No shared **knowledge base** of derivations/standards — the model
  re-derives DSA patterns, SQL index theory, capacity math, and Spring/JWT security
  from scratch each call, which is where ChatGPT/Claude/DeepSeek pull ahead.
- **Prompt weaknesses:** SQL/System-Design prompts ask for the right sections but give
  no worked numeric examples or canonical per-system facts; Full-Stack prompt does not
  pin modern security (SecurityFilterChain, env-var JWT secrets, RBAC).

### 4. Critic + Verifier (`verifier_agent.py`, `dsa_critic.py`, `dsa_complexity.py`)
- **Strengths:** Template isolation (foreign-section rejection) is deterministic.
  `dsa_complexity` deterministically catches the two highest-value fake-complexity
  anti-patterns (SWM O(k) heap-remove; LFU min-scan) before spending an LLM call.
  Verifier is intentionally lenient so correct answers are not rejected for style.
- **Verification risks:**
  - Fake complexity beyond the two coded cases (e.g. nested loops claiming O(n),
    `.sort()` claiming O(n), linear scan claiming O(log n)) is only caught by the LLM,
    which is non-deterministic.
  - "Generic SQL" and "invented scale numbers" are not deterministically detected.
- **Leakage:** Internal verifier/critic notes are never streamed (only the generator
  draft ships) — good.

### 5. Integrity + Delivery (`router.run_agent`)
- **Strengths:** Best-effort delivery (added previously) guarantees a real answer for
  valid queries; fence-balance repair prevents truncated code blocks. Full root-cause
  logging before any non-verified delivery.
- **Bottleneck:** Specialist answers are fully buffered (verified before streaming), so
  TTFB on a 3-attempt escalation can be tens of seconds. Acceptable for correctness.

## Cross-cutting risks
- **Hallucination:** Mitigated by ask-for-schema (SQL), ask-for-trace (Debug), and
  no-implicit-requirements. Remaining gap: invented scale numbers in System Design.
- **Repo hygiene:** Many one-off migration scripts (`replace_*.py`, `update_*.py`)
  clutter the root — tech debt, not a runtime risk.

## Upgrade plan (executed in this effort)
1. Router: add `classify_intent()` (confidence + top-3 + explanation), expand keywords.
2. Knowledge bases: `DSA_KNOWLEDGE_BASE.md`, `SQL_KNOWLEDGE_BASE.md`,
   `SYSTEM_DESIGN_KNOWLEDGE_BASE.md`, `FULLSTACK_STANDARDS.md`, auto-injected into the
   matching agent prompt at load time.
3. Verifier: deterministic fake-complexity detection (broader), generic-SQL rejection,
   derived-numbers check for System Design.
4. Enterprise test suite (`tests/test_jarvis_enterprise.py`).
