"""Deterministic verdict — a faithful, no-network replica of the pipeline's
deterministic gate (everything `verifier_agent` / `dsa_critic` decide BEFORE the
LLM verifier call). Records which stage produced a rejection so the benchmark can
pinpoint the failure mode.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass
class Verdict:
    verified: bool
    stage: str      # rejecting stage, or "accept"
    reason: str


# DSA deterministic chain, in the exact order dsa_critic.critique runs it.
def _dsa_verdict(query: str, text: str) -> Verdict:
    import dsa_complexity
    import dsa_structure
    import compile_verifier
    import dsa_output_quality
    import lfu_critic
    import dsa_algorithm_critic

    ok, reason = dsa_complexity.analyze(query, text)
    if not ok:
        return Verdict(False, "dsa_complexity", reason)

    ok, reason = dsa_structure.check(query, text)
    if not ok:
        return Verdict(False, "dsa_structure", reason)

    if dsa_structure.is_solution_attempt(query, text):
        ok, reason = compile_verifier.check(query, text)
        if not ok:
            return Verdict(False, "compile_verifier", reason)

    ok, reason = dsa_output_quality.check(query, text)
    if not ok:
        return Verdict(False, "dsa_output_quality", reason)

    ok, reason = lfu_critic.check(query, text)
    if not ok:
        return Verdict(False, "lfu_critic", reason)

    ok, reason = dsa_algorithm_critic.check(query, text)
    if not ok:
        return Verdict(False, "dsa_algorithm_critic", reason)

    # Optional reasoning/consistency gate (Phase 3); fail-open if absent.
    try:
        import dsa_reasoning
        ok, reason = dsa_reasoning.check(query, text)
        if not ok:
            return Verdict(False, "dsa_reasoning", reason)
    except ImportError:
        pass

    return Verdict(True, "accept", "")


_DOMAIN_CRITICS = {
    "SQL_AGENT": "sql_critic",
    "SYSTEM_DESIGN_AGENT": "sysdesign_critic",
    "FULLSTACK_AGENT": "fullstack_critic",
    "PROJECT_BUILDER_AGENT": "fullstack_critic",
    "DEBUG_AGENT": "debug_critic",
    "CODE_REVIEW_AGENT": "codereview_critic",
}


def deterministic_verdict(agent: str, query: str, text: str) -> Verdict:
    """Replicate the pipeline's pre-LLM deterministic decision."""
    import verifier_agent
    import response_quality_critic

    foreign = verifier_agent._find_forbidden_section(agent, text)
    if foreign:
        return Verdict(False, "template_isolation",
                       f"foreign section '{foreign}' for {agent}")

    ok, reason = response_quality_critic.deterministic_check(agent, query, text)
    if not ok:
        return Verdict(False, "response_quality", reason)

    if agent == "DSA_AGENT":
        return _dsa_verdict(query, text)

    module_name = _DOMAIN_CRITICS.get(agent)
    if module_name:
        mod = importlib.import_module(module_name)
        res = mod.critique(query, text)
        if not res.get("verified"):
            return Verdict(False, module_name, res.get("feedback", ""))

    return Verdict(True, "accept", "")


def score_answer(agent: str, query: str, expect: str, text: str) -> dict:
    """Score one (agent, query, answer) against an expected verdict."""
    v = deterministic_verdict(agent, query, text)
    correct = (v.verified and expect == "accept") or (not v.verified and expect == "reject")
    return {
        "verified": v.verified,
        "stage": v.stage,
        "reason": (v.reason or "")[:300],
        "correct": correct,
    }


def score_case(case) -> dict:
    """Score a corpus Case using its pre-written solution (critic-accuracy mode)."""
    r = score_answer(case.agent, case.query, case.expect, case.solution)
    r.update({
        "id": case.id, "agent": case.agent, "kind": case.kind,
        "expect": case.expect, "tags": list(case.tags),
    })
    return r


def compile_ok(query: str, text: str) -> bool:
    import compile_verifier
    ok, _ = compile_verifier.check(query, text)
    return ok
