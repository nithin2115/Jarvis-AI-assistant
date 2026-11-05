"""
JARVIS Intelligent Memory Engine v3 — MULTI-USER SaaS edition
─────────────────────────────────────────────────────────────
Every row in every table is scoped by `user_id`. Every method that touches
state takes a `user_id` keyword argument (auto-resolved from Flask context
when not passed) so existing call sites keep working AND new code can be
explicit. Storage layout:

  data/
    memory.db                            ← SQLite (shared, but every row has user_id)
    memory/
      users/<user_id>/
        profile.json                     ← per-user identity facts
        memory_log.json                  ← per-user mem_log
        behavior.json                    ← per-user topic stats
      _legacy/                           ← legacy single-user data

Vector store: ChromaDB collection `jarvis_memory`. Every embedding carries
`metadata.user_id`; every query filters `where={"user_id": uid}`.

All enrichment writes run in daemon background threads — zero latency impact.
"""
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.memory")

# ── Paths ──────────────────────────────────────────────────────────────────────
DATA_DIR     = Path(__file__).parent / "data" / "memory"
DB_PATH      = Path(__file__).parent / "data" / "memory.db"
USERS_DIR    = DATA_DIR / "users"

# Legacy single-user files (still consulted on a fresh install for one-time
# migration into the _legacy user bucket; once migrated, they're left alone).
PROFILE_FILE = DATA_DIR / "profile.json"
MEMLOG_FILE  = DATA_DIR / "memory_log.json"
BEHAV_FILE   = DATA_DIR / "behavior.json"

# Sentinel user_id assigned to:
#   • Rows from before the multi-user upgrade
#   • Background callers that genuinely have no request context
# Use `_legacy` (leading underscore) to make it impossible for a real user
# to claim this id (we enforce username [a-z0-9] → no underscores prefix).
LEGACY_UID = "_legacy"


def _resolve_uid(explicit: Optional[str] = None) -> str:
    """Find the authoritative user_id for the current operation.
    Priority: explicit kwarg → flask.g.user_id → session["uid"] → LEGACY_UID.
    Never raises — defaults to the legacy sentinel so background workers and
    tests without Flask context don't crash."""
    if explicit:
        return explicit
    try:
        from flask import has_request_context, g, session  # noqa
        if has_request_context():
            uid = getattr(g, "user_id", None)
            if uid:
                return str(uid)
            uid = session.get("uid")
            if uid:
                return str(uid)
    except Exception:
        pass
    return LEGACY_UID


def _user_dir(user_id: str) -> Path:
    """Per-user JSON state directory. Created lazily on first write."""
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", user_id or LEGACY_UID)[:64] or LEGACY_UID
    return USERS_DIR / safe


def _purge_user_files(user_id: str) -> int:
    """Delete all per-user JSON state files. Returns count removed."""
    d = _user_dir(user_id)
    if not d.exists():
        return 0
    n = sum(1 for _ in d.rglob("*"))
    try:
        shutil.rmtree(d, ignore_errors=True)
        logger.warning("[MEMORY] Purged %d file(s) for user=%s", n, user_id)
    except Exception as e:
        logger.error("[MEMORY] _purge_user_files: %s", e)
    return n

# ── Greeting / noise filter ────────────────────────────────────────────────────
_GREET_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|howdy|hiya|sup|what'?s up|wassup|"
    r"good morning|good evening|good night|goodnight|bye|goodbye|"
    r"ok|okay|yes|no|thanks|thank you|sure|got it)\b",
    re.IGNORECASE,
)

# ── Profile extraction patterns ────────────────────────────────────────────────
_NAME_RE  = re.compile(r"\bmy name is ([A-Za-z]+)",               re.IGNORECASE)
_LIKE_RE  = re.compile(r"\bi (?:like|enjoy) (.+?)(?:[.!?]|$)",    re.IGNORECASE)
_LOVE_RE  = re.compile(r"\bi love (.+?)(?:[.!?]|$)",              re.IGNORECASE)
_LEARN_RE = re.compile(r"\bi(?:'?m| am) (?:learning|studying) (.+?)(?:[.!?]|$)", re.IGNORECASE)
_SKILL_RE = re.compile(r"\bi (?:know|work with|use|do) (.+?)(?:[.!?]|$)", re.IGNORECASE)

# ── Intent keywords ────────────────────────────────────────────────────────────
_TASK_KW     = {"open","close","search","play","run","create","delete","send","launch","type","click"}
_PERSONAL_KW = {"i am","i'm","i feel","my name","i like","i love","i know","i study"}
_LEARN_KW    = {"learning","studying","practicing","understanding","trying to","working on"}

# ── Stopwords for behavior topic extraction ────────────────────────────────────
_STOP = {
    "the","is","are","was","were","i","you","a","an","and","to","of","in","it",
    "be","do","did","can","could","will","would","what","how","why","when","where",
    "that","this","have","has","had","not","but","for","on","with","he","she","they",
}


class _UserState:
    """Per-user JSON-backed state. Loaded lazily, persisted on each save."""
    __slots__ = ("user_id", "profile", "mem_log", "behavior", "lock")

    def __init__(self, user_id: str):
        self.user_id  = user_id
        self.lock     = threading.Lock()
        d = _user_dir(user_id)
        self.profile  = JarvisMemory._read_json(d / "profile.json", {
            "name": None, "email": None, "first_login": None,
            "preferences": [], "interests": [],
            "skills": [], "communication_style": "short", "last_seen": None,
        })
        self.mem_log  = JarvisMemory._read_json(d / "memory_log.json", [])
        self.behavior = JarvisMemory._read_json(d / "behavior.json", {
            "top_topics": {}, "response_style": "short", "interaction_count": 0,
        })


