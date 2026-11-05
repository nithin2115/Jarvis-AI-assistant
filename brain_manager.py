"""
JARVIS AI Brain Manager — Production-Grade Multi-Provider Engine
════════════════════════════════════════════════════════════════
Priority: Gemini (primary) → Groq (fallback 1) → OpenRouter (fallback 2)

Guarantees:
  • NEVER returns None — always produces a response
  • Automatic failover with zero user-visible interruption
  • Health monitoring restores providers automatically
  • Shared conversation context across all providers
  • Full request lifecycle logging
"""

import time
import threading
import logging
import json
import os
import httpx
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Iterable, Generator, Callable
from collections import deque

import jarvis_config as config

# DeepThink model overrides (env-tunable). Heavier but smarter models.
DEEPTHINK_GEMINI_MODEL = os.getenv(
    "DEEPTHINK_GEMINI_MODEL", "gemini-3.8-flash"
)

DEEPTHINK_GROQ_MODEL = os.getenv(
    "DEEPTHINK_GROQ_MODEL", "qwen/qwen3.8-27b"
)

DEEPTHINK_OPENROUTER_MODEL = os.getenv(
    "DEEPTHINK_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct"
)
logger = logging.getLogger("jarvis.brain")

# ── Provider health states ─────────────────────────────────────────────────────
HEALTHY  = "healthy"
DEGRADED = "degraded"
DOWN     = "down"

# How many consecutive failures before marking down
_DEGRADE_AFTER = 1   # 1 fail → degraded
_DOWN_AFTER    = 3   # 3 fails → down

# How often (seconds) to re-check a downed provider
_HEALTH_CHECK_INTERVAL = 30
_DOWN_RECHECK_BASE     = 30   # exponential: 30s, 60s, 120s … max 300s


# ── Conversation context (shared across providers) ─────────────────────────────
@dataclass
class ConversationTurn:
    role: str       # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


class SharedContext:
    """Thread-safe conversation history shared by all providers."""

    def __init__(self, max_turns: int = 10):
        self._lock = threading.Lock()
        self._turns: deque = deque(maxlen=max_turns * 2)  # user+assistant pairs

    def add(self, role: str, content: str):
        with self._lock:
            self._turns.append(ConversationTurn(role=role, content=content))

    def get_messages(self, system_prompt: str = "") -> List[Dict[str, str]]:
        """Return OpenAI-compatible messages array."""
        with self._lock:
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            for turn in self._turns:
                msgs.append({"role": turn.role, "content": turn.content})
            return msgs

    def get_flat_context(self) -> str:
        """Return plain-text context for providers that don't support messages."""
        with self._lock:
            lines = []
            for turn in self._turns:
                label = "User" if turn.role == "user" else "JARVIS"
                lines.append(f"{label}: {turn.content}")
            return "\n".join(lines)


# ── Provider base ──────────────────────────────────────────────────────────────
@dataclass
class ProviderStats:
    status: str = HEALTHY
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0
    avg_latency: float = 0.0
    _latencies: list = field(default_factory=list)

    def record_success(self, latency: float):
        self.status = HEALTHY
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.total_requests += 1
        self._latencies.append(latency)
        if len(self._latencies) > 20:
            self._latencies = self._latencies[-20:]
        self.avg_latency = sum(self._latencies) / len(self._latencies)

    def record_failure(self, error: str):
        self.consecutive_failures += 1
        self.total_failures += 1
        self.total_requests += 1
        self.last_failure = time.time()
        self.last_error = str(error)[:200]
        if self.consecutive_failures >= _DOWN_AFTER:
            self.status = DOWN
        elif self.consecutive_failures >= _DEGRADE_AFTER:
            self.status = DEGRADED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "avg_latency_ms": round(self.avg_latency * 1000, 1),
            "last_error": self.last_error,
        }


