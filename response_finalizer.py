"""ResponseFinalizer (Phase 1).

Unified pre-streaming finalizer. Runs AFTER generation, critic, and verifier
but BEFORE streaming to the user. It subsumes and extends
final_response_sanitizer (Phase 12) with:

  1. Deduplication of a broader set of canonical sections (keeping only the
     first occurrence of each duplicated section).
  2. Stripping of critic/verifier/regeneration/retry artifacts and partial
     generation fragments.
  3. Markdown structure validation (balanced fences, non-empty sections,
     orphan markdown).
  4. Code-fence validation (balanced fences, non-empty blocks, well-formed
     language labels).

Returns (ok: bool, reason: str, cleaned_text: str).
Fail-safe: on any exception, passes the response through unchanged.
"""
import re
import logging

import final_response_sanitizer as _san
import dsa_structure as ds

logger = logging.getLogger(__name__)

_FENCE = ds._FENCE

# ── Canonical sections that must appear at most once ─────────────────────────
# Order matters: duplicates are resolved by keeping the FIRST occurrence and
# dropping subsequent occurrences of the same canonical bucket.
_MAJOR_SECTIONS = _san._MAJOR_SECTIONS + (
    ("Requirements", ("requirements", "functional requirements",
                      "non-functional requirements", "non functional requirements")),
    ("Tradeoffs", ("tradeoffs", "trade-offs", "trade offs", "tradeoff")),
    ("Monitoring", ("monitoring", "observability", "metrics", "logging",
                      "alerting")),
    ("Cost Analysis", ("cost analysis", "cost", "pricing", "budget",
                        "cost considerations")),
)

# ── Text artifacts that must never reach the user ────────────────────────────
_ARTIFACT_RE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?\s*(?:"
    r"Critic(?:\s+Note|:\s*)?|"
    r"Verifier(?:\s+Feedback|:\s*)?|"
    r"Regeneration(?:\s+Note|:\s*)?|"
    r"Retry(?:\s+#?\d*|:\s*)?|"
    r"Draft(?:\s+#?\d*|:\s*)?|"
    r"Attempt(?:\s+#?\d*|:\s*)?|"
    r"Self[\s-]?Review(?:\s+Note|:\s*)?|"
    r"Internal[\s-]?Note(?:\s*:\s*)?|"
    r"Model[\s-]?Note(?:\s*:\s*)?|"
    r"Generation[\s-]?Note(?:\s*:\s*)?|"
    r"Correction[\s-]?Attempt(?:\s*:\s*)?|"
    r"Revision[\s-]?Note(?:\s*:\s*)?|"
    r"Re(?:try|draft|generate|vision)\s*(?:#?\d+)?"
    r")\s*(?:\*\*)?\s*(?:[:\-]|\n).*?$"
    r"|(?:^|\n)\s*>\s*(?:Critic|Verifier|Regeneration|Retry|Draft|Attempt).*",
    re.IGNORECASE | re.MULTILINE,
)

