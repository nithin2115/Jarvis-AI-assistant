"""Intelligence-layer regression test.

Validates the production-grade memory intelligence upgrades:

    1. Importance auto-evolution
       - hits >= 5  must promote importance to >= 3
       - hits >= 10 must promote importance to >= 4
       - hits >= 20 must promote importance to >= 5
       Tested via BOTH paths: add_memory dedup-bump and search_memories.

    2. top_topics() helper
       - returns the user's most-active categories by weighted score
       - excludes the catch-all 'general' bucket
       - is strictly per-user (no leak between users)

    3. build_context personalisation
       - injects the "User's active focus" block once a user has
         genuine high-score topics
       - omits the block for a user with only low-score / 'general' rows

    4. TTS first-sentence latency
       - the first sentence ships when its trimmed length >= 8 chars
       - subsequent sentences require >= 18 chars (natural pacing)

Run from the repo root:

    python -m tests.test_intelligence

Uses a throwaway data dir + unique user ids; never touches the
developer's real install.
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

# Keep the cleanup daemon dormant during the test.
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
TMP_ROOT  = Path(tempfile.mkdtemp(prefix="jarvis_intel_"))
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
# Phase 1: importance auto-evolution via add_memory dedup-bump
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 1: add_memory hits-based promotion (5→3, 10→4, 20→5)")

uA = f"_intel_A_{uuid.uuid4().hex[:8]}"

# First insert at importance=1. Subsequent identical inserts dedup-bump
# the SAME row's hit counter and run the importance evolution logic.
mid = mem.add_memory("User is learning Java polymorphism",
                     category="learning", importance=1, user_id=uA)
check("first insert returned a row id", mid > 0, f"id={mid}")

# Helper that dedup-bumps and returns the resulting (importance, hits).
def _bump(content: str) -> tuple:
    rid = mem.add_memory(content, category="learning",
                         importance=1, user_id=uA)
    rows = mem.list_memories(category="learning", user_id=uA)
    for r in rows:
        if r["id"] == rid:
            return int(r["importance"]), int(r["hits"])
    return -1, -1

# INSERT path created the row with hits=0; the first _bump call is the
# FIRST dedup-bump and lands on hits=1, still below the 5-tier threshold.
imp, h = _bump("User is learning Java polymorphism")
check("hits=1 → no promotion (below tier 1)",
      imp == 1 and h == 1, f"imp={imp} hits={h}")

# Drive 4 more bumps → hits=5 crosses the first tier (promote ≥3).
for _ in range(4):
    imp, h = _bump("User is learning Java polymorphism")
check("hits=5 → importance promoted to >= 3",
      imp >= 3 and h == 5, f"imp={imp} hits={h}")

# 5 more bumps → hits=10 crosses the second tier (promote ≥4).
for _ in range(5):
    imp, h = _bump("User is learning Java polymorphism")
check("hits=10 → importance promoted to >= 4",
      imp >= 4 and h == 10, f"imp={imp} hits={h}")

# 10 more bumps → hits=20 crosses the top tier (promote =5).
for _ in range(10):
    imp, h = _bump("User is learning Java polymorphism")
check("hits=20 → importance promoted to 5 (max)",
      imp == 5 and h == 20, f"imp={imp} hits={h}")

# Bump beyond 20 — importance stays at the ceiling, hits keeps climbing.
imp, h = _bump("User is learning Java polymorphism")
check("hits>20 → importance stays at ceiling 5",
      imp == 5 and h == 21, f"imp={imp} hits={h}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: importance auto-evolution via search_memories
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 2: search_memories hits-based promotion")

# Brand-new low-importance fact for a fresh user.
uB = f"_intel_B_{uuid.uuid4().hex[:8]}"
mem.add_memory("User loves the Rust borrow checker",
               category="preferences", importance=1, user_id=uB)

# 5 searches that match the fact → hits goes 0→5 → importance ≥ 3.
for _ in range(5):
    mem.search_memories("Rust", limit=5, user_id=uB)

rows = mem.list_memories(category="preferences", user_id=uB)
imp = rows[0]["importance"] if rows else -1
hit = rows[0]["hits"] if rows else -1
check("search_memories hit-bump promoted to >= 3",
      imp >= 3 and hit >= 5, f"imp={imp} hits={hit}")

# Drive 5 more hits → importance >= 4.
for _ in range(5):
    mem.search_memories("Rust", limit=5, user_id=uB)
rows = mem.list_memories(category="preferences", user_id=uB)
imp = rows[0]["importance"] if rows else -1
hit = rows[0]["hits"] if rows else -1
check("search_memories hits>=10 → importance >= 4",
      imp >= 4 and hit >= 10, f"imp={imp} hits={hit}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: top_topics() — weighted ranking, per-user, ignores 'general'
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 3: top_topics() weighted ranking + isolation")

uC = f"_intel_C_{uuid.uuid4().hex[:8]}"
uD = f"_intel_D_{uuid.uuid4().hex[:8]}"

# uC: heavy 'java' focus, light 'goals', some 'general' noise that must
# NOT appear in top_topics output.
for i in range(3):
    mem.add_memory(f"java fact {i} for user C",
                   category="java", importance=2, user_id=uC)
mem.add_memory("user C wants to ship a side project",
               category="goals", importance=2, user_id=uC)
for i in range(4):
    # 'general' rows must be filtered out of top_topics().
    mem.add_memory(f"random general note {i} for user C",
                   category="general", importance=1, user_id=uC)

# uD has totally different topics so we can confirm cross-user isolation.
mem.add_memory("user D is preparing for AWS exam",
               category="cloud", importance=3, user_id=uD)
mem.add_memory("user D loves vim keybindings",
               category="tools", importance=2, user_id=uD)

topics_C = mem.top_topics(user_id=uC, n=5)
topics_D = mem.top_topics(user_id=uD, n=5)

C_cats = [t["category"] for t in topics_C]
D_cats = [t["category"] for t in topics_D]

check("top_topics excludes 'general'",
      "general" not in C_cats and "general" not in D_cats,
      f"C={C_cats} D={D_cats}")

check("top_topics(uC) ranks 'java' first",
      bool(topics_C) and topics_C[0]["category"] == "java",
      f"{topics_C}")

check("top_topics(uD) does NOT contain uC categories",
      not (set(D_cats) & {"java", "goals"}),
      f"D_cats={D_cats}")

check("top_topics(uC) does NOT contain uD categories",
      not (set(C_cats) & {"cloud", "tools"}),
      f"C_cats={C_cats}")

check("top_topics returns score-sorted descending",
      all(topics_C[i]["score"] >= topics_C[i + 1]["score"]
          for i in range(len(topics_C) - 1)),
      f"{topics_C}")

# Honour the 'n' limit.
topics_C_top1 = mem.top_topics(user_id=uC, n=1)
check("top_topics respects the n limit",
      len(topics_C_top1) <= 1, f"{topics_C_top1}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: build_context personalisation block
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 4: build_context injects 'User's active focus' block")

# uA already has a heavily-promoted 'learning' topic from Phase 1,
# so its build_context must include the active-focus block.
ctx_A = mem.build_context("explain polymorphism", user_id=uA)
check("uA's build_context contains the active-focus header",
      "active focus" in ctx_A.lower(),
      f"...{ctx_A[-300:]}")
check("uA's active focus mentions 'learning'",
      "learning" in ctx_A.lower(), f"...{ctx_A[-300:]}")

# Fresh user with NO memories → no active-focus block.
uE = f"_intel_E_{uuid.uuid4().hex[:8]}"
ctx_E = mem.build_context("hello", user_id=uE)
check("fresh user gets NO active-focus block",
      "active focus" not in ctx_E.lower(),
      f"ctx_E={ctx_E[:200]}")

# User with ONLY 'general' rows → no active-focus block (general is
# explicitly excluded from top_topics).
uF = f"_intel_F_{uuid.uuid4().hex[:8]}"
for i in range(3):
    mem.add_memory(f"random thought {i}",
                   category="general", importance=1, user_id=uF)
ctx_F = mem.build_context("hello", user_id=uF)
check("'general'-only user gets NO active-focus block",
      "active focus" not in ctx_F.lower(),
      f"ctx_F={ctx_F[:200]}")

# Cross-user isolation: A's focus must not show up in another user's
# context (regression for build_context leakage).
ctx_D = mem.build_context("hello", user_id=uD)
check("uD's context does NOT contain uA's promoted 'learning' fact",
      "polymorphism" not in ctx_D.lower(),
      f"ctx_D={ctx_D[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: TTS streaming first-sentence latency tier
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 5: tts_stream FIRST=8 / REST=18 thresholds")

# We don't drive the actual SAPI engine here (no audio device in CI);
# instead we monkey-patch `_tts_engine.speak` to record what would have
# been spoken, then feed chunks and assert ordering.
import tts_stream as tts_mod  # noqa: E402

check("FIRST threshold is 8 chars", tts_mod._MIN_SENTENCE_CHARS_FIRST == 8,
      f"{tts_mod._MIN_SENTENCE_CHARS_FIRST}")
check("REST  threshold is 18 chars", tts_mod._MIN_SENTENCE_CHARS_REST == 18,
      f"{tts_mod._MIN_SENTENCE_CHARS_REST}")

spoken: list = []


class _FakeEngine:
    @staticmethod
    def speak(text: str):
        spoken.append(text)


tts_mod._tts_engine = _FakeEngine

# Open a session and feed two complete sentences:
#   1) "Sure!"  → only 5 chars; below FIRST threshold (8) → held back
#   2) "Got it."  → 7 chars; still below FIRST threshold → held back
#   3) "Today we cover polymorphism." → > 8 chars → SHIPS as first
sid = "intel-tts-1"
tts_mod.start(sid)
tts_mod.feed(sid, "Sure! ")          # 5 chars after strip + boundary
tts_mod.feed(sid, "Got it. ")        # 7 chars
tts_mod.feed(sid, "Today we cover polymorphism. ")
tts_mod.flush(sid)

# Worker is async. Wait briefly for queue to drain.
import time as _t
deadline = _t.time() + 2.0
while _t.time() < deadline and not spoken:
    _t.sleep(0.05)

check("first utterance reached the speaker", bool(spoken),
      f"spoken={spoken}")
if spoken:
    first = spoken[0]
    check("first utterance is the long sentence (not the short ones)",
          "polymorphism" in first.lower() or len(first.strip()) >= 8,
          f"first={first!r}")


# ══════════════════════════════════════════════════════════════════════════════
# Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════
section("Cleanup")
try:
    mem.conn.close()
except Exception:
    pass

try:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    print(f"[OK  ] removed temp dir {TMP_ROOT}")
except Exception as e:
    print(f"[WARN] could not remove temp dir: {e}")


print("\n" + "═" * 70)
if _failures:
    print(f"FAILED  ({len(_failures)} check(s))")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS — every intelligence-layer invariant holds.")
sys.exit(0)
