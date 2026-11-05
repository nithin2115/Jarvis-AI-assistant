import logging
import brain_manager
import verdict_utils
import dsa_complexity
import dsa_structure
import dsa_output_quality
import lfu_critic
import dsa_algorithm_critic
import dsa_reasoning
import compile_verifier

logger = logging.getLogger(__name__)

def critique(user_query: str, response_text: str) -> dict:
    """
    Acts as a specialized critic for DSA solutions.
    """
    # ── Deterministic, AST-aware complexity check first (Phase 5) ──
    # Catches "claimed complexity != implementation" anti-patterns reliably and
    # for free, before spending an LLM call.
    ok, reason = dsa_complexity.analyze(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] Complexity mismatch (AST check): {reason}")
        return {"verified": False, "feedback": reason}

    # ── Deterministic structural check (Phase 6) ──
    # For genuine solve requests that ship code: enforce the mandatory sections,
    # reject placeholder/stub bodies, and verify the code compiles logically.
    ok, reason = dsa_structure.check(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] Structural check failed: {reason}")
        return {"verified": False, "feedback": reason}

    # ── Deterministic compile check (Phase 1 hardening) ──
    # For genuine solve requests that ship code: run language-specific compile checks
    # (syntax, missing imports/headers, invalid declarations, multiple mains, etc.).
    if dsa_structure.is_solution_attempt(user_query, response_text):
        ok, reason = compile_verifier.check(user_query, response_text)
        if not ok:
            logger.warning(f"[DSA_CRITIC] Compile check failed: {reason}")
            return {"verified": False, "feedback": reason}

    # ── Deterministic output-quality check (Phase 11) ──
    # Rejects duplicate sections, template artifacts, unfinished sentences,
    # duplicated paragraphs, LFU content gaps, unexplained O(1), and production-grade
    # requests missing validation/encapsulation/tests — before the LLM call.
    ok, reason = dsa_output_quality.check(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] Output-quality check failed: {reason}")
        return {"verified": False, "feedback": reason}

    # ── Deterministic LFU cache check (Phase 13) ──
    # Validates eviction patterns, LRU tie-break, required data structures,
    # O(1) proof, duplicate sections, and template fragments for LFU queries.
    ok, reason = lfu_critic.check(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] LFU critic check failed: {reason}")
        return {"verified": False, "feedback": reason}

    # ── Deterministic algorithm-specific checks (Phase 2) ──
    # Sliding Window Median, LRU Cache, Trie, Segment Tree, Union Find, Rate Limiter.
    ok, reason = dsa_algorithm_critic.check(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] Algorithm-specific check failed: {reason}")
        return {"verified": False, "feedback": reason}

    # ── Deterministic reasoning/consistency check (Phase 3) ──
    # Catches self-contradiction the other gates miss (e.g., two different stated
    # time complexities) — a tell-tale sign of confused / stitched-together reasoning.
    ok, reason = dsa_reasoning.check(user_query, response_text)
    if not ok:
        logger.warning(f"[DSA_CRITIC] Reasoning/consistency check failed: {reason}")
        return {"verified": False, "feedback": reason}

    sys_prompt = (
        "You are a precise DSA Critic. You judge ALGORITHMIC OPTIMALITY and CORRECTNESS, "
        "not coding style. Evaluate the proposed DSA solution against the user's query.\n\n"
        "Reject ONLY if one of these is true:\n"
        "1. The approach has genuinely worse time OR space complexity than the optimal "
        "(e.g., O(n log n) median scan when O(log n) is achievable, or brute force when a "
        "linear solution exists).\n"
        "2. The stated complexity is factually wrong.\n"
        "3. The code is incorrect, incomplete, or stops midway.\n\n"
        "IMPORTANT — do NOT reject for style or for using standard-library structures when "
        "they already achieve optimal complexity. A solution that meets the optimal Big-O is "
        "ACCEPTABLE even if a hand-rolled alternative exists. For example, an LRU cache built "
        "on Python's OrderedDict (or a HashMap + doubly linked list) is O(1) and MUST be accepted.\n\n"
        "If the solution achieves optimal complexity and is correct and complete, "
        "output EXACTLY AND ONLY: VERIFIED\n\n"
        "Otherwise output:\n"
        "REJECTED\n"
        "Reason: [why the complexity is suboptimal/wrong or the code is incomplete]\n"
        "Expected: [the optimal algorithm/data structures and the correct complexity]"
    )
    
    prompt = f"Problem:\n{user_query}\n\nGenerated Solution:\n{response_text}"
    
    logger.info("[DSA_CRITIC] Critiquing DSA solution...")
    
    response, _ = brain_manager.ask(
        prompt=prompt,
        context="",
        sys_prompt=sys_prompt,
        max_tokens=300,
        deepthink=False,
        stateless=True,  # QA call — never pollutes/reads shared conversation history
    )
    
    verified, feedback = verdict_utils.parse_verdict(response, default_verified=False)
    if verified:
        logger.info("[DSA_CRITIC] Status: VERIFIED optimal")
        return {"verified": True, "feedback": ""}
    logger.warning(f"[DSA_CRITIC] Status: REJECTED. Feedback: {feedback}")
    return {"verified": False, "feedback": feedback}
