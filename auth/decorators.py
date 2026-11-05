"""
JARVIS Auth — Flask decorators for unified session/JWT identity.

Two decorators:
- @require_user      → 401 if not authenticated; otherwise sets g.user_id
- @optional_user     → never blocks; sets g.user_id if available

Identity resolution order:
    1. Authorization: Bearer <jwt>     (API clients, mobile, third-party)
    2. session["uid"]                  (browser flow: Google OAuth, demo)

Plus a tiny in-process token-bucket rate limiter for login/signup endpoints
(`@rate_limit("login", limit=5, window=60)`) — for production use a Redis-
backed limiter.
"""
from __future__ import annotations

import time
import logging
import threading
from functools import wraps
from collections import defaultdict, deque
from typing import Optional

from flask import g, request, session, jsonify

from . import jwt_auth as _jwt
from . import db as _db

logger = logging.getLogger("jarvis.auth.dec")


# ══════════════════════════════════════════════════════════════════════════════
# Identity resolution
# ══════════════════════════════════════════════════════════════════════════════

def resolve_user_id() -> Optional[str]:
    """Return the authenticated user_id or None.

    Tries JWT (Bearer header) FIRST so explicit API auth overrides any
    accidentally-stale browser session cookie. Then falls back to Flask
    session for the browser flow.
    """
    # 1. JWT bearer token
    auth_header = request.headers.get("Authorization", "")
    uid = _jwt.user_id_from_header(auth_header)
    if uid:
        return uid

    # 2. Flask session (existing browser flow — Google OAuth, demo user)
    sid = session.get("uid")
    if sid:
        return sid

    return None


def current_user_id() -> Optional[str]:
    """Get user_id from flask.g if set by a decorator, else resolve fresh."""
    cached = getattr(g, "user_id", None)
    if cached:
        return cached
    uid = resolve_user_id()
    if uid:
        g.user_id = uid
    return uid


# ══════════════════════════════════════════════════════════════════════════════
# Decorators
# ══════════════════════════════════════════════════════════════════════════════

def require_user(f):
    """Block the request with 401 if no valid identity. On success sets
    `g.user_id` so downstream code can call `current_user_id()` cheaply."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        uid = resolve_user_id()
        if not uid:
            return jsonify({"ok": False, "error": "authentication required"}), 401
        # Block deactivated/banned accounts
        try:
            row = _db.get_user(uid)
            if row and row.get("account_status") and row["account_status"] != "active":
                return jsonify({"ok": False, "error": "account disabled"}), 403
        except Exception:
            pass
        g.user_id = uid
        return f(*args, **kwargs)
    return wrapper


def optional_user(f):
    """Like require_user but never blocks; just sets g.user_id if available."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        uid = resolve_user_id()
        if uid:
            g.user_id = uid
        return f(*args, **kwargs)
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiter (in-process, per-IP, token bucket)
# ══════════════════════════════════════════════════════════════════════════════
# This is a lightweight defence — sufficient for login/signup endpoints in a
# single-process deployment. For multi-worker / horizontal scaling, swap to a
# Redis-backed limiter (e.g. flask-limiter with redis backend).

_buckets: dict = defaultdict(deque)
_buckets_lock = threading.Lock()


def _client_key() -> str:
    """Best-effort caller identification. Real IP first (X-Forwarded-For),
    then remote_addr. We DON'T trust XFF blindly in production; sites behind
    a reverse proxy should set ProxyFix or similar."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(bucket_name: str, limit: int = 5, window: int = 60):
    """Cap each (bucket, client) pair to `limit` requests per `window` seconds.
    Returns 429 when exceeded. Buckets are isolated so login/signup limits
    don't share counters."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            now    = time.time()
            cutoff = now - window
            key    = (bucket_name, _client_key())
            with _buckets_lock:
                q = _buckets[key]
                # Drop entries outside the window
                while q and q[0] < cutoff:
                    q.popleft()
                if len(q) >= limit:
                    retry_after = max(1, int(q[0] + window - now))
                    logger.warning("[RATE] %s blocked (%d in %ds) for %s",
                                   bucket_name, len(q), window, key[1])
                    resp = jsonify({"ok": False, "error": "rate limit exceeded",
                                    "retry_after": retry_after})
                    resp.status_code = 429
                    resp.headers["Retry-After"] = str(retry_after)
                    return resp
                q.append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator
