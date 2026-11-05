import logging
import sys

# Setup basic logging to see output
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

import router

print("\n--- Testing DSA Routing ---")
agent1 = router.route_agent("how to reverse a linked list using dfs")

print("\n--- Testing SQL Routing ---")
agent2 = router.route_agent("how to do a postgresql join")

print("\n--- Testing General Routing ---")
agent3 = router.route_agent("hello")

print("\n--- Testing Debug Routing ---")
agent4 = router.route_agent("my script is crashing with a null pointer exception")