class JarvisMemory:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        USERS_DIR.mkdir(parents=True, exist_ok=True)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # SQLite (now user-scoped — every row has a user_id)
        self._lock = threading.Lock()
        self.conn  = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

        # Per-user state cache. Reads on cache miss, evicts oldest after 256
        # users (keeps memory bounded for a SaaS deployment with many users).
        self._states: dict[str, _UserState] = {}
        self._states_lock = threading.RLock()
        self._max_cached_users = 256

        # One-time migration: bring old global profile/memlog/behavior into
        # the `_legacy` user bucket so the data isn't lost.
        self._migrate_legacy_files_once()

        # Background cleanup daemon — dedup + prune low-value + per-user
        # cap + JWT revocation sweep. Gated by an env flag so unit tests
        # and one-off scripts don't pay the (tiny) cost. The daemon
        # itself sleeps `JARVIS_CLEANUP_IDLE_SECONDS` before its first
        # iteration, so even when enabled it never fires during a fast
        # test run.
        self._cleanup_thread: Optional[threading.Thread] = None
        if os.environ.get("JARVIS_DISABLE_CLEANUP_DAEMON") not in ("1", "true", "yes"):
            try:
                self.start_cleanup_daemon()
            except Exception as e:
                logger.error("[CLEANUP] daemon auto-start failed: %s", e)

    # ── JSON helpers (now class methods so _UserState can reuse them) ─────────

    @staticmethod
    def _read_json(path: Path, default):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("[MEMORY] JSON read %s: %s", path.name, e)
        return default

    @staticmethod
    def _write_json(path: Path, data):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)   # atomic on both POSIX and Windows
        except Exception as e:
            logger.error("[MEMORY] JSON write %s: %s", path.name, e)

    # ── Per-user state cache ──────────────────────────────────────────────────

    def _state(self, user_id: str) -> _UserState:
        """Return the (cached) UserState for this user. Loads on miss."""
        with self._states_lock:
            st = self._states.get(user_id)
            if st is not None:
                return st
            st = _UserState(user_id)
            # Crude size-cap eviction: drop oldest entry when full.
            if len(self._states) >= self._max_cached_users:
                drop = next(iter(self._states))
                self._states.pop(drop, None)
            self._states[user_id] = st
            return st

    def _save_state(self, user_id: str, *, which: str = "all"):
        """Persist the in-memory UserState back to disk."""
        st = self._states.get(user_id)
        if st is None:
            return
        d = _user_dir(user_id)
        if which in ("all", "profile"):
            self._write_json(d / "profile.json",     st.profile)
        if which in ("all", "memlog"):
            self._write_json(d / "memory_log.json",  st.mem_log)
        if which in ("all", "behavior"):
            self._write_json(d / "behavior.json",    st.behavior)

    def _migrate_legacy_files_once(self):
        """First-run migration of pre-multiuser global files into _legacy/."""
        marker = USERS_DIR / "_legacy" / ".migrated"
        if marker.exists():
            return
        try:
            target = _user_dir(LEGACY_UID)
            target.mkdir(parents=True, exist_ok=True)
            for src, fname in (
                (PROFILE_FILE, "profile.json"),
                (MEMLOG_FILE,  "memory_log.json"),
                (BEHAV_FILE,   "behavior.json"),
            ):
                dst = target / fname
                if src.exists() and not dst.exists():
                    try:
                        shutil.copy2(src, dst)
                        logger.info("[MEMORY] Migrated %s → %s", src, dst)
                    except Exception as e:
                        logger.error("[MEMORY] Legacy copy %s: %s", src, e)
            marker.write_text(datetime.now().isoformat(), encoding="utf-8")
        except Exception as e:
            logger.error("[MEMORY] Legacy migration failed: %s", e)

    # ── SQLite init ────────────────────────────────────────────────────────────

    def _init_tables(self):
        # Fresh-install schema: user_id is mandatory from day one. For
        # databases that pre-date the multi-user upgrade, the migration
        # block below adds the column with the legacy sentinel default.
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   TEXT    NOT NULL DEFAULT '_legacy',
                ts        TEXT    NOT NULL,
                user_msg  TEXT    NOT NULL,
                ai_resp   TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  TEXT    NOT NULL DEFAULT '_legacy',
                ts       TEXT    NOT NULL,
                content  TEXT    NOT NULL,
                tags     TEXT    DEFAULT ''
            );
            -- ── Long-term structured memories (ChatGPT-style "Memory") ──
            -- Each row belongs to ONE user. EVERY query MUST filter on
            -- user_id — the composite indexes below make this both fast
            -- and the natural query path. content_norm is the dedup key
            -- (lowercased + whitespace-collapsed); dedup is per-user.
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL DEFAULT '_legacy',
                category    TEXT    NOT NULL DEFAULT 'general',
                content     TEXT    NOT NULL,
                importance  INTEGER NOT NULL DEFAULT 1,   -- 1 (low) … 5 (critical)
                hits        INTEGER NOT NULL DEFAULT 0,   -- usage count → bumps importance
                created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source      TEXT    NOT NULL DEFAULT 'auto',  -- 'auto' | 'explicit' | 'voice' | 'manual'
                content_norm TEXT   NOT NULL DEFAULT ''       -- lowercased dedup key (per-user)
            );
        """)

        # ── Idempotent ALTER migrations for older single-user databases ──
        # SQLite refuses ADD COLUMN on a column that already exists, so we
        # PRAGMA-check first. Existing rows automatically inherit the
        # default '_legacy' sentinel — preserving every byte of user data.
        for table in ("conversations", "notes", "memories"):
            try:
                cols = {r["name"] for r in
                        self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "user_id" not in cols:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT '_legacy'"
                    )
                    logger.warning(
                        "[MEMORY] Migrated %s: added user_id column "
                        "(legacy rows tagged '_legacy')", table)
            except Exception as e:
                logger.error("[MEMORY] %s migration: %s", table, e)

        # ── Composite indexes (user_id FIRST so every query uses them) ──
        # These replace the old single-column indexes and turn every
        # WHERE user_id = ? AND ... query into a clean index scan even
        # when the SaaS instance has millions of rows.
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_conv_uid_ts        ON conversations(user_id, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_notes_uid_ts       ON notes(user_id, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_mem_uid_imp        ON memories(user_id, importance DESC, hits DESC);
            CREATE INDEX IF NOT EXISTS idx_mem_uid_cat        ON memories(user_id, category);
            CREATE INDEX IF NOT EXISTS idx_mem_uid_norm       ON memories(user_id, content_norm);
            CREATE INDEX IF NOT EXISTS idx_mem_uid_id         ON memories(user_id, id);
        """)
        self.conn.commit()

    # ── Memory permission gate ────────────────────────────────────────────────

    def _memory_enabled(self, user_id: str) -> bool:
        """Honour the per-user toggle from `users.memory_enabled`. We never
        block READS (users always get their old memories), but WRITES go
        through this gate so a disabled user stops accumulating new state."""
        if user_id == LEGACY_UID:
            return True
        try:
            from auth import db as _user_db
            return _user_db.is_memory_enabled(user_id)
        except Exception:
            return True

    # ── Profile extraction ─────────────────────────────────────────────────────

    def _extract_profile(self, text: str, user_id: str):
        st = self._state(user_id)
        changed = False

        m = _NAME_RE.search(text)
        if m:
            name = m.group(1).strip().capitalize()
            if st.profile.get("name") != name:
                st.profile["name"] = name
                logger.info("[MEMORY:%s] Profile name set: %s", user_id, name)
                changed = True

        def _add(lst_key: str, match_obj):
            nonlocal changed
            item = match_obj.group(1).strip().lower()[:80]
            if item and item not in st.profile[lst_key]:
                st.profile[lst_key].append(item)
                changed = True

        for m in _LIKE_RE.finditer(text):
            _add("preferences", m)
        for m in _LOVE_RE.finditer(text):
            _add("interests", m)
        for m in _LEARN_RE.finditer(text):
            _add("skills", m)
        for m in _SKILL_RE.finditer(text):
            _add("interests", m)

        if changed:
            st.profile["last_seen"] = datetime.now().isoformat()
            self._save_state(user_id, which="profile")

    # ── Memory filter ──────────────────────────────────────────────────────────

    def _should_store(self, text: str, user_id: str) -> bool:
        words = text.strip().split()
        if len(words) <= 5:
            return False
        if _GREET_RE.match(text.strip()):
            return False
        # Dedup against last 30 log entries (per-user)
        st = self._state(user_id)
        recent_texts = {e["text"] for e in st.mem_log[-30:]}
        if text.strip() in recent_texts:
            return False
        return True

    # ── Intent + importance classifier ────────────────────────────────────────

    def _classify(self, text: str):
        t = text.lower()
        if any(k in t for k in _TASK_KW):
            return "task", 0.6
        if any(k in t for k in _LEARN_KW):
            return "learning", 0.9
        if any(k in t for k in _PERSONAL_KW):
            return "personal", 0.8
        return "general", 0.5

    # ── Behavior tracker ───────────────────────────────────────────────────────

    def _update_behavior(self, text: str, ai_resp: str, user_id: str):
        st = self._state(user_id)
        st.behavior["interaction_count"] = st.behavior.get("interaction_count", 0) + 1

        for w in re.findall(r"\b[a-z]{3,}\b", text.lower()):
            if w not in _STOP:
                topics = st.behavior.setdefault("top_topics", {})
                topics[w] = topics.get(w, 0) + 1

        avg_words = len(ai_resp.split())
        st.behavior["response_style"] = "detailed" if avg_words >= 10 else "short"

        # Keep top 50 topics
        topics = st.behavior.get("top_topics", {})
        if len(topics) > 50:
            st.behavior["top_topics"] = dict(
                sorted(topics.items(), key=lambda x: x[1], reverse=True)[:50]
            )
        self._save_state(user_id, which="behavior")

    # ── Vector memory (via knowledge_db) ──────────────────────────────────────
    # Every embedding carries the owner's user_id in its metadata; every
    # recall query filters on that metadata. No cross-user leakage possible.

    def _store_vector(self, text: str, intent: str, ts: float, user_id: str):
        try:
            import knowledge_db
            knowledge_db.mem_store(text, intent, ts, user_id=user_id)
        except Exception as e:
            logger.debug("[MEMORY] Vector store skipped: %s", e)

    def semantic_recall(self, query: str, n: int = 3, *,
                        user_id: str = None) -> list:
        """Semantic search over past user inputs — STRICTLY scoped to the
        caller's user_id. Returns [] if no user context can be resolved."""
        uid = _resolve_uid(user_id)
        try:
            import knowledge_db
            return knowledge_db.mem_recall(query, n, user_id=uid)
        except Exception:
            return []

    # ── Background enrichment ──────────────────────────────────────────────────

    def _background_enrich(self, user_msg: str, ai_resp: str, user_id: str):
        try:
            # Honour the per-user memory toggle — disabled users get no
            # auto-extraction, behavior tracking, or vector storage.
            if not self._memory_enabled(user_id):
                return
            self._extract_profile(user_msg, user_id)
            self._update_behavior(user_msg, ai_resp, user_id)

            # ── Smart structured-memory extraction (ChatGPT-style "Memory") ──
            # Pattern-based, zero-API, <1ms. Each match becomes a row in the
            # `memories` table — already deduped via content_norm.
            try:
                self.extract_and_save(user_msg, source="auto", user_id=user_id)
            except Exception as e:
                logger.debug("[MEMORY] smart_extract failed: %s", e)

            if self._should_store(user_msg, user_id):
                intent, importance = self._classify(user_msg)
                ts = time.time()
                st = self._state(user_id)
                st.mem_log.append({
                    "text":       user_msg.strip(),
                    "intent":     intent,
                    "importance": importance,
                    "timestamp":  ts,
                })
                if len(st.mem_log) > 500:
                    st.mem_log = st.mem_log[-500:]
                self._save_state(user_id, which="memlog")
                self._store_vector(user_msg, intent, ts, user_id)
        except Exception as e:
            logger.error("[MEMORY] Background enrich error: %s", e)

    # ── Public write API ───────────────────────────────────────────────────────

    def save_conversation(self, user_msg: str, ai_resp: str, *,
                          user_id: str = None):
        """SQLite write (fast, sync) + async enrichment in background thread.
        Every row is tagged with the resolved user_id so a later cross-user
        query (e.g. another user asking 'what did I say earlier?') cannot
        possibly surface this conversation."""
        uid = _resolve_uid(user_id)
        with self._lock:
            self.conn.execute(
                "INSERT INTO conversations (user_id, ts, user_msg, ai_resp) "
                "VALUES (?,?,?,?)",
                (uid, datetime.now().isoformat(),
                 (user_msg or "")[:1000], (ai_resp or "")[:1000])
            )
            self.conn.commit()

        threading.Thread(
            target=self._background_enrich,
            args=(user_msg, ai_resp, uid),
            daemon=True,
        ).start()

    def save_note(self, content: str, tags: str = '', *,
                  user_id: str = None):
        uid = _resolve_uid(user_id)
        with self._lock:
            self.conn.execute(
                "INSERT INTO notes (user_id, ts, content, tags) VALUES (?,?,?,?)",
                (uid, datetime.now().isoformat(), content, tags)
            )
            self.conn.commit()

    # ── Read / search (USER-SCOPED) ────────────────────────────────────────────
    # Every SELECT below filters on user_id as the FIRST predicate so the
    # composite indexes idx_*_uid_* are used and no cross-user leakage is
    # possible even with a malicious LIKE pattern.

    def get_recent(self, n: int = 5, *, user_id: str = None) -> list:
        uid = _resolve_uid(user_id)
        rows = self.conn.execute(
            "SELECT user_msg, ai_resp FROM conversations "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (uid, n),
        ).fetchall()
        return [{"user": r["user_msg"], "ai": r["ai_resp"]} for r in reversed(rows)]

    def search(self, query: str, n: int = 3, *, user_id: str = None) -> list:
        uid = _resolve_uid(user_id)
        seen, results = set(), []
        for word in query.lower().split():
            if len(word) < 3:
                continue
            rows = self.conn.execute(
                "SELECT user_msg, ai_resp FROM conversations "
                "WHERE user_id = ? AND "
                "      (LOWER(user_msg) LIKE ? OR LOWER(ai_resp) LIKE ?) "
                "ORDER BY id DESC LIMIT ?",
                (uid, f"%{word}%", f"%{word}%", n),
            ).fetchall()
            for r in rows:
                key = r["user_msg"]
                if key not in seen:
                    seen.add(key)
                    results.append({"user": r["user_msg"], "ai": r["ai_resp"]})
        return results[:n]

    def search_notes(self, query: str, n: int = 3, *, user_id: str = None) -> list:
        uid = _resolve_uid(user_id)
        rows = self.conn.execute(
            "SELECT content FROM notes "
            "WHERE user_id = ? AND "
            "      (LOWER(content) LIKE ? OR LOWER(tags) LIKE ?) "
            "ORDER BY id DESC LIMIT ?",
            (uid, f"%{query.lower()}%", f"%{query.lower()}%", n),
        ).fetchall()
        return [r["content"] for r in rows]

    # ── Context builder (enriched) ─────────────────────────────────────────────

    def build_context(self, query: str, *, user_id: str = None) -> str:
        """Rich, USER-SCOPED context for the AI:
            1. User profile (name, interests, skills, prefs) — this user only
            2. Top structured memories — this user only
            3. Query-relevant memory hits — this user only
            4. Semantic recall from ChromaDB — filtered by user_id metadata
            5. Recent conversation (last 8 turns) — this user only
        Order is by importance to the LLM: identity → preferences →
        relevant facts → semantic context → live history.

        Honours the per-user memory toggle: a user with memory_enabled=0
        gets ONLY their stored conversation history (so the chat still
        feels coherent within a session) — no profile, no long-term
        memories, no semantic recall."""
        uid     = _resolve_uid(user_id)
        enabled = self._memory_enabled(uid)
        lines   = []
        top_mems = []

        if enabled:
            # 1. User profile (per-user JSON state)
            p = self._state(uid).profile
            prof_lines = []
            if p.get("name"):
                prof_lines.append(f"User name: {p['name']}")
            if p.get("interests"):
                prof_lines.append(f"Interests: {', '.join(p['interests'][:5])}")
            if p.get("skills"):
                prof_lines.append(f"Learning: {', '.join(p['skills'][:5])}")
            if p.get("preferences"):
                prof_lines.append(f"Likes: {', '.join(p['preferences'][:5])}")
            if prof_lines:
                lines.append("=== User Profile ===")
                lines.extend(prof_lines)

            # 2. Top structured memories — highest-importance facts.
            try:
                top_mems = self.list_memories(limit=8, user_id=uid)
                if top_mems:
                    lines.append("=== Long-term Memory (most important) ===")
                    for m in top_mems:
                        star = "*" * int(m.get("importance", 1))
                        lines.append(f"[{m['category']}{star}] {m['content']}")
            except Exception:
                pass

            # 2b. Active interests — categories the user discusses often.
            #     The LLM uses this to personalise replies naturally:
            #         "Since you're learning Java, let me explain
            #          polymorphism simply…"
            #     Only injected when the user has at least one non-trivial
            #     focus, to avoid polluting the prompt for new users.
            try:
                topics = self.top_topics(user_id=uid, n=3)
                topics = [t for t in topics if t["score"] >= 5]
                if topics:
                    lines.append("=== User's active focus (weave into replies naturally) ===")
                    for t in topics:
                        lines.append(
                            f"- {t['category']} "
                            f"({t['count']} memories, {t['hits']} mentions)"
                        )
            except Exception:
                pass

            # 3. Query-relevant structured memory hits.
            try:
                hits = self.search_memories(query, limit=4, user_id=uid)
                shown = {m["id"] for m in top_mems}
                relevant = [h for h in hits if h.get("id") not in shown]
                if relevant:
                    lines.append("=== Memory relevant to this query ===")
                    for h in relevant:
                        lines.append(f"[{h['category']}] {h['content']}")
            except Exception:
                pass

            # 4. Semantic memory recall (ChromaDB — user_id metadata filter).
            recalled = self.semantic_recall(query, 3, user_id=uid)
            if recalled:
                lines.append("=== Semantic recall ===")
                for item in recalled:
                    lines.append(f"Previously said: {item[:120]}")

        # 5. Recent conversation (always shown — needed for coherent chat
        # even when long-term memory is disabled).
        recent = self.get_recent(8, user_id=uid)
        if recent:
            lines.append("=== Recent Conversation ===")
            for item in recent:
                lines.append(f"User: {item['user']}")
                lines.append(f"JARVIS: {item['ai'][:160]}")

        return "\n".join(lines)

    # ── Profile access (USER-SCOPED) ───────────────────────────────────────────

    def save_google_profile(self, name: str, email: str, *, user_id: str = None):
        """Persist identity from Google OAuth — called once on login. The
        per-user JSON state file is the source of truth; the user db row
        is updated by auth/oauth.py."""
        uid = _resolve_uid(user_id)
        st  = self._state(uid)
        changed = False
        if name and not st.profile.get("name"):
            st.profile["name"] = name.strip().split()[0].capitalize()
            changed = True
        if email and not st.profile.get("email"):
            st.profile["email"] = email.lower().strip()
            changed = True
        if not st.profile.get("first_login"):
            st.profile["first_login"] = datetime.now().isoformat()
            changed = True
        st.profile["last_seen"] = datetime.now().isoformat()
        # Always persist (last_seen changed) — `changed` kept for the log line.
        self._save_state(uid, which="profile")
        logger.info("[MEMORY:%s] Google profile saved: name=%s email=%s changed=%s",
                    uid, name, email, changed)

    def get_profile(self, *, user_id: str = None) -> dict:
        return dict(self._state(_resolve_uid(user_id)).profile)

    def get_name(self, *, user_id: str = None):
        return self._state(_resolve_uid(user_id)).profile.get("name")

    def get_top_topics(self, n: int = 5, *, user_id: str = None) -> list:
        topics = self._state(_resolve_uid(user_id)).behavior.get("top_topics", {})
        return [k for k, _ in sorted(topics.items(), key=lambda x: x[1], reverse=True)[:n]]

    # ══════════════════════════════════════════════════════════════════════════
    # ChatGPT-style Long-Term Memory ("memories" table)
    # ══════════════════════════════════════════════════════════════════════════
    # The methods below operate on the dedicated `memories` table — a
    # structured, queryable, indexed store of FACTS about the user
    # (preferences, goals, learning topics, projects). This is distinct
    # from `conversations` (raw chat log) and `mem_log` (JSON file of
    # significant utterances). The intelligent extractor + the explicit
    # "remember this..." voice path both write here.

    def _norm_content(self, content: str) -> str:
        """Lowercase + collapse whitespace — used as the dedup key."""
        return " ".join((content or "").lower().split())[:240]

    # ── Importance auto-evolution (hits-driven promotion) ──────────────
    # The more often a memory is referenced, the more it must matter to
    # the user. We bump its importance in tiers so high-traffic facts
    # naturally float to the top of `list_memories`/`build_context`.
    #
    #     hits ≥  5  → importance at least 3
    #     hits ≥ 10  → importance at least 4
    #     hits ≥ 20  → importance at least 5  (critical / personalised)
    #
    # Called by both `add_memory` (dedup-bump path) and `search_memories`
    # (post-hit increment). Must be invoked WITH `self._lock` held.
    _HITS_TIERS = ((20, 5), (10, 4), (5, 3))

    @staticmethod
    def _evolved_importance(current_imp: int, hits: int) -> int:
        target = int(current_imp or 1)
        for h_min, imp_min in JarvisMemory._HITS_TIERS:
            if hits >= h_min and target < imp_min:
                target = imp_min
                break
        return target

    def add_memory(self, content: str, category: str = "general",
                   importance: int = 2, source: str = "auto",
                   *, user_id: str = None) -> int:
        """Insert a structured memory for `user_id`. Auto-dedupes by
        (user_id, content_norm). Returns the row id (existing or new).
        Importance 1=low … 5=critical.

        Honours the per-user memory toggle — a disabled user gets a
        no-op so old memories remain readable but new ones are not
        accumulated.

        Also performs IMPORTANCE EVOLUTION on the dedup-bump path: if a
        fact has been re-asserted enough times (see `_HITS_TIERS`), its
        importance is auto-promoted so the LLM ranks it higher in future
        context windows."""
        uid = _resolve_uid(user_id)
        if not self._memory_enabled(uid):
            return -1
        content = (content or "").strip()
        if not content:
            return -1
        content = content[:500]                 # cap row size
        importance = max(1, min(5, int(importance or 1)))
        norm = self._norm_content(content)
        with self._lock:
            try:
                # Per-user dedup: same fact saved twice for the SAME user
                # bumps importance; same fact for a DIFFERENT user inserts
                # fresh (each user owns their own copy).
                row = self.conn.execute(
                    "SELECT id, importance, hits FROM memories "
                    "WHERE user_id = ? AND content_norm = ? LIMIT 1",
                    (uid, norm),
                ).fetchone()
                if row:
                    next_hits = int(row["hits"]) + 1
                    base_imp  = max(int(row["importance"]), importance)
                    new_imp   = self._evolved_importance(base_imp, next_hits)
                    self.conn.execute(
                        "UPDATE memories SET importance=?, hits=hits+1, "
                        "last_seen=CURRENT_TIMESTAMP "
                        "WHERE id=? AND user_id=?",
                        (new_imp, row["id"], uid),
                    )
                    self.conn.commit()
                    if new_imp > base_imp:
                        logger.info("[MEMORY:%s] Auto-promoted #%d (hits=%d imp %d→%d)",
                                    uid, row["id"], next_hits, base_imp, new_imp)
                    else:
                        logger.info("[MEMORY:%s] Bumped existing #%d (imp=%d hits=%d)",
                                    uid, row["id"], new_imp, next_hits)
                    return int(row["id"])
                cur = self.conn.execute(
                    "INSERT INTO memories "
                    "(user_id, category, content, importance, source, content_norm) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, category[:40], content, importance, source[:20], norm),
                )
                self.conn.commit()
                new_id = int(cur.lastrowid)
                logger.info("[MEMORY:%s] Saved #%d [%s,imp=%d,src=%s]: %s",
                            uid, new_id, category, importance, source, content[:60])
                # Also push into vector store so semantic recall can find it,
                # tagged with the owner's user_id so cross-user queries miss.
                try:
                    self._store_vector(content, f"memory:{category}",
                                       time.time(), uid)
                except Exception:
                    pass
                return new_id
            except Exception as e:
                logger.error("[MEMORY:%s] add_memory failed: %s", uid, e)
                return -1

    def search_memories(self, query: str, limit: int = 5,
                        category: str = None,
                        *, user_id: str = None) -> list:
        """LIKE-search (fast) over content for ONE user. For semantic
        recall, use semantic_recall() which goes through ChromaDB."""
        uid = _resolve_uid(user_id)
        query = (query or "").strip().lower()
        if not query:
            return []
        try:
            with self._lock:
                if category:
                    rows = self.conn.execute(
                        "SELECT id, category, content, importance, hits, created_at, source "
                        "FROM memories "
                        "WHERE user_id = ? AND category = ? AND content_norm LIKE ? "
                        "ORDER BY importance DESC, hits DESC, id DESC LIMIT ?",
                        (uid, category, f"%{query}%", limit),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT id, category, content, importance, hits, created_at, source "
                        "FROM memories "
                        "WHERE user_id = ? AND content_norm LIKE ? "
                        "ORDER BY importance DESC, hits DESC, id DESC LIMIT ?",
                        (uid, f"%{query}%", limit),
                    ).fetchall()
                if rows:
                    ids = [r["id"] for r in rows]
                    # Bump hit count — but ALSO scope by user_id so a malicious
                    # caller can't bump another user's row even if they
                    # somehow guessed an id.
                    self.conn.execute(
                        f"UPDATE memories SET hits = hits + 1, "
                        f"last_seen = CURRENT_TIMESTAMP "
                        f"WHERE user_id = ? AND id IN ({','.join('?'*len(ids))})",
                        [uid, *ids],
                    )
                    # Importance evolution: promote any row whose NEW hit
                    # count crossed a tier threshold. We do this in a
                    # single CASE-WHEN update so all promotions for the
                    # search hit-set are flushed atomically.
                    self.conn.execute(
                        "UPDATE memories SET importance = MAX(importance, "
                        "  CASE "
                        "    WHEN hits >= 20 THEN 5 "
                        "    WHEN hits >= 10 THEN 4 "
                        "    WHEN hits >=  5 THEN 3 "
                        "    ELSE importance "
                        "  END) "
                        f"WHERE user_id = ? AND id IN ({','.join('?'*len(ids))})",
                        [uid, *ids],
                    )
                    self.conn.commit()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[MEMORY:%s] search_memories failed: %s", uid, e)
            return []

    def list_memories(self, category: str = None, limit: int = 100,
                      *, user_id: str = None) -> list:
        """List ONE user's memories ordered by importance then recency."""
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                if category:
                    rows = self.conn.execute(
                        "SELECT id, category, content, importance, hits, created_at, source "
                        "FROM memories WHERE user_id = ? AND category = ? "
                        "ORDER BY importance DESC, id DESC LIMIT ?",
                        (uid, category, limit),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT id, category, content, importance, hits, created_at, source "
                        "FROM memories WHERE user_id = ? "
                        "ORDER BY importance DESC, id DESC LIMIT ?",
                        (uid, limit),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[MEMORY:%s] list_memories failed: %s", uid, e)
            return []

    def list_categories(self, *, user_id: str = None) -> list:
        """Distinct categories with counts for ONE user. For UI sidebars."""
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT category, COUNT(*) AS n FROM memories "
                    "WHERE user_id = ? GROUP BY category ORDER BY n DESC",
                    (uid,),
                ).fetchall()
            return [{"category": r["category"], "count": int(r["n"])} for r in rows]
        except Exception as e:
            logger.error("[MEMORY:%s] list_categories failed: %s", uid, e)
            return []

    def top_topics(self, *, user_id: str = None, n: int = 3) -> list:
        """Return the user's most-active topics by a weighted score of
        (total hits, max importance, row count). Excludes the catch-all
        'general' category so the result reflects genuine interests.

        Used by `build_context` to inject a natural 'currently focused
        on …' nudge into the system prompt — the LLM weaves it into
        replies without sounding robotic.

        Returns at most `n` items, each:
            {category, count, hits, importance, score}
        """
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT category, "
                    "       COALESCE(SUM(hits), 0)         AS h, "
                    "       COALESCE(MAX(importance), 1)   AS imp, "
                    "       COUNT(*)                       AS n "
                    "FROM memories "
                    "WHERE user_id = ? AND category != 'general' "
                    "GROUP BY category "
                    "ORDER BY (h * 2 + imp * 3 + n) DESC "
                    "LIMIT ?",
                    (uid, int(n)),
                ).fetchall()
            return [{
                "category":   r["category"],
                "count":      int(r["n"]),
                "hits":       int(r["h"]),
                "importance": int(r["imp"]),
                "score":      int(r["h"]) * 2 + int(r["imp"]) * 3 + int(r["n"]),
            } for r in rows]
        except Exception as e:
            logger.error("[MEMORY:%s] top_topics: %s", uid, e)
            return []

    def delete_memory(self, mem_id: int, *, user_id: str = None) -> bool:
        """Delete a memory ONLY if it belongs to `user_id`. Quietly returns
        False (no error) when the row exists but belongs to someone else —
        the caller can't tell whether the row exists, which prevents id
        enumeration probing."""
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                cur = self.conn.execute(
                    "DELETE FROM memories WHERE id = ? AND user_id = ?",
                    (int(mem_id), uid),
                )
                self.conn.commit()
                ok = (cur.rowcount or 0) > 0
            if ok:
                logger.info("[MEMORY:%s] Deleted #%s", uid, mem_id)
            return ok
        except Exception as e:
            logger.error("[MEMORY:%s] delete_memory failed: %s", uid, e)
            return False

    def update_memory(self, mem_id: int, content: str = None,
                      category: str = None, importance: int = None,
                      *, user_id: str = None) -> bool:
        """Update fields of a memory ONLY if it belongs to `user_id`."""
        uid = _resolve_uid(user_id)
        try:
            sets, args = [], []
            if content is not None:
                sets.append("content = ?")
                args.append(content[:500])
                sets.append("content_norm = ?")
                args.append(self._norm_content(content))
            if category is not None:
                sets.append("category = ?")
                args.append(category[:40])
            if importance is not None:
                sets.append("importance = ?")
                args.append(max(1, min(5, int(importance))))
            if not sets:
                return False
            args.extend([int(mem_id), uid])
            with self._lock:
                cur = self.conn.execute(
                    f"UPDATE memories SET {', '.join(sets)}, "
                    f"last_seen=CURRENT_TIMESTAMP "
                    f"WHERE id = ? AND user_id = ?",
                    args,
                )
                self.conn.commit()
            return (cur.rowcount or 0) > 0
        except Exception as e:
            logger.error("[MEMORY:%s] update_memory failed: %s", uid, e)
            return False

    def clear_memories(self, category: str = None,
                       *, user_id: str = None) -> int:
        """Delete ALL of ONE user's memories (optionally scoped to a category).
        Returns count deleted. NEVER touches another user's data."""
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                if category:
                    cur = self.conn.execute(
                        "DELETE FROM memories WHERE user_id = ? AND category = ?",
                        (uid, category),
                    )
                else:
                    cur = self.conn.execute(
                        "DELETE FROM memories WHERE user_id = ?", (uid,),
                    )
                self.conn.commit()
                n = cur.rowcount or 0
            logger.info("[MEMORY:%s] Cleared %d memories (cat=%s)",
                        uid, n, category or "all")
            return int(n)
        except Exception as e:
            logger.error("[MEMORY:%s] clear_memories failed: %s", uid, e)
            return 0

    # ══════════════════════════════════════════════════════════════════════════
    # Smart Extractor — runs in the background enrich thread, never blocks
    # ══════════════════════════════════════════════════════════════════════════
    # Pattern-based extractor (zero-API, <1ms) that catches the common
    # cases (preferences, learning, goals, projects, communication style).
    # Each match yields a single structured memory written to the table.

    def smart_extract(self, text: str) -> list:
        """Return a list of {category, content, importance} dicts."""
        if not text or len(text) < 8:
            return []
        out = []
        seen = set()

        def _push(category: str, content: str, importance: int = 2):
            content = " ".join(content.split())[:240]
            key = content.lower()
            if not content or key in seen or len(content) < 4:
                return
            seen.add(key)
            out.append({
                "category": category,
                "content": content,
                "importance": importance,
            })

        for pat, cat, imp, fmt in _SMART_PATTERNS:
            for m in pat.finditer(text):
                try:
                    _push(cat, fmt(m), imp)
                except Exception:
                    continue

        return out

    def extract_and_save(self, text: str, source: str = "auto",
                         *, user_id: str = None) -> list:
        """Run the extractor and write each found memory FOR THIS USER.
        Returns inserted ids. Called from the background enrichment
        thread which already resolved user_id from the request context."""
        uid = _resolve_uid(user_id)
        ids = []
        for mem in self.smart_extract(text or ""):
            new_id = self.add_memory(
                mem["content"],
                category=mem.get("category", "general"),
                importance=int(mem.get("importance", 2)),
                source=source,
                user_id=uid,
            )
            if new_id > 0:
                ids.append(new_id)
        return ids

    # ══════════════════════════════════════════════════════════════════════════
    # Multi-turn conversation history (OpenAI-format messages array)
    # ══════════════════════════════════════════════════════════════════════════
    # BrainManager's SharedContext ALSO maintains turn history per mode
    # (in-process). This method provides a SQL-backed fallback / primary
    # source — useful for cross-process recall and the chat-side history UI.

    def get_messages(self, n: int = 20, *, user_id: str = None) -> list:
        """Return ONE user's last `n` interactions as
        `[{role, content}, ...]` — OpenAI-compatible. Order: oldest → newest."""
        uid = _resolve_uid(user_id)
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT user_msg, ai_resp FROM conversations "
                    "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (uid, max(1, int(n))),
                ).fetchall()
        except Exception as e:
            logger.error("[MEMORY:%s] get_messages failed: %s", uid, e)
            return []
        msgs = []
        for r in reversed(rows):
            if r["user_msg"]:
                msgs.append({"role": "user",      "content": r["user_msg"]})
            if r["ai_resp"]:
                msgs.append({"role": "assistant", "content": r["ai_resp"]})
        return msgs

    # ── Stats (USER-SCOPED) ────────────────────────────────────────────────────

    def stats(self, *, user_id: str = None) -> dict:
        """Per-user counts for the Memory Settings UI / privacy export."""
        uid = _resolve_uid(user_id)
        st  = self._state(uid)
        try:
            n_conv = self.conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (uid,),
            ).fetchone()[0]
        except Exception:
            n_conv = 0
        try:
            n_notes = self.conn.execute(
                "SELECT COUNT(*) FROM notes WHERE user_id = ?", (uid,),
            ).fetchone()[0]
        except Exception:
            n_notes = 0
        try:
            n_mem = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ?", (uid,),
            ).fetchone()[0]
        except Exception:
            n_mem = 0
        return {
            "user_id":        uid,
            "conversations":  int(n_conv),
            "notes":          int(n_notes),
            "memories":       int(n_mem),
            "mem_log":        len(st.mem_log),
            "interactions":   st.behavior.get("interaction_count", 0),
            "known_name":     st.profile.get("name"),
            "top_topics":     self.get_top_topics(3, user_id=uid),
            "memory_enabled": self._memory_enabled(uid),
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Privacy / GDPR — export & full purge for one user
    # ══════════════════════════════════════════════════════════════════════════

    def export_user_data(self, *, user_id: str = None) -> dict:
        """Return EVERYTHING the system knows about `user_id` as a JSON-
        serialisable dict. Wired up to `GET /api/memory/export` so users
        can download their data on demand (GDPR Article 20)."""
        uid = _resolve_uid(user_id)
        st  = self._state(uid)
        with self._lock:
            convos = [dict(r) for r in self.conn.execute(
                "SELECT id, ts, user_msg, ai_resp FROM conversations "
                "WHERE user_id = ? ORDER BY id ASC", (uid,),
            ).fetchall()]
            notes  = [dict(r) for r in self.conn.execute(
                "SELECT id, ts, content, tags FROM notes "
                "WHERE user_id = ? ORDER BY id ASC", (uid,),
            ).fetchall()]
            mems   = [dict(r) for r in self.conn.execute(
                "SELECT id, category, content, importance, hits, created_at, "
                "       last_seen, source FROM memories "
                "WHERE user_id = ? ORDER BY id ASC", (uid,),
            ).fetchall()]
        return {
            "user_id":       uid,
            "exported_at":   datetime.now().isoformat(),
            "profile":       dict(st.profile),
            "behavior":      dict(st.behavior),
            "mem_log":       list(st.mem_log),
            "conversations": convos,
            "notes":         notes,
            "memories":      mems,
        }

    def purge_user_data(self, *, user_id: str = None) -> dict:
        """Hard-delete EVERY piece of data owned by `user_id`. Used by
        `DELETE /api/account` and the Memory Settings 'Forget Me' button.
        Returns a counts dict so the UI can confirm."""
        uid = _resolve_uid(user_id)
        if uid == LEGACY_UID:
            # Refuse to wipe the legacy bucket via this entry point — that
            # would nuke pre-multiuser data the admin may still want.
            logger.warning("[MEMORY] purge_user_data refused for _legacy uid")
            return {"refused": True}
        counts = {"conversations": 0, "notes": 0, "memories": 0, "files": 0}
        with self._lock:
            for table in ("conversations", "notes", "memories"):
                try:
                    cur = self.conn.execute(
                        f"DELETE FROM {table} WHERE user_id = ?", (uid,),
                    )
                    counts[table] = int(cur.rowcount or 0)
                except Exception as e:
                    logger.error("[MEMORY:%s] purge %s: %s", uid, table, e)
            self.conn.commit()
        # Drop in-memory cache so the next request reloads fresh defaults.
        with self._states_lock:
            self._states.pop(uid, None)
        # Wipe the on-disk JSON state.
        counts["files"] = _purge_user_files(uid)
        # Wipe vector embeddings (best-effort — collection may not exist yet).
        try:
            import knowledge_db
            counts["vectors"] = int(knowledge_db.mem_purge_user(uid))
        except Exception as e:
            logger.debug("[MEMORY:%s] vector purge skipped: %s", uid, e)
            counts["vectors"] = 0
        logger.warning("[MEMORY:%s] PURGED user data: %s", uid, counts)
        return counts

    def cleanup_low_value(self, *, user_id: str = None,
                          per_user_cap: int = 5000,
                          low_imp_threshold: int = 1) -> dict:
        """Trim a user's memory: drop low-importance untouched rows and
        cap the total row count. Called by the cleanup daemon and
        `POST /api/memory/cleanup`."""
        uid = _resolve_uid(user_id)
        report = {"deleted_low": 0, "deleted_overflow": 0, "deduped": 0}
        with self._lock:
            try:
                # 1. Dedup: collapse rows that share the same content_norm
                #    for the same user (the live add_memory path already
                #    dedupes on insert, but old rows may pre-date the
                #    multi-user upgrade or have been imported).
                cur = self.conn.execute(
                    "DELETE FROM memories WHERE id NOT IN ("
                    "  SELECT MIN(id) FROM memories WHERE user_id = ? "
                    "  GROUP BY content_norm"
                    ") AND user_id = ?",
                    (uid, uid),
                )
                report["deduped"] = int(cur.rowcount or 0)

                # 2. Drop importance-1 rows with hits=0 older than 30 days.
                cur = self.conn.execute(
                    "DELETE FROM memories "
                    "WHERE user_id = ? AND importance <= ? AND hits = 0 "
                    "  AND julianday('now') - julianday(created_at) > 30",
                    (uid, low_imp_threshold),
                )
                report["deleted_low"] = int(cur.rowcount or 0)

                # 3. Cap total rows per user — keep the most important.
                row = self.conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE user_id = ?", (uid,),
                ).fetchone()
                n = int(row[0] or 0)
                if n > per_user_cap:
                    drop = n - per_user_cap
                    cur = self.conn.execute(
                        "DELETE FROM memories WHERE id IN ("
                        "  SELECT id FROM memories WHERE user_id = ? "
                        "  ORDER BY importance ASC, hits ASC, id ASC LIMIT ?)",
                        (uid, drop),
                    )
                    report["deleted_overflow"] = int(cur.rowcount or 0)
                self.conn.commit()
            except Exception as e:
                logger.error("[MEMORY:%s] cleanup_low_value: %s", uid, e)
        logger.info("[MEMORY:%s] cleanup: %s", uid, report)
        return report

    # ═══════════════════════════════════════════════════════════════════════════
    # Background cleanup daemon (multi-user)
    # ═══════════════════════════════════════════════════════════════════════════

    def cleanup_all_users(self) -> dict:
        """Run `cleanup_low_value` for every distinct user_id present in
        the memories table. Returns aggregate counts."""
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT DISTINCT user_id FROM memories"
                ).fetchall()
            uids = [r["user_id"] for r in rows]
        except Exception as e:
            logger.error("[CLEANUP] could not list users: %s", e)
            return {"users": 0}
        agg = {"users": 0, "deleted_low": 0, "deleted_overflow": 0, "deduped": 0}
        for uid in uids:
            try:
                rep = self.cleanup_low_value(user_id=uid)
                agg["users"]            += 1
                agg["deleted_low"]      += int(rep.get("deleted_low", 0)      or 0)
                agg["deleted_overflow"] += int(rep.get("deleted_overflow", 0) or 0)
                agg["deduped"]          += int(rep.get("deduped", 0)          or 0)
            except Exception as e:
                logger.error("[CLEANUP] user %s: %s", uid, e)
        logger.info("[CLEANUP] aggregate: %s", agg)
        return agg

    def start_cleanup_daemon(self, *,
                             interval_hours: int = None,
                             idle_seconds: int = None) -> None:
        """Spawn a low-priority daemon thread that periodically runs
        `cleanup_all_users` and prunes expired JWT revocation rows.
        Idempotent — subsequent calls return without spawning again.

        Configurable via env vars:
            JARVIS_CLEANUP_INTERVAL_HOURS  (default: 6)
            JARVIS_CLEANUP_IDLE_SECONDS    (default: 60)
            JARVIS_DISABLE_CLEANUP_DAEMON  (set to '1' to disable entirely)
        """
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return
        if interval_hours is None:
            try:
                interval_hours = int(os.environ.get(
                    "JARVIS_CLEANUP_INTERVAL_HOURS", "6"))
            except Exception:
                interval_hours = 6
        if idle_seconds is None:
            try:
                idle_seconds = int(os.environ.get(
                    "JARVIS_CLEANUP_IDLE_SECONDS", "60"))
            except Exception:
                idle_seconds = 60
        interval = max(60, int(interval_hours) * 3600)
        idle     = max(0,  int(idle_seconds))

        def _loop():
            # Initial back-off so unit tests / quick scripts that import
            # `memory` and exit don't trigger a wasteful cleanup pass.
            time.sleep(idle)
            while True:
                try:
                    self.cleanup_all_users()
                except Exception as e:
                    logger.error("[CLEANUP] iteration: %s", e)
                # JWT revocation sweep — best-effort, cheap.
                try:
                    from auth import db as _user_db
                    n = _user_db.prune_expired_tokens()
                    if n:
                        logger.info("[CLEANUP] pruned %d expired JWT revocations", n)
                except Exception as e:
                    logger.debug("[CLEANUP] JWT prune skipped: %s", e)
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True, name="jarvis-mem-cleanup")
        t.start()
        self._cleanup_thread = t
        logger.info("[CLEANUP] daemon started (interval=%dh, idle=%ds)",
                    interval_hours, idle_seconds)


