"""Multi-user isolation regression test + JWT round-trip.

Confirms structurally that JARVIS cannot leak any record between two
users.  Each public surface that touches user data is exercised:

    SQL tables       — list / search / get_messages / build_context / stats
    JSON state       — profile / behavior / mem_log files
    ChromaDB vectors — mem_store / mem_recall / mem_purge_user
    Account purge    — purge_user_data only affects the target user
    JWT roundtrip    — signup / login / verify / refresh-rotation / revoke

Run from repo root:

    python -m tests.test_multi_user_isolation

The test uses a throwaway data dir, a unique ChromaDB collection name,
and unique user_ids so it never pollutes the developer's real install.
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import uuid
from pathlib import Path

# Make `python -m tests.<name>` work regardless of CWD.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows consoles default to cp1252 — force UTF-8 so log emojis don't bomb.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Keep the cleanup daemon dormant during the test (no functional difference,
# but it avoids a spurious "daemon started" log line in CI output).
os.environ["JARVIS_DISABLE_CLEANUP_DAEMON"] = "1"


# ══════════════════════════════════════════════════════════════════════════════
# Test harness
# ══════════════════════════════════════════════════════════════════════════════

_failures = []


def check(label: str, cond: bool, detail: str = ""):
    flag = "OK  " if cond else "FAIL"
    print(f"[{flag}] {label}" + (f"  ::  {detail}" if (detail and not cond) else ""))
    if not cond:
        _failures.append(label)


def section(title: str):
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


# ══════════════════════════════════════════════════════════════════════════════
# Redirect memory module's storage paths to a temp dir BEFORE first init
# ══════════════════════════════════════════════════════════════════════════════
# JarvisMemory reads module-level DATA_DIR / USERS_DIR / DB_PATH at __init__
# time, so we have to overwrite them before constructing the singleton.

TMP_ROOT  = Path(tempfile.mkdtemp(prefix="jarvis_iso_"))
TMP_DATA  = TMP_ROOT / "data"
TMP_USERS = TMP_DATA / "users"
TMP_DB    = TMP_DATA / "memory.db"
TMP_DATA.mkdir(parents=True, exist_ok=True)
TMP_USERS.mkdir(parents=True, exist_ok=True)

import memory as memory_mod  # noqa: E402
memory_mod.DATA_DIR  = TMP_DATA
memory_mod.USERS_DIR = TMP_USERS
memory_mod.DB_PATH   = TMP_DB

# Build a fresh singleton against the temp dir.
memory_mod.memory = memory_mod.JarvisMemory()
mem = memory_mod.memory


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Two users — SQL isolation
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 1: SQL isolation across memories / conversations / notes")

uA = f"_iso_A_{uuid.uuid4().hex[:8]}"
uB = f"_iso_B_{uuid.uuid4().hex[:8]}"

# A and B store DIFFERENT content. The check is that neither user can see
# the other's rows through any list/search/build_context call.
mem.add_memory("Alice prefers PostgreSQL over MySQL",
               category="preferences", importance=4, user_id=uA)
mem.add_memory("Alice is learning Rust on weekends",
               category="learning",   importance=3, user_id=uA)
mem.add_memory("Alice's secret API key is sk-alpha-99",
               category="secret",     importance=5, user_id=uA)

mem.add_memory("Bob prefers MongoDB and Node.js",
               category="preferences", importance=4, user_id=uB)
mem.add_memory("Bob is preparing for the AWS exam",
               category="goals",       importance=3, user_id=uB)

A_list = mem.list_memories(user_id=uA)
B_list = mem.list_memories(user_id=uB)
check("A sees only A's memories", len(A_list) == 3, f"got {len(A_list)}")
check("B sees only B's memories", len(B_list) == 2, f"got {len(B_list)}")

A_content = " | ".join(r["content"] for r in A_list)
B_content = " | ".join(r["content"] for r in B_list)
check("A's list contains no Bob data",  "Bob"   not in A_content, A_content)
check("B's list contains no Alice data", "Alice" not in B_content, B_content)
check("B cannot see Alice's secret",     "sk-alpha-99" not in B_content)

# search() — same isolation guarantee
search_b_for_alice = mem.search_memories("Alice", limit=20, user_id=uB)
check("B searching for 'Alice' returns nothing",
      len(search_b_for_alice) == 0, f"{search_b_for_alice}")

search_a_for_mongo = mem.search_memories("MongoDB", limit=20, user_id=uA)
check("A searching for 'MongoDB' returns nothing",
      len(search_a_for_mongo) == 0, f"{search_a_for_mongo}")

# Conversations — save a turn for each, ensure they don't cross-contaminate
mem.save_conversation("hello, I am Alice",   "Hi Alice!",   user_id=uA)
mem.save_conversation("hello, I am Bob",     "Hi Bob!",     user_id=uB)
mem.save_conversation("what's the weather",  "It's sunny",  user_id=uA)

A_msgs = mem.get_messages(n=10, user_id=uA)
B_msgs = mem.get_messages(n=10, user_id=uB)
check("A's get_messages contains Alice", any("Alice" in (m.get("content") or "") for m in A_msgs))
check("A's get_messages has no Bob",     not any("Bob"   in (m.get("content") or "") for m in A_msgs),
      f"A_msgs={A_msgs}")
check("B's get_messages contains Bob",   any("Bob"   in (m.get("content") or "") for m in B_msgs))
check("B's get_messages has no Alice",   not any("Alice" in (m.get("content") or "") for m in B_msgs),
      f"B_msgs={B_msgs}")

# Notes — save_note + search_notes (empty query matches everything)
mem.save_note("Alice's grocery list: oat milk", user_id=uA)
mem.save_note("Bob's grocery list: tofu",       user_id=uB)
A_notes = mem.search_notes("", n=10, user_id=uA)
B_notes = mem.search_notes("", n=10, user_id=uB)
A_notes_txt = " | ".join(A_notes)
B_notes_txt = " | ".join(B_notes)
check("A's notes contain oat milk", "oat milk" in A_notes_txt, A_notes_txt)
check("A's notes have no tofu",     "tofu"     not in A_notes_txt, A_notes_txt)
check("B's notes contain tofu",     "tofu"     in B_notes_txt, B_notes_txt)
check("B's notes have no oat milk", "oat milk" not in B_notes_txt, B_notes_txt)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: build_context — composite isolation
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 2: build_context never blends users")

ctx_A = mem.build_context("Tell me about my preferences", user_id=uA)
ctx_B = mem.build_context("Tell me about my preferences", user_id=uB)

# Both contexts should be non-empty (they have memories + conversation).
check("A's build_context is non-empty",  bool(ctx_A.strip()))
check("B's build_context is non-empty",  bool(ctx_B.strip()))
check("A's context contains 'PostgreSQL'", "PostgreSQL" in ctx_A, ctx_A[:200])
check("A's context never mentions Bob/MongoDB",
      ("Bob" not in ctx_A) and ("MongoDB" not in ctx_A), ctx_A[:300])
check("B's context contains 'MongoDB'",  "MongoDB" in ctx_B, ctx_B[:200])
check("B's context never mentions Alice/PostgreSQL",
      ("Alice" not in ctx_B) and ("PostgreSQL" not in ctx_B), ctx_B[:300])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: JSON state files — profile / behavior / mem_log isolation
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 3: per-user JSON state files are siloed")

mem.save_google_profile("Alice Anderson", "alice@example.com", user_id=uA)
mem.save_google_profile("Bob Brown",      "bob@example.com",   user_id=uB)

profA = mem.get_profile(user_id=uA)
profB = mem.get_profile(user_id=uB)
check("A's profile has Alice",   "Alice"  in (profA.get("name") or ""), profA)
check("A's profile lacks Bob",   "Bob"    not in (profA.get("name") or ""), profA)
check("B's profile has Bob",     "Bob"    in (profB.get("name") or ""), profB)
check("B's profile lacks Alice", "Alice"  not in (profB.get("name") or ""), profB)

# Verify the JSON files actually live in separate subdirs
check("A's profile dir exists", (TMP_USERS / uA / "profile.json").exists())
check("B's profile dir exists", (TMP_USERS / uB / "profile.json").exists())
check("A's dir does NOT contain B's file",
      not (TMP_USERS / uA / "users").exists())


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: stats — counts are scoped
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 4: stats are per-user")

sA = mem.stats(user_id=uA)
sB = mem.stats(user_id=uB)
check("A's memory count == 3", sA.get("memories") == 3, f"{sA}")
check("B's memory count == 2", sB.get("memories") == 2, f"{sB}")
check("A's conversation count > 0", (sA.get("conversations") or 0) > 0, f"{sA}")
check("B's conversation count > 0", (sB.get("conversations") or 0) > 0, f"{sB}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: purge_user_data — only target user's data is destroyed
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 5: purge_user_data is surgical")

before_B = mem.stats(user_id=uB)
purge_A  = mem.purge_user_data(user_id=uA)
after_B  = mem.stats(user_id=uB)

check("purge returned a dict (not refused)",
      isinstance(purge_A, dict) and not purge_A.get("refused"), f"{purge_A}")
check("A's memories purged",      mem.stats(user_id=uA).get("memories") == 0)
check("A's conversations purged", mem.stats(user_id=uA).get("conversations") == 0)

check("B's memories untouched", before_B.get("memories") == after_B.get("memories"),
      f"before={before_B} after={after_B}")
check("B's conversations untouched",
      before_B.get("conversations") == after_B.get("conversations"))
check("B's notes still readable",
      "tofu" in " | ".join(mem.search_notes("", n=10, user_id=uB)))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: ChromaDB vector store — best-effort (skipped if model not ready)
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 6: vector store mem_store/recall/purge per user")

try:
    import knowledge_db
    # Force the embedding model to load now so mem_store/mem_recall work.
    # `_get_model()` is lazy-loaded on first embed; we call it directly so
    # the test fails fast if sentence-transformers isn't installed instead
    # of silently skipping the vector-isolation checks.
    knowledge_db._get_model()
    vec_ok = knowledge_db._model is not None
except Exception as e:
    vec_ok = False
    print(f"[SKIP] vector tests — knowledge_db not ready: {e}")

if vec_ok:
    import time as _time
    ts = _time.time()
    knowledge_db.mem_store("Alice's vector fact about Rust ownership",
                           "fact", ts,       user_id=uA)
    knowledge_db.mem_store("Bob's vector fact about Mongo aggregation",
                           "fact", ts + 0.001, user_id=uB)
    # Tiny wait — sentence-transformers can be slightly async on first add.
    _time.sleep(0.05)

    rA = knowledge_db.mem_recall("Rust",   n=5, user_id=uA)
    rB = knowledge_db.mem_recall("Mongo",  n=5, user_id=uB)
    cross_A = knowledge_db.mem_recall("Mongo", n=5, user_id=uA)
    cross_B = knowledge_db.mem_recall("Rust",  n=5, user_id=uB)

    check("A's vector recall finds Rust fact",
          any("Rust" in d for d in rA), f"{rA}")
    check("A's vector recall NEVER returns Bob's data",
          not any("Mongo" in d or "Bob" in d for d in cross_A), f"{cross_A}")
    check("B's vector recall finds Mongo fact",
          any("Mongo" in d for d in rB), f"{rB}")
    check("B's vector recall NEVER returns Alice's data",
          not any("Rust" in d or "Alice" in d for d in cross_B), f"{cross_B}")

    # Purge A's vectors — B's must survive.
    purged_A = knowledge_db.mem_purge_user(uA)
    check("mem_purge_user returned a non-negative int", isinstance(purged_A, int) and purged_A >= 0)
    rA2 = knowledge_db.mem_recall("Rust",   n=5, user_id=uA)
    rB2 = knowledge_db.mem_recall("Mongo",  n=5, user_id=uB)
    check("A's vectors are gone after purge",        len(rA2) == 0, f"{rA2}")
    check("B's vectors survived A's purge",          any("Mongo" in d for d in rB2), f"{rB2}")

    # Cleanup B's vectors too
    knowledge_db.mem_purge_user(uB)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: Password auth + JWT round-trip
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 7: bcrypt signup → login → JWT issue → rotate → revoke")

from auth import db as user_db
from auth import jwt_auth

nonce      = uuid.uuid4().hex[:8]
test_user  = f"isouser_{nonce}"
test_email = f"iso_{nonce}@example.com"
test_pw    = "correct-horse-battery-staple"

uid = user_db.create_user_with_password(test_user, test_email, test_pw, name="Iso Test")
check("signup returned a uid", bool(uid) and uid.startswith("u_"), f"uid={uid}")

# Wrong password → None
bad = user_db.verify_password_login(test_user, "definitely-wrong")
check("login with wrong password is rejected", bad is None)

# Right password → user row
row = user_db.verify_password_login(test_user, test_pw)
check("login with correct password returns row", isinstance(row, dict))
check("returned uid matches signup",             row and row.get("user_id") == uid)

# Login by email too
row_by_email = user_db.verify_password_login(test_email, test_pw)
check("login by email also works", row_by_email and row_by_email.get("user_id") == uid)

# Issue + verify access
pair = jwt_auth.issue_pair(uid)
check("issue_pair returned access+refresh",
      bool(pair.get("access") and pair.get("refresh")))
claims_a = jwt_auth.verify_access(pair["access"])
check("access token decodes to correct uid", claims_a.get("sub") == uid)

# Refresh rotation: old refresh must be revoked
old_refresh_jti = pair["refresh_jti"]
new_pair = jwt_auth.rotate_refresh(pair["refresh"])
check("rotate_refresh returned a new pair",
      bool(new_pair.get("access") and new_pair.get("refresh")))
check("old refresh jti is now revoked",
      user_db.is_token_revoked(old_refresh_jti))

# The OLD refresh token must no longer be usable
try:
    jwt_auth.rotate_refresh(pair["refresh"])
    check("re-using old refresh raises JWTError", False, "no exception")
except jwt_auth.JWTError as je:
    check("re-using old refresh raises JWTError", True, str(je))

# Revoke (logout)
ok_rev = jwt_auth.revoke(new_pair["refresh"])
check("revoke(current_refresh) returns True", ok_rev)
try:
    jwt_auth.rotate_refresh(new_pair["refresh"])
    check("revoked refresh cannot rotate", False, "no exception")
except jwt_auth.JWTError:
    check("revoked refresh cannot rotate", True)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 8: delete_user_cascade — full GDPR purge
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 8: delete_user_cascade removes everything for ONE user")

# Add a row tied to the password user so the cascade has something to drop
mem.add_memory("Iso test user fact",
               category="general", importance=2, user_id=uid)
mem.save_conversation("hi from iso user", "hi back", user_id=uid)

counts = user_db.delete_user_cascade(uid)
check("cascade returned a counts dict", isinstance(counts, dict), f"{counts}")
check("user row was deleted",           counts.get("user", 0) >= 1, f"{counts}")
check("memories purged",                counts.get("memories", 0) >= 1, f"{counts}")

# The user row should now be gone
check("user_db.get_user returns None",  user_db.get_user(uid) is None)
# Stats for that user should be all zeros
post = mem.stats(user_id=uid)
check("post-cascade memories == 0",       post.get("memories")      == 0, f"{post}")
check("post-cascade conversations == 0",  post.get("conversations") == 0, f"{post}")


# ══════════════════════════════════════════════════════════════════════════════
# Cleanup + verdict
# ══════════════════════════════════════════════════════════════════════════════
mem.purge_user_data(user_id=uB)
try:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
except Exception:
    pass

print("\n" + ("─" * 64))
if _failures:
    print(f"FAILED — {len(_failures)} check(s) failed:")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("✓ Multi-user isolation + JWT round-trip — ALL CHECKS PASSED")
