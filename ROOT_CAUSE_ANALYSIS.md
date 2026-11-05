# ROOT CAUSE ANALYSIS — Jarvis Coding Pipeline

> Grounded audit of the **actual** code paths (file/function references are real).
> Scope: the specialist coding pipeline (`app.ask_ai` → `router` → critics → verifier
> → finalizer → stream). Voice/TTS/wake stack is out of scope.

## How a request actually flows

```
app.ask_ai(text)                                   # app.py:444
  └─ router.classify_intent(text)                  # router.py:222  -> picks agent (WEIGHTED_CONFIG)
  └─ router.run_agent(agent, text, context, …)     # router.py:369
       ├─ requirement_tracker.extract_requirements # router.py:429
       ├─ for attempt in range(3):                 # router.py:456
       │    ├─ attempt 0: self_consistency.generate_best_draft(n=2)   # router.py:490
       │    │             else: brain_manager.ask(...)                # router.py:494
       │    ├─ requirement check (MANDATORY blocks) # router.py:503
       │    ├─ verifier_agent.verify(agent,…)        # router.py:531
       │    │    ├─ template-isolation guard          # verifier_agent.py:60
       │    │    ├─ response_quality_critic.deterministic_check  # verifier_agent.py:71
       │    │    ├─ <domain critic> (dsa/sql/sd/fs/debug/cr)     # verifier_agent.py:76-115
       │    │    ├─ LLM verifier rubric               # verifier_agent.py:197
       │    │    └─ response_quality_critic.score (LLM, fails-open) # verifier_agent.py:211
       │    └─ verified -> break ; else inject feedback, regenerate  # router.py:535-546
       ├─ best-effort fallback if never verified     # router.py:554-568
       ├─ dsa_output_quality.cleanup (DSA only)       # router.py:575
       ├─ lfu_critic.check (DSA only)                 # router.py:588
       ├─ response_finalizer.finalize                 # router.py:608
       ├─ _check_integrity (fence repair)             # router.py:626
       └─ stream buffered text in 400-char chunks     # router.py:638
```

Two **independent** classifiers exist:
- `router.classify_intent` / `route_agent` (`router.py:222/277`) — **weighted keyword** scoring over `WEIGHTED_CONFIG` picks the *specialist agent*. This is what actually drives the pipeline.
- `intent_detector.detect` (`intent_detector.py:264`) — regex intent for *response style + token budget*; used by `main.py:363` and prompt personalization, **not** for specialist selection.

---

## Stage-by-stage analysis

### 1. User Input (`app.py:ask_ai` 444-497)
- **Current behavior:** Accepts `text`, optional `attachments`/`images`, `deepthink`, `mode`. Routes via `classify_intent`, executes `run_agent`, persists to memory, returns full string; `on_chunk` streams.
- **Failure modes:** No length cap / normalization before routing — a long pasted stack trace dilutes keyword density and can misroute. Mixed-intent prompts ("review this code and fix the NPE") collapse to a single agent.
- **Hallucination risk:** Low at this stage.
- **Missing validations:** No language/code-block extraction to bias routing (e.g., a fenced Java block + "why does this fail" is a debug case but routes purely on words).
- **Perf:** None.

### 2. Router (`router.py` 110-286)
- **Current behavior:** `_score_query` sums tiered keyword weights (`_W_STRONG=3/_W_MED=2/_W_WEAK=1`) with word-boundary matching (`_kw_present`); `_best_agent` takes max, ties broken by dict/priority order (DEBUG→PROJECT→SYSDESIGN→SQL→CODE_REVIEW→DSA→FULLSTACK→GENERAL).
- **Failure modes (real):**
  - **Keyword-only, no semantics.** Paraphrases without listed keywords fall through to `GENERAL` (e.g., "make this loop run faster" — no `optimize code`/`complexity` token).
  - **Cross-domain collisions.** `cache` is DSA `_W_MED`; "design a distributed cache" → SYSDESIGN strong (`distributed`) usually wins, but "build a cache" can land on DSA. `schema` is SQL `_W_MED` while `design` is SYSDESIGN `_W_WEAK`, so "design a database schema" → SQL (often desired, sometimes not).
  - **FULLSTACK vs PROJECT_BUILDER overlap.** Both load `FULLSTACK_AGENT.md`; `react`/`express` are PROJECT_BUILDER `_W_MED` while `react component`/`rest api` are FULLSTACK — boundary is brittle.
  - **CODE_REVIEW under-covered.** Only 7 strong phrases, no MED/WEAK; "look over my function" misses.
