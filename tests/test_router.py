import unittest
import logging
import sys
import os

# Add parent directory to path so we can import router
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from router import (
    route_agent,
    DSA_AGENT,
    SQL_AGENT,
    SYSTEM_DESIGN_AGENT,
    PROJECT_BUILDER_AGENT,
    DEBUG_AGENT,
    CODE_REVIEW_AGENT,
    FULLSTACK_AGENT,
    GENERAL_ASSISTANT_AGENT
)

class TestRouter(unittest.TestCase):
    def setUp(self):
        # Optional: Suppress logging during tests or redirect it to check output
        pass

    def test_system_design_routing(self):
        query = "Design WhatsApp"
        self.assertEqual(route_agent(query), SYSTEM_DESIGN_AGENT)

    def test_sql_routing(self):
        query = "Optimize PostgreSQL Query"
        self.assertEqual(route_agent(query), SQL_AGENT)

    def test_dsa_routing(self):
        query = "Solve Sliding Window Maximum"
        self.assertEqual(route_agent(query), DSA_AGENT)

    def test_project_builder_routing(self):
        query = "Build React Todo App"
        self.assertEqual(route_agent(query), PROJECT_BUILDER_AGENT)

    def test_debug_routing(self):
        query = "My Spring Boot app crashes"
        self.assertEqual(route_agent(query), DEBUG_AGENT)

    def test_code_review_routing(self):
        query = "Review this Java code"
        # "review" alone won't trigger it due to our rules, but wait, the keyword is "review code", let's check
        # Ah, the keyword in my config is "review code", but the query is "Review this Java code". 
        # Hmm, "Review this Java code" doesn't strictly contain "review code". Let me check this.
        # Oh wait, my implementation requires strict regex match for "review code" unless it's just "review"
        # Actually Phase 3 says keywords: "review code", "refactor", "optimize code", "improve code", "analyze code"
        # Since the test is "Review this Java code", it doesn't contain "review code".
        # I should probably just ensure the test passes by either tweaking the router keywords or the test.
        # The prompt says 'Verify: "Review this Java code" -> CODE_REVIEW_AGENT'
        # I'll let it fail first and fix it.
        self.assertEqual(route_agent(query), CODE_REVIEW_AGENT)

    def test_general_routing(self):
        query = "What is the weather today?"
        self.assertEqual(route_agent(query), GENERAL_ASSISTANT_AGENT)

if __name__ == '__main__':
    unittest.main()
