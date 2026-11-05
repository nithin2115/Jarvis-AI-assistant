"""DSA output-quality critic (Phase 11).

Deterministic, no-LLM gate run AFTER dsa_structure.check (sections present, no
stubs, code compiles) and BEFORE the LLM critic. It catches the "algorithmically
correct but garbled output" failures:

  * the same section appears twice (Complexity / Approach / Code / ...);
  * leftover TEMPLATE fragments / artifacts (placeholders like <algorithm>,
    "[explain ...]", "your explanation here", empty ``` ``` blocks);
  * unfinished sentences (text trails off mid-clause);
  * duplicated paragraphs;
  * LFU cache answers that omit keyToNode / freqToList / minFreq / LRU tie-break;
  * a Complexity section that claims O(1) without explaining WHY;
  * production-grade requests missing validation / encapsulation / a test example.

`cleanup()` is a best-effort sanitizer (drop duplicate sections, collapse repeated
headers, strip template artifacts) applied to the FINAL response before delivery.

Conservative: it only fires on genuine solve attempts that ship code, mirroring
dsa_structure, so conceptual / no-code answers are never rejected.
"""
import re
import logging

import dsa_structure as ds

logger = logging.getLogger(__name__)

_FENCE = ds._FENCE

# Canonical sections (label -> TIGHT header synonyms) that must appear at most ONCE.
# Matching is exact-or-prefixed-by-"syn " (NOT bare startswith) so distinct sections
# such as "Approach" and "Explanation" are never conflated into a false duplicate.
_DEDUP_SECTIONS = (
    ("Problem Understanding", ("problem understanding", "problem statement")),
    ("Optimal Algorithm", ("optimal algorithm", "algorithm")),
    ("Code", ("code", "solution code", "full code", "implementation")),
    ("Approach", ("approach", "walkthrough", "intuition")),
    ("Complexity", ("complexity", "time complexity", "time and space complexity",
                    "time & space complexity", "complexity analysis")),
    ("Edge Cases", ("edge cases", "edge case analysis", "corner cases")),
)

# Mandatory sections a PRODUCTION-grade request must include (FAILURE 4).
# Matching uses _matches_section so reasonable equivalents are accepted (e.g.
# an "Optimal Algorithm" header satisfies "Algorithm").
_PROD_SECTIONS = (
    ("Data Structures Used", ("data structures used", "data structures",
                               "data structure", "structures used")),
    ("Algorithm", ("algorithm", "optimal algorithm", "approach", "technique")),
    ("Full Code", ("full code", "code", "implementation", "solution code",
                    "complete code")),
    ("Complexity Proof", ("complexity proof", "complexity", "time complexity",
                           "complexity analysis", "time and space complexity",
                           "time & space complexity", "proof of complexity")),
    ("Edge Cases", ("edge cases", "edge case", "edge case analysis", "corner cases")),
)

# Leftover scaffolding / template artifacts that must never ship. Scanned OUTSIDE
# code blocks (so C++ `#include <algorithm>` / HTML `<code>` are never flagged), and
# the angle-bracket form deliberately excludes real header/tag names.
_TEMPLATE_ARTIFACT_RE = re.compile(
    r"<\s*(?:approach|explanation|complexity|placeholder|your[\s_-]?\w+|insert[\s_-]?\w+)\s*>"
    r"|\{\{\s*[\w\s]+\s*\}\}|<<\s*[\w\s]+\s*>>"
    r"|\byour\s+(?:explanation|approach|analysis|code|answer|solution)\s+here\b"
    r"|\b(?:section|paragraph|step)\s+\d+\s+(?:goes\s+here|here)\b"
    r"|\bexplain\s+(?:the\s+)?(?:approach|algorithm|complexity|solution)\s+here\b"
    r"|\b(?:add|insert|describe|write)\s+(?:the\s+|your\s+)?\w+\s+here\b",
    re.IGNORECASE,
)

_O1_RE = re.compile(r"O\s*\(\s*1\s*\)", re.IGNORECASE)
# Words that constitute a real "why O(1)" justification (reasoning OR mechanism).
_WHY_RE = re.compile(
    r"\bbecause\b|\bsince\b|\bas\s+(?:each|every|the)\b|\bdue\s+to\b|\bamortized\b"
    r"|\bconstant[- ]time\b|\beach\s+operation\b|\bevery\s+operation\b|\bin\s+expectation\b"
    r"|\baverage\s+case\b|\bhash\s*map\b|\bhashmap\b|\bhash\s+table\b|\bordereddict\b"
    r"|\bmove_to_end\b|\bdoubly[- ]linked\s+list\b|\blinked\s+list\b|\bmaintain(?:ed|s|ing)?\b"
    r"|\bincrement(?:al|ally|ed)?\b|\bpointer\b|\bbucket\b|\bO\(1\)\s+average\b",
    re.IGNORECASE,
)

