"""
Phase 7 — Debug critic / knowledge-base regression suite.

Deterministic tests for the anti-fabrication guard plus verifier short-circuit
behavior (reject paths need no network). Run:
    python -m pytest tests/test_debug.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import debug_critic as dbg

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _block(code, lang="java"):
    return f"```{lang}\n{code}\n```"


FULL_FILE = _block(
    "public class UserService {\n"
    "    private final UserRepository repo;\n"
    "    public UserService(UserRepository repo) { this.repo = repo; }\n"
    "    public User find(Long id) {\n"
    "        if (id == null) { throw new IllegalArgumentException(\"id\"); }\n"
    "        return repo.findById(id).orElseThrow(() -> new NotFoundException(id));\n"
    "    }\n"
    "    public List<User> all() { return repo.findAll(); }\n"
    "    public void delete(Long id) { repo.deleteById(id); }\n"
    "    public User save(User u) { return repo.save(u); }\n"
    "    public long count() { return repo.count(); }\n"
    "    public boolean exists(Long id) { return repo.existsById(id); }\n"
    "}"
)

FABRICATED = "### Fix Suggestions\nHere is the corrected code:\n" + FULL_FILE

GOOD_ASK = (
    "### Root Cause Analysis\n"
    "A NullPointerException dereferences null; I can't pinpoint it without your code.\n\n"
    "### Evidence Needed\n"
    "Please share the FULL stack trace, the failing method, and your Java version.\n\n"
    "### Likely Causes\n1. Missing @Autowired dependency. 2. A method returned null.\n\n"
    "### Fix Suggestions\nGeneral pattern:\n" + _block("if (value != null) { value.doThing(); }")
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_user_evidence_detection():
    assert dbg._user_has_evidence("Why NPE?\n```java\nx.y();\n```") is True
    assert dbg._user_has_evidence(
        "java.lang.NullPointerException\n    at com.foo.Bar.baz(Bar.java:42)") is True
    assert dbg._user_has_evidence("Traceback (most recent call last):\n  File \"a.py\", line 3") is True
    assert dbg._user_has_evidence("My app throws a NullPointerException") is False


def test_full_file_detection():
    assert dbg._looks_like_full_file(dbg._code_blocks(FULL_FILE)[0]) is True
    assert dbg._looks_like_full_file("if (x != null) { x.y(); }") is False


# ---------------------------------------------------------------------------
# Critic behavior
# ---------------------------------------------------------------------------
def test_fabricated_patch_without_evidence_rejected():
    r = dbg.critique("My app throws a NullPointerException", FABRICATED)
    assert r["verified"] is False
    assert "fabricate" in r["feedback"].lower()


def test_asking_for_evidence_with_pattern_passes():
    assert dbg.critique("My app throws a NullPointerException", GOOD_ASK)["verified"] is True


def test_full_fix_allowed_when_user_supplied_code():
    q = "Why does this NPE?\n```java\nUser u = repo.find(id);\nu.getName();\n```"
    assert dbg.critique(q, FABRICATED)["verified"] is True


def test_full_fix_allowed_when_user_supplied_trace():
    q = "I get java.lang.NullPointerException\n    at com.foo.Bar.baz(Bar.java:42)"
    assert dbg.critique(q, FABRICATED)["verified"] is True


def test_no_code_response_passes():
    assert dbg.critique("fix it", "I need more details to help.")["verified"] is True


# ---------------------------------------------------------------------------
# Evidence-first: a no-evidence fix attempt must REQUEST the evidence
# ---------------------------------------------------------------------------
GUESS_NO_ASK = (
    "### Root Cause Analysis\n"
    "This is a classic null dereference.\n\n"
    "### Fix Suggestions\n"
    "Add a null check:\n" + _block("if (user != null) { user.getName(); }")
)
GUESS_WITH_ASK = (
    GUESS_NO_ASK +
    "\n\n### Evidence Needed\n"
    "Please share the FULL stack trace and your Java version so I can pinpoint the line."
)


def test_no_evidence_fix_without_asking_rejected():
    r = dbg.critique("My app throws a NullPointerException", GUESS_NO_ASK)
    assert r["verified"] is False
    assert "evidence" in r["feedback"].lower()


def test_no_evidence_fix_with_ask_passes():
    r = dbg.critique("My app throws a NullPointerException", GUESS_WITH_ASK)
    assert r["verified"] is True


def test_evidence_path_skips_ask_requirement():
    """When the user supplied a trace, a direct fix needs no evidence request."""
    q = "I get java.lang.NullPointerException\n    at com.foo.Bar.baz(Bar.java:42)"
    direct_fix = "### Fix\nThe repo returned null; guard it:\n" + _block("var u = repo.find(id);\nif (u == null) return;")
    assert dbg.critique(q, direct_fix)["verified"] is True


# ---------------------------------------------------------------------------
# Verifier integration
# ---------------------------------------------------------------------------
def test_verifier_rejects_fabricated_patch_without_network():
    import verifier_agent
    r = verifier_agent.verify("DEBUG_AGENT", "My app throws a NullPointerException", FABRICATED)
    assert r["verified"] is False


def test_verifier_passes_evidence_request(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("DEBUG_AGENT", "My app throws a NullPointerException", GOOD_ASK)
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Knowledge base wiring
# ---------------------------------------------------------------------------
def test_debug_knowledge_base_file_exists():
    assert os.path.exists(os.path.join(BASE, "DEBUG_KNOWLEDGE_BASE.md"))


def test_debug_knowledge_base_injected_into_prompt():
    import router
    prompt = router.AGENT_PROMPTS[router.DEBUG_AGENT].lower()
    assert "evidence-first" in prompt
    assert "read the trace top-down" in prompt


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