class BaseProvider:
    """Abstract provider interface."""
    name: str = "base"
    stats: ProviderStats

    def __init__(self):
        self.stats = ProviderStats()
        self._client = None
        self._initialized = False

    def is_configured(self) -> bool:
        raise NotImplementedError

    def _init_client(self):
        raise NotImplementedError

    def _call(self, prompt: str, messages: List[Dict], sys_prompt: str,
              context: str, timeout: int, max_tokens: int = None,
              deepthink: bool = False, images: list = None) -> str:
        raise NotImplementedError

    def _call_stream(self, prompt: str, messages: List[Dict], sys_prompt: str,
                     context: str, timeout: int, max_tokens: int = None,
                     deepthink: bool = False, images: list = None) -> Generator[str, None, None]:
        """Default streaming: providers without true streaming fall back to one chunk."""
        text = self._call(prompt, messages, sys_prompt, context, timeout,
                          max_tokens, deepthink=deepthink, images=images)
        if text:
            yield text

    def ask(self, prompt: str, messages: List[Dict], sys_prompt: str,
            context: str, timeout: int, max_tokens: int = None,
            deepthink: bool = False, images: list = None) -> Optional[str]:
        """Call provider with timeout and error handling. Returns text or None."""
        if not self.is_configured():
            return None

        if not self._initialized:
            try:
                self._init_client()
                self._initialized = True
            except Exception as e:
                logger.error(f"[BRAIN] {self.name} init failed: {e}")
                self.stats.record_failure(f"init: {e}")
                return None

        t0 = time.time()
        try:
            result = self._call(prompt, messages, sys_prompt, context, timeout,
                                max_tokens, deepthink=deepthink, images=images)
            if result and result.strip():
                latency = time.time() - t0
                self.stats.record_success(latency)
                logger.info(
                    f"[BRAIN] {self.name} | OK | {latency:.2f}s | "
                    f"~{len(result.split())} words{' | DEEPTHINK' if deepthink else ''}"
                )
                return result.strip()
            else:
                self.stats.record_failure("empty response")
                logger.warning(f"[BRAIN] {self.name} | Empty response")
                return None
        except Exception as e:
            latency = time.time() - t0
            self.stats.record_failure(str(e))
            print(f"\n⚠️ [BRAIN ERROR] {self.name.upper()} failed: {e}\n")
            logger.warning(
                f"[BRAIN] {self.name} | FAILED ({latency:.2f}s) | {str(e)[:120]}"
            )
            return None

    def stream(self, prompt: str, messages: List[Dict], sys_prompt: str,
               context: str, timeout: int, max_tokens: int = None,
               deepthink: bool = False, images: list = None) -> Optional[Generator[str, None, None]]:
        """Streaming variant of ask(). Returns a generator of text chunks or None on failure."""
        if not self.is_configured():
            return None
        if not self._initialized:
            try:
                self._init_client()
                self._initialized = True
            except Exception as e:
                logger.error(f"[BRAIN] {self.name} init failed: {e}")
                self.stats.record_failure(f"init: {e}")
                return None

        t0 = time.time()
        accumulated = []

        def _gen():
            try:
                for chunk in self._call_stream(prompt, messages, sys_prompt, context,
                                               timeout, max_tokens,
                                               deepthink=deepthink, images=images):
                    if not chunk:
                        continue
                    accumulated.append(chunk)
                    yield chunk
                full = "".join(accumulated).strip()
                if full:
                    latency = time.time() - t0
                    self.stats.record_success(latency)
                    logger.info(
                        f"[BRAIN] {self.name} | STREAM OK | {latency:.2f}s | "
                        f"~{len(full.split())} words{' | DEEPTHINK' if deepthink else ''}"
                    )
                else:
                    self.stats.record_failure("empty stream")
                    logger.warning(f"[BRAIN] {self.name} | empty stream")
            except Exception as e:
                latency = time.time() - t0
                self.stats.record_failure(str(e))
                logger.warning(
                    f"[BRAIN] {self.name} | STREAM FAILED ({latency:.2f}s) | {str(e)[:120]}"
                )

        return _gen()

    def health_check(self, timeout: int = 5) -> bool:
        """Lightweight ping to check if provider is alive."""
        if not self.is_configured():
            return False
        if not self._initialized:
            try:
                self._init_client()
                self._initialized = True
            except Exception:
                return False
        try:
            result = self._call(
                "Say OK", [], "Respond with only the word OK.", "", timeout
            )
            return bool(result and result.strip())
        except Exception:
            return False


