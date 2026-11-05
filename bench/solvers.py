"""Pluggable solvers for the benchmark.

A solver is a callable(case) -> str | None. Returning None means "skip this case"
(e.g. the provider key is absent or the live pipeline is disabled), so an
unconfigured backend never crashes a run or pollutes the metrics.

  * OfflineCorpusSolver  - returns the pre-written corpus answer (sanity / parity).
  * JarvisLiveSolver     - runs Jarvis's OWN pipeline (router.run_agent). Enabled by
                           env BENCH_LIVE_JARVIS=1 and working provider keys.
  * ClaudeSolver / ChatGPTSolver / DeepSeekSolver / GeminiSolver - external models for
                           head-to-head. Each activates only when its API key exists
                           and is given the SAME Jarvis agent prompt for a fair compare.

External calls require network + API keys + budget; they are NEVER auto-run by the
offline benchmark. `python -m bench --live` opts in explicitly.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _agent_prompt(agent: str) -> str:
    try:
        import router
        return router.AGENT_PROMPTS.get(agent, "")
    except Exception:
        return ""


class OfflineCorpusSolver:
    label = "offline-corpus"

    def __call__(self, case):
        return case.solution


class JarvisLiveSolver:
    """Runs the real Jarvis pipeline. Gated so it never fires unintentionally."""
    label = "jarvis-live"

    def __init__(self):
        self.enabled = os.getenv("BENCH_LIVE_JARVIS", "").strip().lower() in ("1", "true", "yes")

    def __call__(self, case):
        if not self.enabled:
            return None
        try:
            import router
            agent = case.agent or router.route_agent(case.query)
            return router.run_agent(agent, case.query)
        except Exception as e:
            logger.warning(f"[BENCH] JarvisLiveSolver failed on {case.id}: {e}")
            return None


class _ExternalSolver:
    """Base for external chat-completion APIs. Subclasses set provider details."""
    label = "external"
    env_key = ""
    default_model = ""
    model_env = ""

    def __init__(self):
        self.api_key = os.getenv(self.env_key, "").strip()
        self.model = os.getenv(self.model_env, "").strip() or self.default_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _request(self, system: str, user: str) -> str | None:
        raise NotImplementedError

    def __call__(self, case):
        if not self.available:
            return None
        try:
            import requests  # noqa: F401  (ensures dependency present)
            return self._request(_agent_prompt(case.agent), case.query)
        except Exception as e:
            logger.warning(f"[BENCH] {self.label} failed on {case.id}: {e}")
            return None


class ClaudeSolver(_ExternalSolver):
    label = "claude"
    env_key = "ANTHROPIC_API_KEY"
    model_env = "BENCH_CLAUDE_MODEL"
    default_model = "claude-3-5-sonnet-latest"

    def _request(self, system, user):
        import requests
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model, "max_tokens": 4000, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=180,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))


class ChatGPTSolver(_ExternalSolver):
    label = "chatgpt"
    env_key = "OPENAI_API_KEY"
    model_env = "BENCH_OPENAI_MODEL"
    default_model = "gpt-4o"

    def _request(self, system, user):
        import requests
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "content-type": "application/json"},
            json={"model": self.model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class DeepSeekSolver(_ExternalSolver):
    label = "deepseek"
    env_key = "DEEPSEEK_API_KEY"
    model_env = "BENCH_DEEPSEEK_MODEL"
    default_model = "deepseek-chat"

    def _request(self, system, user):
        import requests
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "content-type": "application/json"},
            json={"model": self.model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class GeminiSolver(_ExternalSolver):
    label = "gemini"
    env_key = "GEMINI_API_KEY"
    model_env = "BENCH_GEMINI_MODEL"
    default_model = "gemini-1.5-pro"

    def __init__(self):
        super().__init__()
        if not self.api_key:
            self.api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    def _request(self, system, user):
        import requests
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        r = requests.post(
            url,
            headers={"content-type": "application/json"},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"parts": [{"text": user}]}]},
            timeout=180,
        )
        r.raise_for_status()
        cand = r.json().get("candidates", [])
        if not cand:
            return None
        return "".join(p.get("text", "") for p in cand[0]["content"]["parts"])


_EXTERNAL = [ClaudeSolver, ChatGPTSolver, DeepSeekSolver, GeminiSolver]


def available_external() -> dict:
    """External solvers whose API key is configured."""
    out = {}
    for cls in _EXTERNAL:
        s = cls()
        if s.available:
            out[s.label] = s
    return out


def all_known_external_labels() -> list:
    return [cls.label for cls in _EXTERNAL]
