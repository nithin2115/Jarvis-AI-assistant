"""LFU Cache Critic (Phase 13).

Deterministic, no-LLM gate that validates LFU cache implementations. Runs
AFTER dsa_structure / dsa_output_quality and BEFORE the LLM critic so a
broken LFU answer is rejected with NO network call.

Gated: only fires when the user query mentions "lfu" or "least frequently
used" AND the response ships code (mirrors dsa_structure.is_solution_attempt).

Rejects if:
  1. Eviction uses list.head / list.tail / dummy / sentinel node instead of
     head.next / tail.prev (the correct O(1) DLL pattern).
  2. Missing LRU tie-break rule (least recently used within minFreq).
  3. Missing keyToNode map, freqToList map, or minFreq tracking.
  4. Missing O(1) proof covering: HashMap lookup, DLL insert, DLL remove,
     frequency update.
  5. Duplicate major sections (Problem Understanding, Optimal Algorithm, Code,
     Approach, Complexity, Edge Cases).
  6. Repeated template fragments.

Fail-safe: conceptual / non-LFU queries always pass. On exception, passes.
"""
import re
import logging

import dsa_structure as ds

logger = logging.getLogger(__name__)

_FENCE = ds._FENCE

# ── LFU query gate ───────────────────────────────────────────────────────────
_LFU_QUERY_RE = re.compile(r"\blfu\b|least\s+frequently\s+used", re.IGNORECASE)

# ── Eviction pattern detection ───────────────────────────────────────────────
# Bad: eviction uses list.head / list.tail / dummy / sentinel
_BAD_EVICT_RE = re.compile(
    r"\blist\.head\b|\blist\.tail\b"
    r"|\bdummy\b|\bsentinel\b",
    re.IGNORECASE,
)

# Good: eviction uses head.next / tail.prev
_GOOD_EVICT_RE = re.compile(
    r"\bhead\.next\b|\btail\.prev\b",
    re.IGNORECASE,
)

# ── Required LFU data structures ─────────────────────────────────────────────
_LFU_COMPONENTS = {
    "keyToNode map": re.compile(
        r"keytonode|key\s*to\s*node|key[-_\s]*map.*node|node\s*map|keymap",
        re.IGNORECASE,
    ),
    "freqToList map": re.compile(
        r"freqtolist|freq\s*to\s*list|frequency\s*list|freq[-_\s]*map"
        r"|buckets?\s+of\s+freq|freq.*dll|freq.*linked",
        re.IGNORECASE,
    ),
    "minFreq tracking": re.compile(
        r"minfreq|min\s*freq|minimum\s+frequency",
        re.IGNORECASE,
    ),
}

# ── LRU tie-break ────────────────────────────────────────────────────────────
_LRU_TIEBREAK_RE = re.compile(
    r"tie[- ]?break|least\s+recently\s+used|lru\b|oldest\s+within"
    r"|most\s+recently\s+used|evict.*oldest|remove.*oldest",
    re.IGNORECASE,
)

# ── O(1) proof components ────────────────────────────────────────────────────
_O1_PROOF_COMPONENTS = {
    "HashMap lookup": re.compile(
        r"hash\s*map|hashmap|hash\s*table|dict\b|map\b.*get|map\b.*put"
        r"|o\(1\).*lookup|lookup.*o\(1\)|constant.*lookup",
        re.IGNORECASE,
    ),
    "DLL insert": re.compile(
        r"dll\s+insert|insert.*o\(1\)|o\(1\).*insert"
        r"|doubly\s+linked\s+list.*insert|insert.*doubly"
        r"|add.*front|add.*head|prepend",
        re.IGNORECASE,
    ),
    "DLL remove": re.compile(
        r"dll\s+remove|remove.*o\(1\)|o\(1\).*remove"
        r"|doubly\s+linked\s+list.*remove|remove.*doubly"
        r"|delete.*node|unlink",
        re.IGNORECASE,
    ),
    "frequency update": re.compile(
        r"freq.*update|update.*freq|increment.*freq|freq.*increment"
        r"|freq\+\+|freq\s*\+=|frequency.*update|update.*frequency"
        r"|move.*freq|promote.*freq",
        re.IGNORECASE,
    ),
}

