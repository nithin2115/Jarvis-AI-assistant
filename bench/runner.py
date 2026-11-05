"""Run a corpus over the deterministic scorer (or a live solver) and compute the
benchmark metrics the user asked for: accuracy, compilation success, hallucination
(escape) rate, completeness, and reasoning quality.

Two modes:
  * run()                 - OFFLINE critic-accuracy: score the pre-written golden /
                            adversarial solutions. Measures how well Jarvis's critics
                            accept good answers and reject bad ones. No network.
  * run_live(solver)      - MODEL-QUALITY: ask `solver` each golden query and score
                            its fresh answer. Used for live Jarvis / external models;
                            skips cases the solver returns None for (no API key).
"""
from __future__ import annotations

import json
import os
import time

from . import corpus, scorer

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _has_code(text: str) -> bool:
    return "```" in (text or "")


def _reasoning_quality(golden_dsa) -> dict | None:
    """Fraction of golden DSA answers whose reasoning stages are detectable.
    Returns None if the Phase-3 detector is not present yet."""
    try:
        import dsa_reasoning
    except ImportError:
        return None
    if not golden_dsa:
        return None
    core = ("problem_understanding", "optimal_algorithm", "complexity")
    full = 0
    coverages = []
    for c in golden_dsa:
        stages = dsa_reasoning.stages_present(c.solution)
        coverages.append(len(stages))
        if all(s in stages for s in core):
            full += 1
    return {
        "golden_dsa": len(golden_dsa),
        "core_stage_coverage_rate": round(full / len(golden_dsa), 4),
        "avg_stages_detected": round(sum(coverages) / len(coverages), 2),
    }


def _metrics(label: str, results: list, cases: list) -> dict:
    total = len(results)
    correct = sum(1 for r in results if r["correct"])

    by_agent: dict = {}
    for r in results:
        a = by_agent.setdefault(r["agent"], {"total": 0, "correct": 0})
        a["total"] += 1
        a["correct"] += 1 if r["correct"] else 0
    for a in by_agent.values():
        a["accuracy"] = round(a["correct"] / a["total"], 4) if a["total"] else 0.0

    golden = [r for r in results if r["kind"] == "golden"]
    adversarial = [r for r in results if r["kind"] == "adversarial"]
    g_accepted = sum(1 for r in golden if r["verified"])
    a_rejected = sum(1 for r in adversarial if not r["verified"])

    false_rejects = [r["id"] for r in golden if not r["verified"]]
    false_accepts = [r["id"] for r in adversarial if r["verified"]]

    rejecting_stages: dict = {}
    for r in adversarial:
        if not r["verified"]:
            rejecting_stages[r["stage"]] = rejecting_stages.get(r["stage"], 0) + 1

    halluc = [r for r in adversarial
              if any(t in ("hallucination", "fabricated_patch") for t in r["tags"])]
    halluc_caught = sum(1 for r in halluc if not r["verified"])

    # Compilation success is measured only over DSA golden code answers, because
    # compile_verifier is DSA/code-generation specific and only runs in that path.
    case_by_id = {c.id: c for c in cases}
    code_golden = [r for r in golden
                   if r["agent"] == "DSA_AGENT" and _has_code(case_by_id[r["id"]].solution)]
    compiled = sum(1 for r in code_golden
                   if scorer.compile_ok(case_by_id[r["id"]].query, case_by_id[r["id"]].solution))

    golden_dsa = [c for c in cases if c.agent == "DSA_AGENT" and c.kind == "golden"]

    return {
        "label": label,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "counts": corpus.counts(),
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "by_agent": by_agent,
        "golden": {
            "total": len(golden),
            "accepted": g_accepted,
            "false_reject_rate": round(1 - g_accepted / len(golden), 4) if golden else 0.0,
            "completeness": round(g_accepted / len(golden), 4) if golden else 0.0,
        },
        "adversarial": {
            "total": len(adversarial),
            "rejected": a_rejected,
            "false_accept_rate": round(1 - a_rejected / len(adversarial), 4) if adversarial else 0.0,
            "hallucination_catch_rate": (round(halluc_caught / len(halluc), 4) if halluc else None),
        },
        "compilation_success": {
            "code_golden_total": len(code_golden),
            "compiled": compiled,
            "rate": round(compiled / len(code_golden), 4) if code_golden else None,
        },
        "reasoning_quality": _reasoning_quality(golden_dsa),
        "rejecting_stages": rejecting_stages,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "cases": results,
    }


def run(label: str = "offline-deterministic") -> dict:
    """OFFLINE critic-accuracy benchmark over the pre-written corpus solutions."""
    cases = corpus.CASES
    results = [scorer.score_case(c) for c in cases]
    return _metrics(label, results, cases)


def run_live(solver, label: str | None = None) -> dict:
    """MODEL-QUALITY benchmark: ask the solver each GOLDEN query, score its answer.

    `solver` is a callable(case) -> str | None. Returning None marks the case
    skipped (e.g. provider key absent), so an unconfigured model never crashes
    or pollutes the metrics.
    """
    label = label or getattr(solver, "label", "live")
    golden = [c for c in corpus.CASES if c.kind == "golden"]
    results = []
    used_cases = []
    for c in golden:
        answer = solver(c)
        if answer is None:
            continue
        r = scorer.score_answer(c.agent, c.query, c.expect, answer)
        r.update({"id": c.id, "agent": c.agent, "kind": c.kind,
                  "expect": c.expect, "tags": list(c.tags)})
        results.append(r)
        used_cases.append(c)
    if not results:
        return {"label": label, "skipped": True,
                "reason": "solver returned None for every case (no API key / disabled)"}
    return _metrics(label, results, used_cases)


def save(metrics: dict, name: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return path
