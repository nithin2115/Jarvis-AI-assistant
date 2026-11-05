"""Live end-to-end smoke test: real LLM calls through the full pipeline.
Confirms routing, streaming (chunks actually arrive), verification, and measures
latency (Phase 9 + 10). Network-dependent; providers may rate-limit.
"""
import logging, sys, time
logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

import router

def run(label, query, agent_expected=None):
    print(f"\n{'='*60}\n{label}: {query!r}")
    agent = router.route_agent(query)
    print(f"  routed -> {agent}" + (f" (expected {agent_expected})" if agent_expected else ""))
    chunks = []
    t0 = time.time()
    first = [None]
    def on_chunk(c):
        if first[0] is None:
            first[0] = time.time() - t0
        chunks.append(c)
    resp = router.run_agent(agent, query, context="", on_chunk=on_chunk)
    elapsed = time.time() - t0
    streamed = "".join(chunks)
    print(f"  total={elapsed:.2f}s  ttfb={first[0] if first[0] is not None else -1:.2f}s  "
          f"chunks={len(chunks)}  chars={len(resp)}")
    print(f"  stream==return: {streamed == resp}")
    print(f"  fences_balanced: {resp.count('```') % 2 == 0}")
    print(f"  preview: {resp[:160].replace(chr(10),' ')}")
    return resp

if __name__ == "__main__":
    run("GENERAL fast-path", "hi there, who are you?")
    run("DSA", "Solve the LRU Cache problem", "DSA_AGENT")
    print("\nDone.")
