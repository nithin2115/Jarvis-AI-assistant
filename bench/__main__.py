"""CLI: run the benchmark and (re)generate the reports.

  python -m bench            # offline-deterministic run + write the 4 reports
  python -m bench --live     # also run live Jarvis + any keyed external models
  python -m bench --summary  # print metrics only, do not write reports
"""
from __future__ import annotations

import json
import os
import sys

from . import corpus, runner, report, solvers


def _load_baseline():
    path = os.path.join(os.path.dirname(__file__), "results", "baseline_disabled.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _print_summary(m: dict) -> None:
    print(f"  cases={m['total']} accuracy={m['accuracy'] * 100:.1f}% "
          f"escape={m['adversarial']['false_accept_rate'] * 100:.1f}% "
          f"compile={(m['compilation_success']['rate'] or 0) * 100:.1f}% "
          f"completeness={m['golden']['completeness'] * 100:.1f}%")
    if m["false_accepts"]:
        print(f"  ESCAPES: {', '.join(m['false_accepts'])}")
    if m["false_rejects"]:
        print(f"  FALSE-REJECTS: {', '.join(m['false_rejects'])}")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    live = "--live" in argv
    summary_only = "--summary" in argv

    print(f"[bench] corpus: {corpus.counts()}")
    offline = runner.run("offline-deterministic")
    runner.save(offline, "offline_latest.json")
    print("[bench] OFFLINE deterministic:")
    _print_summary(offline)

    live_results = None
    if live:
        live_results = {}
        jarvis = solvers.JarvisLiveSolver()
        if jarvis.enabled:
            print("[bench] running live Jarvis pipeline ...")
            live_results["jarvis"] = runner.run_live(jarvis, "jarvis-live")
        ext = solvers.available_external()
        if not ext:
            print(f"[bench] no external API keys found for "
                  f"{solvers.all_known_external_labels()} — skipping head-to-head.")
        for name, solver in ext.items():
            print(f"[bench] running external model: {name} ...")
            live_results[name] = runner.run_live(solver, name)
        for name, m in live_results.items():
            if m.get("skipped"):
                print(f"[bench] {name}: skipped ({m['reason']})")
            else:
                runner.save(m, f"live_{name}.json")
                print(f"[bench] {name}:")
                _print_summary(m)

    if not summary_only:
        baseline = _load_baseline()
        written = report.write_all(offline, live_results, baseline)
        print("[bench] reports written:")
        for p in written:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
