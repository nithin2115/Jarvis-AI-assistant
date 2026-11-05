"""Self-consistency Draft A/B comparison (Phase 6).

Generates two independent drafts for the same specialist request, scores them with
existing deterministic domain critics, and returns the stronger one. This gives a
best-of-N safety net without relying on the LLM verifier.

The module is fail-safe: if a critic is missing or raises, the fallback is the
longest/balanced-fences draft. Casual / general chat agents are skipped.
"""
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Agent types that benefit from deterministic A/B comparison.
_AB_AGENTS = {
    "DSA_AGENT",
    "SYSTEM_DESIGN_AGENT",
    "SQL_AGENT",
    "FULLSTACK_AGENT",
    "PROJECT_BUILDER_AGENT",
}


def _draft_quality(text: str) -> float:
    """Cheap completeness score: length + bonus for balanced code fences."""
    if not text or not text.strip():
        return 0.0
    score = float(len(text.strip()))
    if text.count("```") % 2 == 0 and text.count("```") >= 2:
        score += 2000.0
    return score


def _score_draft(agent: str, user_query: str, text: str) -> tuple:
    """Return a deterministic ranking key.

    Lower tuple is better:
      - verified_ok (False is worse than True)
      - inverse quality (-quality)
    """
    quality = _draft_quality(text)
    if not text or not text.strip():
        return (True, float("inf"), -quality)
    verified = False
    try:
        if agent == "DSA_AGENT":
            # Use only the deterministic sub-critics (no LLM call) for fast A/B.
            import dsa_complexity, dsa_structure, dsa_output_quality, lfu_critic, dsa_algorithm_critic
            checks = [
                dsa_complexity.analyze(user_query, text),
                dsa_structure.check(user_query, text),
                dsa_output_quality.check(user_query, text),
                lfu_critic.check(user_query, text),
                dsa_algorithm_critic.check(user_query, text),
            ]
            verified = all(ok for ok, _ in checks)
        elif agent == "SYSTEM_DESIGN_AGENT":
            import sysdesign_critic
            verified = bool(sysdesign_critic.critique(user_query, text).get("verified"))
        elif agent == "SQL_AGENT":
            import sql_critic
            verified = bool(sql_critic.critique(user_query, text).get("verified"))
        elif agent in ("FULLSTACK_AGENT", "PROJECT_BUILDER_AGENT"):
            import fullstack_critic
            verified = bool(fullstack_critic.critique(user_query, text).get("verified"))
    except Exception as e:
        logger.warning(f"[SELF_CONSISTENCY] critic failed for {agent}: {e}")
    return (not verified, -quality)


def compare_drafts(agent: str, user_query: str, draft_a: str, draft_b: str) -> tuple:
    """Return (better_draft, score_a, score_b, was_tie).

    Selection is deterministic: a draft that passes the domain critic beats one
    that fails; if both pass/fail, the higher-quality draft wins. Ties break in
    favor of draft_a.
    """
    score_a = _score_draft(agent, user_query, draft_a)
    score_b = _score_draft(agent, user_query, draft_b)
    was_tie = score_a == score_b
    if score_a <= score_b:
        return draft_a, score_a, score_b, was_tie
    return draft_b, score_a, score_b, was_tie


def generate_best_draft(
    agent: str,
    user_query: str,
    context: str,
    sys_prompt: str,
    ask_fn: Callable,
    n: int = 2,
    **ask_kwargs
) -> tuple:
    """Generate `n` independent drafts and return the best one.

    `ask_fn` must match the brain_manager.ask signature: (prompt, context, sys_prompt, **kwargs)
    -> (text, provider). Returns (best_text, provider, score).
    """
    if agent not in _AB_AGENTS:
        text, provider = ask_fn(user_query, context, sys_prompt, **ask_kwargs)
        return text, provider, _score_draft(agent, user_query, text)

    drafts: list[tuple[str, str, tuple]] = []
    for i in range(n):
        variant_sys = sys_prompt
        if i > 0:
            variant_sys += (
                "\n\nSelf-consistency variant: produce the same complete answer, but vary "
                "the phrasing and structure so we can compare two independent reasoning paths."
            )
        try:
            text, provider = ask_fn(user_query, context, variant_sys, **ask_kwargs)
        except Exception as e:
            logger.warning(f"[SELF_CONSISTENCY] draft {i + 1} generation failed: {e}")
            text, provider = "", ""
        drafts.append((text, provider, _score_draft(agent, user_query, text)))

    if not drafts:
        return "", "", (True, 0.0)

    # Sort by score (lower tuple is better). Stable sort preserves generation order.
    drafts.sort(key=lambda x: x[2])
    best_text, best_provider, best_score = drafts[0]
    logger.info(
        f"[SELF_CONSISTENCY] selected draft {drafts.index((best_text, best_provider, best_score)) + 1}/"
        f"{len(drafts)} for {agent}; scores={[(i + 1, d[2]) for i, d in enumerate(drafts)]}"
    )
    return best_text, best_provider, best_score


def enabled_for(agent: str) -> bool:
    return agent in _AB_AGENTS
