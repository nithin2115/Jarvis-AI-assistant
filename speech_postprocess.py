"""Speech transcription post-processing.

Tightens up the raw output of an offline STT engine (Vosk small-en is
the primary target) before the AI sees it. The Vosk small-en model is
fast and CPU-friendly but has well-known mistranscription patterns —
this module fixes the common ones with a deterministic dictionary
pass, then applies memory-aware vocabulary bias so things the user
talks about regularly stay correctly cased.

Design goals:
    * pure functions, no I/O, no external deps
    * order matters: phonetic → multi-word brand fixes → casing
    * idempotent: post(post(x)) == post(x)
    * memory-aware via a hint list passed by `voice_server`

Public API:
    clean_transcription(text, *, hints=None) -> str
    fix_wake_word(text)                       -> str
    looks_like_jarvis(token)                  -> bool
    edit_distance(a, b)                       -> int
    JARVIS_PHONETIC_NEIGHBOURS                -> frozenset[str]
"""
from __future__ import annotations

import re
from typing import Iterable

# ───────────────────────────────────────────────────────────────────
# Wake-word phonetic neighbourhood
# ───────────────────────────────────────────────────────────────────
# Real-world Vosk small-en outputs that should still trigger the wake.
# Pulled from observed mistranscriptions across multiple users on
# different mics. Keep alphabetised so additions diff cleanly.
JARVIS_PHONETIC_NEIGHBOURS: frozenset[str] = frozenset({
    "harness",
    "harvest",
    "harvis",
    "jaris",
    "jarvi",
    "jarvic",
    "jarvice",
    "jarvis",
    "jarviss",
    "jarvix",
    "jarvus",
    "javes",
    "javis",
    "jervis",
    "jorvis",
    "jurvis",
    "service",  # only fires when paired with hey/hi/hello — see _is_addressed
})

# Words that, when they precede a candidate, signal "user is addressing
# the assistant" — promotes weaker candidates (like 'service') to wake.
_ADDRESS_PREFIXES = ("hey", "hi", "hello", "ok", "okay", "yo", "dear")

# Canonical wake form we replace neighbours with at the start of an
# utterance so downstream code sees one consistent token.
_CANONICAL_WAKE = "jarvis"


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance. Tiny, dependency-free implementation —
    only used for short tokens (wake candidates ≤ 8 chars), so the
    O(len(a)*len(b)) cost is irrelevant."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost, # substitution
            )
        prev = curr
    return prev[-1]


def looks_like_jarvis(token: str) -> bool:
    """True if `token` is plausibly a mistranscription of 'jarvis'.

    Three layered rules:
      1. exact match against the curated phonetic neighbour set
      2. starts with jar-/jav-/jer-/jor- and is 4..9 chars long
      3. Levenshtein distance ≤ 2 to the canonical 'jarvis'
    """
    t = (token or "").lower().strip()
    if not t:
        return False
    if t in JARVIS_PHONETIC_NEIGHBOURS:
        return True
    if 4 <= len(t) <= 9 and t[:3] in ("jar", "jav", "jer", "jor", "jur"):
        return True
    if 4 <= len(t) <= 9 and edit_distance(t, _CANONICAL_WAKE) <= 2:
        return True
    return False


def fix_wake_word(text: str) -> str:
    """Normalise wake-word variants at the START of an utterance.

    'hey javis open vs code' → 'hey jarvis open vs code'
    'jarvi what time is it'  → 'jarvis what time is it'
    'service tell me a joke' → 'jarvis tell me a joke' (only when
                               preceded by hey/hi/hello)
    """
    if not text:
        return text
    parts = text.strip().split()
    if not parts:
        return text

    # Case 1: address-prefix followed by a wake-candidate.
    if (
        len(parts) >= 2
        and parts[0].lower() in _ADDRESS_PREFIXES
        and looks_like_jarvis(parts[1])
    ):
        parts[1] = _CANONICAL_WAKE
        return " ".join(parts)

    # Case 2: utterance begins with a wake-candidate.
    if looks_like_jarvis(parts[0]):
        parts[0] = _CANONICAL_WAKE
        return " ".join(parts)

    # Case 3: the curated neighbour 'service' alone (without an address
    # prefix) is left as-is — too risky to coerce.
    return text


