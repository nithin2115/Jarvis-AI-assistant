"""
JARVIS Tavily Search — Real-Time Internet Awareness
════════════════════════════════════════════════════
Provides live internet search to eliminate outdated/offline responses.

Components:
  • is_realtime_query()  — detects queries needing live data
  • search_live()        — fetches + parses Tavily results
  • _RealtimeCache       — TTL-based dedup cache for search results

Does NOT replace the AI provider chain — enriches context sent to
Gemini → Groq → OpenRouter.
"""

import hashlib
import logging
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

import httpx

import jarvis_config as config

logger = logging.getLogger("jarvis.search")

# ══════════════════════════════════════════════════════════════════════════════
#  REAL-TIME QUERY DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

# Patterns that signal the user wants current/live information
_RT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # ── Time-sensitive keywords ────────────────────────────────────────────────
    (re.compile(
        r"\b(latest|current|recent|newest|today'?s?|tonight|this\s+week|this\s+month"
        r"|this\s+year|right\s+now|breaking|live|happening\s+now|just\s+happened"
        r"|trending|viral|update|updates|updated|real[\s-]?time)\b", re.I),
     "time_sensitive"),

    # ── News & events ─────────────────────────────────────────────────────────
    (re.compile(
        r"\b(news|headlines|announcement|press\s+release|event|events"
        r"|election|politics|government|crisis|war|conflict"
        r"|disaster|earthquake|flood|hurricane|storm)\b", re.I),
     "news"),

    # ── Weather ───────────────────────────────────────────────────────────────
    (re.compile(
        r"\b(weather|temperature|forecast|rain|snow|humidity|wind\s+speed"
        r"|climate\s+today|heat\s*wave|cold\s*wave|storm\s+warning)\b", re.I),
     "weather"),

    # ── Sports ────────────────────────────────────────────────────────────────
    (re.compile(
        r"\b(score|scores|match|game\s+result|tournament|championship"
        r"|world\s+cup|ipl|premier\s+league|nba|nfl|cricket|football\s+score"
        r"|who\s+won|standings|fixtures|playoffs)\b", re.I),
     "sports"),

    # ── Finance / stocks ──────────────────────────────────────────────────────
    (re.compile(
        r"\b(stock|stocks|share\s+price|market|nasdaq|s&p|dow\s+jones|nifty|sensex"
        r"|crypto|bitcoin|ethereum|btc|eth|forex|exchange\s+rate"
        r"|gold\s+price|oil\s+price|trading)\b", re.I),
     "finance"),

    # ── Technology / releases ─────────────────────────────────────────────────
    (re.compile(
        r"\b(release|released|launched|announced|unveiled|new\s+version"
        r"|patch\s+notes|changelog|beta|alpha|preview|roadmap"
        r"|tech\s+news|product\s+launch|keynote)\b", re.I),
     "tech_release"),

    # ── People / celebrity / company ──────────────────────────────────────────
    (re.compile(
        r"\b(who\s+is\s+the\s+current|who\s+is\s+now|new\s+ceo|current\s+president"
        r"|current\s+pm|prime\s+minister|president\s+of)\b", re.I),
     "people"),

    # ── Explicit search intent ────────────────────────────────────────────────
    (re.compile(
        r"\b(search\s+for|look\s+up|find\s+me|google|search\s+the\s+web"
        r"|search\s+online|browse\s+for|check\s+online)\b", re.I),
     "explicit_search"),

    # ── Prices / availability ─────────────────────────────────────────────────
    (re.compile(
        r"\b(price\s+of|how\s+much\s+is|how\s+much\s+does|cost\s+of"
        r"|buy|purchase|available|in\s+stock|discount|deal|offer|sale)\b", re.I),
     "prices"),
]

# Queries that should NEVER trigger a live search (save API calls)
_SKIP_PATTERNS = re.compile(
    r"^("
    r"(hi|hello|hey|bye|goodbye|thanks?|thank\s+you|good\s+(morning|evening|night))"
    r"|how\s+are\s+you"
    r"|what\s+is\s+your\s+name"
    r"|who\s+are\s+you"
    r"|tell\s+me\s+a\s+joke"
    r"|motivate\s+me"
    r"|i('?m|\s+am)\s+(tired|bored|happy|sad|stressed|excited)"
    r")(\s|[?.!,])*$",
    re.I,
)

# Coding / explanation questions — handled well by the LLM alone
_CODE_SKIP = re.compile(
    r"\b(explain|define|definition|what\s+is\s+a|what\s+are|difference\s+between"
    r"|how\s+does\s+.+\s+work|how\s+to\s+code|write\s+a\s+(program|function|script|code)"
    r"|syntax|algorithm|data\s+structure|loop|function|class|variable"
    r"|compile|debug|error|exception|import|install|pip|npm)\b",
    re.I,
)


