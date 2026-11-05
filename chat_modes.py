"""
JARVIS Chat Modes — Assistant, Code-Me
Specialized system prompts, routing rules, per-mode session memory,
response-style detection, and TTS voice sanitization.

This file is the central orchestrator's brain for mode behavior.
It does ONE job per public function so callers stay simple.
"""
import re
import threading
from typing import Dict, Optional

import jarvis_config as config

# ── Mode identifiers (match frontend) ─────────────────────────────────────────
MODE_ASSISTANT = "assistant"
MODE_CODEME    = "codeme"

VALID_MODES = {MODE_ASSISTANT, MODE_CODEME}
DEFAULT_MODE  = MODE_ASSISTANT

MODE_LABELS = {
    MODE_ASSISTANT: "Assistant",
    MODE_CODEME:    "Code-Me",
}

MODE_MAX_TOKENS = {
    MODE_ASSISTANT: int(getattr(config, "MAX_TOKENS", 220)),
    MODE_CODEME:    1024,
}

# DeepThink expands the token budget for advanced reasoning.
DEEPTHINK_MAX_TOKENS = {
    MODE_ASSISTANT: 1400,
    MODE_CODEME:    2048,
}

MODE_AI_TIMEOUT = {
    MODE_ASSISTANT: int(getattr(config, "AI_TIMEOUT", 10)),
    MODE_CODEME:    18,
}

# DeepThink relaxes the timeout — deeper models legitimately take longer.
DEEPTHINK_AI_TIMEOUT = {
    MODE_ASSISTANT: 28,
    MODE_CODEME:    40,
}

# ── DeepThink behavioural addendum (appended to system prompt) ────────────────
DEEPTHINK_SUFFIX = """\

═══ DEEPTHINK MODE — ENABLED ═══
You are now in DeepThink. Reason slower, deeper, more rigorously. The user has
opted into a higher-latency, higher-quality answer — deliver it.

Reasoning rules:
- Privately think before answering. Consider angles, edge cases, trade-offs.
- Pick the single strongest answer and justify it briefly inside the answer.
- For code: choose the most efficient correct algorithm, include edge cases,
  validation, and error handling. State complexity precisely.
- For architecture / system design: think about scalability, separation of
  concerns, failure modes, and observability.
- For explanations: cover the "why", not just the "what". Use precise terms.
- Prefer clarity over brevity — but never pad. No filler.
- Output ONLY the polished final answer. Do NOT reveal your chain of thought,
  scratchpad, or internal deliberation.
"""

DEEPTHINK_HINT = {
    MODE_ASSISTANT: (
        "DeepThink ON — take a moment to reason carefully. Give a deeper, "
        "structured answer with comparisons, trade-offs, and concrete examples "
        "where they add real value. Do not pad. Do not reveal chain of thought."
    ),
    MODE_CODEME: (
        "DeepThink ON — think before you code. Identify the core problem, edge "
        "cases, complexity targets, and input validation. Then produce "
        "production-grade code with imports, full driver, error handling, and a "
        "precise complexity note. Prefer the most efficient correct algorithm."
    ),
}

# ── Specialized system prompts ─────────────────────────────────────────────────
ASSISTANT_PROMPT = """\
You are JARVIS in Assistant mode — a premium conversational AI on par with
ChatGPT, Gemini Advanced, and Claude. You sound confident, intelligent,
futuristic, calm, emotionally balanced — like a real high-end AI assistant.

What you handle:
normal conversations, real-time questions, explanations, comparisons,
study help, summaries, brainstorming, reasoning, light planning, and voice
conversations. You can use live web search results when the orchestrator
injects them.

SMART RESPONSE FORMAT — auto-detect what the user wants and adapt:
- "difference between X and Y" / "X vs Y"           → clean markdown table
- "explain simply" / "in simple words"              → short friendly paragraph
- "short" / "brief" / "tl;dr" / "one line"          → 1–3 sentence answer
- "detailed" / "in depth" / "explain fully"         → deep structured answer
  with examples and reasoning
- "step by step" / "stepwise"                       → numbered steps
- "list" / "bullets"                                → tight bullet list
- casual chat / small talk                          → one or two natural lines
- factual / definition                              → one tight paragraph, no
  headings
- opinion / brainstorm                              → confident take + 2–3
  alternatives

REAL-TIME / LIVE TOPICS (weather, news, scores, prices, current events,
trends): if a "LIVE INTERNET SEARCH RESULTS" section is present in your
context, treat it as ground truth and cite values from it accurately. If
it is absent, say plainly that you don't have a live feed for that query
and offer the closest useful answer.

TONE:
- Natural, conversational, intelligent. Match the user's register.
- Confident and direct. No "I'm listening", no "Could you rephrase", no
  apologies for being an AI.
- Use the user's name only if it appears in the personalization block.
- For voice replies (when the orchestrator marks the turn as voice) keep
  sentences short, fluid, and human-sounding — NO markdown symbols, NO
  code, NO long lists.

HARD DO-NOTs in Assistant mode:
- DO NOT generate code unless the user explicitly asks for code, a program,
  implementation, query, syntax, snippet, or function.
- DO NOT use rigid Code-Me headings (## Problem Understanding / ## Code /
  ## Complexity). Those belong to Code-Me mode only.
- DO NOT add safety disclaimers, hedging, or filler.
- DO NOT pad. End the answer when it's complete.
"""

