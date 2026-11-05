"""Deterministic structural checks for DSA solutions (Phase 6).

Runs BEFORE the LLM critic (after the complexity validator) to enforce, for genuine
"solve this problem" answers that contain code:

  * the mandatory answer sections are present (Problem Understanding, Optimal
    Algorithm, Code, Approach, Complexity);
  * the code has no placeholder / stub method bodies (TODO, NotImplementedError,
    `pass`-only or `...`-only bodies, "your code here", etc.);
  * the code "compiles logically": balanced code fences, balanced (){}[] delimiters
    (string/comment aware), no truncation markers, and — for Python blocks — it
    actually parses with `ast.parse`.

It is conservative so correct answers are NEVER rejected:
  * Conceptual questions ("what is a trie?", "explain Dijkstra", "difference
    between…") are NOT forced into the solution template.
  * If there is no real code block, the structural template does not apply.
"""
import ast
import re
import logging

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)

# Mandatory solution sections (canonical name + accepted header synonyms).
_REQUIRED_SECTIONS = (
    ("Problem Understanding", ("problem understanding", "problem statement",
                                "understanding the problem", "restate the problem")),
    ("Optimal Algorithm", ("optimal algorithm", "algorithm", "technique",
                            "pattern", "data structure")),
    ("Code", ("code", "solution", "implementation")),
    ("Approach", ("approach", "explanation", "how it works", "walkthrough",
                  "intuition", "step-by-step", "step by step")),
    ("Complexity", ("complexity", "time complexity", "time & space",
                    "time and space")),
)

# A conceptual / explanatory question is not a solve request.
_CONCEPTUAL_RE = re.compile(
    r"\b(what\s+is|what\s+are|what'?s|explain|describe|difference\s+between|"
    r"why\s+is|why\s+do|when\s+(?:to|should|would)|how\s+does|pros\s+and\s+cons|"
    r"compare|define|meaning\s+of)\b",
    re.IGNORECASE,
)

# Placeholder / stub markers that must never appear in a complete solution.
_PLACEHOLDER_MARKERS = re.compile(
    r"\bTODO\b|\bFIXME\b|your\s+code\s+here|your\s+solution\s+here|"
    r"implement\s+(?:this|me|here)|fill\s+in|write\s+your\s+code|"
    r"NotImplementedError|UnsupportedOperationException|"
    r"throw\s+new\s+UnsupportedOperation|raise\s+NotImplemented",
    re.IGNORECASE,
)

# Truncation markers — the answer trails off instead of finishing the code.
_TRUNCATION_MARKERS = re.compile(
    r"(?://|#)\s*\.\.\.\s*(?:rest|remaining|more|continue|continued|implementation|code)|"
    r"\brest\s+of\s+(?:the\s+)?(?:code|implementation)|code\s+continues|"
    r"omitted\s+for\s+brevity|truncated|\(\s*\.\.\.\s*\)",
    re.IGNORECASE,
)


def _code_blocks(text: str):
    """Return [(lang, code), ...] for every fenced block."""
    return [(m.group(1).lower(), m.group(2)) for m in _FENCE.finditer(text or "")]


def _header_lines(text: str):
    out = []
    for line in (text or "").splitlines():
        s = line.strip().lower()
        if not s:
            continue
        if s.startswith("#") or s.startswith("**") or (s.endswith(":") and len(s) < 48):
            out.append(re.sub(r"[#*`:_]", "", s).strip())
    return out


def is_conceptual(user_query: str) -> bool:
    return bool(_CONCEPTUAL_RE.search(user_query or ""))


def _real_code(code: str) -> bool:
    """Heuristic: the block is real code, not a one-liner / prose snippet."""
    stripped = (code or "").strip()
    if not stripped:
        return False
    if len(stripped.splitlines()) >= 2:
        return True
    return bool(re.search(r"\b(def|class|return|for|while|if|public|private|void|int|"
                          r"function|const|let|var)\b|[{};]", stripped))


def is_solution_attempt(user_query: str, text: str) -> bool:
    """A solve request that actually ships code => the strict template applies."""
    if is_conceptual(user_query):
        return False
    return any(_real_code(code) for _, code in _code_blocks(text))


def missing_sections(text: str):
    headers = _header_lines(text)
    missing = []
    for canonical, synonyms in _REQUIRED_SECTIONS:
        if not any(any(syn in h for syn in synonyms) for h in headers):
            missing.append(canonical)
    return missing


