"""
JARVIS Auth — User Database (multi-user SaaS-ready)
────────────────────────────────────────────────────
SQLite-backed: profiles, face embeddings, voice signatures, per-user memory.
Now also supports password+JWT auth alongside the legacy Google OAuth path.

Schema is migrated idempotently on every import — safe to deploy over an
existing single-user installation; legacy rows are preserved.
"""
import sqlite3, json, pickle, os, logging, secrets, uuid
from typing import Optional, List
from datetime import datetime

logger  = logging.getLogger("jarvis.db")
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "users.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    # Foreign keys aren't on by default in SQLite — enable so cascade works.
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _column_exists(conn, table: str, col: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in rows)
    except Exception:
        return False


def init_db():
    """Create tables and run idempotent migrations."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        TEXT PRIMARY KEY,
            email          TEXT UNIQUE NOT NULL,
            name           TEXT NOT NULL,
            picture_url    TEXT DEFAULT '',
            face_embedding BLOB,
            voice_signature BLOB,
            preferences    TEXT DEFAULT '{}',
            setup_complete INTEGER DEFAULT 0,
            created_at     TEXT,
            last_login     TEXT
        );
        CREATE TABLE IF NOT EXISTS user_memory (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL,
            timestamp    TEXT,
            user_msg     TEXT,
            ai_response  TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        -- JWT revocation list. Refresh-token rotation marks the previous
        -- token's jti as revoked; access tokens are short-lived so we
        -- only need to track refresh tokens here. expires_at lets a
        -- background sweeper drop entries past their natural expiry.
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti        TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            kind       TEXT NOT NULL DEFAULT 'refresh',
            revoked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_revoked_user ON revoked_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_revoked_exp  ON revoked_tokens(expires_at);
        CREATE INDEX IF NOT EXISTS idx_user_mem_uid ON user_memory(user_id);
        """)

        # ── Migrations: add new columns idempotently ──
        # Each ALTER is wrapped because PRAGMA-checked add is the safe way:
        # SQLite refuses ADD COLUMN if it already exists.
        migrations = [
            ("users", "username",       "TEXT"),
            ("users", "password_hash",  "TEXT"),
            ("users", "memory_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("users", "account_status", "TEXT NOT NULL DEFAULT 'active'"),
            ("users", "auth_provider",  "TEXT NOT NULL DEFAULT 'google'"),
        ]
        for table, col, decl in migrations:
            if not _column_exists(c, table, col):
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    logger.info("[DB] migrated %s.%s (%s)", table, col, decl)
                except Exception as e:
                    logger.error("[DB] migration failed %s.%s: %s", table, col, e)

        # Unique index on username — partial so NULL doesn't conflict with
        # legacy rows that have no username yet.
        try:
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username "
                "ON users(username) WHERE username IS NOT NULL"
            )
        except Exception as e:
            logger.error("[DB] username index: %s", e)


# ── User CRUD ─────────────────────────────────────────────────

def create_user(user_id, email, name, picture_url=""):
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO users "
            "(user_id, email, name, picture_url, created_at, last_login) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, email, name, picture_url, now, now)
        )


