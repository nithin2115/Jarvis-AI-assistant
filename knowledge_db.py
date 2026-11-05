"""
JARVIS Knowledge DB
Semantic search over Q&A knowledge using ChromaDB + sentence-transformers.
Replaces keyword matching with meaning-based intent detection.

Flow:
  1. Auto-generate  data/knowledge/jarvis_knowledge.json  from local_talk data
  2. Embed questions with all-MiniLM-L6-v2
  3. Store in persistent ChromaDB collection  "jarvis_knowledge"
  4. query(text) → (answer, score) if cosine similarity >= SIM_THRESHOLD else (None, None)
"""

import json
import logging
import random
import re
from pathlib import Path

logger = logging.getLogger("jarvis.knowledge")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
KNOWLEDGE_FILE = BASE_DIR / "data" / "knowledge" / "jarvis_knowledge.json"
AI_ML_FILE     = BASE_DIR / "data" / "knowledge" / "ai_ml_dataset.json"
CHROMA_DIR     = BASE_DIR / "data" / "chroma_db"
COLLECTION     = "jarvis_knowledge"
MODEL_NAME     = "all-MiniLM-L6-v2"
SIM_THRESHOLD  = 0.55   # minimum cosine similarity to count as a confident match

# ── Singletons ────────────────────────────────────────────────────────────────
_model      = None
_chroma     = None
_collection = None
_ready      = False   # True once init() completes successfully


# ── Embedding model ───────────────────────────────────────────────────────────

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[KNOWLEDGE] Loading sentence-transformer: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("[KNOWLEDGE] Embedding model ready")
    return _model


def _embed(texts: list) -> list:
    """Return list-of-lists (float) embeddings for a batch of texts."""
    vecs = _get_model().encode(texts, batch_size=64, show_progress_bar=False)
    # encode() returns numpy ndarray; convert to plain Python lists for ChromaDB
    return vecs.tolist()


# ── ChromaDB collection ───────────────────────────────────────────────────────

def _get_col():
    global _chroma, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma     = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _chroma.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"},   # cosine distance in [0,1] for unit vectors
        )
        logger.info("[KNOWLEDGE] ChromaDB collection ready (%d entries)", _collection.count())
    except Exception as e:
        logger.error("[KNOWLEDGE] ChromaDB init error: %s", e)
        raise
    return _collection


# ── JSON knowledge builder ────────────────────────────────────────────────────

def _build_json() -> list:
    """
    Auto-generate jarvis_knowledge.json from local_talk.INTENT_KEYWORDS + RESPONSES.
    One entry per (keyword, cycling_response) pair → rich semantic coverage.
    """
    from local_talk import RESPONSES, INTENT_KEYWORDS   # noqa: local import

    entries = []
    for intent, keywords in INTENT_KEYWORDS.items():
        responses = RESPONSES.get(intent, [])
        if not responses:
            continue
        for ki, kw in enumerate(keywords):
            entries.append({
                "id":       f"{intent}_{ki}",
                "question": kw,
                "answer":   responses[ki % len(responses)],
                "intent":   intent,
            })

    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    logger.info("[KNOWLEDGE] Generated %d entries → %s", len(entries), KNOWLEDGE_FILE)
    return entries


def _load_knowledge() -> list:
    if not KNOWLEDGE_FILE.exists():
        logger.info("[KNOWLEDGE] No JSON file found — generating from local_talk…")
        return _build_json()
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info("[KNOWLEDGE] Loaded %d entries from %s", len(data), KNOWLEDGE_FILE)
    return data


# ── Ingestion ─────────────────────────────────────────────────────────────────