# ── Node must be a DLL node carrying these fields (O(1) LFU + LRU tie-break) ──
_NODE_FIELD_RES = {
    "key": re.compile(r"\bkey\b", re.IGNORECASE),
    "value": re.compile(r"\bval(?:ue)?\b", re.IGNORECASE),
    "freq": re.compile(r"\bfreq(?:uency)?\b", re.IGNORECASE),
    "prev": re.compile(r"\bprev(?:ious)?\b", re.IGNORECASE),
    "next": re.compile(r"\bnext\b", re.IGNORECASE),
}

# ── Structures that make LFU worse than O(1) (forbidden) ─────────────────────
_FORBIDDEN_STRUCT_RES = {
    "PriorityQueue / heap": re.compile(
        r"priority[\s_]?queue|priorityqueue|\bheapq\b|heappush|heappop|heapify",
        re.IGNORECASE,
    ),
    "TreeMap / sorted structure": re.compile(
        r"\btreemap\b|tree[\s_]?map|sorteddict|sortedcontainers|sorted[\s_]?list"
        r"|std::map\b",
        re.IGNORECASE,
    ),
}

# ── Scanning the frequency map for the minimum is O(n) — forbidden ────────────
_FREQ_SCAN_RE = re.compile(
    r"(?:\bmin\b|\bmax\b|\bsorted\b)\s*\(\s*(?:self\.)?\w*freq\w*"
    r"(?:\.keys\s*\(\s*\)|\.items\s*\(\s*\)|\.values\s*\(\s*\))?\s*\)",
    re.IGNORECASE,
)

# ── Deleting a frequency bucket from the freq map ────────────────────────────
_BUCKET_DELETE_RE = re.compile(
    r"del\s+[\w.]*freq\w*\s*\["
    r"|[\w.]*freq\w*\.(?:pop|erase|remove)\s*\(",
    re.IGNORECASE,
)

# ── An emptiness guard around a bucket deletion ──────────────────────────────
_EMPTY_GUARD_RE = re.compile(
    r"\.empty\s*\(\s*\)|\bis[\s_]?empty\b|\bisempty\b"
    r"|\blen\s*\([^)]*\)\s*==\s*0|\.size\s*\(\s*\)\s*==\s*0"
    r"|==\s*0\b|\bif\s+not\b|\bnot\s+\w*freq",
    re.IGNORECASE,
)

# ── Major sections for duplicate detection ───────────────────────────────────
_MAJOR_SECTIONS = (
    ("Problem Understanding", ("problem understanding", "problem statement")),
    ("Optimal Algorithm", ("optimal algorithm", "algorithm")),
    ("Code", ("code", "solution code", "full code", "implementation")),
    ("Approach", ("approach", "walkthrough", "intuition")),
    ("Complexity", ("complexity", "time complexity", "time and space complexity",
                    "time & space complexity", "complexity analysis")),
    ("Edge Cases", ("edge cases", "edge case analysis", "corner cases")),
)

