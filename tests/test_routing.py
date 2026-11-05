"""
Phase 2 — Weighted intent-routing regression suite.

Pure-function tests (no network): they exercise router.route_agent and
router.classify_intent only. Run:
    python -m pytest tests/test_routing.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import pytest
import router
from router import (
    route_agent,
    classify_intent,
    DSA_AGENT,
    SQL_AGENT,
    SYSTEM_DESIGN_AGENT,
    PROJECT_BUILDER_AGENT,
    DEBUG_AGENT,
    CODE_REVIEW_AGENT,
    FULLSTACK_AGENT,
    GENERAL_ASSISTANT_AGENT,
)

# ---------------------------------------------------------------------------
# 50 representative routing cases spanning every agent + the general fallback.
# ---------------------------------------------------------------------------
ROUTING_CASES = [
    # --- DEBUG (7) ---
    ("My app throws a NullPointerException", DEBUG_AGENT),
    ("I'm getting a segmentation fault", DEBUG_AGENT),
    ("This throws an exception at runtime", DEBUG_AGENT),
    ("How do I fix this bug", DEBUG_AGENT),
    ("Stack trace shows IndexOutOfBounds", DEBUG_AGENT),
    ("My program is not working", DEBUG_AGENT),
    ("Why won't this compile", DEBUG_AGENT),

    # --- PROJECT BUILDER (6) ---
    ("Build a Spring Boot React app", PROJECT_BUILDER_AGENT),
    ("Create a project with Django", PROJECT_BUILDER_AGENT),
    ("Scaffold a MERN stack application", PROJECT_BUILDER_AGENT),
    ("Generate a Flask boilerplate", PROJECT_BUILDER_AGENT),
    ("Set up a Next.js project with Docker", PROJECT_BUILDER_AGENT),
    ("Build a todo app", PROJECT_BUILDER_AGENT),

    # --- SYSTEM DESIGN (7) ---
    ("Design WhatsApp", SYSTEM_DESIGN_AGENT),
    ("Design a URL shortener for a billion users", SYSTEM_DESIGN_AGENT),
    ("Design a rate limiter", SYSTEM_DESIGN_AGENT),
    ("How would you design a scalable distributed system", SYSTEM_DESIGN_AGENT),
    ("Design Netflix video streaming", SYSTEM_DESIGN_AGENT),
    ("Explain consistent hashing and sharding", SYSTEM_DESIGN_AGENT),
    ("Design a web crawler", SYSTEM_DESIGN_AGENT),

    # --- SQL (6) ---
    ("Optimize this PostgreSQL query", SQL_AGENT),
    ("Write a complex SQL join across three tables", SQL_AGENT),
    ("How do I add an index to speed up a slow query", SQL_AGENT),
    ("Explain analyze shows a sequential scan", SQL_AGENT),
    ("Create a materialized view for reporting", SQL_AGENT),
    ("Partition a large MySQL table by date", SQL_AGENT),

    # --- CODE REVIEW (4) ---
    ("Review this Java code", CODE_REVIEW_AGENT),
    ("Can you refactor this function", CODE_REVIEW_AGENT),
    ("Please review my pull request", CODE_REVIEW_AGENT),
    ("Analyze this code for improvements", CODE_REVIEW_AGENT),

    # --- DSA (9) ---
    ("Implement an LFU cache", DSA_AGENT),
    ("Sliding window median problem", DSA_AGENT),
    ("Find the kth largest element in an array", DSA_AGENT),
    ("Dijkstra shortest path algorithm", DSA_AGENT),
    ("What is the time complexity of quicksort", DSA_AGENT),
    ("Reverse a linked list", DSA_AGENT),
    ("Detect a cycle in a graph using DFS", DSA_AGENT),
    ("Solve the 0/1 knapsack problem with DP", DSA_AGENT),
    ("Two sum problem", DSA_AGENT),

    # --- FULLSTACK (4) ---
    ("Build a REST API with JWT authentication", FULLSTACK_AGENT),
    ("Implement OAuth login on the backend", FULLSTACK_AGENT),
    ("Set up RBAC with Spring Security", FULLSTACK_AGENT),
    ("Create a React component for the frontend", FULLSTACK_AGENT),

    # --- GENERAL (7) ---
    ("What is the capital of France", GENERAL_ASSISTANT_AGENT),
    ("Tell me a joke", GENERAL_ASSISTANT_AGENT),
    ("Who won the world cup in 2018", GENERAL_ASSISTANT_AGENT),
    ("Explain photosynthesis", GENERAL_ASSISTANT_AGENT),
    ("What's the weather like today", GENERAL_ASSISTANT_AGENT),
    ("Recommend a good book to read", GENERAL_ASSISTANT_AGENT),
    ("How are you doing", GENERAL_ASSISTANT_AGENT),
]


def test_case_count():
    """Guard: we maintain at least 50 routing assertions."""
    assert len(ROUTING_CASES) >= 50


@pytest.mark.parametrize("query,expected", ROUTING_CASES)
def test_route_agent(query, expected):
    got = route_agent(query)
    assert got == expected, (
        f"route_agent({query!r}) -> {got}, expected {expected}. "
        f"explain: {classify_intent(query)['explanation']}"
    )


@pytest.mark.parametrize("query,expected", ROUTING_CASES)
def test_route_agent_matches_classify_intent(query, expected):
    """route_agent and classify_intent must always agree on the chosen agent."""
    assert route_agent(query) == classify_intent(query)["agent"]


# ---------------------------------------------------------------------------
# classify_intent structural contract.
# ---------------------------------------------------------------------------
def test_classify_intent_structure():
    r = classify_intent("Design WhatsApp for a billion users")
    assert set(r.keys()) == {
        "agent", "confidence", "top_intents", "scores", "matched", "explanation",
    }
    assert r["agent"] == SYSTEM_DESIGN_AGENT
    assert 0.0 <= r["confidence"] <= 1.0
    assert isinstance(r["top_intents"], list) and len(r["top_intents"]) <= 3
    assert r["top_intents"][0]["agent"] == r["agent"]
    assert isinstance(r["explanation"], str) and r["explanation"]


def test_classify_intent_single_strong_match_is_full_confidence():
    r = classify_intent("Design a rate limiter")
    # Only SYSTEM_DESIGN scores, so its normalized confidence is 1.0.
    assert r["agent"] == SYSTEM_DESIGN_AGENT
    assert r["confidence"] == 1.0


def test_classify_intent_ambiguous_topk_and_confidence():
    """A query with genuine overlap exposes a ranked top-3 with a split confidence."""
    r = classify_intent("Design a scalable SQL database for Twitter")
    agents = [t["agent"] for t in r["top_intents"]]
    assert r["agent"] == SYSTEM_DESIGN_AGENT
    assert SYSTEM_DESIGN_AGENT in agents and SQL_AGENT in agents
    # SD scores 6 (twitter 3 + scalable 2 + design 1), SQL scores 4 (sql 2 + database 2).
    assert r["top_intents"][0]["agent"] == SYSTEM_DESIGN_AGENT
    assert r["top_intents"][1]["agent"] == SQL_AGENT
    assert r["top_intents"][0]["confidence"] == pytest.approx(0.6, abs=0.01)
    # Confidences for positive intents should sum to ~1.0.
    pos = [t["confidence"] for t in r["top_intents"] if t["score"] > 0]
    assert pytest.approx(sum(pos), abs=0.01) == 1.0


def test_classify_intent_general_has_zero_confidence():
    r = classify_intent("What is the capital of France")
    assert r["agent"] == GENERAL_ASSISTANT_AGENT
    assert r["confidence"] == 0.0
    assert all(t["score"] == 0 for t in r["top_intents"])


def test_classify_intent_empty_query_is_general():
    for q in ("", "   ", None):
        r = classify_intent(q)
        assert r["agent"] == GENERAL_ASSISTANT_AGENT
        assert r["confidence"] == 0.0


def test_top_intents_sorted_descending_by_score():
    r = classify_intent("Design a scalable SQL database for Twitter")
    scores = [t["score"] for t in r["top_intents"]]
    assert scores == sorted(scores, reverse=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