def _load_ai_ml() -> list:
    """Load AI/ML Q&A dataset and assign stable IDs with 'aiml_' prefix."""
    if not AI_ML_FILE.exists():
        logger.debug("[KNOWLEDGE] ai_ml_dataset.json not found — skipping")
        return []
    with open(AI_ML_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = []
    for i, item in enumerate(raw):
        kw = item.get("keywords", [])
        entries.append({
            "id":       f"aiml_{i}",
            "question": item["question"],
            "answer":   item["answer"],
            "intent":   "ai_ml",
            "topic":    item.get("topic", ""),
            "keywords": ",".join(kw) if isinstance(kw, list) else str(kw),
            "type":     item.get("type", "atomic"),
        })
    logger.info("[KNOWLEDGE] Loaded %d AI/ML entries from ai_ml_dataset.json", len(entries))
    return entries


def _ingest():
    """
    Upsert all knowledge sources into ChromaDB.
    Uses upsert (not add) so it is safe to call on every startup —
    new entries are added, existing ones updated, no duplicates.
    Sources:
      1. jarvis_knowledge.json  (local_talk intents)    prefix: intent_*
      2. ai_ml_dataset.json     (AI/ML Q&A dataset)     prefix: aiml_*
    """
    col     = _get_col()
    entries = _load_knowledge() + _load_ai_ml()
    if not entries:
        logger.warning("[KNOWLEDGE] No entries to ingest")
        return

    ids        = [e["id"]       for e in entries]
    documents  = [e["question"] for e in entries]
    metadatas  = [
        {
            "answer":   e["answer"],
            "intent":   e.get("intent",   ""),
            "topic":    e.get("topic",    ""),
            "keywords": e.get("keywords", ""),
            "type":     e.get("type",     "atomic"),
        }
        for e in entries
    ]
    embeddings = _embed(documents)

    # Upsert in batches of 500
    BATCH = 500
    for i in range(0, len(ids), BATCH):
        col.upsert(
            ids        = ids       [i:i+BATCH],
            documents  = documents [i:i+BATCH],
            metadatas  = metadatas [i:i+BATCH],
            embeddings = embeddings[i:i+BATCH],
        )
    logger.info("[KNOWLEDGE] Upserted %d entries into ChromaDB (total in DB: %d)",
                len(entries), col.count())


# ── Query ─────────────────────────────────────────────────────────────────────

# ── Stopwords for keyword focus extraction ────────────────────────────────────
_QUERY_STOP = {
    "what", "when", "where", "how", "why", "does", "about", "explain",
    "tell", "define", "means", "describe", "give", "example", "examples",
    "the", "and", "for", "with", "into", "from", "that", "this", "types",
    "type", "used", "uses", "using", "common", "most", "some", "all",
    "each", "are", "is", "was", "were", "has", "have", "can", "will",
    "would", "could", "should", "name", "list", "brief", "basic", "main",
    "please", "jarvis", "hey", "okay", "just",
}
_COMPARISON_WORDS = {"vs", "versus", "difference", "compare", "better",
                     "between", "compared", "contrast"}


def _focus_keywords(text: str) -> list:
    """Extract meaningful topic keywords from a query (non-stopword words > 3 chars)."""
    words = re.findall(r"\b[a-z][a-z\-]{2,}\b", text.lower())
    return [w for w in words if w not in _QUERY_STOP]


def _is_comparison_query(text: str) -> bool:
    """Return True if the query is asking for a comparison/difference."""
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & _COMPARISON_WORDS)


