"""Universal Response Quality Critic (Phase 10).

Goal: make Jarvis answer like ChatGPT / Claude / DeepSeek — direct, correct,
complete, appropriately deep, and free of boilerplate. This critic runs for EVERY
specialist answer (it is domain-agnostic) and complements the domain critics.

Two layers, by design:

  1. ``deterministic_check`` — cheap, precise, NO LLM call. Runs first (before the
     domain critics) so obvious quality failures are caught for free and never reach
     the network. It only fires on HIGH-CONFIDENCE anti-patterns so a correct answer
     is never rejected:
       * placeholder / stub markers (TODO/FIXME, "your code here", "[insert ...]");
       * truncated / "rest omitted" code and unbalanced ``` code fences;
       * the same section header repeated 3+ times (boilerplate spam);
       * a verbatim long paragraph repeated (boilerplate repetition);
       * generic AI filler ("as an AI", "I hope this helps", "feel free to ask");
       * a generic apology / fallback / deflection of an answerable request.

  2. ``score`` — an LLM call that grades the answer 0-10 on Correctness,
     Completeness, Depth, Clarity, and Production Readiness. If ANY category scores
     below ``THRESHOLD`` (8) the answer is rejected so the router regenerates. It is
     calibrated to the QUESTION's complexity (a concise answer to a simple question
     is ideal) and FAILS OPEN if the model output cannot be parsed, so a good answer
     is never blocked by a flaky grade.

Conservative on purpose: the deterministic layer never trips on a legitimate
clarification ("could you share the stack trace?"), and the scorer is told that a
focused clarification for a genuinely under-specified request is a GOOD answer.
"""
import logging
import re

import brain_manager

logger = logging.getLogger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
ENABLED = True
THRESHOLD = 8  # any category strictly below this -> regenerate
CATEGORIES = ("Correctness", "Completeness", "Depth", "Clarity", "Production Readiness")

_FENCE = re.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)

# ── High-confidence deterministic anti-patterns ─────────────────────────────
# Placeholder / stub markers. Deliberately omits the bare word "placeholder"
# (collides with the HTML/JSX `placeholder` attribute) and prose like
# "implement this" / "fill in the form".
_PLACEHOLDER_RE = re.compile(
    r"(?:#|//|/\*|<!--)\s*(?:TODO|FIXME)\b"
    r"|^\s*(?:TODO|FIXME)\b\s*:"  # standalone "TODO:" line (colon required; not "todo-app")
    r"|\byour\s+code\s+(?:goes\s+)?here\b|\byour\s+solution\s+here\b"
    r"|\bcode\s+goes\s+here\b|\bimplementation\s+goes\s+here\b"
    r"|\b(?:insert|add|put)\s+(?:your\s+)?(?:code|logic|implementation)\s+here\b"
    r"|\blorem\s+ipsum\b|\bto\s+be\s+implemented\b|\bcoming\s+soon\b|\bimplement\s+me\b"
    r"|\bplaceholder\s+(?:text|here|content|value|comment)\b"
    r"|\bNotImplementedError\b|\bUnsupportedOperationException\b"
    r"|\[\s*(?:insert|your|todo|placeholder|fill[\s_-]?in|add\s+your)\b[^\]]*\]",  # \b: not "[todos]"
    re.IGNORECASE | re.MULTILINE,
)

# Truncation markers — the answer trails off instead of finishing.
_TRUNCATION_RE = re.compile(
    r"(?:#|//|/\*)\s*\.\.\.?\s*(?:rest|remaining|more|continued?|implementation|code|logic|omitted|unchanged)\b"
    r"|\b(?:rest|remainder)\s+of\s+(?:the\s+)?(?:code|implementation|file|function|method|class)\b"
    r"|\bcode\s+continues\b|\bomitted\s+for\s+brevity\b"
    r"|\b(?:remaining|other)\s+(?:methods?|functions?|fields?|code|logic)\s+(?:omitted|unchanged|go\s+here|here)\b"
    r"|\.\.\.\s+(?:unchanged|rest\s+omitted)\b",
    re.IGNORECASE,
)

# Generic AI filler that top assistants strip out.
_FILLER_RE = re.compile(
    r"\bas an ai\b|\bas a large language model\b|\bas an? language model\b"
    r"|\bi hope (?:this|that) helps\b|\bi hope this (?:answers|clarifies)\b"
    r"|\bfeel free to (?:ask|reach out|let me know)\b"
    r"|\bif you have any (?:other |more |further |additional )?questions\b"
    r"|\bis there anything else\b|\bwithout further ado\b"
    r"|\bin today'?s (?:fast[- ]paced|digital) world\b"
    r"|\blet me know if you (?:need|have|'?d like)\b"
    r"|\bi'?m happy to help\b|\bhappy to assist\b|\bgreat question\b"
    r"|\bplease don'?t hesitate to\b",
    re.IGNORECASE,
)

# Generic apology / fallback / deflection of an answerable request. Carefully
# scoped to refusal-to-help so a legitimate clarification ("I can't pinpoint it
# without your code") is NOT flagged.
_DEFLECTION_RE = re.compile(
    r"\bi (?:can'?t|cannot|am unable to|'?m unable to|am not able to|'?m not able to) (?:help|assist)\b"
    r"|\bi (?:can'?t|cannot) (?:help|assist) (?:you )?with\b"
    r"|\b(?:i'?m|i am) sorry,? but i (?:can'?t|cannot|am unable|won'?t be able)\b"
    r"|\bi apolog(?:ize|ise),? but i (?:can'?t|cannot|am unable|won'?t)\b"
    r"|\bunfortunately,? i (?:can'?t|cannot|am unable to|don'?t have the ability)\b"
    r"|\bi (?:can'?t|cannot) (?:provide|do|complete|fulfill) (?:that|this|your request)\b",
    re.IGNORECASE,
)


# ── Deterministic helpers ───────────────────────────────────────────────────
def _strip_code(text: str) -> str:
    return _FENCE.sub("\n", text or "")


def _repeated_header(text: str):
    """Return a header repeated 3+ times (boilerplate spam), else None."""
    counts = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s.startswith("#"):
            continue
        norm = re.sub(r"[#*`]", "", s).strip().lower()
        if len(norm) < 3:
            continue
        counts[norm] = counts.get(norm, 0) + 1
    for header, n in counts.items():
        if n >= 3:
            return header
    return None


def _repeated_paragraph(text: str):
    """Return a verbatim >=12-word paragraph that appears 2+ times, else None."""
    seen = {}
    for block in re.split(r"\n\s*\n", _strip_code(text)):
        s = block.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith(">"):
            continue
        if len(s.split()) < 12:
            continue
        norm = re.sub(r"\s+", " ", s).lower()
        seen[norm] = seen.get(norm, 0) + 1
    for norm, n in seen.items():
        if n >= 2:
            return norm[:60]
    return None


def deterministic_check(agent_type: str, user_query: str, response_text: str):
    """Cheap, precise, no-LLM quality gate. Return (ok: bool, reason: str)."""
    if not ENABLED:
        return True, ""
    text = response_text or ""
    if not text.strip():
        return True, ""  # empty drafts are handled by the generation/verifier loop

    if text.count("```") % 2 != 0:
        return False, ("A code fence is left open (odd number of ``` markers) — the code is "
                       "truncated. Close every fenced block and ship complete, runnable code.")

    if _TRUNCATION_RE.search(text):
        return False, ("The answer is truncated (it says the rest is omitted / unchanged / "
                       "continues). Provide the FULL, complete content — never abbreviate code.")

    if _PLACEHOLDER_RE.search(text):
        return False, ("The answer contains a placeholder / stub (TODO, 'your code here', "
                       "'[insert ...]', NotImplementedError). Replace every placeholder with the "
                       "complete, working implementation.")

    header = _repeated_header(text)
    if header:
        return False, (f"The section header '{header}' is repeated {3}+ times. Remove the "
                       "duplicated boilerplate sections and keep a single, well-organized structure.")

    para = _repeated_paragraph(text)
    if para:
        return False, ("A paragraph is repeated verbatim (boilerplate repetition). Write each point "
                       "once; do not pad the answer by repeating the same text.")

    m = _FILLER_RE.search(text)
    if m:
        return False, (f"Remove generic filler ('{m.group(0).strip()}'). Lead with the direct "
                       "answer and keep the response substantive — no meta-disclaimers or padding.")

    m = _DEFLECTION_RE.search(text)
    if m:
        return False, ("Do not deflect or apologize for an answerable technical question. Answer it "
                       "directly and completely instead of refusing or falling back.")

    return True, ""


