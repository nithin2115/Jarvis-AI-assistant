"""Phase 2 — Routing audit regression gate.

Runs the labeled corpus (tests/routing_corpus.py) through router.route_agent and
asserts overall accuracy + per-agent recall stay above the bar. This is the
machine-checkable backbone of the accuracy claims in ROUTING_AUDIT.md.

Run:
    python -m pytest tests/test_routing_audit.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.disable(logging.CRITICAL)

import pytest
import routing_corpus as rc
from router import route_agent

# Bars chosen from the measured post-fix results (overall 99.46%). They guard
# against regressions while leaving headroom for the one inherent keyword-routing
# miss (a behavioral bug description with no error vocabulary).
OVERALL_MIN = 0.97
PER_AGENT_MIN = 0.90


@pytest.fixture(scope="module")
def results():
    return rc.evaluate(route_agent)


def test_corpus_is_substantial():
    assert len(rc.CORPUS) >= 150


def test_overall_accuracy(results):
    acc = results["accuracy"]
    misroutes = "\n".join(
        f"  [{m['expected']} -> {m['got']}] {m['query']}" for m in results["misroutes"]
    )
    assert acc >= OVERALL_MIN, (
        f"Overall routing accuracy {acc:.4f} < {OVERALL_MIN}.\nMisroutes:\n{misroutes}"
    )


def test_per_agent_recall(results):
    weak = {
        agent: pa["recall"]
        for agent, pa in results["per_agent"].items()
        if pa["recall"] < PER_AGENT_MIN
    }
    assert not weak, f"Agents below {PER_AGENT_MIN} recall: {weak}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
