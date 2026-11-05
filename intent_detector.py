"""
JARVIS Intent Detector — ChatGPT-like Intent-Aware Response Routing
═══════════════════════════════════════════════════════════════════
Zero-API, <1ms classification of user intent to dynamically adapt
response style, token budget, and prompt behavior.

Usage:
    from intent_detector import detect
    result = detect("give polymorphism code in java")
    # result.intent == "code_request"
    # result.language == "java"
    # result.style == "code_first"
    # result.tokens == 1600
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger("jarvis.intent")

# ── Intent Types ───────────────────────────────────────────────────────────────
INTENT_GREETING   = "greeting"
INTENT_CASUAL     = "casual"
INTENT_CODE       = "code_request"
INTENT_EXPLAIN    = "explain"
INTENT_DEBUG      = "debug"
INTENT_OPTIMIZE   = "optimize"
INTENT_QUICK      = "quick_answer"
INTENT_PROJECT    = "project_plan"
INTENT_ARCHITECT  = "architecture"
INTENT_INTERVIEW  = "interview_prep"
INTENT_COMPARE    = "compare"
INTENT_GENERAL    = "general"

# ── Response Style Hints ───────────────────────────────────────────────────────
STYLE_CODE_FIRST    = "code_first"
STYLE_EXPLAIN_FIRST = "explain_first"
STYLE_FIX_FIRST     = "fix_first"
STYLE_PLAN_FIRST    = "structured_plan"
STYLE_DIRECT        = "direct_answer"
STYLE_CONVERSATIONAL = "conversational"

# ── Result dataclass ───────────────────────────────────────────────────────────
@dataclass
class IntentResult:
    intent: str = INTENT_GENERAL
    language: Optional[str] = None
    style: str = STYLE_CONVERSATIONAL
    tokens: int = 600
    confidence: float = 0.0
    skip_local_fallback: bool = False
    prompt_suffix: str = ""

    def __repr__(self):
        return (f"Intent({self.intent}, lang={self.language}, "
                f"style={self.style}, tokens={self.tokens}, conf={self.confidence:.2f})")


# ── Language Detection ─────────────────────────────────────────────────────────
_LANG_PATTERNS = {
    "python":     re.compile(r"\b(python|py|django|flask|pandas|numpy|pip)\b", re.I),
    "java":       re.compile(r"\b(java\b|jdk|spring\s*boot|maven|gradle|servlet|jdbc)", re.I),
    "javascript": re.compile(r"\b(javascript|js\b|node\.?js|react|vue|angular|express|npm)\b", re.I),
    "typescript": re.compile(r"\b(typescript|ts\b|tsx|angular)\b", re.I),
    "c":          re.compile(r"\b(c\s+program|c\s+code|c\s+language|#include|stdio\.h|printf\b)\b", re.I),
    "cpp":        re.compile(r"\b(c\+\+|cpp|iostream|cout|cin|stl)\b", re.I),
    "csharp":     re.compile(r"\b(c\s*#|csharp|\.net|asp\.net|unity)\b", re.I),
    "sql":        re.compile(r"\b(sql|mysql|postgres|sqlite|select\s+\*|insert\s+into|create\s+table|alter\s+table|join\s+on)\b", re.I),
    "html":       re.compile(r"\b(html|css|dom|webpage|web\s*page)\b", re.I),
    "rust":       re.compile(r"\b(rust|cargo|rustc)\b", re.I),
    "go":         re.compile(r"\b(golang|go\s+lang)\b", re.I),
    "kotlin":     re.compile(r"\b(kotlin|android)\b", re.I),
    "swift":      re.compile(r"\b(swift|ios\s+app|xcode)\b", re.I),
    "php":        re.compile(r"\b(php|laravel|wordpress)\b", re.I),
    "r":          re.compile(r"\b(r\s+language|rstudio|ggplot|dplyr)\b", re.I),
    "bash":       re.compile(r"\b(bash|shell|sh\b|terminal|command\s+line|linux\s+command)\b", re.I),
}

def _detect_language(text: str) -> Optional[str]:
    """Detect programming language from user query."""
    for lang, pattern in _LANG_PATTERNS.items():
        if pattern.search(text):
            return lang
    return None


# ── Intent Patterns (ordered by specificity) ──────────────────────────────────

# GREETING
_GREETING_PATTERNS = [
    re.compile(r"^(hi|hello|hey|g'day|yo|sup|good\s+(morning|afternoon|evening|day))(\s+jarvis)?\b", re.I),
    re.compile(r"^hey(\s+jarvis)?$", re.I),
]

# CASUAL
_CASUAL_PATTERNS = [
    re.compile(r"\b(how\s+are\s+you|how's\s+it\s+going|what's\s+up|what's\s+new|tell\s+me\s+a\s+joke|are\s+you\s+there|talk\s+to\s+me|casual\s+chat)\b", re.I),
]

# CODE REQUEST — user wants runnable code
_CODE_PATTERNS = [
    re.compile(r"\b(write|give|create|make|build|generate|show)\s+(me\s+)?(a\s+|an\s+|the\s+)?(code|program|script|function|class|method|snippet|implementation)\b", re.I),
    re.compile(r"\b(code|program|script)\s+(for|to|that|which|in)\b", re.I),
    re.compile(r"\b(write|give|create|code|implement)\s+.{0,30}\s+in\s+(python|java|javascript|c\+\+|c#|sql|typescript|go|rust|kotlin|swift|php|ruby|bash)\b", re.I),
    re.compile(r"\b(give|show|write)\s+(me\s+)?.*\b(code|program|script)\b", re.I),
    re.compile(r"\b(implement|code)\s+(a\s+|an\s+)?\w+", re.I),
    re.compile(r"\b(how\s+to\s+(write|code|implement|create|make|build))\b", re.I),
    re.compile(r"\b(fibonacci|factorial|sorting|linked\s*list|binary\s*(search|tree)|stack|queue|array|matrix)\s+(code|program|implementation|in)\b", re.I),
    re.compile(r"\b(program|code)\s+.{0,20}\s+(using|with)\s+\w+", re.I),
]

# DEBUG — user wants to fix something (weighted +2 to win over code_request)
_DEBUG_PATTERNS = [
    re.compile(r"\b(fix|debug|solve|resolve|repair|correct)\s+(this|my|the|a)?\s*\w+", re.I),
    re.compile(r"\b(fix|debug)\b", re.I),  # standalone fix/debug is strong signal
    re.compile(r"\b(what('?s|\s+is)\s+(wrong|the\s+(error|issue|bug|problem)))\b", re.I),
    re.compile(r"\b(why\s+(is|does|doesn'?t|isn'?t|am\s+i\s+getting|do\s+i\s+get))\b.*\b(error|exception|fail|crash|not\s+work|broken)\b", re.I),
    re.compile(r"\b(error|exception|traceback|stacktrace|bug|crash|syntax\s+error|runtime\s+error|compilation\s+error)\b", re.I),
    re.compile(r"\b(not\s+working|doesn'?t\s+work|won'?t\s+run|won'?t\s+compile|fails?\s+to)\b", re.I),
    re.compile(r"\b(getting\s+(an?\s+)?error|throws?\s+(an?\s+)?exception)\b", re.I),
]

# EXPLAIN — user wants understanding
_EXPLAIN_PATTERNS = [
    re.compile(r"\b(explain|describe|what\s+is|what\s+are|what\s+does|what\s+do)\b", re.I),
    re.compile(r"\b(tell\s+me\s+about|teach\s+me|help\s+me\s+understand|break\s*down)\b", re.I),
    re.compile(r"\b(how\s+does|how\s+do|how\s+is|how\s+are)\b.*\b(work|function|operate)\b", re.I),
    re.compile(r"\b(meaning|definition|concept|theory)\s+of\b", re.I),
    re.compile(r"\b(difference\s+between|vs\b|versus)\b", re.I),
    re.compile(r"\b(why\s+(do\s+we|should\s+we|is\s+it|would\s+you))\b", re.I),
]

# OPTIMIZE — user wants improvement
_OPTIMIZE_PATTERNS = [
    re.compile(r"\b(optimize|improve|refactor|make\s+(it\s+)?(faster|better|cleaner|efficient|shorter)|speed\s+up|reduce)\b", re.I),
    re.compile(r"\b(time\s+complexity|space\s+complexity|performance|efficiency|bottleneck)\b", re.I),
    re.compile(r"\b(better\s+(way|approach|method|solution)|best\s+practice)\b", re.I),
    re.compile(r"\b(can\s+this\s+be\s+(improved|optimized|made\s+faster|simplified))\b", re.I),
]

# PROJECT — user wants a full project
_PROJECT_PATTERNS = [
    re.compile(r"\b(build|create|make|develop|design)\s+(me\s+)?(a|an)\s+.{1,40}?(app|application|website|system|platform|tool|project|portal|dashboard)\b", re.I),
    re.compile(r"\b(build|create|make|develop)\s+(me\s+)?(a|an)\s+", re.I),  # "build me a ..." is strong project signal
    re.compile(r"\b(project\s+(idea|plan|structure|architecture|blueprint|roadmap))\b", re.I),
    re.compile(r"\b(full[\s-]?stack|end[\s-]?to[\s-]?end|complete\s+(project|application|system))\b", re.I),
    re.compile(r"\b(tech\s*stack|technology\s+stack)\s+(for|to|of)\b", re.I),
    re.compile(r"\b(folder\s+structure|project\s+structure|directory\s+structure)\b", re.I),
]

# ARCHITECTURE — design-level questions
_ARCHITECT_PATTERNS = [
    re.compile(r"\b(system\s+design|architecture|design\s+pattern|microservice|scalab|high\s+level\s+design|low\s+level\s+design|HLD|LLD)\b", re.I),
    re.compile(r"\b(database\s+design|schema\s+design|api\s+design|class\s+diagram|er\s+diagram)\b", re.I),
    re.compile(r"\b(how\s+(would|should|to)\s+(you\s+)?(design|architect|structure|scale))\b", re.I),
    re.compile(r"\b(scalab(le|ility)|distributed|high\s+availability|load\s+balanc)\b", re.I),
]

# INTERVIEW — prep questions
_INTERVIEW_PATTERNS = [
    re.compile(r"\b(interview\s+(question|prep|practice|tip)|viva\s+question)\b", re.I),
    re.compile(r"\binterview\s+questions?\s+(for|on|about|in|of)\b", re.I),
    re.compile(r"\b(asked\s+in\s+interview|frequently\s+asked|common\s+question)\b", re.I),
    re.compile(r"\b(prepare\s+for\s+(interview|placement|viva))\b", re.I),
]

# COMPARE — comparison requests
_COMPARE_PATTERNS = [
    re.compile(r"\b(compare|comparison|difference\s+between|vs\.?|versus)\b", re.I),
    re.compile(r"\b(\w+)\s+vs\.?\s+(\w+)\b", re.I),
    re.compile(r"\b(which\s+is\s+(better|faster|best|preferred|recommended))\b", re.I),
]

# QUICK ANSWER — simple factual
_QUICK_PATTERNS = [
    re.compile(r"^(what|who|when|where|which|how\s+many|how\s+much|is\s+it|can\s+you|do\s+you)\b.{0,60}$", re.I),
    re.compile(r"^.{0,40}\?$"),  # very short questions
]


# ── Style Hints (injected into system prompt) ─────────────────────────────────
_STYLE_HINTS = {
    INTENT_CODE: (
        "The user wants CODE. Give clean, COMPLETE, RUNNABLE code FIRST inside markdown fences. "
        "The code MUST compile and run as-is when pasted into Programiz, Replit, or any IDE. "
        "Include ALL imports/headers, entry point (main method), balanced braces, and return statements. "
        "For C++: use cout << (two less-than) for output, cin >> (two greater-than) for input, "
        "complete #include <header> directives, and proper for-loop syntax with < comparisons. "
        "NEVER output partial, truncated, or incomplete code. "
        "Add only a brief explanation after the code (2-3 lines max). No theory dump."
    ),
    INTENT_EXPLAIN: (
        "The user wants an EXPLANATION. Be clear, practical, and beginner-friendly. "
        "Use simple examples. Keep it concise — no academic textbook paragraphs. "
        "If a small code snippet helps illustrate, include one."
    ),
    INTENT_DEBUG: (
        "The user needs DEBUGGING help. Identify the bug FIRST in one line. "
        "Show the corrected code immediately. Then briefly explain what was wrong. "
        "Don't lecture — just fix it."
    ),
    INTENT_OPTIMIZE: (
        "The user wants OPTIMIZATION. Show the improved version first. "
        "Briefly state what changed and why it's better (complexity, readability). "
        "Compare old vs new if helpful."
    ),
    INTENT_PROJECT: (
        "The user wants a FULL PROJECT plan. Act like a senior software architect. "
        "Give: overview → tech stack → features → architecture → folder structure → "
        "implementation steps → starter code. Be practical and actionable."
    ),
    INTENT_ARCHITECT: (
        "The user wants ARCHITECTURE/DESIGN guidance. Think like a senior engineer. "
        "Give structured design with components, data flow, and trade-offs. "
        "Use diagrams described in text if helpful."
    ),
    INTENT_INTERVIEW: (
        "The user is preparing for INTERVIEWS. Give clear, concise answers "
        "that would impress an interviewer. Include key points, examples, "
        "and common follow-up topics."
    ),
    INTENT_COMPARE: (
        "The user wants a COMPARISON. Use a clear structure: "
        "key differences, when to use each, pros/cons. "
        "A brief table or bullet list works best."
    ),
    INTENT_QUICK: (
        "The user wants a QUICK ANSWER. Be direct and concise. "
        "Answer in 1-3 sentences. No unnecessary elaboration."
    ),
    INTENT_GREETING: (
        "The user is GREETING you. Respond naturally, warmly, and concisely (1 sentence). "
        "Do NOT output any code, system design, or technical template sections."
    ),
    INTENT_CASUAL: (
        "The user is engaging in CASUAL CONVERSATION. Respond in a natural, friendly, conversational tone (1-2 sentences). "
        "Do NOT output any code, system design, or technical template sections."
    ),
    INTENT_GENERAL: "",
}


# ── Token Budgets ──────────────────────────────────────────────────────────────
_TOKEN_BUDGETS = {
    INTENT_GREETING:  200,
    INTENT_CASUAL:    300,
    INTENT_CODE:      2400,
    INTENT_EXPLAIN:   800,
    INTENT_DEBUG:     1800,
    INTENT_OPTIMIZE:  1800,
    INTENT_PROJECT:   2560,
    INTENT_ARCHITECT: 2048,
    INTENT_INTERVIEW: 1024,
    INTENT_COMPARE:   800,
    INTENT_QUICK:     300,
    INTENT_GENERAL:   600,
}


# ── Main Detection Function ───────────────────────────────────────────────────

def detect(text: str) -> IntentResult:
    """
    Classify user intent from their message.
    Returns IntentResult with intent type, language, style hint, and token budget.
    Runs in <1ms, zero API calls.
    """
    if not text or not text.strip():
        return IntentResult()

    text_clean = text.strip()
    scores = {}

    # Score each intent category
    for intent, patterns in [
        (INTENT_GREETING,  _GREETING_PATTERNS),
        (INTENT_CASUAL,    _CASUAL_PATTERNS),
        (INTENT_DEBUG,     _DEBUG_PATTERNS),
        (INTENT_CODE,      _CODE_PATTERNS),
        (INTENT_OPTIMIZE,  _OPTIMIZE_PATTERNS),
        (INTENT_PROJECT,   _PROJECT_PATTERNS),
        (INTENT_ARCHITECT, _ARCHITECT_PATTERNS),
        (INTENT_INTERVIEW, _INTERVIEW_PATTERNS),
        (INTENT_COMPARE,   _COMPARE_PATTERNS),
        (INTENT_EXPLAIN,   _EXPLAIN_PATTERNS),
    ]:
        score = 0
        for p in patterns:
            if p.search(text_clean):
                score += 1
        if score > 0:
            scores[intent] = score

    # Quick answer detection (only if nothing else matched strongly)
    if not scores:
        for p in _QUICK_PATTERNS:
            if p.search(text_clean):
                scores[INTENT_QUICK] = 1
                break

    # Pick highest-scoring intent
    if scores:
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]
        confidence = min(best_score / 3.0, 1.0)
    else:
        best_intent = INTENT_GENERAL
        best_score = 0
        confidence = 0.0

    # Detect programming language
    lang = _detect_language(text_clean)

    # If we detected a language but intent is general/explain,
    # and the message is short, it's likely a code request
    if lang and best_intent in (INTENT_GENERAL, INTENT_EXPLAIN):
        word_count = len(text_clean.split())
        if word_count <= 12:
            # Short message + language mention = likely wants code
            code_score = scores.get(INTENT_CODE, 0)
            if code_score == 0 and best_intent == INTENT_GENERAL:
                best_intent = INTENT_CODE
                confidence = 0.5

    # Build style and token budget
    style_map = {
        INTENT_GREETING:  STYLE_CONVERSATIONAL,
        INTENT_CASUAL:    STYLE_CONVERSATIONAL,
        INTENT_CODE:      STYLE_CODE_FIRST,
        INTENT_DEBUG:     STYLE_FIX_FIRST,
        INTENT_OPTIMIZE:  STYLE_CODE_FIRST,
        INTENT_EXPLAIN:   STYLE_EXPLAIN_FIRST,
        INTENT_PROJECT:   STYLE_PLAN_FIRST,
        INTENT_ARCHITECT: STYLE_PLAN_FIRST,
        INTENT_INTERVIEW: STYLE_EXPLAIN_FIRST,
        INTENT_COMPARE:   STYLE_EXPLAIN_FIRST,
        INTENT_QUICK:     STYLE_DIRECT,
        INTENT_GENERAL:   STYLE_CONVERSATIONAL,
    }

    # Determine if we should skip local hardcoded fallbacks
    skip_local = best_intent in (
        INTENT_CODE, INTENT_DEBUG, INTENT_OPTIMIZE,
        INTENT_PROJECT, INTENT_ARCHITECT,
    )

    result = IntentResult(
        intent=best_intent,
        language=lang,
        style=style_map.get(best_intent, STYLE_CONVERSATIONAL),
        tokens=_TOKEN_BUDGETS.get(best_intent, 600),
        confidence=confidence,
        skip_local_fallback=skip_local,
        prompt_suffix=_STYLE_HINTS.get(best_intent, ""),
    )

    logger.info(f"[INTENT] {result}")
    return result


# ── Convenience ────────────────────────────────────────────────────────────────

def is_code_intent(result: IntentResult) -> bool:
    return result.intent in (INTENT_CODE, INTENT_DEBUG, INTENT_OPTIMIZE)

def is_technical_intent(result: IntentResult) -> bool:
    return result.intent in (
        INTENT_CODE, INTENT_DEBUG, INTENT_OPTIMIZE,
        INTENT_PROJECT, INTENT_ARCHITECT, INTENT_INTERVIEW,
        INTENT_COMPARE, INTENT_EXPLAIN,
    )

def should_skip_hardcoded(result: IntentResult) -> bool:
    """Whether to bypass ai_knowledge.py and semantic cache for this intent."""
    return result.skip_local_fallback