- **Missing validations:** No confidence floor that forces a clarification on near-ties; `classify_intent` exposes margin but `run_agent` ignores it.
- **Perf:** Negligible (<1ms, pure regex).
- **Audit:** Quantified in `ROUTING_AUDIT.md`.

### 3. Intent Classifier (`intent_detector.py`)
- **Current behavior:** Regex → intent (code/debug/explain/…), language, style suffix, token budget.
- **Failure modes:** **Divergence from the specialist router** — `intent_detector` may classify "explain" while `router` routes DSA, yielding a style hint that fights the agent template. The two systems share no source of truth.
- **Missing validations:** No reconciliation step; token budgets here (e.g., `INTENT_CODE=2400`) are unrelated to the router's `max_tokens=4096`.

### 4. Knowledge Base Injection (`router._load_agent_prompts` 65-105)
- **Current behavior:** At import, each `*_AGENT.md` prompt is concatenated with its `*_KNOWLEDGE_BASE.md` once and cached in `AGENT_PROMPTS`.
- **Failure modes:** **Whole-file static injection** — the entire KB is prepended regardless of the specific question. No retrieval/RAG, no per-query selection.
- **Hallucination risk:** Indirect — large static prefixes push the actual question far down the context and can dilute instruction-following on long generations.
- **Perf:** One-time read; adds fixed token overhead to **every** call in that domain.

### 5. Prompt Builder (`router.run_agent` 428-496)
- **Current behavior:** `gen_kwargs` defaults `max_tokens=4096`, `timeout=60` (decremented on retry), `stateless=True`. Final attempt appends a `_RECOVERY_PROMPTS[agent]` and sets `deepthink=True`. Verifier feedback / missing-requirement feedback is appended to `current_sys_prompt` between attempts.
- **Failure modes (real):**
  - **Token ceiling vs. output size.** A full System Design (15 sections) or Full-Stack build (multi-file) can exceed 4096 output tokens → truncated → quality/verifier rejects truncation → regenerate → may exhaust 3 attempts → **best-effort ships the truncated draft**.
  - **Monotonically growing sys_prompt.** Each failed attempt appends feedback; by attempt 3 the system prompt is long and can bury the original instructions.
- **Missing validations:** No dynamic `max_tokens` bump for known-large domains (system design / full-stack).

### 6. LLM Invocation (`brain_manager.py`)
- **Current behavior:** Multi-provider failover **Gemini → Groq → OpenRouter** with health states (healthy/degraded/down), DeepThink model overrides, never returns `None`.
- **Failure modes:** External dependency — all-providers-down yields empty draft → clarification fallback. Non-deterministic outputs across providers make verification flaky.
- **Hallucination risk:** Inherent to LLMs; mitigated downstream by deterministic critics.
- **Perf (real bottleneck):** A single verified answer can cost, worst case, `2 (A/B drafts)` + `1×2 retries` generations **plus** a verifier LLM call **plus** a quality-score LLM call **per attempt** — many sequential round-trips under a 150s ceiling (`_TOTAL_ROUTER_TIMEOUT`).

### 7. Critic Layer (deterministic, pre-LLM)
- **Current behavior:** `response_quality_critic.deterministic_check` (placeholders, truncation, unbalanced fences, repeated headers/paragraphs, filler, deflection) runs first, then domain critics:
  - **DSA** (`dsa_critic` → complexity/structure/compile/output-quality/LFU/algorithm) — **strong, mature**.
  - **SQL** (`sql_critic`), **System Design** (`sysdesign_critic`) — substantial.
  - **Full Stack** (`fullstack_critic`) — **strong** (dirs, truncation, JWT/Redis/Kafka/ecommerce/security/docker/react/swagger/prod-readiness).
  - **Debug** (`debug_critic`) — **thin**: only blocks a fabricated full file when no evidence; does NOT enforce the Reproduce→Evidence→Root-Cause→Fix→Verification structure.
  - **Code Review** (`codereview_critic`) — **thin**: requires *some* critique header + a refactor block + no truncation; does NOT require the 7 mandated dimensions (Correctness, Complexity, Bugs, Security, Maintainability, Performance, Refactor).
