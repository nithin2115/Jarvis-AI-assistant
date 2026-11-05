"""End-to-end smoke test for the new memory layer.

Run from repo root:
    python -m tests.test_memory_smoke

Exercises every newly-added surface: smart extractor, explicit-remember
detector, CRUD, search, build_context, get_messages, stats.
"""
import sys
import sqlite3
from pathlib import Path

# Windows consoles default to cp1252 which can't render unicode — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Use a throwaway DB so the test never pollutes the user's real memory store.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory as memory_mod  # noqa: E402

# Redirect to a temp DB BEFORE the singleton initialises tables.
import tempfile
_tmp = tempfile.NamedTemporaryFile(prefix="jarvis_memtest_", suffix=".db", delete=False)
_tmp.close()
memory_mod.DB_PATH = Path(_tmp.name)

# Re-init the singleton against the temp DB
memory_mod.memory = memory_mod.JarvisMemory()
mem = memory_mod.memory


def assert_eq(label, got, expected):
    ok = got == expected
    flag = "OK " if ok else "FAIL"
    print(f"[{flag}] {label}: got={got!r} expected={expected!r}")
    if not ok:
        sys.exit(1)


def assert_true(label, cond, detail=""):
    flag = "OK " if cond else "FAIL"
    # Only echo the detail string when the check actually FAILED — otherwise
    # the green path stays clean and easy to scan.
    if cond:
        print(f"[{flag}] {label}")
    else:
        print(f"[{flag}] {label}{(' :: ' + detail) if detail else ''}")
    if not cond:
        sys.exit(1)


print("\n── Phase 1: Smart extractor ─────────────────────────────────────")

cases = [
    ("I am learning Java for my placement",                "learning"),
    ("I'm preparing for SDE interviews next month",        "goals"),
    ("I prefer Python for backend work",                   "coding"),
    ("I like short answers please",                        "communication_style"),
    ("I love clean architecture",                          "interests"),
    ("I am a third year CS student",                       "personal"),
]
for text, expect_cat in cases:
    facts = mem.smart_extract(text)
    cats = [f["category"] for f in facts]
    assert_true(f"extract '{text[:40]}…'", expect_cat in cats,
                f"got categories={cats}")

print("\n── Phase 2: Explicit 'remember this...' detector ─────────────────")

remember_cases = [
    ("remember this: I'm preparing for Google interviews",  "goals"),
    ("note that I prefer Python examples",                  "coding"),
    ("save this — I like short answers",                    "communication_style"),
    ("Jarvis, remember I'm a beginner in Java",             "learning"),
    ("keep in mind I'm working on a chess engine",          "projects"),
]
for text, expect_cat in remember_cases:
    res = memory_mod.detect_explicit_remember(text)
    assert_true(f"remember '{text[:40]}…'", res is not None, "no match")
    content, cat, imp = res
    assert_true(f"  → cat={cat} (expected {expect_cat})", cat == expect_cat,
                f"content={content!r}")
    assert_true(f"  → imp in 1..5", 1 <= imp <= 5)

# Negative case — a normal question must NOT match
neg = memory_mod.detect_explicit_remember("what is polymorphism in Java")
assert_eq("non-remember stays None", neg, None)

print("\n── Phase 3: CRUD on `memories` table ────────────────────────────")

mem.clear_memories()
id1 = mem.add_memory("User is learning Java",   category="learning",            importance=4)
id2 = mem.add_memory("User prefers Python",     category="coding",              importance=3)
id3 = mem.add_memory("User prefers concise answers", category="communication_style", importance=4)
assert_true("3 inserts returned positive ids", id1 > 0 and id2 > 0 and id3 > 0,
            f"got {id1},{id2},{id3}")

# Dedup: re-adding the same content bumps existing row instead of inserting
id1_again = mem.add_memory("User is learning Java", category="learning", importance=4)
assert_eq("dedup returns same id", id1_again, id1)

all_mems = mem.list_memories()
assert_eq("list_memories count", len(all_mems), 3)

filtered = mem.list_memories(category="coding")
assert_eq("list_memories(category=coding) count", len(filtered), 1)
assert_eq("filtered content", filtered[0]["content"], "User prefers Python")

# Search
hits = mem.search_memories("java")
assert_true("search 'java' returns at least 1", len(hits) >= 1,
            f"got {[h['content'] for h in hits]}")

# Update
ok = mem.update_memory(id2, content="User prefers Python and Go", importance=5)
assert_true("update_memory ok", ok)
updated = [m for m in mem.list_memories() if m["id"] == id2][0]
assert_eq("updated content",    updated["content"],    "User prefers Python and Go")
assert_eq("updated importance", updated["importance"], 5)

# Delete
ok = mem.delete_memory(id3)
assert_true("delete_memory ok", ok)
remaining = mem.list_memories()
assert_eq("after delete count", len(remaining), 2)

# Categories
cats = mem.list_categories()
assert_true("list_categories returns dicts",
            all("category" in c and "count" in c for c in cats))

print("\n── Phase 4: build_context (full memory injection) ────────────────")

# Add a conversation turn so build_context has live history
mem.save_conversation("Teach me Java", "Java is a strongly-typed language…")
ctx = mem.build_context("polymorphism")
assert_true("ctx has Long-term Memory section",
            "Long-term Memory" in ctx,
            f"len={len(ctx)}")
assert_true("ctx contains 'learning'",   "learning" in ctx.lower())
assert_true("ctx contains 'java'",       "java" in ctx.lower())
assert_true("ctx has Recent Conversation",
            "Recent Conversation" in ctx)

print("\n── Phase 5: get_messages (OpenAI-format multi-turn) ──────────────")

mem.save_conversation("What is OOP?",       "OOP is a paradigm…")
mem.save_conversation("Give me an example", "Here is an example…")
msgs = mem.get_messages(n=5)
assert_true("messages is list of dicts",
            all(isinstance(m, dict) and "role" in m and "content" in m for m in msgs))
roles = [m["role"] for m in msgs]
assert_true("roles alternate user/assistant",
            roles[0] == "user" and roles[1] == "assistant",
            f"got {roles}")
assert_true("messages count >= 4 (3 turns × 2 - cap)", len(msgs) >= 4)

print("\n── Phase 6: stats ────────────────────────────────────────────────")
s = mem.stats()
assert_true("stats has 'memories' key", "memories" in s, f"got {list(s.keys())}")
assert_true("memories count > 0",        s["memories"] > 0, f"got {s['memories']}")

print("\n── Phase 7: clear_memories ───────────────────────────────────────")
n = mem.clear_memories()
assert_true("clear returned count > 0", n > 0, f"got {n}")
assert_eq("after clear list_memories", len(mem.list_memories()), 0)

print("\n✓ All memory smoke tests passed.")
