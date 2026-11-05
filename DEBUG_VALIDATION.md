# DEBUG VALIDATION

How Debug answers are validated **deterministically** (`debug_critic.critique`, run
from `verifier_agent.verify` before any LLM call). The debugger's cardinal rule is
**evidence-first: never fabricate the user's code, and ask for the evidence you lack.**

## Validation logic

| Case | Behavior |
|------|----------|
| User **supplied** code or a stack trace (`_user_has_evidence`) | A concrete corrected file is legitimate → **PASS** (anti-fabrication guard does not trip) |
| User gave **no** evidence + response invents a **full patched file** (`_looks_like_full_file`, ≥12 real lines + a definition) | **REJECT** — fabrication |
| User gave **no** evidence + a **substantive fix attempt** (code block or fix/root-cause language) that **never requests evidence** | **REJECT (NEW)** — must add an `Evidence Needed` step |
| Pure clarification / one-liner with no fix attempt | **PASS** |

## What changed in this phase
Previously the only no-evidence guard was the fabricated-full-file check; a
medium-sized "here's a null check" fix with **no request for the stack trace / failing
code / runtime version** passed silently. That violates the documented evidence-first
template (the `GOOD_ASK` reference fixture has an explicit `Evidence Needed` step and
the `DEBUG_KNOWLEDGE_BASE.md` teaches "evidence-first").

The critic now requires, **only on the no-evidence path**, that a substantive
diagnosis/fix also REQUEST the evidence. Detection is deliberately broad
(`_EVIDENCE_ASK_RE`: stack trace, share/provide/paste code·trace·version, "which
line/version", "how to reproduce", "can you share…") so a genuine senior answer that
asks for the trace is never rejected. "Substantive" = a code block or fix/root-cause
language (`_FIX_INTENT_RE`); a short clarification stays exempt.

The change is **scoped** so it cannot regress the anti-fabrication contract: when the
user supplied a trace/code, `critique` returns early (evidence path) and the new check
never runs.

## Test coverage (`tests/test_debug.py` — 14 tests)
New:
- `test_no_evidence_fix_without_asking_rejected` — root-cause + fix snippet, **no** ask → reject
- `test_no_evidence_fix_with_ask_passes` — same answer **plus** an `Evidence Needed` step → pass
- `test_evidence_path_skips_ask_requirement` — user supplied a trace → a direct fix needs no ask → pass

Pre-existing (still green): user-evidence detection, full-file detection, fabricated
patch rejected, evidence-request pattern passes, full fix allowed when the user
supplied code/trace, verifier short-circuits without network, KB wiring.

Run: `python -m pytest tests/test_debug.py -v` → **14 passed**.

## Coverage vs. the Debug mandate
Evidence-first (ask for trace/code/version) ✓ (new), no-fabrication of unseen code ✓,
fix patterns over invented files ✓, foreign-section isolation ✓ (verifier
`_FORBIDDEN_SECTIONS` blocks System-Design/DSA sections leaking into a debug answer).

## Known limitations (honest)
- The critic does not parse the stack trace to verify the proposed fix targets the
  exact failing frame — that semantic judgement is left to the LLM verifier.
- It enforces that evidence is *requested*, not a rigid 5-heading layout, to avoid
  rejecting correct answers that use reasonable section-name variants.