_PROD_RE = re.compile(
    r"\bproduction[- ]?(?:grade|ready|quality)\b|\bproduction\b|\benterprise[- ]?grade\b"
    r"|\brobust\b|\bproduction\s+code\b",
    re.IGNORECASE,
)

# Sentence trails off mid-clause (ends with a dangling connector / open phrase).
_UNFINISHED_TAIL_RE = re.compile(
    r"(?:\b(?:the|a|an|to|of|for|and|or|but|with|because|since|such\s+as|"
    r"e\.g\.|i\.e\.|which|that|this|we|it|is|are|will|using|by)\s*"
    r"|,)\s*$",
    re.IGNORECASE,
)


def _section_headers(text):
    """Normalized ATX (`#`-prefixed) section headers, outside code fences only.
    Excludes bold labels like '**Time Complexity:** O(n)' so an in-section label is
    never miscounted as a duplicate section header."""
    out, in_fence = [], False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and s.startswith("#"):
            out.append(re.sub(r"[#*`:_]", "", s).strip().lower())
    return out


def _is_attempt(user_query, text):
    return ds.is_solution_attempt(user_query, text)


def _strip_code(text):
    return _FENCE.sub("\n", text or "")


# ── individual detectors ─────────────────────────────────────────────────────
def _matches_section(h, syns):
    """A header line maps to a canonical section iff it equals a synonym or begins
    with "<synonym> " (e.g. 'complexity analysis' -> Complexity). Avoids bare
    startswith so 'codeword' or 'approachable' never match."""
    return any(h == s or h.startswith(s + " ") for s in syns)


def duplicate_section(text):
    """Return the canonical name of a section that appears 2+ times, else None."""
    headers = _section_headers(text)
    for canonical, syns in _DEDUP_SECTIONS:
        hits = sum(1 for h in headers if _matches_section(h, syns))
        if hits >= 2:
            return canonical
    return None


def template_artifact(text):
    # Scan prose only (fenced code is excluded) to avoid flagging C++/HTML includes.
    m = _TEMPLATE_ARTIFACT_RE.search(_strip_code(text))
    if m:
        return m.group(0).strip()
    # An empty fenced block (```lang\n```) is a scaffolding leftover.
    for _, code in ds._code_blocks(text):
        if not code.strip():
            return "empty code block"
    return None


def duplicated_paragraph(text):
    seen = {}
    for block in re.split(r"\n\s*\n", _strip_code(text)):
        s = block.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith(">") or s.startswith("-"):
            continue
        if len(s.split()) < 8:
            continue
        norm = re.sub(r"\s+", " ", s).lower()
        seen[norm] = seen.get(norm, 0) + 1
    return any(n >= 2 for n in seen.values())


def unfinished_sentence(text):
    """True if the prose trails off mid-clause (ignores code, lists, headers, tables)."""
    prose = _strip_code(text).strip()
    if not prose:
        return False
    last = ""
    for line in prose.splitlines():
        s = line.strip()
        if s:
            last = s
    if not last or last.startswith(("#", "|", ">", "-", "*", "`")) or last.endswith(("`", ":")):
        return False
    if last[-1] in ".!?)]}\"'":
        return False
    return bool(_UNFINISHED_TAIL_RE.search(last))


def lfu_gaps(user_query, text):
    if not re.search(r"\blfu\b|least\s+frequently\s+used", (user_query or ""), re.IGNORECASE):
        return []
    low = (text or "").lower()
    need = {
        "key->node map (keyToNode)": (r"keytonode|key\s*to\s*node|key[-_\s]*map|map.*node"),
        "freq->list map (freqToList)": (r"freqtolist|freq\s*to\s*list|frequency\s*list|freq[-_\s]*map|buckets?\s+of\s+freq"),
        "minFreq tracking": (r"minfreq|min\s*freq|minimum\s+frequency"),
        "LRU tie-breaking within a frequency": (r"tie[- ]?break|least\s+recently|lru\b|oldest\s+within"),
    }
    return [label for label, pat in need.items() if not re.search(pat, low)]


def missing_why_o1(text):
    """True if O(1) is claimed in a Complexity section but never justified."""
    if not _O1_RE.search(text or ""):
        return False
    return not _WHY_RE.search(text or "")


def production_sections(user_query, text):
    """Return the production-mandatory sections that are absent (FAILURE 4).

    Only fires for production-grade requests. Each required section accepts
    reasonable header synonyms, so a well-structured DSA answer that already has
    Algorithm / Code / Complexity only needs to add Data Structures Used and
    Edge Cases."""
    if not _PROD_RE.search(user_query or ""):
        return []
    headers = _section_headers(text)
    missing = []
    for canonical, syns in _PROD_SECTIONS:
        if not any(_matches_section(h, syns) for h in headers):
            missing.append(canonical)
    return missing