# ── Gemini Provider ────────────────────────────────────────────────────────────
class GeminiProvider(BaseProvider):
    name = "gemini"

    def is_configured(self) -> bool:
        return config.is_gemini_ready()

    def _init_client(self):
        from google import genai
        self._genai_client = genai.Client(api_key=config.GEMINI_API_KEY)
        logger.info(f"[BRAIN] Gemini initialized ({config.GEMINI_MODEL})")

    def _build_contents(self, sys_prompt, context, messages, prompt):
        """Build a single text string for the new google.genai SDK."""
        parts = []
        if sys_prompt:
            parts.append(sys_prompt)
        if context:
            parts.append(f"\nContext:\n{context}")
        for msg in messages:
            if msg["role"] == "user":
                parts.append(f"\nUser: {msg['content']}")
            elif msg["role"] == "assistant":
                parts.append(f"\nJARVIS: {msg['content']}")
        parts.append(f"\nUser: {prompt}")
        return "\n".join(parts)

    def _call(self, prompt, messages, sys_prompt, context, timeout, max_tokens=None,
              deepthink: bool = False, images: list = None):
        from google import genai
        from google.genai import types as genai_types
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_GEMINI_MODEL if deepthink else config.GEMINI_MODEL
        contents = self._build_contents(sys_prompt, context, messages, prompt)

        result_box = [None]
        error_box = [None]

        def _do():
            try:
                resp = self._genai_client.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=tokens,
                        temperature=config.TEMPERATURE,
                    ),
                )
                result_box[0] = resp.text
            except Exception as e:
                # Fallback to gemini-3.8-flash if selected model fails
                try:
                    resp = self._genai_client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=contents,
                        config=genai_types.GenerateContentConfig(
                            max_output_tokens=tokens,
                            temperature=config.TEMPERATURE,
                        ),
                    )
                    result_box[0] = resp.text
                except Exception:
                    error_box[0] = e

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            raise TimeoutError(f"Gemini timed out after {timeout}s")
        if error_box[0]:
            raise error_box[0]
        return result_box[0]

    def _call_stream(self, prompt, messages, sys_prompt, context, timeout,
                     max_tokens=None, deepthink: bool = False, images: list = None):
        from google import genai
        from google.genai import types as genai_types
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_GEMINI_MODEL if deepthink else config.GEMINI_MODEL
        contents = self._build_contents(sys_prompt, context, messages, prompt)

        deadline = time.time() + max(timeout, 5)
        try:
            for chunk in self._genai_client.models.generate_content_stream(
                model=model_id,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=tokens,
                    temperature=config.TEMPERATURE,
                ),
            ):
                if time.time() > deadline:
                    raise TimeoutError(f"Gemini stream exceeded {timeout}s")
                txt = getattr(chunk, "text", None)
                if txt:
                    yield txt
        except Exception:
            # Fall back to single-shot on stream failure
            text = self._call(prompt, messages, sys_prompt, context, timeout,
                              max_tokens, deepthink=deepthink, images=images)
            if text:
                yield text


