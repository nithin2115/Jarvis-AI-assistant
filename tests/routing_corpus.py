"""Phase 2 — Routing audit corpus + evaluator (pure functions, no network).

A large, hand-labeled corpus spanning every specialist agent + the general
fallback. Each label is the agent a competent engineer would EXPECT the query to
route to. The evaluator runs the corpus through a routing function and reports
overall accuracy, per-agent recall, and the exact misroutes.

Reused by:
  * tests/test_routing_audit.py  — threshold-gated regression test
  * scripts/gen_routing_audit.py — regenerates ROUTING_AUDIT.md from a live run
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router import (  # noqa: E402
    DSA_AGENT,
    SQL_AGENT,
    SYSTEM_DESIGN_AGENT,
    PROJECT_BUILDER_AGENT,
    DEBUG_AGENT,
    CODE_REVIEW_AGENT,
    FULLSTACK_AGENT,
    GENERAL_ASSISTANT_AGENT,
)

# ── Labeled corpus ──────────────────────────────────────────────────────────
# (query, expected_agent). Kept diverse: canonical phrasings, paraphrases, and
# deliberately tricky cross-domain cases.
CORPUS: list[tuple[str, str]] = []


def _add(agent: str, queries: list[str]) -> None:
    for q in queries:
        CORPUS.append((q, agent))


# --- DEBUG -------------------------------------------------------------------
_add(DEBUG_AGENT, [
    "My app throws a NullPointerException",
    "I'm getting a segmentation fault",
    "This throws an exception at runtime",
    "How do I fix this bug",
    "Stack trace shows IndexOutOfBounds",
    "My program is not working",
    "Why won't this compile",
    "Getting a ClassNotFoundException on startup",
    "NoSuchMethodError when calling the service",
    "StackOverflowError in my recursion",
    "The server crashes on every request",
    "My code crashed with an unhandled exception",
    "Traceback most recent call last KeyError",
    "Why does this throw an exception",
    "Fix the null pointer in my handler",
    "My test is failing intermittently",
    "The function returns null unexpectedly",
    "I keep getting an off by one error",
    "Infinite loop somewhere in my code",
    "Why am I getting a deadlock",
    "Segfault when freeing memory",
    "App freezes and then crashes",
    "Debug this race condition",
    "My build fails with a compilation error",
    "This won't run, it just hangs",
    "Getting an undefined is not a function error",
    "My API returns 500 internal server error",
    "Why is my regex not matching",
    "The for loop is skipping the last element",
    "My program throws an array index out of bounds exception",
])

# --- PROJECT_BUILDER ---------------------------------------------------------
_add(PROJECT_BUILDER_AGENT, [
    "Build a Spring Boot React app",
    "Create a project with Django",
    "Scaffold a MERN stack application",
    "Generate a Flask boilerplate",
    "Set up a Next.js project with Docker",
    "Build a todo app",
    "Create an application with Express and MongoDB",
    "Generate a full stack app with authentication",
    "Build me a blog platform with Django",
    "Scaffold a microservices boilerplate",
    "Create a new React project structure",
    "Build a chat application with Node.js",
    "Set up a Spring Boot project with Maven",
    "Create a starter template for a Vue app",
    "Build a complete e-commerce application",
    "Generate a REST backend with Flask and a React frontend",
    "Make a CRUD app with Django REST framework",
    "Bootstrap a Next.js and Prisma project",
    "Create a dockerized Node.js application",
    "Build a SaaS starter kit",
])

# --- SYSTEM_DESIGN -----------------------------------------------------------
_add(SYSTEM_DESIGN_AGENT, [
    "Design WhatsApp",
    "Design a URL shortener for a billion users",
    "Design a rate limiter",
    "How would you design a scalable distributed system",
    "Design Netflix video streaming",
    "Explain consistent hashing and sharding",
    "Design a web crawler",
    "Design Twitter timeline",
    "Design Uber's backend",
    "Design Instagram's photo feed",
    "Design a distributed message queue",
    "Design a notification system at scale",
    "How to design a highly available service",
    "Design a CDN architecture",
    "Design YouTube's video upload pipeline",
    "Design Dropbox file sync",
    "Design a payment system architecture",
    "Design a load balancer",
    "Design a key value store like DynamoDB",
    "Design a ride sharing system",
    "How would you architect a microservices platform",
    "Design a real time analytics pipeline with Kafka",
    "Design Google Drive",
    "Design a tinyurl service",
    "Design a scalable chat backend for millions of users",
])

# --- SQL ---------------------------------------------------------------------
_add(SQL_AGENT, [
    "Optimize this PostgreSQL query",
    "Write a complex SQL join across three tables",
    "How do I add an index to speed up a slow query",
    "Explain analyze shows a sequential scan",
    "Create a materialized view for reporting",
    "Partition a large MySQL table by date",
    "Why is my query slow",
    "Write a SQL query to find the second highest salary",
    "How to optimize a query with multiple joins",
    "My query plan shows a full table scan",
    "Add a composite index on user_id and created_at",
    "Denormalize this schema for read performance",
    "Write a window function to rank rows",
    "How to use a CTE in PostgreSQL",
    "Group by with having clause example",
    "Fix the N+1 query problem in my ORM",
    "Tune this slow aggregation query",
    "Design indexes for this query pattern",
    "Convert this subquery to a join",
    "Shard a large orders table",
    "Speed up a query that filters on a non indexed column",
    "Write an upsert in PostgreSQL",
    "Explain the execution plan for this select",
    "Optimize a query doing a seq scan on a million rows",
    "How do I create a covering index",
])

# --- CODE_REVIEW -------------------------------------------------------------
_add(CODE_REVIEW_AGENT, [
    "Review this Java code",
    "Can you refactor this function",
    "Please review my pull request",
    "Analyze this code for improvements",
    "Review my code",
    "Look over my function and suggest improvements",
    "Is this code idiomatic",
    "Refactor this method to be cleaner",
    "What are the code smells in this class",
    "Improve the readability of this code",
    "Critique my implementation",
    "Give me feedback on this code",
    "Clean up this messy function",
    "Review this code for best practices",
    "How can I make this code more maintainable",
    "Refactor this for better separation of concerns",
    "Review my React component for issues",
    "Can you do a code review of this snippet",
    "Suggest improvements to this algorithm implementation",
    "Audit this code for quality issues",
])

# --- DSA ---------------------------------------------------------------------
_add(DSA_AGENT, [
    "Implement an LFU cache",
    "Sliding window median problem",
    "Find the kth largest element in an array",
    "Dijkstra shortest path algorithm",
    "What is the time complexity of quicksort",
    "Reverse a linked list",
    "Detect a cycle in a graph using DFS",
    "Solve the 0/1 knapsack problem with DP",
    "Two sum problem",
    "Implement an LRU cache",
    "Build a trie for autocomplete",
    "Implement a segment tree for range sum",
    "Fenwick tree for prefix sums",
    "Union find with path compression",
    "Merge two sorted arrays",
    "Find the median of two sorted arrays",
    "Top k frequent elements",
    "Implement a min heap",
    "Lowest common ancestor in a binary tree",
    "Longest common subsequence",
    "Level order traversal of a binary tree",
    "Find the longest palindromic substring",
    "Implement binary search on a rotated array",
    "Count inversions in an array",
    "Topological sort of a DAG",
    "Maximum subarray sum",
    "Implement quicksort",
    "Balance a binary search tree",
    "Number of islands using BFS",
    "Coin change dynamic programming",
    "Find duplicates using two pointers",
    "Implement a monotonic stack",
    "Kth smallest element in a BST",
    "Backtracking solution for N queens",
    "Memoized fibonacci",
])

# --- FULLSTACK ---------------------------------------------------------------
_add(FULLSTACK_AGENT, [
    "Build a REST API with JWT authentication",
    "Implement OAuth login on the backend",
    "Set up RBAC with Spring Security",
    "Create a React component for the frontend",
    "Add JWT auth to my Express backend",
    "Implement a REST API for user management",
    "Wire up the frontend and backend with an API",
    "Add OAuth2 login with Google",
    "Build a backend authentication service",
    "Create a protected route with JWT",
    "Set up nginx as a reverse proxy for my app",
    "Implement role based access control",
    "Build a REST API with pagination and filtering",
    "Add Spring Security to my endpoints",
    "Create an Angular frontend for my API",
])

# --- GENERAL -----------------------------------------------------------------
_add(GENERAL_ASSISTANT_AGENT, [
    "What is the capital of France",
    "Tell me a joke",
    "Who won the world cup in 2018",
    "Explain photosynthesis",
    "What's the weather like today",
    "Recommend a good book to read",
    "How are you doing",
    "What time is it in Tokyo",
    "Give me a recipe for pancakes",
    "Translate hello into Spanish",
    "What is the meaning of life",
    "Tell me an interesting fact",
    "Who painted the Mona Lisa",
    "What's a good movie to watch tonight",
    "How tall is Mount Everest",
])


# ── Evaluator ────────────────────────────────────────────────────────────────
def evaluate(route_fn):
    """Run the corpus through `route_fn` and return a results dict.

    Returns:
        {
          "total": int, "correct": int, "accuracy": float,
          "per_agent": {agent: {"total","correct","recall"}},
          "misroutes": [{"query","expected","got"}],
        }
    """
    per_agent: dict[str, dict] = {}
    misroutes: list[dict] = []
    correct = 0
    for query, expected in CORPUS:
        got = route_fn(query)
        pa = per_agent.setdefault(expected, {"total": 0, "correct": 0})
        pa["total"] += 1
        if got == expected:
            correct += 1
            pa["correct"] += 1
        else:
            misroutes.append({"query": query, "expected": expected, "got": got})

    for agent, pa in per_agent.items():
        pa["recall"] = round(pa["correct"] / pa["total"], 4) if pa["total"] else 0.0

    total = len(CORPUS)
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "per_agent": per_agent,
        "misroutes": misroutes,
    }