# ───────────────────────────────────────────────────────────────────
# Brand / acronym fixes
# ───────────────────────────────────────────────────────────────────
# Order matters. Each entry is (regex, replacement). Compiled once at
# import. We use word boundaries everywhere so 'vs' inside 'visualise'
# is never touched.
_RAW_RULES: list[tuple[str, str]] = [
    # ── Editors / IDEs ───────────────────────────────────────────
    (r"\bv\s*s\s*cold\b",                 "VS Code"),
    (r"\bv\s*s\s*code\b",                 "VS Code"),
    (r"\bvee\s*ess\s*code\b",             "VS Code"),
    (r"\bvisual\s*studio\s*code\b",       "Visual Studio Code"),
    (r"\bjet\s*brains\b",                 "JetBrains"),
    (r"\bint\s*el\s*li\s*j\b",            "IntelliJ"),
    (r"\bi\s*de\b",                       "IDE"),

    # ── Languages / frameworks ───────────────────────────────────
    (r"\bjava\s*script\b",                "JavaScript"),
    (r"\bj\s*s\b(?!\w)",                  "JS"),
    (r"\btype\s*script\b",                "TypeScript"),
    (r"\bt\s*s\b(?!\w)",                  "TS"),
    (r"\breact\s*j\s*s\b",                "React.js"),
    (r"\breact\s*jay\s*s\b",              "React.js"),
    (r"\bnode\s*j\s*s\b",                 "Node.js"),
    (r"\bnode\s*jay\s*s\b",               "Node.js"),
    (r"\bnext\s*j\s*s\b",                 "Next.js"),
    (r"\bvue\s*j\s*s\b",                  "Vue.js"),
    (r"\bpy\s*thon\b",                    "Python"),
    (r"\bc\s*plus\s*plus\b",              "C++"),
    (r"\bc\s*sharp\b",                    "C#"),
    (r"\bdot\s*net\b",                    "dotnet"),
    (r"\bnest\s*j\s*s\b",                 "Nest.js"),
    (r"\bsquel\b",                        "SQL"),     # 'sequel'→'SQL' (case-by-case via boundary)
    (r"\bs\s*q\s*l\b",                    "SQL"),
    (r"\bno\s*sql\b",                     "NoSQL"),
    (r"\bmongo\s*d\s*b\b",                "MongoDB"),
    (r"\bpostgres\s*sql\b",               "PostgreSQL"),
    (r"\bpost\s*gres\b",                  "Postgres"),
    (r"\bmy\s*sql\b",                     "MySQL"),

    # ── Platforms / tools ────────────────────────────────────────
    (r"\bgit\s*hub\b",                    "GitHub"),
    (r"\bgit\s*lab\b",                    "GitLab"),
    (r"\bbit\s*bucket\b",                 "Bitbucket"),
    (r"\bstack\s*overflow\b",             "Stack Overflow"),
    (r"\bdocker\s*hub\b",                 "Docker Hub"),
    (r"\bk\s*8\s*s\b",                    "Kubernetes"),
    (r"\bkube\s*c\s*t\s*l\b",             "kubectl"),
    (r"\bopen\s*a\s*i\b",                 "OpenAI"),
    (r"\bchat\s*g\s*p\s*t\b",             "ChatGPT"),
    (r"\bclaude\s*sonnet\b",              "Claude Sonnet"),
    (r"\bgoogle\s*gemini\b",              "Google Gemini"),
    (r"\bhugging\s*face\b",               "Hugging Face"),

    # ── Standalone two-letter acronyms commonly butchered ────────
    (r"\b(?<![A-Za-z])ai(?!\w)",          "AI"),
    (r"\b(?<![A-Za-z])ml(?!\w)",          "ML"),
    (r"\b(?<![A-Za-z])dsa\b",             "DSA"),
    (r"\b(?<![A-Za-z])api(?!\w)",         "API"),
    (r"\b(?<![A-Za-z])ui(?!\w)",          "UI"),
    (r"\b(?<![A-Za-z])ux(?!\w)",          "UX"),
    (r"\b(?<![A-Za-z])url\b",             "URL"),
    (r"\b(?<![A-Za-z])html\b",            "HTML"),
    (r"\b(?<![A-Za-z])css\b",             "CSS"),
    (r"\b(?<![A-Za-z])json\b",            "JSON"),
    (r"\b(?<![A-Za-z])xml\b",             "XML"),
    (r"\b(?<![A-Za-z])yaml\b",            "YAML"),

    # ── Misc filler / noise the recogniser sometimes inserts ─────
    (r"\bthe the\b",                      "the"),
    (r"\ba a\b",                          "a"),
    (r"\b(uh|um|er|ah)\b",                ""),    # fillers
]

_COMPILED_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), rep) for pat, rep in _RAW_RULES
]


def _apply_rules(text: str) -> str:
    out = text
    for pat, rep in _COMPILED_RULES:
        out = pat.sub(rep, out)
    return out


# ───────────────────────────────────────────────────────────────────
# Memory-aware bias
# ───────────────────────────────────────────────────────────────────
def _apply_hints(text: str, hints: Iterable[str]) -> str:
    """Preserve correct casing for words the user talks about often.

    Vosk transcribes everything lowercase. If the user's active topics
    say they care about 'Java', we want 'java' inside this transcript
    to render as 'Java' so the AI sees a properly-cased technical term.
    """
    if not hints:
        return text
    out = text
    seen = set()
    for hint in hints:
        h = (hint or "").strip()
        if not h or h.lower() in seen:
            continue
        seen.add(h.lower())
        # Word-boundary, case-insensitive replace with the hint's
        # original casing. We DON'T touch tokens that already match
        # the hint's exact case to keep idempotency cheap.
        pattern = re.compile(r"\b" + re.escape(h) + r"\b", re.IGNORECASE)
        out = pattern.sub(h, out)
    return out


# ───────────────────────────────────────────────────────────────────
# Top-level entry point
# ───────────────────────────────────────────────────────────────────
def clean_transcription(text: str, *, hints: Iterable[str] | None = None) -> str:
    """Pipeline:
      1. collapse whitespace
      2. fix wake-word at the start (downstream `_strip_wake` removes it)
      3. apply brand / acronym substitutions
      4. apply memory-aware casing hints
      5. tidy whitespace + capitalise the first letter

    `hints` is an iterable of pre-cased terms the user cares about,
    e.g. ['Java', 'DSA', 'VS Code']. Safe to pass None.
    """
    if not text:
        return ""
    out = re.sub(r"\s+", " ", text.strip())
    out = fix_wake_word(out)
    out = _apply_rules(out)
    if hints:
        out = _apply_hints(out, hints)
    out = re.sub(r"\s+", " ", out).strip()
    if out:
        out = out[0].upper() + out[1:]
    return out
