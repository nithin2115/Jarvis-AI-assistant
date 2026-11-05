import logging
import brain_manager
import dsa_critic

logger = logging.getLogger(__name__)

def verify(agent_type: str, user_query: str, response_text: str) -> dict:
    if agent_type == "DSA_AGENT":
        # Run specialized DSA Critic first
        dsa_result = dsa_critic.critique(user_query, response_text)
        if not dsa_result["verified"]:
            return dsa_result

    sys_prompt = (
        "You are the Verifier Agent. Your job is to strictly evaluate the proposed answer "
        "to the user's query.\n\n"
        "Responsibilities based on domain:\n"
        "- DSA: Verify optimality, complexity, code completeness.\n"
        "- SQL: Verify syntax, ensure NO hallucinated schema/tables, and verify ALL required sections are present (Root Cause Analysis, Index Strategy, Partitioning, Read Replicas, Materialized Views, Redis, Monitoring, Cost Tradeoffs). If the query is missing in the user prompt, verify the response asks for it instead of inventing tables.\n"
        "- System Design: Verify all requirements covered, tradeoffs included.\n"
        "- Full Stack / Project Builder: Verify folder structure exists, all requested modules generated.\n\n"
        "General Rejection Criteria (Reject if ANY of these are true):\n"
        "- Code is incomplete or stops midway.\n"
        "- User requirements are missing.\n"
        "- Complexity analysis is wrong or missing.\n"
        "- Duplicated sections exist.\n\n"
        "Evaluate the response. If it perfectly passes all relevant criteria, output EXACTLY AND ONLY the word: VERIFIED\n"
        "If it fails ANY criteria, output: REJECTED\n"
        "Followed by a detailed explanation of what is wrong and needs to be fixed."
    )

    prompt = f"User Query:\n{user_query}\n\nProposed Response:\n{response_text}"

    logger.info(f"[VERIFIER] Verifying response for {agent_type}...")

    response, _ = brain_manager.ask(
        prompt=prompt,
        context="",
        sys_prompt=sys_prompt,
        max_tokens=500,
        deepthink=False
    )

    text = response.strip()
    if text.startswith("VERIFIED"):
        logger.info(f"[VERIFIER] Status: VERIFIED")
        return {"verified": True, "feedback": ""}
    else:
        feedback = text.replace("REJECTED", "").strip()
        if feedback.startswith(":"):
            feedback = feedback[1:].strip()
        logger.warning(f"[VERIFIER] Status: REJECTED. Reason: {feedback}")
        return {"verified": False, "feedback": feedback}