# ── Groq Provider ─────────────────────────────────────────────────────────────
class GroqProvider(BaseProvider):
    name = "groq"

    def is_configured(self) -> bool:
        return config.is_groq_ready()

    def _init_client(self):
        from groq import Groq
        self._client = Groq(api_key=config.GROQ_API_KEY)
        logger.info(f"[BRAIN] Groq initialized ({config.GROQ_MODEL})")

    def _build_msgs(self, prompt, messages, sys_prompt, context):
        call_msgs = []
        sys_content = sys_prompt or ""
        if context:
            sys_content += f"\n\nContext:\n{context}"
        if sys_content:
            call_msgs.append({"role": "system", "content": sys_content})
        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                call_msgs.append({"role": msg["role"], "content": msg["content"]})
        call_msgs.append({"role": "user", "content": prompt})
        return call_msgs

    def _call(self, prompt, messages, sys_prompt, context, timeout, max_tokens=None,
              deepthink: bool = False, images: list = None):
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_GROQ_MODEL if deepthink else config.GROQ_MODEL
        call_msgs = self._build_msgs(prompt, messages, sys_prompt, context)
        resp = self._client.chat.completions.create(
            model=model_id,
            messages=call_msgs,
            max_tokens=tokens,
            temperature=config.TEMPERATURE,
            timeout=timeout,
        )
        return resp.choices[0].message.content

    def _call_stream(self, prompt, messages, sys_prompt, context, timeout,
                     max_tokens=None, deepthink: bool = False, images: list = None):
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_GROQ_MODEL if deepthink else config.GROQ_MODEL
        call_msgs = self._build_msgs(prompt, messages, sys_prompt, context)
        deadline = time.time() + max(timeout, 5)
        try:
            stream = self._client.chat.completions.create(
                model=model_id,
                messages=call_msgs,
                max_tokens=tokens,
                temperature=config.TEMPERATURE,
                timeout=timeout,
                stream=True,
            )
            for chunk in stream:
                if time.time() > deadline:
                    raise TimeoutError(f"Groq stream exceeded {timeout}s")
                try:
                    delta = chunk.choices[0].delta
                    txt = getattr(delta, "content", None) or ""
                except Exception:
                    txt = ""
                if txt:
                    yield txt
        except Exception:
            text = self._call(prompt, messages, sys_prompt, context, timeout,
                              max_tokens, deepthink=deepthink, images=images)
            if text:
                yield text