CODEME_PROMPT = """\
CODE-ME ELITE ARCHITECT MODE

MISSION
You are no longer a DSA tutor. You are a Senior/Staff/Principal Engineer, Solutions Architect, Database Architect, and Distributed Systems Engineer who solves real-world engineering problems.

CORE PRINCIPLE
- Do not answer immediately. Think → analyze → reason → then answer.
- Optimize for: Correctness, Scalability, Reliability, Observability, Maintainability, Performance, Security, Cost.

MODE DETECTION (automatic)
- Classify each request into one (choose the best fit):
  1) DSA MODE
  2) SQL MODE
  3) BACKEND MODE
  4) SYSTEM DESIGN MODE
  5) DATABASE ARCHITECT MODE
  6) DISTRIBUTED SYSTEM MODE
  7) DEBUGGING MODE
  8) CODE REVIEW MODE
- Do NOT use the same response template for every mode; adapt structure to the mode.

DSA MODE (only when truly algorithmic/LeetCode-style. Triggers: array, tree, graph, linked list, leetcode, dfs, bfs, dynamic programming, heap, stack, queue)
- CRITICAL OPTIMIZATION RULES:
  * STEP 1: Determine if the problem asks for optimal/production/scalable solution or no brute force.
  * STEP 2: If an optimal solution exists, NEVER generate a Brute force, Naive, Educational, or Intermediate solution. Generate ONLY the optimal solution.
  * STEP 3: Do not show multiple solutions unless explicitly asked. Forbidden phrases: "First let's do brute force", "Another better solution is", "More optimal approach", "We can improve further".
  * STEP 4: Choose the final algorithm BEFORE generating code (e.g. Sliding Window Median -> Two Heaps + Lazy Deletion).
  * STEP 5: After code generation, never replace the solution or generate a second implementation.
- STRICT SECTION ORDER (Do not change order, no duplicate sections, nothing else):
  1. Problem Understanding
  2. Optimal Algorithm
  3. Full Code (Generate FULL CODE first before explanation if language is requested)
  4. Approach Explanation
  5. Time Complexity
  6. Space Complexity
  7. Edge Cases (Must be problem-specific. e.g., "All elements negative", "Integer overflow". No generic "Empty array" / "Large array" unless uniquely relevant)
- INTERNAL CODE REVIEW PASS: Before generating the final answer, silently review for: Null pointer risk, Overflow risk, Division by zero, Infinite loops, Incorrect edge cases, Off-by-one errors.
- REMOVE MARKDOWN NOISE: Do not use random separators (---), duplicate headers, empty sections, or broken markdown. Use clean formatting.
- QUALITY CHECK: Verify internally that there are no duplicate headings/paragraphs/complexities.

ARCHITECT MODE / DISTRIBUTED SYSTEM MODE / SYSTEM DESIGN MODE (Triggers: million rows, billion rows, redis, kafka, scaling, system design, architecture, mysql optimization, postgres optimization, distributed systems, high traffic, production systems, microservices)
- CRITICAL RULE: When ARCHITECT MODE is active, FORBIDDEN SECTIONS: Problem Understanding, Sample Input, Sample Output, Approach, Time Complexity, Space Complexity, Edge Cases, LeetCode style templates.
- FORBIDDEN SYNTAX: Fake commands, fake SQL, fake infrastructure syntax (e.g., CREATE REPLICA ..., CREATE SHARD ..., CREATE REDIS ...). If syntax is unknown, explain conceptually instead.
- ALLOWED SECTIONS ONLY: Problem Analysis, Root Cause Analysis, Bottlenecks, Scalability Concerns, Architecture Design, Database Strategy, Caching Strategy, Read Replica Strategy, Partition Strategy, Sharding Strategy, Monitoring, Failure Scenarios, Security Considerations, Cost Tradeoffs, Rollout Strategy.
- DEEP ENGINEERING RULE: Every recommendation MUST include Why, Benefits, Tradeoffs, Failure Modes, and Operational Cost.
  * When mentioning Redis: Explain Key Structure, TTL, Invalidation, Failure Recovery.
  * When mentioning Read Replicas: Explain Replication Lag, Failover, Read Routing, Consistency Tradeoffs.
  * When mentioning Partitioning: Explain Partition Key, Pruning, Maintenance Cost, Tradeoffs.
  * When mentioning Sharding: Explain Shard Key, Hot Partitions, Rebalancing, Cross-Shard Queries, Tradeoffs.

DEBUGGING MODE / CODE REVIEW MODE
- Provide: Symptoms, Hypotheses, Investigation Steps, Metrics, Logs, Root Cause Analysis, Fix, Validation, Rollback Plan, Tradeoffs.

STAFF ENGINEER DEPTH
- Ask internally: What breaks at 10x scale? What breaks at 100x scale? What breaks during failover? What breaks during network partition? What breaks during Black Friday traffic? What breaks during database outage?

ULTIMATE GOAL
- Answer like Google Staff / Netflix Architect / Uber Principal / Amazon Solutions Architect. Prioritize scalability, reliability, observability, maintainability, security, cost, and tradeoffs over interview-style fluff. Never answer like a coding interview tutor for production scenarios.

ABSOLUTE RULES
- NEVER greet.
- Code fences ALWAYS have a language tag.
- Never return broken or partial code — mentally compile first.
- You are NOT an autonomous agent — do not create files, projects, or workspaces.
"""

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, dict]] = {}