_PARTIAL_GENERATION_RE = re.compile(
    r"(?:^|\n)\s*(?:"
    r"\(continued\)|\(cont\.\)|\[continued\]|\[more\]|\[continues\]|"
    r"continued below|continued from above|generating[\s\.]{0,3}|"
    r"\.\.\.\s*(?:generating|thinking|processing|loading)|"
    r"as an AI.*(?:rephrase|ask again|try again)"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ── Markdown / code-fence validation ───────────────────────────────────────
_VALID_LANGS = frozenset({
    "python", "py", "java", "cpp", "c++", "c", "csharp", "cs", "dotnet",
    "javascript", "js", "typescript", "ts", "jsx", "tsx", "go", "golang",
    "rust", "ruby", "rb", "php", "swift", "kotlin", "scala", "r",
    "sql", "mysql", "postgres", "postgresql", "bash", "sh", "shell",
    "powershell", "ps1", "yaml", "yml", "json", "xml", "html", "css",
    "dockerfile", "makefile", "cmake", "toml", "ini", "config", "text",
    "diff", "patch", "markdown", "md", "",  # empty language is allowed
})


def _norm_header(line):
    return _san._norm_header(line)


def _section_headers_with_positions(text):
    """Return [(norm_header, line_index), ...] for ATX headers outside code."""
    return _san._header_positions(text)


def _matches_section(h, syns):
    return _san._matches_section(h, syns)


def _canonical_header(norm):
    """Return the canonical bucket name for a normalized header, or None."""
    for canonical, syns in _MAJOR_SECTIONS:
        if _matches_section(norm, syns):
            return canonical
    return None


# ── Deduplication ────────────────────────────────────────────────────────────

def deduplicate_sections(text):
    """Remove duplicate canonical sections, keeping only the first occurrence.

    Returns (cleaned_text, list_of_removed_canonical_names)."""
    if not (text or "").strip():
        return text, []
    lines = text.splitlines()
    positions = []
    in_fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and s.startswith("#"):
            positions.append((i, _norm_header(s)))

    if len(positions) < 2:
        return text, []

    # For each canonical bucket, keep the first position; drop the rest.
    seen = {}
    removed_lines = set()
    removed_names = []
    for idx, (line_i, norm) in enumerate(positions):
        canonical = _canonical_header(norm)
        if canonical is None:
            continue
        if canonical in seen:
            # Remove lines from this duplicate header up to (but not including)
            # the next header or EOF.
            start = line_i
            end = len(lines)
            if idx + 1 < len(positions):
                end = positions[idx + 1][0]
            for r in range(start, end):
                removed_lines.add(r)
            removed_names.append(canonical)
        else:
            seen[canonical] = line_i

    if not removed_lines:
        return text, []

    cleaned = "\n".join(lines[i] for i in range(len(lines)) if i not in removed_lines)
    # Collapse multiple consecutive blank lines to at most two.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.rstrip("\n") + "\n", removed_names


# ── Artifact stripping ───────────────────────────────────────────────────────

def strip_artifacts(text):
    """Remove critic/verifier/regeneration/retry/partial-generation artifacts.

    Returns the original text unchanged if no artifacts were found."""
    if not (text or "").strip():
        return text
    original = text
    text = _ARTIFACT_RE.sub("", text)
    text = _PARTIAL_GENERATION_RE.sub("", text)
    # Remove stray lines that are only artifacts (e.g. "Draft 2:")
    text = re.sub(r"(?:^|\n)\s*(?:Draft|Retry|Attempt)\s*#?\d*\s*[:\-]?\s*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    if text == original:
        return original
    # Collapse blank lines and trim trailing whitespace only when changed
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


# ── Markdown validation ────────────────────────────────────────────────────

def _validate_markdown(text):
    """Return (ok, reason) for markdown structural checks."""
    if not (text or "").strip():
        return True, ""

    # Balanced code fences
    fence_count = sum(1 for line in text.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 != 0:
        return False, "Unbalanced code fences (odd number of ``` markers)."

    # Orphan bold labels (prose only)
    prose = _san._strip_code(text)
    if _san._ORPHAN_BOLD_RE.search(prose):
        return False, "Orphan markdown bold label detected (missing closing **)."

    # No partial sections (header with no body, excluding code-only sections)
    partial = _san.template_fragment(text)
    if partial and partial.startswith("partial section"):
        return False, f"Partial section detected: {partial}"

    # No empty fenced code blocks
    for _, code in ds._code_blocks(text):
        if not code.strip():
            return False, "Empty fenced code block detected."

    return True, ""


# ── Code-fence validation ───────────────────────────────────────────────────

def _validate_code_fences(text):
    """Return (ok, reason) for fenced code block quality checks."""
    if not (text or "").strip():
        return True, ""

    # Balanced fences
    fences = []
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s.startswith("```"):
            if in_fence:
                in_fence = False
            else:
                lang = s[3:].strip().split()[0].lower() if len(s) > 3 else ""
                fences.append((i, lang))
                in_fence = True
    if in_fence:
        return False, "Unclosed fenced code block at end of response."

    # Validate language labels
    for line_no, lang in fences:
        if lang and lang not in _VALID_LANGS:
            return False, f"Invalid code fence language label '{lang}' at line {line_no}."

    # Non-empty blocks (already checked in markdown validation, but be explicit)
    for _, code in ds._code_blocks(text):
        if not code.strip():
            return False, "Empty fenced code block detected."

    return True, ""


# ── Public API ───────────────────────────────────────────────────────────────

def finalize(agent_type: str, user_query: str, response_text: str):
    """Run the ResponseFinalizer.

    Returns (ok: bool, reason: str, cleaned_text: str).
    - Auto-cleans duplicate sections and artifacts (does not reject on its own).
    - Rejects if markdown or code-fence corruption remains after cleanup.
    - Delegates to final_response_sanitizer for remaining checks.
    - Fail-safe on exception: returns (True, "", response_text).
    """
    try:
        if response_text is None:
            return True, "", response_text
        text = response_text
        if not text.strip():
            return True, "", text

        # Phase 1: deduplicate canonical sections (keep first occurrence)
        cleaned, removed = deduplicate_sections(text)
        if removed:
            logger.info(f"[RESPONSE_FINALIZER] deduplicated sections: {removed}")
            text = cleaned

        # Phase 1: strip critic/verifier/regeneration artifacts
        stripped = strip_artifacts(text)
        if stripped != text:
            logger.info("[RESPONSE_FINALIZER] stripped response artifacts")
            text = stripped

        # Phase 1: validate markdown structure and code fences
        ok, reason = _validate_markdown(text)
        if not ok:
            return False, f"Response finalizer rejected: {reason}", text

        ok, reason = _validate_code_fences(text)
        if not ok:
            return False, f"Response finalizer rejected: {reason}", text

        # Phase 12 sanitizer: remaining checks (duplicate headers, merge artifacts,
        # repeated paragraphs/code blocks, DSA order, template fragments, etc.)
        ok, reason, cleaned = _san.sanitize(agent_type, user_query, text)
        if cleaned != text:
            text = cleaned
        if not ok:
            return False, reason, text

        return True, "", text
    except Exception as e:
        logger.warning(f"[RESPONSE_FINALIZER] fail-safe passthrough: {e}")
        return True, "", response_text


def critique(agent_type: str, user_query: str, response_text: str) -> dict:
    """Convenience wrapper returning {'verified': bool, 'feedback': str}."""
    ok, reason, _ = finalize(agent_type, user_query, response_text)
    return {"verified": ok, "feedback": "" if ok else reason}
