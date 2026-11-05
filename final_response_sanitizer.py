"""FINAL_RESPONSE_SANITIZER (Phase 12).

Runs AFTER generation, critic, and verifier but BEFORE streaming to the user.
Enforces strict quality checks and performs automatic cleanup so the final
output is polished and correct.

Detection (reject if found, return reason for regeneration):
  1. Duplicate major sections (Problem Understanding, Optimal Algorithm, Code,
     Approach, Complexity, Edge Cases).
  2. Same header appears more than once (any ATX header, not just canonical).
  3. Template fragments: orphan markdown (**Word with no closing), unfinished
     bullets (a list item that trails off), partial sections (header with no
     body), and the existing template-artifact patterns.
  4. Repeated paragraphs using similarity matching (>=80% word overlap).
  5. Repeated code blocks (identical or near-identical fenced blocks).
  6. Generator merge artifacts: a sequence of section headers appearing twice
     (e.g. Complexity -> Optimal Algorithm -> Code repeated).
  7. For DSA: exact section order — Problem Understanding, Optimal Algorithm,
     Full Code, Approach, Complexity (in that order).

Cleanup (auto-fix, does not reject):
  8. Auto-remove duplicated trailing sections if identical to an earlier section.

The sanitizer is FAIL-SAFE: if any detector throws, it passes the response
through unchanged so a correct answer is never blocked by a bug.
"""
import re
import logging

import dsa_structure as ds

logger = logging.getLogger(__name__)

_FENCE = ds._FENCE

# ── Major sections that must appear at most once ─────────────────────────────
_MAJOR_SECTIONS = (
    ("Problem Understanding", ("problem understanding", "problem statement")),
    ("Optimal Algorithm", ("optimal algorithm", "algorithm")),
    ("Code", ("code", "solution code", "full code", "implementation")),
    ("Approach", ("approach", "walkthrough", "intuition")),
    ("Complexity", ("complexity", "time complexity", "time and space complexity",
                    "time & space complexity", "complexity analysis")),
    ("Edge Cases", ("edge cases", "edge case analysis", "corner cases")),
)

# ── Required DSA section order ───────────────────────────────────────────────
_DSA_ORDER = (
    ("Problem Understanding", ("problem understanding", "problem statement")),
    ("Optimal Algorithm", ("optimal algorithm", "algorithm")),
    ("Full Code", ("full code", "code", "solution code", "implementation")),
    ("Approach", ("approach", "walkthrough", "intuition")),
    ("Complexity", ("complexity", "time complexity", "time and space complexity",
                    "time & space complexity", "complexity analysis")),
)

# ── Template artifact patterns (scanned outside code only) ───────────────────
_TEMPLATE_RE = re.compile(
    r"<\s*(?:approach|explanation|complexity|placeholder|your[\s_-]?\w+|insert[\s_-]?\w+)\s*>"
    r"|\{\{\s*[\w\s]+\s*\}\}|<<\s*[\w\s]+\s*>>"
    r"|\byour\s+(?:explanation|approach|analysis|code|answer|solution)\s+here\b"
    r"|\b(?:section|paragraph|step)\s+\d+\s+(?:goes\s+here|here)\b"
    r"|\bexplain\s+(?:the\s+)?(?:approach|algorithm|complexity|solution)\s+here\b"
    r"|\b(?:add|insert|describe|write)\s+(?:the\s+|your\s+)?\w+\s+here\b"
    r"|\*\*(?:Time|Space|Time\s+and\s+Space|Time\s+&\s+Space)\s+Complexity\b[^*]*$"  # orphan bold label
    r"|\[\s*(?:insert|your|todo|placeholder|fill[\s_-]?in|add\s+your)\b[^\]]*\]",
    re.IGNORECASE | re.MULTILINE,
)

# Orphan markdown: a bold opener with no closing ** on the same line
_ORPHAN_BOLD_RE = re.compile(
    r"(?<!\*)\*\*[^*\n]{2,80}$(?!\s*\*\*)",
    re.MULTILINE,
)