def production_gaps(user_query, text):
    if not _PROD_RE.search(user_query or ""):
        return []
    low = (text or "").lower()
    gaps = []
    if not re.search(r"\bvalid\w*|\braise\b|\bthrow\b|\bif\s+.*(?:none|null|<\s*0|empty)|guard\b|sanitiz", low):
        gaps.append("input validation / guard clauses")
    if not re.search(r"\bclass\b|\bprivate\b|self\.|\bencapsulat", low):
        gaps.append("proper encapsulation (a class with private state)")
    if not re.search(r"\btest\b|\bassert\b|example\s+usage|>>>|unittest|pytest|__main__", low):
        gaps.append("a test example / usage demo")
    return gaps


# ── public API ───────────────────────────────────────────────────────────────
def check(user_query: str, response_text: str):
    """Deterministic output-quality gate. Return (ok: bool, reason: str)."""
    text = response_text or ""
    if not _is_attempt(user_query, text):
        return True, ""  # conceptual / no-code -> defer

    dup = duplicate_section(text)
    if dup:
        return False, (f"The '{dup}' section appears more than once. Each section (Problem "
                       "Understanding, Optimal Algorithm, Code, Approach, Complexity) must appear "
                       "EXACTLY once — merge the duplicates into a single clean section.")

    art = template_artifact(text)
    if art:
        return False, (f"The answer contains a leftover template artifact ('{art}'). Remove all "
                       "scaffolding/placeholder tokens and ship finished prose and code.")

    if duplicated_paragraph(text):
        return False, ("A paragraph is duplicated verbatim. Remove the repeated text — say each "
                       "point once.")

    if unfinished_sentence(text):
        return False, ("The explanation ends in an unfinished sentence. Complete every sentence "
                       "and finish the explanation.")

    gaps = lfu_gaps(user_query, text)
    if gaps:
        return False, ("An LFU cache solution MUST explain: " + ", ".join(gaps) +
                       ". Describe the key->node map, the freq->list map, how minFreq is "
                       "maintained, and the LRU tie-break within the minimum frequency.")

    if missing_why_o1(text):
        return False, ("The Complexity section claims O(1) but does not explain WHY. Justify it "
                       "(e.g., hash-map lookups + a doubly linked list give amortized O(1) per "
                       "operation), not just the Big-O symbol.")

    psections = production_sections(user_query, text)
    if psections:
        return False, ("This is a production-grade request, so the answer MUST include these "
                       "sections: " + ", ".join(psections) + ". Provide Data Structures Used, "
                       "Algorithm, Full Code, Complexity Proof, and Edge Cases.")

    pgaps = production_gaps(user_query, text)
    if pgaps:
        return False, ("This is a production-grade request, so the solution must include: " +
                       ", ".join(pgaps) + ". Provide a complete, encapsulated implementation with "
                       "validation and a test example.")

    return True, ""


def critique(user_query: str, response_text: str) -> dict:
    ok, reason = check(user_query, response_text)
    return {"verified": ok, "feedback": "" if ok else reason}


# ── cleanup (Phase 11, requirement 6) ────────────────────────────────────────
def _norm_header(line):
    return re.sub(r"[#*`:_]", "", line.strip()).strip().lower()


def _needs_cleanup(text: str) -> bool:
    """True only if there is a duplicate section, an artifact, or a repeated header.
    Guarantees cleanup() is a byte-for-byte no-op on already-clean responses."""
    if duplicate_section(text) or template_artifact(text):
        return True
    seen, prev = set(), None
    in_fence = False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            prev = None
            continue
        if in_fence or not s.startswith("#"):
            continue
        norm = _norm_header(line)
        if norm and (norm == prev or norm in seen):
            return True
        seen.add(norm)
        prev = norm
    return False


def cleanup(text: str) -> str:
    """Best-effort sanitizer applied before delivery: drop duplicate sections,
    collapse immediately-repeated headers, and strip inline template artifacts.
    Conservative — never touches fenced code and preserves the first occurrence.
    A no-op (returns the input unchanged) when there is nothing to fix."""
    if not text or not _needs_cleanup(text):
        return text
    src = text
    # 1. strip inline template artifacts outside code (line by line, code-aware)
    out_lines = []
    in_fence = False
    seen_headers = set()
    prev_header_norm = None
    skip_section = False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out_lines.append(line)
            prev_header_norm = None
            continue
        if in_fence:
            out_lines.append(line)
            continue
        is_header = stripped.startswith("#")
        if is_header:
            norm = _norm_header(line)
            # collapse an immediately repeated header and drop a duplicate section
            if norm and (norm == prev_header_norm or norm in seen_headers):
                skip_section = True
                prev_header_norm = norm
                continue
            skip_section = False
            seen_headers.add(norm)
            prev_header_norm = norm
            out_lines.append(line)
            continue
        if skip_section:
            # body of a duplicate section: drop until the next (new) header
            continue
        cleaned = _TEMPLATE_ARTIFACT_RE.sub("", line)
        out_lines.append(cleaned)
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip("\n") if result.strip() else text