def normalize_mode(mode: Optional[str]) -> str:
    if not mode:
        return DEFAULT_MODE
    m = str(mode).lower().strip().replace("-", "").replace("_", "")
    aliases = {
        "assistant": MODE_ASSISTANT,
        "default":   MODE_ASSISTANT,
        "normal":    MODE_ASSISTANT,
        "codeme":    MODE_CODEME,
        "code":      MODE_CODEME,
        "coding":    MODE_CODEME,
    }
    return aliases.get(m, DEFAULT_MODE)


def get_max_tokens(mode: str, deepthink: bool = False) -> int:
    m = normalize_mode(mode)
    if deepthink:
        return DEEPTHINK_MAX_TOKENS.get(m, DEEPTHINK_MAX_TOKENS[MODE_ASSISTANT])
    return MODE_MAX_TOKENS.get(m, MODE_MAX_TOKENS[MODE_ASSISTANT])


def get_ai_timeout(mode: str, deepthink: bool = False) -> int:
    m = normalize_mode(mode)
    if deepthink:
        return DEEPTHINK_AI_TIMEOUT.get(m, DEEPTHINK_AI_TIMEOUT[MODE_ASSISTANT])
    return MODE_AI_TIMEOUT.get(m, MODE_AI_TIMEOUT[MODE_ASSISTANT])


def get_deepthink_hint(mode: str) -> str:
    """Return the per-mode DeepThink instruction (used in user-context banner)."""
    return DEEPTHINK_HINT.get(normalize_mode(mode), DEEPTHINK_HINT[MODE_ASSISTANT])


def should_skip_daily_talk(mode: str) -> bool:
    """Specialized modes bypass casual local routing for technical focus."""
    return normalize_mode(mode) != MODE_ASSISTANT


def should_skip_semantic_cache(mode: str) -> bool:
    """Code answers should come from the LLM, not cached trivia."""
    return normalize_mode(mode) == MODE_CODEME