# ── Template fragments ───────────────────────────────────────────────────────
_TEMPLATE_RE = re.compile(
    r"<\s*(?:approach|explanation|complexity|placeholder|your[\s_-]?\w+|insert[\s_-]?\w+)\s*>"
    r"|\{\{\s*[\w\s]+\s*\}\}|<<\s*[\w\s]+\s*>>"
    r"|\byour\s+(?:explanation|approach|analysis|code|answer|solution)\s+here\b"
    r"|\b(?:section|paragraph|step)\s+\d+\s+(?:goes\s+here|here)\b"
    r"|\bexplain\s+(?:the\s+)?(?:approach|algorithm|complexity|solution)\s+here\b"
    r"|\b(?:add|insert|describe|write)\s+(?:the\s+|your\s+)?\w+\s+here\b"
    r"|\[\s*(?:insert|your|todo|placeholder|fill[\s_-]?in|add\s+your)\b[^\]]*\]",
    re.IGNORECASE | re.MULTILINE,
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _strip_code(text):
    return _FENCE.sub("\n", text or "")


def _code_text(text):
    """Concatenate all fenced code blocks into one string."""
    return "\n".join(code for _, code in ds._code_blocks(text))


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


def _matches_section(h, syns):
    return any(h == s or h.startswith(s + " ") for s in syns)


def _is_lfu_query(user_query):
    return bool(_LFU_QUERY_RE.search(user_query or ""))


# ── Detectors ────────────────────────────────────────────────────────────────

def bad_eviction_pattern(text):
    """Return (bad_pattern, has_good_pattern) for eviction style check.

    bad_pattern is the first bad pattern found, or None.
    has_good_pattern is True if head.next / tail.prev is present.
    """
    code = _code_text(text)
    full = text or ""
    # Search in both code and prose (explanations may describe the pattern)
    combined = code + "\n" + _strip_code(full)
    bad_match = _BAD_EVICT_RE.search(combined)
    bad = bad_match.group(0) if bad_match else None
    good = bool(_GOOD_EVICT_RE.search(combined))
    return bad, good


def missing_lru_tiebreak(text):
    """True if LRU tie-break rule is not mentioned anywhere."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    return not _LRU_TIEBREAK_RE.search(combined)


def missing_lfu_components(text):
    """Return list of missing LFU component labels."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    return [label for label, pat in _LFU_COMPONENTS.items()
            if not pat.search(combined)]


def missing_o1_proof(text):
    """Return list of missing O(1) proof component labels."""
    # Search in prose (the Complexity/Approach section) and code comments
    prose = _strip_code(text)
    code = _code_text(text)
    combined = prose + "\n" + code
    return [label for label, pat in _O1_PROOF_COMPONENTS.items()
            if not pat.search(combined)]


def duplicate_major_section(text):
    """Return canonical name of a major section appearing 2+, else None."""
    headers = _section_headers(text)
    for canonical, syns in _MAJOR_SECTIONS:
        hits = sum(1 for h in headers if _matches_section(h, syns))
        if hits >= 2:
            return canonical
    return None


def template_fragment(text):
    """Return the first template fragment found in prose, else None."""
    m = _TEMPLATE_RE.search(_strip_code(text))
    if m:
        return m.group(0).strip()
    for _, code in ds._code_blocks(text):
        if not code.strip():
            return "empty code block"
    return None


def missing_node_fields(text):
    """Return the DLL node fields (key, value, freq, prev, next) that are absent."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    return [name for name, pat in _NODE_FIELD_RES.items() if not pat.search(combined)]


def forbidden_structure(text):
    """Return the label of a non-O(1) structure (heap / TreeMap), else None."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    for label, pat in _FORBIDDEN_STRUCT_RES.items():
        if pat.search(combined):
            return label
    return None


