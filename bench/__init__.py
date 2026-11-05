"""Jarvis intelligence benchmark harness.

Offline-deterministic core (no network, fully reproducible) that scores answers
with Jarvis's own deterministic critics, plus pluggable live solvers (Jarvis's own
providers and external models) that activate only when API keys are configured.

Public entry points:
    bench.corpus.CASES        - curated golden + adversarial cases (ground truth)
    bench.scorer.score_case   - deterministic verdict for one case (no LLM)
    bench.runner.run          - run a solver over the corpus -> metrics dict
    bench.report.write_all    - emit the markdown reports from a results dict

Run the offline benchmark + reports:  python -m bench
"""