# Unfinished bullet: a list item (- or *) whose text trails off
_UNFINISHED_BULLET_RE = re.compile(
    r"^\s*[-*]\s+.{2,200}?\s(?:and|or|the|a|to|of|for|with|by|which|that|this|we|is|are|will|using|because|since)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _strip_code(text):
    return _FENCE.sub("\n", text or "")


def _section_headers(text):
    """Normalized ATX (#-prefixed) headers outside code fences."""
    out, in_fence = [], False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and s.startswith("#"):
            out.append(re.sub(r"[#*`:_]", "", s).strip().lower())
    return out


def _header_positions(text):
    """Return [(norm_header, line_index), ...] for ATX headers outside code."""
    out, in_fence = [], False
    for i, line in enumerate((text or "").splitlines()):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and s.startswith("#"):
            out.append((re.sub(r"[#*`:_]", "", s).strip().lower(), i))
    return out


def _matches_section(h, syns):
    return any(h == s or h.startswith(s + " ") for s in syns)


def _norm_header(line):
    return re.sub(r"[#*`:_]", "", line.strip()).strip().lower()


# ── Detectors ────────────────────────────────────────────────────────────────

def duplicate_major_section(text):
    """Return canonical name of a major section appearing 2+, else None."""
    headers = _section_headers(text)
    for canonical, syns in _MAJOR_SECTIONS:
        hits = sum(1 for h in headers if _matches_section(h, syns))
        if hits >= 2:
            return canonical
    return None


def repeated_header(text):
    """Return the header text that appears 2+ times (any ATX header), else None."""
    headers = _section_headers(text)
    seen = {}
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        if seen[h] >= 2:
            return h
    return None


def template_fragment(text):
    """Return a description of the first template fragment found, else None."""
    prose = _strip_code(text)
    m = _TEMPLATE_RE.search(prose)
    if m:
        return m.group(0).strip()
    # orphan bold label (e.g. "**Time Complexity" with no closing **)
    m2 = _ORPHAN_BOLD_RE.search(prose)
    if m2:
        return f"orphan markdown: {m2.group(0).strip()}"
    # unfinished bullet
    m3 = _UNFINISHED_BULLET_RE.search(prose)
    if m3:
        return f"unfinished bullet: {m3.group(0).strip()}"
    # partial section: ATX header followed by only blank lines until the next
    # header/EOF. A code block counts as body, so we track fence state while
    # scanning forward.
    lines = (text or "").splitlines()
    in_fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s.startswith("#"):
            continue
        # check if there's any non-empty, non-header body before the next header/EOF
        has_body = False
        scan_in_fence = False
        for j in range(i + 1, len(lines)):
            ls = lines[j].strip()
            if ls.startswith("```"):
                scan_in_fence = not scan_in_fence
                has_body = True  # a code block is body
                break
            if scan_in_fence:
                has_body = True
                break
            if ls.startswith("#"):
                break
            if ls:
                has_body = True
                break
        if not has_body:
            return f"partial section: {s} has no body"
    # empty fenced code block
    for _, code in ds._code_blocks(text):
        if not code.strip():
            return "empty code block"
    return None


def _word_set(s):
    return set(re.findall(r"\w+", s.lower()))


def _similarity(a, b):
    """Jaccard word-overlap similarity (0..1)."""
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def repeated_paragraph(text, min_words=8, threshold=0.8):
    """Return True if two prose paragraphs are verbatim or >=threshold similar.

    Strips leading header lines from each block so a paragraph under a header
    is still compared against paragraphs under other headers."""
    blocks = []
    for block in re.split(r"\n\s*\n", _strip_code(text)):
        s = block.strip()
        if not s:
            continue
        # Strip leading header lines so body text under a header is checked
        lines = s.splitlines()
        while lines and lines[0].strip().startswith("#"):
            lines.pop(0)
        s = "\n".join(lines).strip()
        if not s or s.startswith(("|", ">", "-", "*", "`")):
            continue
        if len(s.split()) < min_words:
            continue
        norm = re.sub(r"\s+", " ", s).lower()
        blocks.append((norm, s))
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            if blocks[i][0] == blocks[j][0]:
                return True
            if _similarity(blocks[i][0], blocks[j][0]) >= threshold:
                return True
    return False


def repeated_code_block(text):
    """Return True if two fenced code blocks are identical (after stripping)."""
    seen = set()
    for _, code in ds._code_blocks(text):
        norm = code.strip()
        if not norm:
            continue
        if norm in seen:
            return True
        seen.add(norm)
    return False


def merge_artifact(text):
    """Detect a repeated sequence of section headers (generator merge artifact).

    Returns a description string or None.
    Looks for a sub-sequence of >=2 consecutive headers that appears twice.
    """
    positions = _header_positions(text)
    headers = [h for h, _ in positions]
    if len(headers) < 4:
        return None
    # Try sub-sequences of length 2..4
    for seq_len in range(2, min(5, len(headers) // 2 + 1)):
        for i in range(len(headers) - seq_len):
            seq = tuple(headers[i:i + seq_len])
            for j in range(i + seq_len, len(headers) - seq_len + 1):
                if tuple(headers[j:j + seq_len]) == seq:
                    return f"repeated section sequence: {' -> '.join(seq)}"
    return None


def dsa_section_order(text):
    """Return (ok, reason) for DSA section order enforcement.

    Required order: Problem Understanding, Optimal Algorithm, Full Code,
    Approach, Complexity. Returns (True, "") if order is correct or sections
    are missing (missing sections are handled by dsa_structure, not here).
    """
    positions = _header_positions(text)
    headers = [h for h, _ in positions]

    # Map each required section to its first occurrence index
    section_indices = {}
    for canonical, syns in _DSA_ORDER:
        for idx, h in enumerate(headers):
            if _matches_section(h, syns):
                section_indices[canonical] = idx
                break

    # Only enforce order among sections that ARE present
    present = [(canonical, section_indices[canonical])
               for canonical, _ in _DSA_ORDER
               if canonical in section_indices]

    for i in range(len(present) - 1):
        if present[i][1] > present[i + 1][1]:
            return (False,
                    f"DSA section order violation: '{present[i][0]}' appears after "
                    f"'{present[i + 1][0]}'. Required order: "
                    + ", ".join(c for c, _ in _DSA_ORDER))
    return True, ""


# ── Cleanup: auto-remove duplicated trailing sections ────────────────────────

def _extract_section(text, start_idx, end_idx):
    """Extract lines [start_idx, end_idx) from text."""
    lines = text.splitlines()
    return "\n".join(lines[start_idx:end_idx]).strip()


def remove_duplicate_trailing_sections(text):
    """If the trailing section(s) duplicate an earlier section, remove them.

    Compares the full body (header + content) of the last section against all
    earlier sections. If an exact match is found, the trailing duplicate is
    removed. Repeats until no more trailing duplicates exist.
    """
    if not text:
        return text
    lines = text.splitlines()
    positions = []
    in_fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and s.startswith("#"):
            positions.append(i)
    if len(positions) < 2:
        return text

    removed_any = False
    changed = True
    while changed and len(positions) >= 2:
        changed = False
        last_start = positions[-1]
        last_end = len(lines)
        last_section = "\n".join(lines[last_start:last_end]).strip()

        for i in range(len(positions) - 1):
            sec_start = positions[i]
            sec_end = positions[i + 1] if i + 1 < len(positions) else len(lines)
            earlier_section = "\n".join(lines[sec_start:sec_end]).strip()
            if earlier_section == last_section:
                # Remove the trailing duplicate
                lines = lines[:last_start]
                # Strip trailing blank lines
                while lines and not lines[-1].strip():
                    lines.pop()
                # Recompute positions
                positions = []
                in_fence = False
                for j, line in enumerate(lines):
                    s = line.strip()
                    if s.startswith("```"):
                        in_fence = not in_fence
                        continue
                    if not in_fence and s.startswith("#"):
                        positions.append(j)
                changed = True
                removed_any = True
                break

    if not removed_any:
        return text
    result = "\n".join(lines)
    return result.strip("\n") if result.strip() else text


# ── Main API ─────────────────────────────────────────────────────────────────

def sanitize(agent_type, user_query, response_text):
    """Run the final sanitizer.

    Returns (ok: bool, reason: str, cleaned_text: str).
    - If ok is False, the response should be rejected for regeneration.
    - cleaned_text is the auto-cleaned version (trailing duplicates removed).
    - Fail-safe: on any exception, returns (True, "", response_text).
    """
    try:
        text = response_text or ""
        if not text.strip():
            return True, "", text

        # ── Auto-cleanup first (non-rejecting) ──
        cleaned = remove_duplicate_trailing_sections(text)
        if cleaned != text:
            logger.info("[SANITIZER] removed duplicate trailing section(s)")
            text = cleaned

        # ── Detection (rejecting) ──
        # merge_artifact first — it's a more specific diagnosis than the
        # generic duplicate_major_section / repeated_header checks.
        artifact = merge_artifact(text)
        if artifact:
            return False, (
                f"Generator merge artifact detected: {artifact}. "
                "The response appears to be a merged/duplicated generation."), text

        dup = duplicate_major_section(text)
        if dup:
            return False, (
                f"Duplicate major section '{dup}' detected. Each major section "
                "(Problem Understanding, Optimal Algorithm, Code, Approach, "
                "Complexity, Edge Cases) must appear exactly once."), text

        rh = repeated_header(text)
        if rh:
            return False, (
                f"Repeated header '{rh}' detected. Each section header must "
                "appear only once."), text

        frag = template_fragment(text)
        if frag:
            return False, (
                f"Template fragment detected: {frag}. Remove all scaffolding, "
                "orphan markdown, unfinished bullets, and empty sections."), text

        if repeated_paragraph(text):
            return False, (
                "Repeated paragraph detected (verbatim or highly similar). "
                "Remove duplicated text — say each point once."), text

        if repeated_code_block(text):
            return False, (
                "Repeated code block detected. Remove the duplicate code block."), text

        # DSA-specific: exact section order
        if agent_type == "DSA_AGENT":
            ok, reason = dsa_section_order(text)
            if not ok:
                return False, reason, text

        return True, "", text
    except Exception as e:
        logger.warning(f"[SANITIZER] fail-safe passthrough: {e}")
        return True, "", response_text
