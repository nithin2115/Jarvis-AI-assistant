"""
JARVIS TTS Streaming Pipeline
═════════════════════════════
Sentence-level streaming TTS that consumes the SAME chunk stream the
frontend is rendering. Voice and text stay synchronised because both
consumers read from the same buffer in real time.

Pipeline:
    AI provider chunks
        ↓
    feed(chunk)                  ← called from app.py:_on_chunk
        ↓
    accumulator buffer
        ↓
    sentence-boundary splitter   (skips fenced code blocks)
        ↓
    queue (worker thread)
        ↓
    tts.speak(sentence)          ← existing blocking SAPI5 engine
        ↓
    speaker

Key properties
- Voice starts as soon as the FIRST complete sentence is available,
  not when the full response arrives.
- The worker is a single daemon thread per stream so utterances never
  overlap and ordering is preserved.
- cancel() drops the queue and signals the worker to stop AFTER the
  current sentence (we cannot rip the SAPI engine mid-utterance, but
  the next queued sentence will not play).
- Code fences (``` ... ```) are skipped entirely — the voice says
  "code shown on screen" once instead of reading source code.
- Markdown is stripped per-sentence so the speaker hears clean prose.

The public surface is intentionally small so app.py can drive it
without knowing anything about queues or threading:
    start(session_id, on_first=None, on_drain=None)
    feed(session_id, chunk)
    flush(session_id)
    cancel(session_id)
    is_speaking(session_id)
"""
from __future__ import annotations

import re
import time
import queue
import logging
import threading
from typing import Callable, Dict, Optional

import tts as _tts_engine  # existing pyttsx3/sapi5 wrapper

logger = logging.getLogger("jarvis.tts_stream")

# ── Markdown / formatting cleaners (per-sentence, cheap) ─────────────────────
_FENCE_RE       = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE     = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BOLD_ITAL_RE   = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
_LINK_RE        = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_TABLE_PIPE_RE  = re.compile(r"[ \t]*\|[ \t]*")
_BULLET_RE      = re.compile(r"^\s*[-*•]\s+", re.M)
_NUMLIST_RE     = re.compile(r"^\s*\d+[.)]\s+", re.M)
_EMOJI_HEAD_RE  = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*")  # decorative emoji
_MULTISPACE_RE  = re.compile(r"\s+")

# Sentence-end punctuation we'll split on. Includes : and ; for natural pauses.
_SENTENCE_END_RE = re.compile(r"([.!?:;])\s+(?=\S)|([.!?])\s*\n+|(\n{2,})")

# Minimum chars in a sentence before we send it to TTS. Prevents choppy
# single-word utterances ("Hello." "Vamsi." "Today.") and lets us coalesce
# the AI's natural micro-fragments into smooth chunks.
#
# We use a TWO-TIER threshold so the FIRST sentence ships fast (audio
# begins ~300-500ms after the AI's first token) while subsequent
# sentences keep the natural pacing — "Sure." spoken alone feels great
# at the start of a reply but jarring in the middle of a paragraph.
_MIN_SENTENCE_CHARS_FIRST = 8     # first utterance: ship as soon as audible
_MIN_SENTENCE_CHARS_REST  = 18    # rest: longer chunks for natural cadence
# Maximum buffered chars without a boundary — force-flush long monologues.
_HARD_FLUSH_CHARS   = 240


