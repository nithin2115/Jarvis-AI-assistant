"""
JARVIS JWT Auth — access + refresh tokens with rotation
────────────────────────────────────────────────────────
- Access tokens (TTL 30 min)  : sent on every API request as Bearer
- Refresh tokens (TTL 14 days): used ONLY at /api/auth/refresh

Refresh-token rotation: every successful /refresh issues a NEW pair AND
records the OLD refresh token's `jti` in the `revoked_tokens` table. This
protects against token theft — once a stolen refresh token is used, the
legitimate user's next refresh will be rejected, surfacing the breach.

Secrets:
- JWT_SECRET env var preferred (set in production via .env)
- In dev, a random secret is generated once and persisted to data/.jwt_secret
  so tokens survive process restarts.
"""
from __future__ import annotations

import os
import uuid
import logging
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt as _jwt   # PyJWT

from . import db as _db

logger = logging.getLogger("jarvis.auth.jwt")

# ── Config ──
ALGORITHM       = "HS256"
ISSUER          = "jarvis"
AUDIENCE        = "jarvis-app"
ACCESS_TTL_MIN  = int(os.getenv("JWT_ACCESS_TTL_MIN",  "30"))     # 30 min
REFRESH_TTL_DAYS = int(os.getenv("JWT_REFRESH_TTL_DAYS", "14"))   # 14 days

# ── Secret ──
def _load_or_create_secret() -> str:
    """Return the HS256 signing secret. Order:
        1. JWT_SECRET env var (production)
        2. data/.jwt_secret file (persisted dev secret)
        3. Generate + persist a new 256-bit secret
    """
    env = os.getenv("JWT_SECRET", "").strip()
    if env and len(env) >= 32:
        return env
    secret_path = Path(__file__).parent.parent / "data" / ".jwt_secret"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        try:
            s = secret_path.read_text(encoding="utf-8").strip()
            if len(s) >= 32:
                return s
        except Exception:
            pass
    # Generate a fresh 64-char hex secret
    s = _secrets.token_hex(32)
    try:
        secret_path.write_text(s, encoding="utf-8")
        # On *nix this would be 0600; on Windows we rely on user dir ACLs.
        logger.warning("[JWT] Generated new dev secret at %s — set JWT_SECRET in production",
                       secret_path)
    except Exception as e:
        logger.error("[JWT] Could not persist secret: %s — using ephemeral", e)
    return s


_SECRET = _load_or_create_secret()


# ══════════════════════════════════════════════════════════════════════════════
# Issue
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_token(user_id: str, kind: str, ttl: timedelta,
                extra: dict = None) -> tuple[str, str, datetime]:
    """Encode a JWT. Returns (token_string, jti, expiry_datetime)."""
    jti = uuid.uuid4().hex
    exp = _now() + ttl
    claims = {
        "iss":   ISSUER,
        "aud":   AUDIENCE,
        "sub":   user_id,
        "iat":   int(_now().timestamp()),
        "exp":   int(exp.timestamp()),
        "jti":   jti,
        "kind":  kind,        # "access" | "refresh"
    }
    if extra:
        claims.update(extra)
    token = _jwt.encode(claims, _SECRET, algorithm=ALGORITHM)
    # PyJWT >=2 returns str; older returns bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, jti, exp


def issue_pair(user_id: str, *, scopes: list = None) -> dict:
    """Issue (access, refresh) pair for a user. Returns:
        {"access": "...", "refresh": "...",
         "access_expires_at": iso, "refresh_expires_at": iso,
         "user_id": "..."}"""
    extra = {"scopes": scopes or ["user"]}
    access,  _ajti, aexp = _make_token(user_id, "access",  timedelta(minutes=ACCESS_TTL_MIN), extra)
    refresh, rjti,  rexp = _make_token(user_id, "refresh", timedelta(days=REFRESH_TTL_DAYS), {})
    return {
        "access":             access,
        "refresh":            refresh,
        "access_expires_at":  aexp.isoformat(),
        "refresh_expires_at": rexp.isoformat(),
        "refresh_jti":        rjti,
        "user_id":            user_id,
        "token_type":         "Bearer",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Verify
# ══════════════════════════════════════════════════════════════════════════════

class JWTError(Exception):
    """Raised for any token verification failure (expired, bad sig, revoked,
    wrong kind). The message is safe to surface to clients."""


def _decode(token: str, expected_kind: str) -> dict:
    """Decode & validate a token. Raises JWTError on any problem."""
    if not token:
        raise JWTError("missing token")
    try:
        claims = _jwt.decode(
            token, _SECRET,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "jti", "kind"]},
        )
    except _jwt.ExpiredSignatureError:
        raise JWTError("token expired")
    except _jwt.InvalidAudienceError:
        raise JWTError("invalid audience")
    except _jwt.InvalidIssuerError:
        raise JWTError("invalid issuer")
    except _jwt.InvalidTokenError as e:
        raise JWTError(f"invalid token: {e}")

    if claims.get("kind") != expected_kind:
        raise JWTError(f"wrong token kind (expected {expected_kind})")

    # Per-token revocation
    if _db.is_token_revoked(claims["jti"]):
        raise JWTError("token revoked")

    # Wildcard revocation (e.g. password change forces logout-all)
    # We check by querying for any 'wildcard' row issued AFTER this token's iat.
    try:
        with _db._conn() as c:
            row = c.execute(
                "SELECT 1 FROM revoked_tokens "
                "WHERE user_id=? AND kind='wildcard' AND revoked_at > datetime(?, 'unixepoch') "
                "LIMIT 1",
                (claims["sub"], claims["iat"]),
            ).fetchone()
        if row:
            raise JWTError("session invalidated")
    except JWTError:
        raise
    except Exception as e:
        logger.error("[JWT] wildcard check failed: %s", e)

    return claims


def verify_access(token: str) -> dict:
    return _decode(token, "access")


def verify_refresh(token: str) -> dict:
    return _decode(token, "refresh")


# ══════════════════════════════════════════════════════════════════════════════
# Rotation + revocation
# ══════════════════════════════════════════════════════════════════════════════

def rotate_refresh(refresh_token: str) -> dict:
    """Verify the supplied refresh token, revoke its jti, and issue a fresh
    pair. The caller (POST /api/auth/refresh) returns the new pair to the
    client. Raises JWTError on any failure."""
    claims = verify_refresh(refresh_token)
    user_id = claims["sub"]

    # Revoke the old refresh BEFORE minting the new one — if the new mint
    # somehow fails we still leave the system in a safe state (user just
    # has to log in again).
    exp_iso = datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()
    _db.revoke_token(claims["jti"], user_id, expires_at=exp_iso, kind="refresh")

    return issue_pair(user_id)


def revoke(refresh_token: str) -> bool:
    """Add this refresh token's jti to the revocation list. Used on logout."""
    try:
        claims = verify_refresh(refresh_token)
    except JWTError:
        return False
    exp_iso = datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()
    return _db.revoke_token(claims["jti"], claims["sub"],
                            expires_at=exp_iso, kind="refresh")


# ══════════════════════════════════════════════════════════════════════════════
# Convenience: extract user_id from a Bearer header
# ══════════════════════════════════════════════════════════════════════════════

def user_id_from_header(authorization: str) -> Optional[str]:
    """Parse 'Authorization: Bearer <token>' and return user_id, or None.
    Never raises — returns None on any failure so callers can fall back to
    session auth without try/except boilerplate."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        claims = verify_access(parts[1])
        return claims.get("sub")
    except JWTError:
        return None
    except Exception as e:
        logger.debug("[JWT] header parse failed: %s", e)
        return None