# ── Placeholder detection ───────────────────────────────────────────────────
def _python_empty_bodies(code: str):
    """Return True if a Python def/class body is only `pass` / `...` / a placeholder."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False  # handled by the compile check, not here
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [n for n in node.body if not isinstance(n, ast.Expr)
                    or not isinstance(getattr(n, "value", None), ast.Constant)
                    or not isinstance(n.value.value, str)]  # drop docstrings
            if not body:
                body = node.body
            if len(body) == 1:
                only = body[0]
                if isinstance(only, ast.Pass):
                    return True
                if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) \
                        and only.value.value is Ellipsis:
                    return True
                if isinstance(only, ast.Raise) and only.exc is not None:
                    name = ""
                    exc = only.exc
                    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                        name = exc.func.id
                    elif isinstance(exc, ast.Name):
                        name = exc.id
                    if name == "NotImplementedError":
                        return True
    return False


def placeholder_violation(text: str):
    """Return a reason string if the code contains a placeholder/stub, else None."""
    blocks = _code_blocks(text)
    for lang, code in blocks:
        if _PLACEHOLDER_MARKERS.search(code):
            return ("The code contains a placeholder / stub (TODO, 'your code here', "
                    "NotImplementedError, or UnsupportedOperationException). Ship the COMPLETE, "
                    "working implementation — no stubbed-out methods.")
    # Python empty bodies (pass / ... / raise NotImplementedError).
    for lang, code in blocks:
        if lang in ("python", "py", ""):
            if _python_empty_bodies(code):
                return ("A method body is just `pass` / `...` / `raise NotImplementedError` — that "
                        "is a placeholder, not an implementation. Provide the real method body.")
    # Standalone `...` line in any block (common stub for omitted code).
    for lang, code in blocks:
        for line in code.splitlines():
            if line.strip() == "..." or line.strip() == "# ...":
                return ("The code uses `...` as a stand-in for omitted code. Provide the full "
                        "implementation instead of an ellipsis placeholder.")
    return None


# ── Logical compile check ───────────────────────────────────────────────────
_OPEN = {")": "(", "]": "[", "}": "{"}


def _balanced_delimiters(code: str, lang: str) -> bool:
    """Bracket balance that ignores characters inside strings and comments."""
    stack = []
    i, n = 0, len(code)
    in_line_comment = False
    in_block_comment = False
    string_ch = None        # current string delimiter (', ", or `)
    triple = False          # inside a python triple-quoted string
    while i < n:
        c = code[i]
        two = code[i:i + 2]
        three = code[i:i + 3]
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if string_ch is not None:
            if c == "\\":            # skip escaped char
                i += 2
                continue
            if triple and three == string_ch * 3:
                string_ch, triple = None, False
                i += 3
                continue
            if not triple and c == string_ch:
                string_ch = None
            i += 1
            continue
        # not in string/comment
        if three in ('"""', "'''"):
            string_ch, triple = c, True
            i += 3
            continue
        if c in ("'", '"', "`"):
            string_ch, triple = c, False
            i += 1
            continue
        if c == "#":
            in_line_comment = True
            i += 1
            continue
        if two == "//":
            in_line_comment = True
            i += 2
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != _OPEN[c]:
                return False
            stack.pop()
        i += 1
    return not stack and string_ch is None


def compiles_logically(text: str):
    """Return (ok, reason). Checks fences, delimiter balance, truncation, and (for
    Python blocks) that the code actually parses."""
    if (text or "").count("```") % 2 != 0:
        return False, ("A code fence is left open (odd number of ``` markers) — the code block is "
                       "truncated. Close every fenced block and ship complete code.")
    if _TRUNCATION_MARKERS.search(text or ""):
        return False, ("The code is truncated (it says the rest is omitted/continues). Provide the "
                       "FULL implementation in one complete block.")
    for lang, code in _code_blocks(text):
        if not _balanced_delimiters(code, lang):
            return False, ("The code has unbalanced parentheses/brackets/braces — it does not "
                           "compile. Fix the delimiters and ship complete, runnable code.")
        if lang in ("python", "py") or (lang == "" and re.search(r"^\s*(?:def|class|import|from)\s",
                                                                  code, re.MULTILINE)):
            src = re.sub(r"(?m)^\s*(?:>>>|\.\.\.)\s?", "", code)  # strip REPL markers
            try:
                ast.parse(src)
            except SyntaxError as e:
                return False, (f"The Python code does not parse (syntax error: {e.msg}). It must "
                               "compile logically — provide complete, syntactically valid code.")
    return True, ""


def check(user_query: str, response_text: str):
    """Deterministic structural gate. Return (ok: bool, reason: str)."""
    text = response_text or ""
    if not is_solution_attempt(user_query, text):
        return True, ""  # conceptual / no-code answer -> defer to the LLM critic

    missing = missing_sections(text)
    if missing:
        logger.warning(f"[DSA_STRUCTURE] Missing sections: {missing}")
        return False, (
            "The DSA solution is missing required sections. Every solution MUST include: "
            "Problem Understanding, Optimal Algorithm, Code (complete), Approach, and Complexity. "
            f"Missing: {', '.join(missing)}."
        )

    ph = placeholder_violation(text)
    if ph:
        logger.warning("[DSA_STRUCTURE] Placeholder/stub detected")
        return False, ph

    ok, reason = compiles_logically(text)
    if not ok:
        logger.warning(f"[DSA_STRUCTURE] Compile check failed: {reason}")
        return False, reason

    return True, ""