def query(text: str, n_results: int = 1):
    """
    Semantic search with keyword post-filter.

    Returns:
        (answer: str, similarity: float)  if best match >= SIM_THRESHOLD
        (None, None)                       if no confident match or DB not ready

    Post-filter logic:
      - For single-concept queries (not asking 'difference between X and Y'):
        prefer atomic entries over comparison/combined ones.
      - Among the top-3 candidates, pick the first atomic entry whose question
        or answer contains at least one focus keyword from the query.
      - Fall back to the best semantic match if no filtered result found.
    """
    if not _ready:
        logger.warning("[KNOWLEDGE] query called before DB is ready")
        return None, None

    col   = _get_col()
    count = col.count()
    if count == 0:
        logger.warning("[KNOWLEDGE] Collection is empty — skipping query")
        return None, None

    text = text.lower().strip()

    embedding = _embed([text])[0]
    fetch     = min(max(n_results, 3), count)   # always fetch at least 3
    results   = col.query(
        query_embeddings = [embedding],
        n_results        = fetch,
        include          = ["metadatas", "distances", "documents"],
    )

    if not results["ids"][0]:
        return None, None

    distances = results["distances"][0]
    metadatas = results["metadatas"][0]
    documents = results["documents"][0]

    # Best candidate (highest similarity)
    best_sim  = 1.0 - distances[0]
    best_meta = metadatas[0]

    logger.info(
        "[KNOWLEDGE] query='%s' best_sim=%.3f type=%s (threshold=%.2f)",
        text[:60], best_sim, best_meta.get("type", "?"), SIM_THRESHOLD,
    )

    if best_sim < SIM_THRESHOLD:
        logger.info("[KNOWLEDGE] No confident match (sim=%.3f < %.2f)", best_sim, SIM_THRESHOLD)
        return None, None

    # ── Keyword post-filter (only for non-comparison queries) ─────────────────
    is_comp_query = _is_comparison_query(text)
    if not is_comp_query:
        focus = _focus_keywords(text)
        if focus:
            for doc, meta, dist in zip(documents, metadatas, distances):
                sim = 1.0 - dist
                if sim < SIM_THRESHOLD:
                    break
                # Skip comparison/combined entries for single-concept queries
                if meta.get("type") == "comparison":
                    continue
                # Check that at least one focus keyword appears in the entry
                doc_lower = doc.lower()
                ans_lower = meta.get("answer", "").lower()
                kw_lower  = meta.get("keywords", "").lower()
                if any(f in doc_lower or f in kw_lower or f in ans_lower
                       for f in focus[:3]):
                    logger.info(
                        "[KNOWLEDGE] post-filter selected sim=%.3f type=atomic | '%s'",
                        sim, doc[:50],
                    )
                    # Prefer response variety from local_talk if applicable
                    intent = meta.get("intent", "")
                    if intent and intent != "ai_ml":
                        try:
                            from local_talk import RESPONSES   # noqa
                            options = RESPONSES.get(intent)
                            if options:
                                return random.choice(options), sim
                        except Exception:
                            pass
                    return meta["answer"], sim

    # ── Fallback: best semantic match ─────────────────────────────────────────
    intent = best_meta.get("intent", "")
    if intent and intent != "ai_ml":
        try:
            from local_talk import RESPONSES   # noqa
            options = RESPONSES.get(intent)
            if options:
                return random.choice(options), best_sim
        except Exception:
            pass
    return best_meta["answer"], best_sim


# ── Auto-learning: store new Q&A pairs from API responses ─────────────────────

def auto_learn(question: str, answer: str) -> bool:
    """
    Upsert a new question→answer pair into the knowledge collection so future
    queries with similar phrasing get an instant local hit.

    Returns True if stored successfully, False otherwise.
    """
    if not _ready:
        return False
    if not question or not answer:
        return False
    try:
        col = _get_col()
        # Stable ID based on a hash of the question text
        import hashlib
        qid = "learned_" + hashlib.md5(question.lower().strip().encode()).hexdigest()[:12]
        embedding = _embed([question.lower().strip()])[0]
        col.upsert(
            ids        = [qid],
            documents  = [question],
            metadatas  = [{"answer": answer, "intent": "learned", "source": "api"}],
            embeddings = [embedding],
        )
        logger.info("[KNOWLEDGE] auto_learn stored: '%s...' (id=%s)", question[:50], qid)
        return True
    except Exception as e:
        logger.error("[KNOWLEDGE] auto_learn error: %s", e)
        return False


# ── Vector memory (jarvis_memory collection) ──────────────────────────────────

_mem_col = None
MEM_SIM_THRESHOLD = 0.75   # stricter than knowledge search — memory recall needs high confidence