def build_system_prompt(mode: str, personalized_base: str,
                        session_key: str = "default",
                        deepthink: bool = False,
                        intent: Optional[str] = None) -> str:
    """Compose the final system prompt for the given mode.

    `personalized_base` is the user-personalized base prompt (already enriched
    with profile + intent style hints upstream). For specialized modes we
    REPLACE the base with our strict mode prompt and append only the
    personalization tail (so the AI still knows the user's name etc.).
    When `deepthink` is True the DeepThink reasoning suffix is appended.
    """
    mode = normalize_mode(mode)
    pers = _personalization_suffix(personalized_base)
    if mode == MODE_CODEME:
        if intent in ("greeting", "casual"):
            prompt = "You are JARVIS in Code-Me mode, but the user is currently just greeting you or engaging in casual small talk (e.g., 'hi', 'hello', 'how are you'). DO NOT output any coding template sections (## Problem Understanding, ## Code, ## Sample Input, ## Sample Output, ## Approach, ## Complexity). Instead, respond warmly, naturally, and concisely in 1-2 friendly sentences. Do not show any code or system design." + ("\n\n" + pers if pers else "")
        else:
            prompt = CODEME_PROMPT + ("\n\n" + pers if pers else "")
    else:
        # Assistant mode: prepend our strict assistant prompt, keep personalized base after
        prompt = ASSISTANT_PROMPT + "\n\n" + personalized_base

    if deepthink:
        prompt += "\n" + DEEPTHINK_SUFFIX
    return prompt


def _personalization_suffix(personalized_base: str) -> str:
    idx = personalized_base.find("Personalisation:")
    if idx >= 0:
        return personalized_base[idx:].strip()
    return ""


def build_mode_context(mode: str, query: str, session_key: str = "default") -> str:
    """Inject active coding session memory into LLM context."""
    mode = normalize_mode(mode)
    if mode != MODE_CODEME:
        return ""

    with _lock:
        sess = _sessions.get(session_key, {}).get(mode, {})

    lines = []
    if sess.get("last_code_snippet"):
        lines.append("=== Active Coding Session ===")
        lines.append(f"Recent code context:\n{sess['last_code_snippet'][:600]}")
    if sess.get("last_error"):
        lines.append(f"Last debug context: {sess['last_error'][:300]}")
    if sess.get("languages"):
        lines.append(f"Languages in session: {', '.join(sess['languages'][:5])}")

    if lines:
        return "\n".join(lines)
    return ""


def update_session(mode: str, user_text: str, response: str, session_key: str = "default"):
    """Extract and store session memory from exchanges."""
    mode = normalize_mode(mode)
    if mode == MODE_ASSISTANT:
        return

    with _lock:
        if session_key not in _sessions:
            _sessions[session_key] = {}
        if mode not in _sessions[session_key]:
            _sessions[session_key][mode] = {}
        sess = _sessions[session_key][mode]

    if mode == MODE_CODEME:
        code_blocks = re.findall(r"```[\w]*\n([\s\S]*?)```", response)
        if code_blocks:
            sess["last_code_snippet"] = code_blocks[-1][:800]
        langs = re.findall(r"```(\w+)", response)
        if langs:
            existing = sess.get("languages", [])
            for lg in langs:
                if lg not in existing and lg not in ("", "text"):
                    existing.append(lg)
            sess["languages"] = existing[-8:]
        err_kw = ("error", "exception", "traceback", "bug", "fix", "debug")
        if any(k in user_text.lower() for k in err_kw):
            sess["last_error"] = user_text[:400]


# ── Response-style detection (user-controlled formatting hints) ───────────────
#
# Inspects the user's message for explicit format requests and returns a
# short instruction the system prompt can include. This lets the AI respect
# "short answer", "in a table", "step by step", etc. without us having to
# post-process the response.
#
_STYLE_PATTERNS = [
    (re.compile(r"\b(short|brief|one[- ]liner|concise|tl;?dr)\b", re.I),
     "Respond very concisely in 1-3 sentences. No headings, no lists."),
    (re.compile(r"\b(detail(ed)?|in[- ]depth|elaborate|long answer|explain fully)\b", re.I),
     "Give a thorough, detailed explanation with examples where useful."),
    (re.compile(r"\b(table|tabular|in a table|comparison table)\b", re.I),
     "Format the answer as a clean markdown table with clear column headers."),
    (re.compile(r"\b(paragraph|in (a )?paragraph|prose form)\b", re.I),
     "Write the answer as flowing paragraphs. No bullet lists, no tables."),
    (re.compile(r"\b(bullet(s| points?)|list it|as a list)\b", re.I),
     "Format the answer as a clean bullet-point list."),
    (re.compile(r"\b(step[- ]by[- ]step|stepwise|numbered steps)\b", re.I),
     "Format the answer as numbered steps from start to finish."),
    (re.compile(r"\b(interview style|interview answer|tell me like in an interview)\b", re.I),
     "Answer in an interview style: clear, structured, confident, with a brief example."),
    (re.compile(r"\bdifference between\b", re.I),
     "Default to a side-by-side comparison table unless the user requested another format."),
]