def is_realtime_query(text: str) -> Tuple[bool, str]:
    """
    Determine if a query requires real-time internet information.

    Returns:
        (needs_live: bool, category: str)
        category is one of: time_sensitive, news, weather, sports, finance,
        tech_release, people, explicit_search, prices, or "none"
    """
    clean = text.strip()
    if not clean or len(clean) < 4:
        return False, "none"

    # Fast skip for daily-talk / greeting / basic queries
    if _SKIP_PATTERNS.match(clean):
        logger.debug("[SEARCH] Skipped (daily talk pattern): '%s'", clean[:50])
        return False, "none"

    # Skip pure coding / explanation queries (LLM handles these fine)
    word_count = len(clean.split())
    if word_count <= 8 and _CODE_SKIP.search(clean) and not any(
        p.search(clean) for p, _ in _RT_PATTERNS[:2]  # unless also time-sensitive
    ):
        logger.debug("[SEARCH] Skipped (coding/explanation): '%s'", clean[:50])
        return False, "none"

    # Check against real-time patterns
    for pattern, category in _RT_PATTERNS:
        if pattern.search(clean):
            logger.info("[SEARCH] Real-time detected [%s]: '%s'", category, clean[:60])
            return True, category

    return False, "none"


# ══════════════════════════════════════════════════════════════════════════════
#  TTL CACHE FOR SEARCH RESULTS
# ══════════════════════════════════════════════════════════════════════════════

class _RealtimeCache:
    """Thread-safe TTL cache for Tavily search results."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 50):
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, str]] = {}  # key → (timestamp, result)
        self._ttl = ttl_seconds
        self._max = max_entries

    @staticmethod
    def _key(query: str) -> str:
        """Normalise query to a cache key."""
        normalised = re.sub(r"\s+", " ", query.lower().strip())
        return hashlib.md5(normalised.encode()).hexdigest()

    def get(self, query: str) -> Optional[str]:
        key = self._key(query)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, result = entry
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            return result

    def set(self, query: str, result: str):
        key = self._key(query)
        with self._lock:
            self._store[key] = (time.time(), result)
            # Evict oldest if over capacity
            if len(self._store) > self._max:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._store), "ttl_seconds": self._ttl}


_search_cache = _RealtimeCache(ttl_seconds=300, max_entries=50)


# ══════════════════════════════════════════════════════════════════════════════
#  TAVILY SEARCH CLIENT
# ══════════════════════════════════════════════════════════════════════════════

_TAVILY_API_URL = "https://api.tavily.com/search"


def _build_search_context(results: List[dict]) -> str:
    """
    Parse Tavily results into a clean, concise context paragraph
    suitable for injection into the AI system prompt.
    """
    if not results:
        return ""

    parts = []
    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "").strip()
        content = r.get("content", "").strip()
        url = r.get("url", "")

        if not content:
            continue

        # Truncate individual results to keep context manageable
        if len(content) > 400:
            content = content[:400].rsplit(" ", 1)[0] + "…"

        entry = f"[{i}] {title}: {content}"
        if url:
            entry += f" (Source: {url})"
        parts.append(entry)

    if not parts:
        return ""

    return (
        "=== LIVE INTERNET SEARCH RESULTS (use this information to answer) ===\n"
        + "\n".join(parts)
        + "\n=== END OF SEARCH RESULTS ==="
    )


def search_live(query: str, max_retries: int = 1) -> Optional[str]:
    """
    Search the internet via Tavily API and return formatted context.

    Returns:
        Formatted context string ready for injection into AI prompt,
        or None if search failed or no results found.
    """
    if not config.is_tavily_ready():
        logger.warning("[SEARCH] Tavily API key not configured")
        return None

    # Check cache first
    cached = _search_cache.get(query)
    if cached:
        logger.info("[SEARCH] Cache hit for: '%s'", query[:50])
        return cached

    t_start = time.time()
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "[SEARCH] Tavily search (attempt %d): '%s'",
                attempt + 1, query[:60],
            )

            response = httpx.post(
                _TAVILY_API_URL,
                json={
                    "api_key": config.TAVILY_API_KEY,
                    "query": query,
                    "search_depth": config.TAVILY_SEARCH_DEPTH,
                    "max_results": config.TAVILY_MAX_RESULTS,
                    "include_answer": True,
                    "include_raw_content": False,
                },
                timeout=httpx.Timeout(8.0, connect=4.0),
            )
            response.raise_for_status()
            data = response.json()

            # Extract results
            results = data.get("results", [])
            answer = data.get("answer", "")

            # Build context from results
            context = _build_search_context(results)

            # Prepend Tavily's built-in answer if available
            if answer and answer.strip():
                context = f"Quick Answer: {answer.strip()}\n\n{context}"

            if context.strip():
                elapsed = time.time() - t_start
                logger.info(
                    "[SEARCH] ✓ Tavily returned %d results in %.2fs",
                    len(results), elapsed,
                )
                # Cache the result
                _search_cache.set(query, context)
                return context
            else:
                logger.warning("[SEARCH] Tavily returned empty results")
                return None

        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
            logger.warning("[SEARCH] Tavily timeout (attempt %d): %s", attempt + 1, e)
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e}"
            logger.warning("[SEARCH] Tavily HTTP error (attempt %d): %s", attempt + 1, e)
            # Don't retry on auth errors
            if e.response.status_code in (401, 403):
                break
        except Exception as e:
            last_error = str(e)
            logger.warning("[SEARCH] Tavily error (attempt %d): %s", attempt + 1, e)

        # Brief pause before retry
        if attempt < max_retries:
            time.sleep(0.5)

    elapsed = time.time() - t_start
    logger.error("[SEARCH] ✗ Tavily failed after %.2fs: %s", elapsed, last_error)
    return None


def get_search_cache_stats() -> dict:
    """Return current search cache statistics."""
    return _search_cache.stats()