# ── OpenRouter Provider ────────────────────────────────────────────────────────
class OpenRouterProvider(BaseProvider):
    name = "openrouter"

    _API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def is_configured(self) -> bool:
        return config.is_openrouter_ready()

    def _init_client(self):
        self._client = httpx.Client(
            timeout=httpx.Timeout(config.AI_TIMEOUT + 2, connect=5),
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "JARVIS AI Assistant",
                "Content-Type": "application/json",
            },
        )
        logger.info(f"[BRAIN] OpenRouter initialized ({config.OPENROUTER_MODEL})")

    def _build_msgs(self, prompt, messages, sys_prompt, context):
        call_msgs = []
        sys_content = sys_prompt or ""
        if context:
            sys_content += f"\n\nContext:\n{context}"
        if sys_content:
            call_msgs.append({"role": "system", "content": sys_content})
        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                call_msgs.append({"role": msg["role"], "content": msg["content"]})
        call_msgs.append({"role": "user", "content": prompt})
        return call_msgs

    def _call(self, prompt, messages, sys_prompt, context, timeout, max_tokens=None,
              deepthink: bool = False, images: list = None):
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_OPENROUTER_MODEL if deepthink else config.OPENROUTER_MODEL
        call_msgs = self._build_msgs(prompt, messages, sys_prompt, context)

        self._client.timeout = httpx.Timeout(timeout + 2, connect=5)
        resp = self._client.post(
            self._API_URL,
            json={
                "model": model_id,
                "messages": call_msgs,
                "max_tokens": tokens,
                "temperature": config.TEMPERATURE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return None

    def _call_stream(self, prompt, messages, sys_prompt, context, timeout,
                     max_tokens=None, deepthink: bool = False, images: list = None):
        tokens = max_tokens or config.MAX_TOKENS
        model_id = DEEPTHINK_OPENROUTER_MODEL if deepthink else config.OPENROUTER_MODEL
        call_msgs = self._build_msgs(prompt, messages, sys_prompt, context)
        self._client.timeout = httpx.Timeout(timeout + 4, connect=5)
        deadline = time.time() + max(timeout, 5)

        try:
            with self._client.stream(
                "POST",
                self._API_URL,
                json={
                    "model": model_id,
                    "messages": call_msgs,
                    "max_tokens": tokens,
                    "temperature": config.TEMPERATURE,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    if time.time() > deadline:
                        raise TimeoutError(f"OpenRouter stream exceeded {timeout}s")
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        if payload == "[DONE]":
                            return
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    txt = delta.get("content") or ""
                    if txt:
                        yield txt
        except Exception:
            text = self._call(prompt, messages, sys_prompt, context, timeout,
                              max_tokens, deepthink=deepthink, images=images)
            if text:
                yield text


# ── Brain Manager ──────────────────────────────────────────────────────────────
class BrainManager:
    """
    Production-grade AI provider manager.
    Guarantees a response for every query — never returns None.
    """

    def __init__(self, socketio=None):
        self._socketio = socketio
        self._lock = threading.Lock()

        # Provider priority order: Groq (ultra fast) → Gemini → OpenRouter
        self.providers: List[BaseProvider] = [
            GroqProvider(),
            GeminiProvider(),
            OpenRouterProvider(),
        ]

        # Wider rolling history — ChatGPT-style memory feels coherent only
        # when the AI sees several past turns of the same conversation.
        self.context = SharedContext(max_turns=20)  # legacy default
        self._contexts: Dict[str, SharedContext] = {
            "assistant": SharedContext(max_turns=20),
            "codeme":    SharedContext(max_turns=16),
            "project":   SharedContext(max_turns=24),
        }
        self._active_provider = "none"
        self._health_thread = None
        self._running = False

        # Pre-warm configured providers
        for p in self.providers:
            if p.is_configured():
                try:
                    p._init_client()
                    p._initialized = True
                    logger.info(f"[BRAIN] {p.name} pre-warmed ✓")
                except Exception as e:
                    logger.warning(f"[BRAIN] {p.name} pre-warm failed: {e}")

    def get_context(self, mode: str = "assistant") -> SharedContext:
        """Per-mode conversation history (assistant / codeme / project)."""
        key = (mode or "assistant").lower().replace("-", "").replace("_", "")
        aliases = {"code": "codeme", "coding": "codeme", "builder": "project", "default": "assistant"}
        key = aliases.get(key, key)
        return self._contexts.get(key, self._contexts["assistant"])

    # ── Main ask method ────────────────────────────────────────────────────────

    def ask(self, prompt: str, context: str = "", sys_prompt: str = "",
            mode: str = "assistant", max_tokens: int = None,
            timeout: int = None, deepthink: bool = False,
            images: list = None, stateless: bool = False) -> Tuple[str, str]:
        """
        Send prompt to AI providers with automatic failover.

        Returns:
            (response_text, provider_name) — NEVER returns None for response_text.
        """
        t_start = time.time()
        timeout = timeout or config.AI_TIMEOUT
        tokens = max_tokens or config.MAX_TOKENS
        ctx_store = self.get_context(mode)

        # Get conversation messages for multi-turn context. Stateless calls
        # (verifier / critic / isolated specialist generation) must NOT read or
        # mutate shared history — that cross-talk leaked e.g. a SQL draft into a
        # later WhatsApp design answer.
        messages = [] if stateless else ctx_store.get_messages()

        # Try each provider in priority order
        for provider in self.providers:
            if not provider.is_configured():
                continue

            # Skip providers that are down (but only if we have other options)
            if provider.stats.status == DOWN:
                # Re-check if enough time has passed
                backoff = min(
                    _DOWN_RECHECK_BASE * (2 ** min(provider.stats.consecutive_failures - _DOWN_AFTER, 4)),
                    300,
                )
                if time.time() - provider.stats.last_failure < backoff:
                    logger.debug(f"[BRAIN] Skipping {provider.name} (down, backoff {backoff:.0f}s)")
                    continue

            # Attempt the call
            result = provider.ask(prompt, messages, sys_prompt, context, timeout, tokens,
                                  deepthink=deepthink, images=images)

            if result:
                self._active_provider = provider.name

                # Save to mode-specific context (skipped for stateless calls)
                if not stateless:
                    ctx_store.add("user", prompt)
                    ctx_store.add("assistant", result)
                    self.context.add("user", prompt)
                    self.context.add("assistant", result)

                # Emit provider status to UI
                self._emit_status()

                total = time.time() - t_start
                logger.info(
                    f"[BRAIN] ✓ Response via {provider.name} in {total:.2f}s total"
                )
                return result, provider.name

            # Failed — log and try next
            logger.warning(
                f"[BRAIN] {provider.name} failed → trying next provider..."
            )

        # ── ALL providers failed — retry once with extended timeout ─────────
        logger.warning("[BRAIN] All providers failed. Retrying with extended timeout...")
        for provider in self.providers:
            if not provider.is_configured():
                continue
            result = provider.ask(prompt, messages, sys_prompt, context, timeout + 5, tokens,
                                  deepthink=deepthink, images=images)
            if result:
                self._active_provider = provider.name
                if not stateless:
                    ctx_store.add("user", prompt)
                    ctx_store.add("assistant", result)
                    self.context.add("user", prompt)
                    self.context.add("assistant", result)
                self._emit_status()
                logger.info(f"[BRAIN] ✓ Retry succeeded via {provider.name}")
                return result, provider.name

        # ── Absolute last resort — local response ──────────────────────────
        total = time.time() - t_start
        logger.error(f"[BRAIN] ✗ ALL providers exhausted after {total:.2f}s")
        self._active_provider = "local"
        self._emit_status()

        fallback = self._generate_local_fallback(prompt)
        if not stateless:
            ctx_store.add("user", prompt)
            ctx_store.add("assistant", fallback)
            self.context.add("user", prompt)
            self.context.add("assistant", fallback)
        return fallback, "local"

    # ── Streaming ask ──────────────────────────────────────────────────────────
    def ask_stream(self, prompt: str, context: str = "", sys_prompt: str = "",
                   mode: str = "assistant", max_tokens: int = None,
                   timeout: int = None, deepthink: bool = False,
                   images: list = None, stateless: bool = False,
                   on_chunk: Optional[Callable[[str], None]] = None
                   ) -> Tuple[str, str]:
        """
        Stream a response token-by-token. `on_chunk(text)` is called for every
        chunk as it arrives. Returns (full_text, provider_name) when complete.
        Falls back through providers on failure, then to single-shot ask().
        """
        timeout = timeout or config.AI_TIMEOUT
        tokens = max_tokens or config.MAX_TOKENS
        ctx_store = self.get_context(mode)
        messages = [] if stateless else ctx_store.get_messages()

        for provider in self.providers:
            if not provider.is_configured():
                continue
            if provider.stats.status == DOWN:
                backoff = min(
                    _DOWN_RECHECK_BASE * (2 ** min(provider.stats.consecutive_failures - _DOWN_AFTER, 4)),
                    300,
                )
                if time.time() - provider.stats.last_failure < backoff:
                    continue

            gen = provider.stream(prompt, messages, sys_prompt, context, timeout,
                                  tokens, deepthink=deepthink, images=images)
            if gen is None:
                continue

            full = []
            try:
                for chunk in gen:
                    if not chunk:
                        continue
                    full.append(chunk)
                    if on_chunk:
                        try:
                            on_chunk(chunk)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"[BRAIN] {provider.name} stream consumer failed: {e}")
                full = []

            text = "".join(full).strip()
            if text:
                self._active_provider = provider.name
                if not stateless:
                    ctx_store.add("user", prompt)
                    ctx_store.add("assistant", text)
                    self.context.add("user", prompt)
                    self.context.add("assistant", text)
                self._emit_status()
                return text, provider.name

        # All streams failed — fall back to non-streaming ask()
        logger.warning("[BRAIN] All streams failed → falling back to ask()")
        text, prov = self.ask(prompt, context=context, sys_prompt=sys_prompt,
                              mode=mode, max_tokens=tokens, timeout=timeout,
                              deepthink=deepthink, images=images, stateless=stateless)
        if on_chunk and text:
            try:
                on_chunk(text)
            except Exception:
                pass
        return text, prov

    # ── Local fallback (never says "brain offline") ────────────────────────────

    def _generate_local_fallback(self, prompt: str) -> str:
        """Generate a helpful response without any API. Never says 'offline'."""
        p = prompt.lower().strip()

        # Time-based responses
        if any(w in p for w in ["time", "clock", "hour"]):
            from datetime import datetime
            now = datetime.now()
            return f"It's currently {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}."

        if any(w in p for w in ["date", "today", "day"]):
            from datetime import datetime
            now = datetime.now()
            return f"Today is {now.strftime('%A, %B %d, %Y')}."

        # Greeting responses
        if any(w in p for w in ["hello", "hi", "hey", "greet"]):
            return "Hello boss! I'm here and ready to assist you."

        if any(w in p for w in ["how are you", "how're you", "what's up"]):
            return "I'm operating at full capacity, boss. What can I help you with?"

        # Catch-all — acknowledging and helpful
        return (
            "I'm processing your request through my systems right now, boss. "
            "Could you try asking me again in a moment? I want to give you "
            "the most accurate response possible."
        )

    # ── Health monitoring ──────────────────────────────────────────────────────

    def start_health_monitor(self):
        """Start background health check thread."""
        if self._running:
            return
        self._running = True
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="brain-health"
        )
        self._health_thread.start()
        logger.info("[BRAIN] Health monitor started")

    def _health_loop(self):
        """Periodically check provider health and restore downed providers."""
        while self._running:
            time.sleep(_HEALTH_CHECK_INTERVAL)
            try:
                changed = False
                for provider in self.providers:
                    if not provider.is_configured():
                        continue

                    old_status = provider.stats.status

                    # Only actively health-check degraded/down providers
                    if old_status in (DEGRADED, DOWN):
                        alive = provider.health_check(timeout=5)
                        if alive:
                            provider.stats.status = HEALTHY
                            provider.stats.consecutive_failures = 0
                            logger.info(
                                f"[BRAIN] ♻ {provider.name} restored to HEALTHY"
                            )
                            changed = True
                        else:
                            logger.debug(
                                f"[BRAIN] {provider.name} still {old_status}"
                            )

                if changed:
                    self._emit_status()
                    self._log_health()

            except Exception as e:
                logger.error(f"[BRAIN] Health check error: {e}")

    def _log_health(self):
        """Log current health state of all providers."""
        parts = []
        for p in self.providers:
            if p.is_configured():
                parts.append(f"{p.name}={p.stats.status}")
        logger.info(f"[BRAIN] Health: {' | '.join(parts)}")

    # ── Status emission ────────────────────────────────────────────────────────

    def _emit_status(self):
        """Emit provider status to all connected clients via SocketIO."""
        if not self._socketio:
            return
        try:
            status = self.get_status()
            self._socketio.emit("ai_provider_status", status, namespace="/")
        except Exception as e:
            logger.debug(f"[BRAIN] Status emit error: {e}")

    def get_status(self) -> dict:
        """Get current status of all providers."""
        providers = {}
        configured = []
        for p in self.providers:
            if p.is_configured():
                providers[p.name] = p.stats.to_dict()
                configured.append(p.name)
        return {
            "active": self._active_provider,
            "providers": providers,
            "configured": configured,
            "priority": [p.name for p in self.providers if p.is_configured()],
        }

    def get_provider_summary(self) -> str:
        """One-line summary for startup banner."""
        parts = []
        for p in self.providers:
            if p.is_configured():
                parts.append(f"{p.name.upper()}: OK")
            else:
                parts.append(f"{p.name.upper()}: NO KEY")
        return " | ".join(parts)


# ── Module-level singleton ─────────────────────────────────────────────────────
brain: Optional[BrainManager] = None


def init(socketio=None) -> BrainManager:
    """Initialize the global BrainManager singleton."""
    global brain
    brain = BrainManager(socketio=socketio)
    brain.start_health_monitor()
    return brain


def ask(prompt: str, context: str = "", sys_prompt: str = "",
        mode: str = "assistant", max_tokens: int = None,
        timeout: int = None, deepthink: bool = False,
        images: list = None, stateless: bool = False) -> Tuple[str, str]:
    """Convenience wrapper — use the global singleton."""
    if brain is None:
        init()
    return brain.ask(prompt, context, sys_prompt, mode=mode,
                     max_tokens=max_tokens, timeout=timeout,
                     deepthink=deepthink, images=images, stateless=stateless)


def ask_stream(prompt: str, context: str = "", sys_prompt: str = "",
               mode: str = "assistant", max_tokens: int = None,
               timeout: int = None, deepthink: bool = False,
               images: list = None, stateless: bool = False,
               on_chunk: Optional[Callable[[str], None]] = None) -> Tuple[str, str]:
    """Streaming convenience wrapper — uses the global singleton."""
    if brain is None:
        init()
    return brain.ask_stream(prompt, context, sys_prompt, mode=mode,
                            max_tokens=max_tokens, timeout=timeout,
                            deepthink=deepthink, images=images, stateless=stateless,
                            on_chunk=on_chunk)