def _strip_markdown(text: str) -> str:
    """Convert a markdown sentence into clean speakable text."""
    if not text:
        return ""
    # Drop code fences entirely (replaced upstream with " " marker).
    text = _FENCE_RE.sub(" code shown on screen. ", text)
    # Strip table pipes → commas (so rows read as natural lists).
    text = _TABLE_PIPE_RE.sub(", ", text)
    # Drop bullet/list markers.
    text = _BULLET_RE.sub("", text)
    text = _NUMLIST_RE.sub("", text)
    # Strip heading hashes.
    text = _HEADING_RE.sub("", text)
    # Bold / italic / inline code → plain.
    text = _BOLD_ITAL_RE.sub(r"\2", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    # Decorative emoji at sentence start (📄, 🎯, 🔧, etc.) — speaker should not say "page facing up".
    text = _EMOJI_HEAD_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    return text


# ── Per-session streaming state ──────────────────────────────────────────────
class _Stream:
    __slots__ = ("sid", "buf", "q", "worker", "alive", "in_fence",
                 "on_first", "on_drain", "first_spoken", "lock")

    def __init__(self, sid: str,
                 on_first: Optional[Callable[[], None]] = None,
                 on_drain: Optional[Callable[[], None]] = None):
        self.sid = sid
        self.buf: str = ""
        self.q: "queue.Queue[Optional[str]]" = queue.Queue()
        self.alive: bool = True
        self.in_fence: bool = False   # are we currently inside ``` ... ``` ?
        self.first_spoken: bool = False
        self.on_first = on_first
        self.on_drain = on_drain
        self.lock = threading.Lock()
        self.worker = threading.Thread(
            target=self._run, name=f"tts-stream-{sid[:8]}", daemon=True,
        )
        self.worker.start()

    # ── Worker loop ──
    def _run(self):
        logger.info(f"[TTS-STREAM] {self.sid[:8]} worker started")
        try:
            while True:
                item = self.q.get()
                if item is None:
                    break  # sentinel → drain
                if not self.alive:
                    # Drop remaining queue silently on cancel.
                    self.q.task_done()
                    continue
                clean = _strip_markdown(item)
                if not clean or len(clean) < 2:
                    self.q.task_done()
                    continue
                if not self.first_spoken:
                    self.first_spoken = True
                    if self.on_first:
                        try: self.on_first()
                        except Exception as e:
                            logger.debug(f"[TTS-STREAM] on_first error: {e}")
                try:
                    _tts_engine.speak(clean)
                except Exception as e:
                    logger.warning(f"[TTS-STREAM] speak error: {e}")
                finally:
                    self.q.task_done()
        finally:
            if self.on_drain:
                try: self.on_drain()
                except Exception as e:
                    logger.debug(f"[TTS-STREAM] on_drain error: {e}")
            logger.info(f"[TTS-STREAM] {self.sid[:8]} worker exited")

    # ── Feeding chunks ──
    def feed(self, chunk: str):
        if not chunk or not self.alive:
            return
        with self.lock:
            self.buf += chunk
            self._drain_sentences_locked()

    def flush(self):
        with self.lock:
            tail = self.buf.strip()
            self.buf = ""
        if tail and self.alive:
            self._enqueue(tail)
        # Send sentinel — worker will exit cleanly after this drains.
        self.q.put(None)

    def cancel(self):
        self.alive = False
        # Clear pending queue (we let the in-flight utterance finish — SAPI
        # has no safe mid-utterance abort; its watchdog timeout caps it).
        try:
            while True:
                self.q.get_nowait()
                self.q.task_done()
        except queue.Empty:
            pass
        self.q.put(None)

    # ── Internal: split buffer on sentence boundaries ──
    def _drain_sentences_locked(self):
        """Pull complete sentences out of the buffer and enqueue them.

        Code fences are tracked across calls: once we see an opening ``` we
        skip everything until the closing ``` (with one spoken marker).
        """
        # Handle code fences first — they swallow line breaks and we never
        # want to read source code aloud.
        while True:
            buf = self.buf
            if self.in_fence:
                end = buf.find("```")
                if end < 0:
                    # Code fence still open — drop everything we have, wait.
                    self.buf = ""
                    return
                # Close fence, emit one "code shown on screen" marker.
                self.in_fence = False
                self.buf = buf[end + 3:]
                self._enqueue("Code shown on screen.")
                continue
            # Not in fence — check for opening fence.
            start = buf.find("```")
            if start < 0:
                break  # no fence anywhere
            # Everything before the fence is normal prose — process it,
            # then enter fence mode.
            pre = buf[:start]
            self.buf = pre  # process this normally below…
            self._split_and_enqueue_locked()
            # …then enter fence and continue scanning the remainder.
            self.in_fence = True
            self.buf = buf[start + 3:]
            # loop continues to find the closing ``` or wait for it

        # Pure-prose path (no open fence): split on sentence punctuation.
        self._split_and_enqueue_locked()

    def _split_and_enqueue_locked(self):
        """Cut self.buf at the latest safe sentence boundary and enqueue."""
        if not self.buf:
            return

        # Find the last sentence terminator in the buffer.
        last_end = -1
        for m in _SENTENCE_END_RE.finditer(self.buf):
            last_end = m.end()
        if last_end <= 0:
            # No boundary yet. Force-flush if we've buffered too much
            # (safety valve for long unpunctuated outputs).
            if len(self.buf) >= _HARD_FLUSH_CHARS:
                head = self.buf
                self.buf = ""
                if len(head.strip()) >= 4:
                    self._enqueue(head)
            return

        head = self.buf[:last_end]
        tail = self.buf[last_end:]

        # If the head is too short, hold it back and wait for more — this
        # avoids speaking "Yes." then a 600ms gap then "I think so."
        # The FIRST utterance gets a smaller threshold so audio starts
        # quickly even when the AI opens with "Sure!" or "Got it.".
        threshold = (_MIN_SENTENCE_CHARS_FIRST if not self.first_spoken
                     else _MIN_SENTENCE_CHARS_REST)
        if len(head.strip()) < threshold:
            return

        self.buf = tail
        self._enqueue(head)

    def _enqueue(self, sentence: str):
        s = sentence.strip()
        if not s:
            return
        # Skip enqueueing the standalone code marker if it's already the
        # tail of the previous one (prevents "code shown on screen. code
        # shown on screen.").
        self.q.put(s)


# ── Registry & public API ────────────────────────────────────────────────────
_streams: Dict[str, _Stream] = {}
_reg_lock = threading.Lock()


def start(session_id: str,
          on_first: Optional[Callable[[], None]] = None,
          on_drain: Optional[Callable[[], None]] = None) -> None:
    """Open a new TTS streaming session.

    `on_first`  fires the moment the FIRST sentence is dispatched to the
                speaker — use it to flip the UI into the speaking state.
    `on_drain`  fires after the LAST sentence has finished playing — use
                it to flip the UI back to idle.
    """
    if not session_id:
        return
    with _reg_lock:
        # If a stream already exists for this id, cancel it first.
        old = _streams.get(session_id)
        if old is not None:
            old.cancel()
        _streams[session_id] = _Stream(session_id, on_first=on_first,
                                       on_drain=on_drain)


def feed(session_id: str, chunk: str) -> None:
    """Append a streaming chunk to the TTS pipeline."""
    if not session_id or not chunk:
        return
    s = _streams.get(session_id)
    if s is not None:
        s.feed(chunk)


def flush(session_id: str) -> None:
    """Signal end-of-stream — speak any remaining buffered text and exit."""
    if not session_id:
        return
    s = _streams.get(session_id)
    if s is not None:
        s.flush()
    # Don't remove from registry yet — the worker may still be reading
    # the last sentences. cleanup() handles GC after drain.
    threading.Thread(target=_cleanup_after, args=(session_id,),
                     daemon=True).start()


def cancel(session_id: str) -> None:
    """Abort: drop pending sentences, let the current utterance finish."""
    if not session_id:
        return
    s = _streams.pop(session_id, None)
    if s is not None:
        s.cancel()


def is_speaking(session_id: str) -> bool:
    s = _streams.get(session_id)
    return bool(s and s.alive and (s.first_spoken or not s.q.empty()))


def _cleanup_after(session_id: str, wait: float = 60.0):
    """Remove the session from the registry once its worker has exited."""
    s = _streams.get(session_id)
    if s is None:
        return
    t0 = time.time()
    while time.time() - t0 < wait:
        if not s.worker.is_alive():
            break
        time.sleep(0.5)
    with _reg_lock:
        _streams.pop(session_id, None)
