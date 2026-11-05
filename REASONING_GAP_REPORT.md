# REASONING GAP REPORT
_Audit of Jarvis's reasoning pipeline vs. the self-checking behaviour of frontier coding models (Claude, ChatGPT, DeepSeek, Gemini)._

## Current pipeline
```
User -> Router (route_agent) -> Specialist prompt (AGENT_PROMPTS) -> LLM (brain_manager) -> Critic (domain) -> Verifier (verifier_agent) -> [reject -> regenerate with feedback] -> Finalizer
```

## Technique-by-technique audit
| Technique frontier models use | Jarvis mechanism | Status |
|---|---|---|
| Internal self-checking | self_consistency.py (best-of-N) + per-stage critics | Partial — best-of-N picks the critic-best draft, but there is no explicit self-critique-then-revise of a single draft. |
| Multi-pass reasoning | router.run_agent regenerate loop on critic feedback | Yes — rejected drafts are regenerated with feedback up to the retry budget. |
| Solution verification | verifier_agent + domain critics (deterministic + LLM) | Yes — every answer is verified before it ships. |
| Edge-case simulation | DSA_AGENT.md Edge Cases section; no execution | Gap — edge cases are requested in prose but never simulated/executed. |
| Complexity validation | dsa_complexity.py (AST-based claimed-vs-actual Big-O) | Yes — strongest gate; reliably catches false O(1)/O(log n) claims. |
| Consistency checks | dsa_output_quality.py (duplicate sections, artifacts) | Partial — structural consistency only. |
| Contradiction detection | dsa_reasoning.py (Phase 3) | Added — flags answers whose stated complexity contradicts itself or whose 'tested' claim conflicts with stub code. |

## Key gaps
- **No execution-based edge-case simulation.** Edge cases are described, not run. Frontier models reason through concrete inputs; Jarvis relies on static critics. This remains a gap; the new Phase 3 gate addresses self-contradiction, not concrete execution.
- **No explicit hidden-draft self-revision.** The pipeline regenerates *new* drafts on rejection but does not critique-and-patch a single draft the way a chain-of-thought model self-edits. This is a future direction, not a currently implemented stage.
- **Contradiction detection was missing** and is now implemented in `dsa_reasoning.py`. It rejects answers that state two different time complexities for the same implementation.

## Strengths to preserve
- The AST complexity validator (`dsa_complexity`) is a genuine edge over naive LLM self-grading: it catches false-complexity claims mechanically.
- Deterministic critics now achieve 100.0% accuracy on the adversarial+golden corpus with a 0.0% escape rate.
- Without the contradiction gate, accuracy was 97.6% and the escape rate was 3.7%.
