"""Quick integration test for Tavily search."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Test 1: Real-time detection
from tavily_search import is_realtime_query, search_live, get_search_cache_stats

tests = [
    "What is the latest AI news today?",
    "Current weather in New York",
    "Who won the IPL match",
    "What is machine learning?",
    "Hello Jarvis",
    "Explain backpropagation",
    "Latest stock price of Tesla",
    "Tell me a joke",
    "What are the trending topics right now",
    "How to write a Python function",
]

print("=== REAL-TIME DETECTION TEST ===")
for q in tests:
    live, cat = is_realtime_query(q)
    tag = "LIVE" if live else "----"
    print(f"  {tag} [{cat:16s}] {q}")

print()

# Test 2: Actual Tavily search
print("=== TAVILY LIVE SEARCH TEST ===")
ctx = search_live("latest AI news May 2026")
if ctx:
    print(f"SUCCESS - Got {len(ctx)} chars of context")
    print(f"Preview: {ctx[:250]}...")
else:
    print("FAILED - No results returned")

print()

# Test 3: Cache test (same query should be cached)
print("=== CACHE TEST ===")
ctx2 = search_live("latest AI news May 2026")
stats = get_search_cache_stats()
print(f"Cache entries: {stats['entries']}")
print(f"Second call returned: {'cached result' if ctx2 else 'None'}")

print()

# Test 4: Health endpoint
try:
    import requests
    r = requests.get("http://localhost:5000/health", timeout=5)
    health = r.json()
    print("=== HEALTH ENDPOINT ===")
    print(f"Status: {health.get('status')}")
    print(f"Tavily configured: {health.get('tavily', {}).get('configured')}")
    print(f"Brain active: {health.get('brain', {}).get('active')}")
except Exception as e:
    print(f"Health endpoint: {e}")

print()
print("=== ALL TESTS COMPLETE ===")