# ── LLM scorer ──────────────────────────────────────────────────────────────
_SCORER_SYS = (
    "You are the Verifier Agent's Response Quality Critic. Judge the RESPONSE to the "
    "USER QUESTION the way a senior engineer comparing ChatGPT, Claude, and DeepSeek "
    "would. Be fair and calibrated: a correct, complete, well-written answer PASSES. "
    "Reserve low scores for real, nameable deficiencies.\n\n"
    "Calibrate to the QUESTION's complexity:\n"
    "- Simple / factual question -> a SHORT, direct, correct answer is ideal; do NOT "
    "demand extra depth or padding — brevity is a virtue here.\n"
    "- Complex / open-ended question -> expect appropriate depth, structure, and tradeoffs.\n"
    "A focused clarification for a GENUINELY under-specified request is a GOOD answer. "
    "A deflection, generic apology, or fallback for an ANSWERABLE question is a failure.\n\n"
    "Score each category 0-10 (8 = clearly ship-quality; 10 = excellent):\n"
    "- CORRECTNESS: factually right; no hallucinated APIs/facts; no self-contradiction.\n"
    "- COMPLETENESS: fully answers what was asked; nothing the user requested is missing; "
    "code is complete (not truncated or stubbed).\n"
    "- DEPTH: reasoning and insight appropriate to the question's difficulty (not padding).\n"
    "- CLARITY: leads with the direct answer, then concise justification; well structured; "
    "no filler, boilerplate, or unnecessary verbosity.\n"
    "- PRODUCTION_READINESS: code/advice is usable as-is; no TODOs/placeholders; correct, "
    "safe defaults.\n\n"
    "Output EXACTLY these six lines and NOTHING else:\n"
    "CORRECTNESS: <0-10>\n"
    "COMPLETENESS: <0-10>\n"
    "DEPTH: <0-10>\n"
    "CLARITY: <0-10>\n"
    "PRODUCTION_READINESS: <0-10>\n"
    "ISSUES: <one short line naming the single biggest fix, or \"none\">"
)

_SCORE_PATTERNS = {
    "Correctness": re.compile(r"correctness\s*[:=\-]*\s*(\d{1,2})", re.IGNORECASE),
    "Completeness": re.compile(r"completeness\s*[:=\-]*\s*(\d{1,2})", re.IGNORECASE),
    "Depth": re.compile(r"\bdepth\s*[:=\-]*\s*(\d{1,2})", re.IGNORECASE),
    "Clarity": re.compile(r"clarity\s*[:=\-]*\s*(\d{1,2})", re.IGNORECASE),
    "Production Readiness": re.compile(r"production[\s_]*readiness\s*[:=\-]*\s*(\d{1,2})", re.IGNORECASE),
}
_ISSUES_RE = re.compile(r"issues?\s*[:=\-]+\s*(.+)", re.IGNORECASE)


def _parse_scores(out: str):
    """Parse the six-line rubric. Returns {category: int}. Missing entries omitted."""
    scores = {}
    for name, pat in _SCORE_PATTERNS.items():
        m = pat.search(out or "")
        if m:
            scores[name] = max(0, min(10, int(m.group(1))))
    return scores


def _extract_issues(out: str):
    m = _ISSUES_RE.search(out or "")
    if not m:
        return ""
    issue = m.group(1).strip().strip("\"'")
    if issue.lower() in ("none", "n/a", "na", "-", ""):
        return ""
    return issue


def score(agent_type: str, user_query: str, response_text: str):
    """LLM quality grade. Return (ok: bool, feedback: str). Fails OPEN on any
    parse/transport problem so a good answer is never blocked by a flaky grade."""
    if not ENABLED:
        return True, ""
    if not (response_text or "").strip():
        return True, ""

    prompt = f"USER QUESTION:\n{user_query}\n\nRESPONSE:\n{response_text}"
    try:
        out, _ = brain_manager.ask(
            prompt=prompt,
            context="",
            sys_prompt=_SCORER_SYS,
            max_tokens=220,
            deepthink=False,
            stateless=True,  # QA call — never reads/pollutes shared history
        )
    except Exception as e:  # transport failure -> do not block a good answer
        logger.warning(f"[QUALITY] scorer call failed ({e}) — failing open")
        return True, ""

    scores = _parse_scores(out)
    if len(scores) < len(CATEGORIES):
        logger.info("[QUALITY] scorer output unparseable — failing open")
        return True, ""

    failing = {k: v for k, v in scores.items() if v < THRESHOLD}
    if not failing:
        logger.info(f"[QUALITY] passed ({', '.join(f'{k} {v}' for k, v in scores.items())})")
        return True, ""

    issues = _extract_issues(out)
    low = ", ".join(f"{k} {v}/10" for k, v in failing.items())
    feedback = (
        f"Response quality is below the bar (regenerate). Low scores: {low}. "
        + (f"Biggest fix: {issues}. " if issues else "")
        + "Deliver a ChatGPT/Claude-grade answer: lead with the direct answer, then a concise "
        "justification; be correct and complete with no missing parts; match depth to the "
        "question's difficulty; and include NO filler, boilerplate, TODOs, placeholders, or "
        "unnecessary verbosity."
    )
    logger.warning(f"[QUALITY] below bar: {low}")
    return False, feedback


def critique(agent_type: str, user_query: str, response_text: str) -> dict:
    """Convenience wrapper running both layers. Returns {"verified", "feedback"}."""
    ok, reason = deterministic_check(agent_type, user_query, response_text)
    if not ok:
        return {"verified": False, "feedback": reason}
    ok, reason = score(agent_type, user_query, response_text)
    if not ok:
        return {"verified": False, "feedback": reason}
    return {"verified": True, "feedback": ""}