- **Gaps:** Debug + Code Review under-enforced relative to the mission. No Fenwick/Dijkstra/heap-specific DSA validators yet (LFU/LRU/Trie/SegTree/UnionFind exist).

### 8. Verifier Layer (`verifier_agent.verify`)
- **Current behavior:** Template-isolation guard (foreign section headers), deterministic quality gate, domain critic, **LLM rubric** (detailed per-domain), then **post-pass quality `score`** (5 dims, threshold 8, fails-open).
- **Failure modes:** LLM verifier is **non-deterministic** — can pass a subtly wrong answer or reject a good one; partially mitigated by deterministic gates. The post-pass scorer can trigger **over-regeneration** (latency) when it dips a category to 7.
- **Missing validations:** No caching of verdicts; identical regenerations can be re-verified.

### 9. Formatter / Finalizer Layer
- **Current behavior:** `dsa_output_quality.cleanup` (DSA), `lfu_critic.check` (DSA), `response_finalizer.finalize` (dedupe canonical sections, strip QA artifacts, fence validation), `_check_integrity` (fence repair appends a closing ```).
- **Failure modes:** **Overlapping responsibilities** across `dsa_output_quality`, `response_finalizer`, `final_response_sanitizer`, `_check_integrity` — multiple passes that mostly no-op but increase the chance of an unintended edit on edge content.
- **Missing validations:** Fence repair only appends a closing fence; it does not detect a fence opened with no content.

### 10. Streaming Layer (`router.run_agent` 638-643; `app.py`)
- **Current behavior:** The **fully buffered, verified** response is sliced into 400-char chunks and emitted via `on_chunk`/SocketIO. Per-request isolation + cancellation (`_cancelled_streams`) and voice barge-in are handled in `app.py`.
- **Failure modes (real UX gap):** **No true token streaming on the verified path** — the user sees nothing until generation **and** verification **and** finalization complete. Time-to-first-token is effectively time-to-final-answer. This is the single biggest *perceived* gap vs. ChatGPT/Claude.
- **Perf:** The 400-char chunking is cosmetic; it does not reduce latency-to-first-token.

---

## Prioritized findings

| # | Severity | Stage | Finding | Action |
|---|----------|-------|---------|--------|
| F1 | P1 | Router | Keyword-only routing misses paraphrases & cross-domain collisions | Measure (ROUTING_AUDIT), expand `WEIGHTED_CONFIG`, add CODE_REVIEW MED/WEAK tiers |
| F2 | P1 | Critic | Debug critic doesn't enforce evidence-based 5-step structure | Harden `debug_critic` + tests (Phase 7) |
| F3 | P1 | Critic | Code Review critic doesn't require the 7 dimensions | Harden `codereview_critic` + tests (Phase 8) |
| F4 | P2 | Critic | DSA lacks Fenwick/Dijkstra/heap-specific validators | Extend `dsa_algorithm_critic` + tests (Phase 3) |
| F5 | P2 | Prompt | Static `max_tokens=4096` truncates large SysDesign/Full-Stack | Domain-aware token budget |
| F6 | P2 | Classifiers | `router` vs `intent_detector` can disagree | Reconcile or document precedence |
| F7 | P3 | Streaming | Buffer-then-chunk → poor TTFT | Documented; true streaming is a larger architectural change |
| F8 | P3 | KB | Whole-file static KB injection (no retrieval) | Documented; candidate for future RAG |

**Already strong (avoid redundant rework):** multi-provider failover, DSA deterministic stack, Full-Stack critic, universal quality gate, template isolation, best-effort no-generic-fallback delivery.

---

## Verification methodology (for the claims in the other reports)
- **Routing accuracy:** labeled corpus run through `router.route_agent` (`ROUTING_AUDIT.md`). Reproducible: `pytest tests/test_routing_audit.py`.
- **Specialist correctness:** golden (must-pass) + adversarial (must-reject) fixtures through each deterministic critic. Reproducible per-phase test files.
- **Benchmark:** internal deterministic-critic **pass-rate** on the labeled corpus (`BENCHMARK_RESULTS.md`). **No competitor model is executed**; competitor columns are intentionally omitted as un-measurable from this environment.