def extract_response_style(user_text: str) -> str:
    """Return a short style instruction derived from the user's message.

    Returns an empty string when no explicit style cue is detected.
    Multiple matches are joined; later matches override earlier ones in
    spirit, but we just concatenate to give the LLM full context.
    """
    if not user_text:
        return ""
    hits = []
    for pat, instr in _STYLE_PATTERNS:
        if pat.search(user_text):
            hits.append(instr)
    if not hits:
        return ""
    # De-duplicate while preserving order
    seen = set()
    uniq = []
    for h in hits:
        if h not in seen:
            uniq.append(h); seen.add(h)
    return "USER FORMAT REQUEST: " + " ".join(uniq)


# ── Voice formatter — strip markdown for TTS ──────────────────────────────────
#
# JARVIS speaks responses out loud. Markdown symbols (#, *, ``, |, ---) sound
# terrible when read literally. This function turns the on-screen markdown
# into clean spoken-style text WITHOUT changing what's shown in the chat.
#
_FENCE_RE       = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE     = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BOLD_ITAL_RE   = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
_TABLE_SEP_RE   = re.compile(r"^\s*\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)+\s*\|?\s*$", re.M)
_RULE_RE        = re.compile(r"^\s*([=*\-]{3,})\s*$", re.M)
_BULLET_RE      = re.compile(r"^\s*[-*•]\s+", re.M)
_NUMLIST_RE     = re.compile(r"^\s*\d+[\.)]\s+", re.M)
_LINK_RE        = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def format_for_voice(text: str, mode: str = MODE_ASSISTANT,
                     max_chars: int = 800) -> str:
    """Convert a markdown response into clean text suitable for TTS.

    - Strips heading hashes, bold/italic markers, code fences, table
      separators, horizontal rules, and link URLs (keeps the link label).
    - For Code-Me replies that contain code, only the prose preamble
      is spoken plus a short pointer to the chat panel.
    - Caps total spoken length at `max_chars` characters.
    """
    if not text:
        return ""
    mode = normalize_mode(mode)

    # For modes that produce code, speak only the prose intro and signal
    # the user that the full thing is on screen.
    if mode == MODE_CODEME and "```" in text:
        prose = _FENCE_RE.split(text, maxsplit=1)[0].strip()
        if not prose:
            prose = "Here is the solution."
        text = prose + " The full code is on screen."
    else:
        # Replace fences with a brief mention so the AI doesn't read code.
        text = _FENCE_RE.sub(" (code shown on screen) ", text)

    # Drop table separator lines entirely
    text = _TABLE_SEP_RE.sub("", text)
    # Replace remaining table pipes with commas so rows read naturally.
    # IMPORTANT: only horizontal whitespace, never newlines, otherwise the
    # next list/bullet/heading line gets glued onto the table row.
    text = re.sub(r"[ \t]*\|[ \t]*", ", ", text)
    # Drop horizontal rules / decorative ===/---
    text = _RULE_RE.sub("", text)
    # Strip heading hashes
    text = _HEADING_RE.sub("", text)
    # Bold/italic -> plain
    text = _BOLD_ITAL_RE.sub(r"\2", text)
    # Inline code -> plain word
    text = _INLINE_CODE_RE.sub(r"\1", text)
    # Markdown links -> just the label
    text = _LINK_RE.sub(r"\1", text)
    # Bullets / numbered list markers -> nothing (the prose still flows)
    text = _BULLET_RE.sub("", text)
    text = _NUMLIST_RE.sub("", text)
    # Collapse runs of blank lines
    text = _MULTI_BLANK_RE.sub("\n\n", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def tts_summary(response: str, mode: str) -> str:
    """Short spoken summary for code-heavy responses (voice pipeline)."""
    mode = normalize_mode(mode)
    if mode == MODE_ASSISTANT:
        return response

    if "```" not in response:
        return response

    # Speak intro only — skip code blocks for TTS
    parts = re.split(r"```[\s\S]*?```", response)
    intro = parts[0].strip() if parts else response
    if len(intro) > 320:
        intro = intro[:317] + "..."
    suffix = " Full code is in the chat panel." if mode == MODE_CODEME else ""
    return (intro or "Done. Check the chat panel for the full response.") + suffix