# ══════════════════════════════════════════════════════════════════════════════
# Smart extractor patterns (compiled once, module-level)
# ══════════════════════════════════════════════════════════════════════════════
# Each tuple = (regex, category, default_importance, format_fn(match)→str).
# Patterns are ordered most-specific → least-specific. The fmt callback
# returns the canonical fact string we'll persist.
_SMART_PATTERNS = [
    # ── LEARNING (high importance — drives personalization) ─────────────────
    (re.compile(r"\bi(?:'?m| am)\s+(?:learning|studying|trying to learn|teaching myself)\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "learning", 4,
     lambda m: f"User is learning {m.group(1).strip().rstrip('.,!?').lower()}"),

    (re.compile(r"\bteach me\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "learning", 3,
     lambda m: f"User wants to learn {m.group(1).strip().rstrip('.,!?').lower()}"),

    (re.compile(r"\bi(?:'?m| am)\s+(?:practicing|practising)\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "learning", 3,
     lambda m: f"User is practicing {m.group(1).strip().rstrip('.,!?').lower()}"),

    # ── GOALS ───────────────────────────────────────────────────────────────
    (re.compile(r"\bi(?:'?m| am)\s+preparing\s+for\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "goals", 5,
     lambda m: f"User is preparing for {m.group(1).strip().rstrip('.,!?').lower()}"),

    (re.compile(r"\b(?:my goal|i want to|i'?m trying to|i need to)\s+(?:become|build|learn|master|finish|complete)\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "goals", 4,
     lambda m: f"User's goal: {m.group(1).strip().rstrip('.,!?').lower()}"),

    (re.compile(r"\bi(?:'?m| am)\s+working\s+on\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "projects", 3,
     lambda m: f"User is working on {m.group(1).strip().rstrip('.,!?').lower()}"),

    # ── CODING PREFERENCES ──────────────────────────────────────────────────
    (re.compile(r"\bi (?:prefer|use|code in|write in|like to use)\s+(python|java|c\+\+|c#|javascript|typescript|rust|go|ruby|php|swift|kotlin|scala|r|sql|html|css|node|react|vue|angular|django|flask|fastapi|spring|express)\b", re.IGNORECASE),
     "coding", 4,
     lambda m: f"User prefers {m.group(1).strip().lower()}"),

    (re.compile(r"\b(?:show me|give me|explain in)\s+(python|java|c\+\+|c#|javascript|typescript|rust|go|sql)\s+(?:examples?|code|syntax)\b", re.IGNORECASE),
     "coding", 3,
     lambda m: f"User prefers {m.group(1).strip().lower()} examples"),

    # ── COMMUNICATION STYLE ─────────────────────────────────────────────────
    (re.compile(r"\bi (?:like|prefer|want|need)\s+(short|concise|brief|quick|detailed|long|thorough|step[- ]by[- ]step)\s+(?:answers?|responses?|explanations?)\b", re.IGNORECASE),
     "communication_style", 4,
     lambda m: f"User prefers {m.group(1).strip().lower()} answers"),

    (re.compile(r"\b(?:keep it|make it|be)\s+(short|brief|concise|detailed|simple)\b", re.IGNORECASE),
     "communication_style", 3,
     lambda m: f"User prefers {m.group(1).strip().lower()} responses"),

    # ── PERSONAL CONTEXT (interests, profession) ─────────────────────────────
    (re.compile(r"\bi(?:'?m| am)\s+(?:a|an)\s+([a-z][a-z\s]{2,40}?)(?:\s+(?:and|in|at|with)|[.!?\n,]|$)", re.IGNORECASE),
     "personal", 3,
     lambda m: f"User is {m.group(1).strip().lower()}"),

    (re.compile(r"\bi (?:love|enjoy)\s+(.+?)(?:[.!?\n]|$)", re.IGNORECASE),
     "interests", 2,
     lambda m: f"User enjoys {m.group(1).strip().rstrip('.,!?').lower()}"),

    # ── EXAM / INTERVIEW (high importance) ──────────────────────────────────
    (re.compile(r"\bi have\s+(?:a|an)\s+(\w+\s+(?:interview|exam|test|assessment|placement))\s+(?:on|in|tomorrow|next|this)?", re.IGNORECASE),
     "goals", 5,
     lambda m: f"User has upcoming {m.group(1).strip().lower()}"),
]


# ══════════════════════════════════════════════════════════════════════════════
# Explicit "remember this..." detector — module-level helpers
# ══════════════════════════════════════════════════════════════════════════════
# Catches user utterances like:
#   "remember this: I prefer dark mode"
#   "remember that I'm preparing for SDE interviews"
#   "note that I use VS Code"
#   "save this — my goal is to learn Java by Friday"
#   "keep in mind I'm a beginner"
# Returns (content, category, importance) or None.

_REMEMBER_RE = re.compile(
    r"^\s*(?:please\s+)?(?:remember|note|save|keep in mind|don'?t forget|memorise|memorize|jarvis,?\s+remember)\s*"
    r"(?:this|that|the following)?\s*[:,\-\u2014]?\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Keyword groups for the heuristic categorizer. Each pattern uses word
# boundaries so e.g. "exam" doesn't match inside "examples". Rules are
# evaluated top-to-bottom; FIRST match wins. Most-specific intents are
# placed first so they don't get shadowed by a generic keyword (e.g. a
# "Python examples" message must categorize as `coding`, not `goals`,
# which is why we put `goals` AFTER `coding` and explicitly drop "exam"
# from the goals pattern).
_CAT_RULES = [
    ("communication_style", 4, re.compile(r"\b(short|concise|brief|detailed|thorough|verbose|terse)\s*(?:answers?|responses?|replies|explanations?)?\b", re.IGNORECASE)),
    ("communication_style", 4, re.compile(r"\bstep[- ]by[- ]step\b",                                                                                       re.IGNORECASE)),
    ("learning",            4, re.compile(r"\b(learning|studying|practicing|practising|beginner|novice|new to|intermediate|advanced|tutorial|teach me)\b", re.IGNORECASE)),
    ("goals",               5, re.compile(r"\b(interview|placement|deadline|preparing|prepare|my goal|aiming for|aim to)\b",                                re.IGNORECASE)),
    ("projects",            3, re.compile(r"\b(working on|building|developing|creating|making|side project|my project|engine|hackathon)\b",                  re.IGNORECASE)),
    ("coding",              4, re.compile(r"\b(python|java|c\+\+|c#|javascript|typescript|rust|go(?:lang)?|ruby|php|swift|kotlin|scala|sql|html|css|node|react|vue|angular|django|flask|fastapi|spring|express|code|coding|examples?)\b", re.IGNORECASE)),
    ("preferences",         4, re.compile(r"\b(prefer|like|love|enjoy|favourite|favorite|hate|dislike)\b",                                                  re.IGNORECASE)),
]

def detect_explicit_remember(text: str):
    """If text is an explicit memory command, return (content, category, importance).
    Otherwise None. Category is heuristic based on content."""
    if not text:
        return None
    m = _REMEMBER_RE.match(text.strip())
    if not m:
        return None
    content = m.group(1).strip().rstrip(".!?,").strip()
    if len(content) < 3:
        return None
    # Heuristic categorization — first matching rule wins
    cat, imp = "general", 3
    for rule_cat, rule_imp, rule_re in _CAT_RULES:
        if rule_re.search(content):
            cat, imp = rule_cat, rule_imp
            break
    else:
        cl = content.lower()
        if cl.startswith(("i am", "i'm")):
            cat, imp = "personal", 3
    # Normalize first-person to canonical form for natural recall
    canon = content
    if not canon.lower().startswith("user"):
        # Convert "I am X" → "User is X" for storage consistency
        canon = re.sub(r"^\s*I'?m\s+", "User is ", canon, count=1, flags=re.IGNORECASE)
        canon = re.sub(r"^\s*I am\s+",  "User is ", canon, count=1, flags=re.IGNORECASE)
        canon = re.sub(r"^\s*I\s+",     "User ",    canon, count=1, flags=re.IGNORECASE)
        canon = re.sub(r"^\s*my\s+",    "User's ",  canon, count=1, flags=re.IGNORECASE)
    return canon[:240], cat, imp


# Singleton
memory = JarvisMemory()