def _get_mem_col():
    """Separate persistent ChromaDB collection for user interaction memory."""
    global _mem_col
    if _mem_col is not None:
        return _mem_col
    try:
        import chromadb
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client   = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _mem_col = client.get_or_create_collection(
            name="jarvis_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug("[MEMORY-VEC] Collection ready (%d entries)", _mem_col.count())
    except Exception as e:
        logger.error("[MEMORY-VEC] Collection init error: %s", e)
        raise
    return _mem_col


_LEGACY_VEC_UID = "_legacy"


def _safe_uid(user_id) -> str:
    """Coerce any incoming uid to a non-empty string. ChromaDB metadata
    values must be primitive types and are used as-is in `where=` filters."""
    if user_id is None or user_id == "":
        return _LEGACY_VEC_UID
    return str(user_id)[:64]


def mem_store(text: str, intent: str, ts: float, *, user_id: str = None):
    """
    Embed and store a meaningful user input in the jarvis_memory collection.
    Every record is tagged with the owner's user_id in its metadata so
    later recalls can filter via `where={"user_id": uid}` and never leak
    one user's recollections to another.

    Called from memory.py background thread — never blocks main response.
    """
    if _model is None:
        return  # model not loaded yet — skip silently
    try:
        col = _get_mem_col()
        uid = _safe_uid(user_id)
        # Compose record id from owner + timestamp so two users hitting
        # the system at the same millisecond can't collide.
        rid = f"mem_{uid}_{int(ts * 1000)}"
        emb = _embed([text])[0]
        col.add(
            ids        = [rid],
            documents  = [text],
            metadatas  = [{
                "intent":  intent,
                "ts":      str(ts),
                "user_id": uid,
            }],
            embeddings = [emb],
        )
        logger.debug("[MEMORY-VEC:%s] Stored '%s' (intent=%s)", uid, text[:50], intent)
    except Exception as e:
        logger.debug("[MEMORY-VEC] Store failed: %s", e)


def mem_recall(query: str, n: int = 3, *, user_id: str = None) -> list:
    """
    Semantic search over ONE user's past inputs. Filters by the
    `user_id` metadata key so cross-user leakage is structurally
    impossible — ChromaDB enforces the where-clause server-side.

    Returns list of matching text strings where similarity >= MEM_SIM_THRESHOLD.
    Called from memory.py.build_context() — fast after model warm-up.
    """
    if _model is None:
        return []
    try:
        col   = _get_mem_col()
        count = col.count()
        if count == 0:
            return []
        uid     = _safe_uid(user_id)
        emb     = _embed([query])[0]
        results = col.query(
            query_embeddings = [emb],
            n_results        = min(n, count),
            where            = {"user_id": uid},
            include          = ["documents", "distances"],
        )
        # Defensive: results["documents"] can be empty list-of-lists when
        # the user has no embeddings yet (where-clause matches nothing).
        if not results.get("documents") or not results["documents"][0]:
            return []
        out = []
        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            if (1.0 - dist) >= MEM_SIM_THRESHOLD:
                out.append(doc)
        return out
    except Exception as e:
        logger.debug("[MEMORY-VEC] Recall failed: %s", e)
        return []


def mem_purge_user(user_id: str) -> int:
    """Hard-delete every embedding owned by `user_id`. Used by the GDPR
    purge path (`memory.purge_user_data` → `DELETE /api/account`).
    Returns the count removed (best-effort; ChromaDB does not always
    report rowcount on delete-by-where)."""
    uid = _safe_uid(user_id)
    if uid == _LEGACY_VEC_UID:
        # Refuse to wipe the legacy bucket from this entry point.
        return 0
    try:
        col = _get_mem_col()
        # Count first so we have something to report (ChromaDB returns
        # None from delete()).
        before = 0
        try:
            got = col.get(where={"user_id": uid}, include=[])
            before = len(got.get("ids", []) or [])
        except Exception:
            pass
        col.delete(where={"user_id": uid})
        logger.warning("[MEMORY-VEC:%s] Purged %d embedding(s)", uid, before)
        return before
    except Exception as e:
        logger.error("[MEMORY-VEC] Purge failed for uid=%s: %s", uid, e)
        return 0


def top_matches(text: str, n: int = 5) -> list:
    """
    Debug helper. Returns list of {question, answer, intent, similarity} dicts.
    """
    if not _ready:
        return []
    col = _get_col()
    if col.count() == 0:
        return []
    embedding = _embed([text])[0]
    results = col.query(
        query_embeddings = [embedding],
        n_results        = min(n, col.count()),
        include          = ["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        out.append({
            "question":   doc,
            "answer":     meta.get("answer", ""),
            "intent":     meta.get("intent", ""),
            "similarity": round(1.0 - dist, 4),
        })
    return out


# ── Public init ───────────────────────────────────────────────────────────────

def init():
    """
    Load model + populate ChromaDB.
    Call once at startup (runs in a background thread in app.py so Flask is not blocked).
    """
    global _ready
    try:
        _get_model()
        _ingest()
        count = _get_col().count()
        _ready = True
        logger.info("[KNOWLEDGE] Ready — %d entries indexed, threshold=%.2f", count, SIM_THRESHOLD)
    except ImportError as e:
        logger.warning(
            "[KNOWLEDGE] Dependency missing (%s). "
            "Run: pip install chromadb sentence-transformers", e,
        )
    except Exception as e:
        logger.error("[KNOWLEDGE] Init failed: %s", e)