def frequency_scan(text):
    """True if the code scans the frequency map for the minimum (O(n))."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    return bool(_FREQ_SCAN_RE.search(combined))


def bucket_delete_without_guard(text):
    """True if a frequency bucket is deleted without an emptiness check."""
    combined = _code_text(text) + "\n" + _strip_code(text or "")
    if not _BUCKET_DELETE_RE.search(combined):
        return False
    return not _EMPTY_GUARD_RE.search(combined)


# ── Public API ───────────────────────────────────────────────────────────────

def check(user_query: str, response_text: str):
    """Deterministic LFU cache quality gate. Return (ok: bool, reason: str)."""
    try:
        if not _is_lfu_query(user_query):
            return True, ""
        text = response_text or ""
        if not ds.is_solution_attempt(user_query, text):
            return True, ""

        # 1. Eviction pattern check
        bad, good = bad_eviction_pattern(text)
        if bad and not good:
            return False, (
                f"LFU eviction uses '{bad}' (list.head/list.tail/dummy/sentinel). "
                "The correct O(1) DLL eviction pattern must use head.next and "
                "tail.prev to access the least recently used node in the minFreq "
                "list. Replace the sentinel/dummy approach with head.next / "
                "tail.prev traversal.")

        # 2. LRU tie-break
        if missing_lru_tiebreak(text):
            return False, (
                "Missing LRU tie-break rule. When multiple keys share the same "
                "minimum frequency, the LFU cache must evict the LEAST RECENTLY "
                "USED among them. Explain how the DLL within each frequency "
                "bucket maintains LRU order (head.next = oldest, tail.prev = newest).")

        # 3. Required LFU data structures
        missing = missing_lfu_components(text)
        if missing:
            return False, (
                "Missing required LFU data structure(s): " + ", ".join(missing) +
                ". An O(1) LFU cache requires: (1) a keyToNode map for O(1) key "
                "lookup, (2) a freqToList map mapping each frequency to a DLL of "
                "nodes at that frequency, and (3) minFreq tracking to find the "
                "minimum frequency in O(1).")

        # 4. O(1) proof
        missing_proof = missing_o1_proof(text)
        if missing_proof:
            return False, (
                "Missing O(1) proof for: " + ", ".join(missing_proof) +
                ". The Complexity section must justify O(1) for each operation: "
                "HashMap lookup (keyToNode), DLL insert (add to freq bucket), "
                "DLL remove (unlink from current bucket), and frequency update "
                "(move to next bucket, update minFreq).")

        # 4a. Node must carry the DLL fields (key, value, freq, prev, next).
        missing_fields = missing_node_fields(text)
        if missing_fields:
            return False, (
                "The LFU node is missing required field(s): " + ", ".join(missing_fields) +
                ". Each cache entry must be a doubly linked list node carrying key, value, "
                "freq, prev, and next so every frequency bucket is a DLL that supports O(1) "
                "insert/remove and preserves LRU order for the tie-break.")

        # 4b. Forbidden non-O(1) structures (heap / TreeMap / sorted containers).
        bad_struct = forbidden_structure(text)
        if bad_struct:
            return False, (
                f"An O(1) LFU cache must not use a {bad_struct}. A PriorityQueue/heap is "
                "O(log n) per operation and a TreeMap/sorted structure is O(log n) to find "
                "the minimum frequency. Use a keyToNode HashMap + freqToList of doubly linked "
                "lists + an incrementally maintained minFreq for true O(1).")

        # 4c. Scanning the frequency map for the minimum is O(n).
        if frequency_scan(text):
            return False, (
                "The solution scans the frequency map for the minimum (min/max/sorted over "
                "frequencies), which is O(n). Track minFreq incrementally instead: set it to 1 "
                "on insert and increase it only when the current minFreq bucket becomes empty.")

        # 4d. A frequency bucket may be deleted ONLY when it becomes empty.
        if bucket_delete_without_guard(text):
            return False, (
                "A frequency bucket is deleted without first checking that it is empty. Only "
                "remove a freqToList bucket when it becomes empty (and then update minFreq); "
                "deleting a non-empty bucket discards live cache entries.")

        # 5. Duplicate sections
        dup = duplicate_major_section(text)
        if dup:
            return False, (
                f"Duplicate major section '{dup}' detected. Each major section "
                "(Problem Understanding, Optimal Algorithm, Code, Approach, "
                "Complexity, Edge Cases) must appear exactly once.")

        # 6. Template fragments
        frag = template_fragment(text)
        if frag:
            return False, (
                f"Template fragment detected: '{frag}'. Remove all scaffolding "
                "and placeholder tokens — ship finished prose and code.")

        return True, ""
    except Exception as e:
        logger.warning(f"[LFU_CRITIC] fail-safe passthrough: {e}")
        return True, ""


def critique(user_query: str, response_text: str) -> dict:
    ok, reason = check(user_query, response_text)
    return {"verified": ok, "feedback": "" if ok else reason}