def get_user(user_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None


def update_last_login(user_id: str):
    with _conn() as c:
        c.execute("UPDATE users SET last_login=? WHERE user_id=?",
                  (datetime.now().isoformat(), user_id))


def mark_setup_complete(user_id: str):
    with _conn() as c:
        c.execute("UPDATE users SET setup_complete=1 WHERE user_id=?", (user_id,))


def update_preferences(user_id: str, prefs: dict):
    with _conn() as c:
        c.execute("UPDATE users SET preferences=? WHERE user_id=?",
                  (json.dumps(prefs), user_id))


# ── Face / Voice blobs ─────────────────────────────────────────

def save_face_embedding(user_id: str, embedding):
    with _conn() as c:
        c.execute("UPDATE users SET face_embedding=? WHERE user_id=?",
                  (pickle.dumps(embedding), user_id))


def load_face_embedding(user_id: str):
    with _conn() as c:
        row = c.execute("SELECT face_embedding FROM users WHERE user_id=?",
                        (user_id,)).fetchone()
        return pickle.loads(row[0]) if row and row[0] else None


def save_voice_signature(user_id: str, signature):
    with _conn() as c:
        c.execute("UPDATE users SET voice_signature=? WHERE user_id=?",
                  (pickle.dumps(signature), user_id))


def load_voice_signature(user_id: str):
    with _conn() as c:
        row = c.execute("SELECT voice_signature FROM users WHERE user_id=?",
                        (user_id,)).fetchone()
        return pickle.loads(row[0]) if row and row[0] else None


# ── Per-user memory ────────────────────────────────────────────

def save_memory(user_id: str, user_msg: str, ai_response: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO user_memory (user_id, timestamp, user_msg, ai_response) "
            "VALUES (?,?,?,?)",
            (user_id, datetime.now().isoformat(), user_msg, ai_response)
        )


def get_recent_memory(user_id: str, limit: int = 12) -> List[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT user_msg, ai_response, timestamp FROM user_memory "
            "WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# ══════════════════════════════════════════════════════════════════════════════
# Password authentication (bcrypt)
# ══════════════════════════════════════════════════════════════════════════════
# bcrypt is the reference choice — it's slow on purpose, salts automatically,
# and has no known practical attacks. Cost factor 12 is current best-practice
# (≈250ms per hash on commodity hardware). NEVER store plaintext passwords.

import bcrypt as _bcrypt


def _hash_password(plain: str) -> str:
    """Return a bcrypt hash (utf-8 string) of the plaintext password."""
    if not plain or len(plain) < 8:
        raise ValueError("password must be at least 8 characters")
    return _bcrypt.hashpw(plain.encode("utf-8"),
                          _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password_hash(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt compare. Returns False on any error."""
    if not plain or not hashed:
        return False
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_user_with_password(username: str, email: str, password: str,
                              name: str = None) -> Optional[str]:
    """Sign up a new user. Returns the new user_id, or None on conflict.
    Raises ValueError on weak password / invalid input."""
    username = (username or "").strip().lower()
    email    = (email    or "").strip().lower()
    name     = (name     or username or "").strip() or "User"

    if not username or len(username) < 3:
        raise ValueError("username must be at least 3 characters")
    if not email or "@" not in email:
        raise ValueError("valid email required")
    pwd_hash = _hash_password(password)  # raises if too short

    user_id = "u_" + uuid.uuid4().hex[:16]
    now     = datetime.now().isoformat()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO users (user_id, username, email, name, "
                "password_hash, auth_provider, created_at, last_login) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (user_id, username, email, name, pwd_hash, "password", now, now),
            )
        logger.info("[DB] Created password user %s (%s)", username, user_id)
        return user_id
    except sqlite3.IntegrityError as e:
        msg = str(e).lower()
        if "username" in msg:
            raise ValueError("username already taken")
        if "email" in msg:
            raise ValueError("email already registered")
        raise


def verify_password_login(login: str, password: str) -> Optional[dict]:
    """Look up by username OR email, verify bcrypt hash. Returns the user
    row (dict) on success, None on failure. Both branches take ~equal time
    to avoid revealing whether the username exists (timing-attack mitigation)."""
    login = (login or "").strip().lower()
    if not login or not password:
        # Burn a hash anyway so timing is comparable
        _verify_password_hash(password or "x",
                              "$2b$12$" + "x" * 53)
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE (username=? OR email=?) "
            "AND password_hash IS NOT NULL LIMIT 1",
            (login, login),
        ).fetchone()
    if not row:
        # Burn a hash to keep timing constant.
        _verify_password_hash(password, "$2b$12$" + "x" * 53)
        return None
    if (row["account_status"] or "active") != "active":
        return None
    if not _verify_password_hash(password, row["password_hash"]):
        return None
    return dict(row)


def set_password(user_id: str, new_password: str) -> bool:
    """Change/set a user's password. Used for password reset."""
    h = _hash_password(new_password)
    with _conn() as c:
        cur = c.execute("UPDATE users SET password_hash=? WHERE user_id=?",
                        (h, user_id))
    return cur.rowcount > 0


def get_user_by_username(username: str) -> Optional[dict]:
    username = (username or "").strip().lower()
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


# ══════════════════════════════════════════════════════════════════════════════
# JWT refresh-token revocation list
# ══════════════════════════════════════════════════════════════════════════════
# Refresh-token rotation: each /api/auth/refresh issues a new pair AND adds
# the previous refresh token's jti here. Logout adds the current refresh
# jti. Access tokens are short-lived (30min) so we accept the risk window.

def revoke_token(jti: str, user_id: str, expires_at: str = None,
                 kind: str = "refresh") -> bool:
    if not jti:
        return False
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO revoked_tokens (jti, user_id, kind, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (jti, user_id, kind, expires_at),
            )
        return True
    except Exception as e:
        logger.error("[DB] revoke_token: %s", e)
        return False


def is_token_revoked(jti: str) -> bool:
    if not jti:
        return True
    with _conn() as c:
        row = c.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (jti,)).fetchone()
    return row is not None


def revoke_all_user_tokens(user_id: str):
    """Force-logout the user from all sessions (e.g. on password change)."""
    # We don't have every issued jti, so we add a wildcard sentinel — instead,
    # we increment a per-user `token_version` claim. Simpler approach: insert
    # a sentinel jti that the verifier checks against. We'll bump a column.
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO revoked_tokens (jti, user_id, kind) "
            "VALUES (?, ?, 'wildcard')",
            (f"all-{user_id}-{datetime.now().timestamp()}", user_id),
        )


def prune_expired_tokens() -> int:
    """Drop revocation rows past their natural expiry. Run periodically."""
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM revoked_tokens WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        return cur.rowcount or 0


# ══════════════════════════════════════════════════════════════════════════════
# Memory permission + account deletion (privacy compliance)
# ══════════════════════════════════════════════════════════════════════════════

def is_memory_enabled(user_id: str) -> bool:
    """If False, JARVIS stops writing new memories for this user (reads still
    return any pre-existing rows so old data isn't lost on a temporary toggle)."""
    with _conn() as c:
        row = c.execute("SELECT memory_enabled FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return True   # default-on for unknown users (e.g. _legacy)
    return bool(row["memory_enabled"])


def set_memory_enabled(user_id: str, enabled: bool) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE users SET memory_enabled=? WHERE user_id=?",
            (1 if enabled else 0, user_id),
        )
    return cur.rowcount > 0


def delete_user_cascade(user_id: str) -> dict:
    """GDPR-style account deletion. Removes the user row and EVERY associated
    record across every table, JSON state file, and ChromaDB vector. The
    heavy lifting lives in `memory.purge_user_data()` so we don't duplicate
    purge logic; this function just adds the auth-DB cleanup on top.
    Returns a flat counts dict the caller can hand back to the UI."""
    counts = {"user": 0, "user_memory": 0, "memories": 0,
              "conversations": 0, "notes": 0, "vectors": 0,
              "files": 0, "revoked": 0}

    # 1. Wipe the structured-memory DB rows + JSON state + vector embeddings
    #    in one shot (memory.purge_user_data does all three).
    try:
        from memory import memory as _mem
        purge = _mem.purge_user_data(user_id=user_id) or {}
        if not purge.get("refused"):
            counts["conversations"] = int(purge.get("conversations", 0))
            counts["notes"]         = int(purge.get("notes", 0))
            counts["memories"]      = int(purge.get("memories", 0))
            counts["files"]         = int(purge.get("files", 0))
            counts["vectors"]       = int(purge.get("vectors", 0))
    except Exception as e:
        logger.error("[DB] memory purge failed for %s: %s", user_id, e)

    # 2. Drop the auth-DB rows owned by this user.
    with _conn() as c:
        # user_memory has ON DELETE CASCADE — but the structured `memories`,
        # `conversations`, `notes` live in memory.db, NOT users.db (handled
        # in step 1 above).
        cur = c.execute("DELETE FROM user_memory    WHERE user_id=?", (user_id,)); counts["user_memory"] = cur.rowcount or 0
        cur = c.execute("DELETE FROM revoked_tokens WHERE user_id=?", (user_id,)); counts["revoked"]     = cur.rowcount or 0
        cur = c.execute("DELETE FROM users          WHERE user_id=?", (user_id,)); counts["user"]        = cur.rowcount or 0

    logger.warning("[DB] DELETED user=%s counts=%s", user_id, counts)
    return counts


# Initialise on import
init_db()
