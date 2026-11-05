"""
JARVIS local voice server.

Primary pipeline:
  persistent OS microphone stream
    -> Porcupine wake detection (when configured)
    -> Vosk offline speech recognition
    -> Socket.IO command event
    -> TTS response
    -> return to idle listening

The browser may still request mic permission for the visualizer, but speech
recognition is owned by this backend listener.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger("jarvis.voice")


class VoiceState:
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


WAKE_PHRASES = [
    "hey jarvis",
    "hi jarvis",
    "hello jarvis",
    "jarvis",
    "ok jarvis",
    "okay jarvis",
    "yo jarvis",
    "dear jarvis",
    "hey jervis",
    "hi jervis",
    "jar vis",
    "jarv is",
    "javis",
    "hey javis",
    "hey travis",
    "hey service",
    "hello service",
]

# Words that, when they precede a wake-candidate, push the candidate
# over the threshold even if it would normally be borderline. Mirrors
# `speech_postprocess._ADDRESS_PREFIXES`.
_WAKE_ADDRESS_PREFIXES = ("hey", "hi", "hello", "ok", "okay", "yo", "dear")


def _clean_words(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


# Pull the Levenshtein-based fuzzy matcher from the post-processor so
# wake detection and transcription cleanup share a single source of
# truth for "what does Jarvis sound like".
from speech_postprocess import (  # noqa: E402
    JARVIS_PHONETIC_NEIGHBOURS,
    clean_transcription,
    edit_distance,
    looks_like_jarvis,
)


def _has_wake(text: str) -> bool:
    """Fallback textual wake detection for systems without Porcupine access.

    Layered match (cheapest checks first):
      1. exact phrase in the curated WAKE_PHRASES list
      2. ANY token in the utterance looks like 'jarvis' (Levenshtein ≤ 2,
         or curated phonetic neighbour)
      3. an address-prefix (hey/hi/hello/...) followed by a borderline
         candidate ('service', 'travis', etc.) — only then do we accept
         those weaker neighbours

    This catches everything Vosk small-en typically misreads "Jarvis"
    as: javis, jaris, jarvi, jervis, jorvis, harvest, harness, jarvix,
    plus letter-split outputs like 'jar vis'.
    """
    t = _clean_words(text)
    if not t:
        return False

    # Cheap exact-phrase check first.
    if any(w in t for w in WAKE_PHRASES):
        return True

    tokens = t.split()
    if not tokens:
        return False

    # Strong rule: any token is a phonetic match for 'jarvis'.
    # Skip the borderline 'service' here — we only accept it when
    # preceded by an explicit address prefix (handled below).
    for tok in tokens:
        if tok == "service":
            continue
        if looks_like_jarvis(tok):
            return True

    # Weaker rule: address-prefix + borderline neighbour ('service',
    # 'travis', etc.).
    for i in range(len(tokens) - 1):
        if (
            tokens[i] in _WAKE_ADDRESS_PREFIXES
            and tokens[i + 1] in JARVIS_PHONETIC_NEIGHBOURS
        ):
            return True

    return False


def _strip_wake(text: str) -> str:
    """Remove wake words and their phonetic neighbours from recognized text.

    Operates on the LEADING tokens only — if 'jarvis' appears mid-
    sentence (e.g. "tell me what jarvis means"), we keep it. This
    prevents the user's actual command from getting words clipped
    out of the middle.
    """
    t = (text or "").strip()
    if not t:
        return ""
    tokens = t.split()

    # Strip up to 3 leading tokens that match wake/address vocabulary.
    stripped = 0
    while tokens and stripped < 3:
        first = re.sub(r"[^a-z0-9]", "", tokens[0].lower())
        if not first:
            tokens.pop(0)
            stripped += 1
            continue
        if first in _WAKE_ADDRESS_PREFIXES or looks_like_jarvis(first):
            tokens.pop(0)
            stripped += 1
            continue
        break
    return " ".join(tokens).strip()


def _resample(audio_data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample signed 16-bit mono PCM with lightweight linear interpolation."""
    if from_rate == to_rate:
        return audio_data
    samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return b""
    new_length = max(1, int(round(samples.size * (to_rate / float(from_rate)))))
    indices = np.linspace(0, samples.size - 1, new_length)
    resampled = np.interp(indices, np.arange(samples.size), samples)
    return resampled.astype(np.int16).tobytes()


def _rms_energy(audio_bytes: bytes) -> float:
    try:
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples * samples)))
    except Exception:
        return 0.0


def _env_float(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


@dataclass
class MicCandidate:
    index: int
    name: str
    channels: int
    default_rate: int
    test_rate: int
    is_default: bool
    got_data: bool
    energy: float
    score: float


class VoiceServer:
    """Always-ready local microphone listener with recovery and diagnostics."""

    def __init__(self, socketio=None):
        self.socketio = socketio
        self.state = VoiceState.IDLE
        self._lock = threading.RLock()
        self._rec_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=96)

        self._model = None
        self._recognizer = None
        self._vosk_rate = 16000

        self._porcupine = None
        self._wake_mode = "vosk-fallback"
        # Porcupine sensitivity: higher = more recall (fewer missed
        # wakes) at the cost of more false positives. We raise the
        # default from 0.72 → 0.78 because the cooldown (`_wake_cooldown
        # = 1.0s`) plus the state machine already absorb the occasional
        # false fire, and users overwhelmingly complain about MISSED
        # wakes, not false ones. Still env-tunable.
        self._porcupine_sensitivity = _env_float("PORCUPINE_SENSITIVITY", 0.78, 0.1, 1.0)
        self._wake_frame_buffer = bytearray()

        self._device_index: Optional[int] = None
        self._device_name = ""
        self._mic_rate: Optional[int] = None
        self._block_size: Optional[int] = None
        self._failed_devices: set[int] = set()

        self._listen_start = 0.0
        self._listen_timeout = _env_float("JARVIS_LISTEN_TIMEOUT", 9.0, 3.0, 30.0)
        # Adaptive silence-timeout knobs. The OLD code used a fixed
        # 1.15s window that simultaneously cut off thoughtful users
        # ("Jarvis... open VS Code") AND made simple commands ("yes",
        # "stop") feel sluggish. We now derive the effective timeout
        # per-frame from these envelopes:
        #   pre_voice : how long we'll wait after wake for ANY speech
        #               before declaring "no speech detected"
        #   base      : silence-after-speech timeout for normal phrases
        #   conj      : extended timeout when the user just said a
        #               conjunction (and / but / so / because / ...)
        #   max_total : absolute cap so a stuck mic can't loop forever
        self._silence_pre_voice = _env_float("JARVIS_SILENCE_PRE_VOICE", 4.0, 1.0, 12.0)
        self._silence_base = _env_float("JARVIS_SILENCE_BASE", 1.4, 0.4, 4.0)
        self._silence_conj = _env_float("JARVIS_SILENCE_CONJUNCTION", 2.4, 0.5, 6.0)
        self._listen_total_max = _env_float("JARVIS_LISTEN_MAX", 14.0, 5.0, 40.0)
        # Backwards-compat alias used by external callers (do NOT remove).
        self._silence_timeout = self._silence_base
        # Word-level confidence captured from the most recent Vosk
        # final result. Used to attach a quality hint to voice_command
        # events so the UI can render an "I think I heard…" indicator.
        self._last_confidence = 1.0
        self._last_voice_at = 0.0
        self._command_started = False
        self._pending_parts: list[str] = []
        self._last_partial = ""
        self._last_interim_emit = 0.0
        self._last_command = ""
        self._last_command_at = 0.0

        self._state_changed_at = time.time()
        self._last_wake_at = 0.0
        self._wake_cooldown = 1.0
        self._ignore_audio_until = 0.0
        self._reset_requested = threading.Event()
        self._restart_requested = threading.Event()

        self._last_chunk_at = 0.0
        self._last_energy_log = 0.0
        self._last_status_log = 0.0
        self._silent_chunks = 0
        self._total_chunks = 0
        # Start the ambient estimate at a low value (40) so a quiet
        # room calibrates downward fast; was 80, which combined with
        # the old 3.2× multiplier baked-in a 256 floor that masked
        # normal speech on cheap mics.
        self._ambient_energy = _env_float("JARVIS_AMBIENT_START", 40.0, 5.0, 400.0)
        # Threshold-formula knobs, all env-tunable.
        self._energy_floor = _env_float("JARVIS_ENERGY_FLOOR", 80.0, 20.0, 400.0)
        self._energy_ceiling = _env_float("JARVIS_ENERGY_CEILING", 800.0, 300.0, 2500.0)
        self._energy_mult = _env_float("JARVIS_ENERGY_MULT", 2.4, 1.5, 5.0)
        self._stream_errors = 0

        # ── Barge-in (interrupt) VAD that runs DURING the SPEAKING state.
        # When the user produces sustained voice energy above a higher
        # threshold (so JARVIS's own audio bleed-through does not
        # trigger), we fire `_barge_in_callback` so app.py can cancel
        # the active TTS stream + AI generation, then immediately flip
        # the state machine to LISTENING so the next words are captured
        # as a fresh command. This is the centerpiece of "Iron Man"
        # conversational feel — talk over JARVIS naturally.
        self._barge_in_enabled = os.getenv(
            "JARVIS_BARGE_IN", "1"
        ).strip().lower() not in ("0", "false", "off", "no")
        self._barge_in_callback: Optional[Callable[[], None]] = None
        self._barge_in_voiced_frames = 0
        # Sustained frames before we fire — each frame is ~50ms, so 5
        # frames ≈ 250ms of voice. Tunable via env.
        self._barge_in_threshold_frames = int(_env_float(
            "JARVIS_BARGE_IN_FRAMES", 5, 2, 30,
        ))
        # Multiplier on top of the dynamic speech threshold so a single
        # loud TTS syllable doesn't masquerade as the user's voice.
        self._barge_in_energy_mult = _env_float(
            "JARVIS_BARGE_IN_ENERGY_MULT", 1.8, 1.0, 3.0,
        )
        # Cooldown so we never fire two barge-ins back to back (would
        # ping-pong state during the cancellation handshake).
        self._barge_in_cooldown_s = _env_float(
            "JARVIS_BARGE_IN_COOLDOWN", 1.5, 0.3, 5.0,
        )
        self._barge_in_last_at = 0.0

        # ── Continuous conversation window. After JARVIS finishes
        # speaking we stay alert for follow-up speech for N seconds —
        # the user can keep talking WITHOUT repeating the wake word.
        # Set to 0 to disable. Default 12s feels conversational without
        # leaving the mic open all night.
        self._conversation_window_s = _env_float(
            "JARVIS_CONVERSATION_WINDOW", 12.0, 0.0, 60.0,
        )
        self._conversation_active_until = 0.0

        logger.info("[VOICE] VoiceServer created")

    # ------------------------------------------------------------------
    # Public API used by app.py
    # ------------------------------------------------------------------

    def init(self) -> bool:
        """Load recognition engines and bind the best available microphone."""
        if not self._load_vosk():
            return False
        self._init_porcupine()
        if not self._detect_microphone():
            print("[VOICE] [X] Microphone detection failed. Local voice is unavailable.")
            self._emit("voice_status", {"active": False, "status": "No working microphone found"})
            return False
        return True

    def start(self) -> bool:
        if self._running:
            return True
        if self._model is None and not self.init():
            return False

        self._running = True
        self._thread = threading.Thread(target=self._audio_loop, daemon=True, name="voice-audio")
        self._thread.start()
        self._watchdog_thread = threading.Thread(
            target=self._state_watchdog, daemon=True, name="voice-watchdog"
        )
        self._watchdog_thread.start()

        print("[VOICE] [OK] Local voice listener started")
        logger.info("[VOICE] Local voice listener started")
        return True

    def stop(self) -> None:
        self.release_microphone("voice server stopped")
        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None
        print("[VOICE] Local voice listener stopped")
        logger.info("[VOICE] Local voice listener stopped")

    def release_microphone(self, reason: str = "microphone released") -> None:
        """Stop the active mic stream without unloading Vosk/Porcupine engines."""
        was_running = self._running
        self._running = False
        self._restart_requested.set()
        self._drain_queue()
        self._wake_frame_buffer.clear()
        self._clear_command_buffers()
        self.set_state(VoiceState.IDLE)

        current = threading.current_thread()
        for attr in ("_thread", "_watchdog_thread"):
            thread = getattr(self, attr)
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=4.0)
            if thread is not None and not thread.is_alive():
                setattr(self, attr, None)

        status = "Microphone released: %s" % reason
        if was_running:
            print("[VOICE] %s" % status)
            logger.info("[VOICE] %s", status)
        self._emit("voice_status", {"active": False, "status": status, "released": True})

    def notify_speaking_start(self) -> None:
        """Called by app.py before TTS begins so Jarvis does not hear itself."""
        self._drain_queue()
        self.set_state(VoiceState.SPEAKING)
        self._emit("voice_status", {"active": True, "status": "TTS active; mic suppressed"})

    def notify_speaking_end(self) -> None:
        """Called by app.py after TTS ends.

        On the normal path: drops back to IDLE and (if configured)
        opens a continuous-conversation window so the user can keep
        talking without re-saying the wake word.

        On the barge-in path: this becomes a no-op because the audio
        loop has already moved us to LISTENING and started capturing
        the user's interruption — we must NOT clobber that.
        """
        if self.get_state() == VoiceState.LISTENING:
            logger.info("[VOICE] notify_speaking_end no-op (already LISTENING — barge-in)")
            return
        drained = self._drain_queue()
        if drained:
            logger.info("[VOICE] Drained %d chunks after TTS", drained)
        self._clear_command_buffers()
        self._wake_frame_buffer.clear()
        self._ignore_audio_until = time.time() + 0.80
        self._reset_requested.set()

        # Continuous-conversation window: accept speech WITHOUT a wake
        # word for the next N seconds. Frontend can show a subtle
        # "still listening…" affordance using the `conversation_active`
        # event.
        if self._conversation_window_s > 0:
            now = time.time()
            self._conversation_active_until = now + self._conversation_window_s
            self._emit("conversation_active", {
                "window_s": self._conversation_window_s,
                "until":    self._conversation_active_until,
            })
            logger.info("[VOICE] Conversation window open for %.1fs",
                        self._conversation_window_s)
            status = "Conversation active — keep talking"
        else:
            status = "Listening for wake word"

        self.set_state(VoiceState.IDLE)
        self._emit("voice_status", {"active": True, "status": status})

    # ── Barge-in public API ───────────────────────────────────
    def register_barge_in_callback(self, cb: Optional[Callable[[], None]]) -> None:
        """Wire app.py's TTS-cancel + UI-notify hook. Invoked from the
        audio thread when sustained user speech is detected during the
        SPEAKING state. Must be quick + thread-safe."""
        self._barge_in_callback = cb

    def is_in_conversation_window(self) -> bool:
        """True if we are still inside the post-reply continuous
        conversation window (set after `notify_speaking_end`)."""
        return self._conversation_active_until > time.time()

    def start_manual_listening(self) -> None:
        """Manual activation hook for any UI button or debugging client."""
        self._begin_listening(source="manual", text="manual activation", confidence=1.0)

    def reset_to_idle(self, reason: str = "manual reset") -> None:
        self._clear_command_buffers()
        self._wake_frame_buffer.clear()
        self._reset_requested.set()
        self.set_state(VoiceState.IDLE)
        self._emit("voice_status", {"active": True, "status": reason})

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._running,
                "state": self.state,
                "wake_mode": self._wake_mode,
                "device_index": self._device_index,
                "device_name": self._device_name,
                "mic_rate": self._mic_rate,
                "vosk_rate": self._vosk_rate,
                "status": "Listening for wake word" if self.state == VoiceState.IDLE else self.state,
            }

    # ------------------------------------------------------------------
    # Engine and microphone initialization
    # ------------------------------------------------------------------

    def _load_vosk(self) -> bool:
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            model_path = os.getenv("VOSK_MODEL_PATH")
            if not model_path:
                model_path = str(Path(__file__).resolve().parent / "data" / "vosk-model")
            if not os.path.isdir(model_path):
                print("[VOICE] [X] Vosk model not found at %s" % model_path)
                logger.error("[VOICE] Vosk model not found at %s", model_path)
                return False

            print("[VOICE] Loading Vosk model from %s" % model_path)
            self._model = Model(model_path)
            self._recognizer = KaldiRecognizer(self._model, self._vosk_rate)
            self._recognizer.SetWords(True)
            print("[VOICE] [OK] Vosk offline recognizer ready")
            logger.info("[VOICE] Vosk recognizer ready")
            return True
        except ImportError:
            print("[VOICE] [X] vosk is not installed. Run: pip install vosk")
            logger.error("[VOICE] vosk is not installed")
            return False
        except Exception as exc:
            print("[VOICE] [X] Vosk init failed: %s" % exc)
            logger.exception("[VOICE] Vosk init failed")
            return False

    def _init_porcupine(self) -> None:
        """Initialize Porcupine if a Picovoice access key is configured."""
        try:
            import pvporcupine
        except ImportError:
            print("[VOICE] [WARN] pvporcupine not installed; using Vosk wake fallback")
            logger.warning("[VOICE] pvporcupine not installed")
            self._wake_mode = "vosk-fallback"
            return

        access_key = (
            os.getenv("PICOVOICE_ACCESS_KEY")
            or os.getenv("PORCUPINE_ACCESS_KEY")
            or os.getenv("PV_ACCESS_KEY")
            or os.getenv("PV_PORCUPINE_KEY")
        )
        key_file = Path("config") / "porcupine_key.txt"
        if not access_key and key_file.exists():
            access_key = key_file.read_text(encoding="utf-8").strip()

        if not access_key:
            print("[VOICE] [WARN] Porcupine key not configured; using Vosk wake fallback")
            print("[VOICE]        Set PICOVOICE_ACCESS_KEY or create config/porcupine_key.txt")
            logger.warning("[VOICE] Porcupine key not configured")
            self._wake_mode = "vosk-fallback"
            return

        try:
            keyword_path = os.getenv("PORCUPINE_KEYWORD_PATH", "").strip()
            keyword_paths = []
            if keyword_path:
                keyword_paths.append(keyword_path)
            else:
                for candidate in (
                    Path("config") / "jarvis.ppn",
                    Path("config") / "wake_word_models" / "jarvis.ppn",
                ):
                    if candidate.exists():
                        keyword_paths.append(str(candidate))
                        break

            kwargs: dict[str, Any] = {
                "access_key": access_key,
                "sensitivities": [self._porcupine_sensitivity],
            }
            if keyword_paths:
                kwargs["keyword_paths"] = keyword_paths
                label = keyword_paths[0]
            else:
                kwargs["keywords"] = ["jarvis"]
                label = "built-in:jarvis"

            self._porcupine = pvporcupine.create(**kwargs)
            self._vosk_rate = int(self._porcupine.sample_rate)
            self._wake_mode = "porcupine"
            print(
                "[VOICE] [OK] Porcupine wake ready (%s, frame=%d, sensitivity=%.2f)"
                % (label, self._porcupine.frame_length, self._porcupine_sensitivity)
            )
            logger.info(
                "[VOICE] Porcupine ready label=%s frame=%d sensitivity=%.2f",
                label,
                self._porcupine.frame_length,
                self._porcupine_sensitivity,
            )
            self._reset_recognizer()
        except Exception as exc:
            print("[VOICE] [WARN] Porcupine init failed: %s" % exc)
            print("[VOICE]        Continuing with Vosk wake fallback")
            logger.exception("[VOICE] Porcupine init failed")
            self._porcupine = None
            self._wake_mode = "vosk-fallback"

    def _detect_microphone(self) -> bool:
        """Find and bind the best working input device with fallbacks."""
        try:
            import sounddevice as sd
        except ImportError:
            print("[VOICE] [X] sounddevice is not installed. Run: pip install sounddevice")
            logger.error("[VOICE] sounddevice is not installed")
            return False

        try:
            devices = sd.query_devices()
        except Exception as exc:
            print("[VOICE] [X] Could not query audio devices: %s" % exc)
            logger.exception("[VOICE] Could not query audio devices")
            return False

        default_input = self._default_input_index(sd)
        input_devices = []
        print("[VOICE] === MICROPHONE DETECTION ===")
        for index, dev in enumerate(devices):
            channels = int(dev.get("max_input_channels", 0))
            if channels <= 0:
                continue
            default_rate = int(float(dev.get("default_samplerate") or self._vosk_rate))
            name = str(dev.get("name", "Input %d" % index))
            is_default = index == default_input
            marker = " [DEFAULT]" if is_default else ""
            print(
                "[VOICE]   [%d] %s | channels=%d | default_rate=%d%s"
                % (index, name, channels, default_rate, marker)
            )
            input_devices.append((index, name, channels, default_rate, is_default))

        if not input_devices:
            print("[VOICE] [X] No input devices reported by the OS")
            logger.error("[VOICE] No input devices reported by the OS")
            return False

        input_devices.sort(key=lambda d: (not d[4], d[0] in self._failed_devices, d[0]))
        candidates: list[MicCandidate] = []

        for index, name, channels, default_rate, is_default in input_devices:
            for rate in self._candidate_rates(default_rate):
                candidate = self._test_input_device(sd, index, name, channels, default_rate, rate, is_default)
                if candidate is not None:
                    candidates.append(candidate)
                    break

        if not candidates and self._failed_devices:
            print("[VOICE] [WARN] Retrying previously failed microphones")
            self._failed_devices.clear()
            return self._detect_microphone()

        if not candidates:
            print("[VOICE] [X] No microphone could be opened")
            logger.error("[VOICE] No microphone could be opened")
            return False

        candidates.sort(key=lambda c: (-c.score, not c.is_default, c.index))
        selected = candidates[0]
        self._device_index = selected.index
        self._device_name = selected.name
        self._mic_rate = selected.test_rate
        self._block_size = self._stream_block_size(selected.test_rate)

        if selected.energy <= 1.0:
            print("[VOICE] [WARN] Selected microphone is open but silent; check mute/privacy controls")
            logger.warning("[VOICE] Selected mic is open but silent")

        print(
            "[VOICE] [OK] Bound microphone [%d] %s | rate=%d -> %d | block=%d | energy=%.1f | wake=%s"
            % (
                self._device_index,
                self._device_name,
                self._mic_rate,
                self._vosk_rate,
                self._block_size,
                selected.energy,
                self._wake_mode,
            )
        )
        logger.info(
            "[VOICE] Bound mic index=%s name=%s mic_rate=%s vosk_rate=%s block=%s energy=%.1f wake=%s",
            self._device_index,
            self._device_name,
            self._mic_rate,
            self._vosk_rate,
            self._block_size,
            selected.energy,
            self._wake_mode,
        )
        self._emit("voice_status", self.get_status())
        return True

    def _default_input_index(self, sd) -> Optional[int]:
        try:
            default = sd.default.device
            if isinstance(default, (list, tuple)) and default:
                index = int(default[0])
                return index if index >= 0 else None
            index = int(default)
            return index if index >= 0 else None
        except Exception:
            return None

    def _candidate_rates(self, default_rate: int) -> list[int]:
        rates = [self._vosk_rate, default_rate, 48000, 44100, 32000]
        unique: list[int] = []
        for rate in rates:
            if rate and rate > 0 and rate not in unique:
                unique.append(int(rate))
        return unique

    def _test_input_device(
        self,
        sd,
        index: int,
        name: str,
        channels: int,
        default_rate: int,
        test_rate: int,
        is_default: bool,
    ) -> Optional[MicCandidate]:
        chunks: list[bytes] = []
        statuses: list[str] = []

        def callback(indata, frames, time_info, status):
            if status:
                statuses.append(str(status))
            chunks.append(bytes(indata))

        try:
            blocksize = max(256, int(test_rate * 0.04))
            with sd.RawInputStream(
                device=index,
                samplerate=test_rate,
                blocksize=blocksize,
                dtype="int16",
                channels=1,
                callback=callback,
            ):
                time.sleep(0.45)
        except Exception as exc:
            print("[VOICE]   [%d] %s @ %dHz failed: %s" % (index, name, test_rate, exc))
            logger.warning("[VOICE] Mic test failed index=%s rate=%s error=%s", index, test_rate, exc)
            return None

        got_data = bool(chunks)
        energy = _rms_energy(b"".join(chunks)) if got_data else 0.0
        score = 0.0
        if is_default:
            score += 100.0
        if got_data:
            score += 35.0
        if energy > 20.0:
            score += min(45.0, energy / 25.0)
        if test_rate == self._vosk_rate:
            score += 20.0
        if index not in self._failed_devices:
            score += 10.0

        status_note = "; ".join(statuses[-2:]) if statuses else "ok"
        print(
            "[VOICE]   [%d] %s @ %dHz -> data=%s energy=%.1f score=%.1f status=%s"
            % (index, name, test_rate, got_data, energy, score, status_note)
        )
        logger.info(
            "[VOICE] Mic test index=%s name=%s rate=%s data=%s energy=%.1f score=%.1f status=%s",
            index,
            name,
            test_rate,
            got_data,
            energy,
            score,
            status_note,
        )

        return MicCandidate(index, name, channels, default_rate, test_rate, is_default, got_data, energy, score)

    def _stream_block_size(self, rate: int) -> int:
        if self._porcupine is not None and rate == self._vosk_rate:
            return int(self._porcupine.frame_length)
        return max(256, int(rate * 0.04))

    # ------------------------------------------------------------------
    # Persistent audio loop
    # ------------------------------------------------------------------

    def _audio_loop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            print("[VOICE] [X] sounddevice is not installed")
            return

        while self._running:
            try:
                if self._device_index is None and not self._detect_microphone():
                    time.sleep(5)
                    continue
                self._run_stream(sd)
                self._stream_errors = 0
            except Exception as exc:
                if not self._running:
                    break
                self._stream_errors += 1
                if self._device_index is not None:
                    self._failed_devices.add(self._device_index)
                backoff = min(12.0, 1.5 * self._stream_errors)
                print(
                    "[VOICE] [RECOVER] Stream error #%d: %s; restarting in %.1fs"
                    % (self._stream_errors, exc, backoff)
                )
                logger.exception("[VOICE] Stream error #%d", self._stream_errors)
                self._emit(
                    "voice_status",
                    {"active": False, "status": "Mic stream recovering", "error": str(exc)},
                )
                self._drain_queue()
                self._wake_frame_buffer.clear()
                self._reset_requested.set()
                if self._stream_errors == 1 or self._stream_errors % 3 == 0:
                    self._detect_microphone()
                time.sleep(backoff)

        logger.info("[VOICE] Audio loop stopped")

    def _run_stream(self, sd) -> None:
        if self._device_index is None or self._mic_rate is None or self._block_size is None:
            raise RuntimeError("microphone is not selected")

        self._drain_queue()
        self._last_chunk_at = time.time()
        self._restart_requested.clear()
        needs_resample = self._mic_rate != self._vosk_rate

        def callback(indata, frames, time_info, status):
            self._last_chunk_at = time.time()
            if status:
                logger.debug("[VOICE] Audio callback status: %s", status)
            chunk = bytes(indata)
            try:
                self._audio_queue.put_nowait(chunk)
            except queue.Full:
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._audio_queue.put_nowait(chunk)
                except queue.Full:
                    pass

        print(
            "[VOICE] Opening persistent mic stream device=%s rate=%s block=%s wake=%s"
            % (self._device_index, self._mic_rate, self._block_size, self._wake_mode)
        )
        logger.info(
            "[VOICE] Opening stream device=%s name=%s rate=%s block=%s wake=%s",
            self._device_index,
            self._device_name,
            self._mic_rate,
            self._block_size,
            self._wake_mode,
        )

        with sd.RawInputStream(
            device=self._device_index,
            samplerate=self._mic_rate,
            blocksize=self._block_size,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            self._stream_errors = 0
            self._last_energy_log = time.time()
            self._last_status_log = time.time()
            self._emit("voice_status", self.get_status())
            print("[VOICE] [OK] Mic stream alive; listening for Jarvis")

            while self._running:
                if self._restart_requested.is_set():
                    raise RuntimeError("stream restart requested")

                if time.time() - self._last_chunk_at > 6.0:
                    raise RuntimeError("no microphone frames received for 6 seconds")

                try:
                    raw = self._audio_queue.get(timeout=0.75)
                except queue.Empty:
                    continue

                if time.time() < self._ignore_audio_until:
                    continue

                if self._reset_requested.is_set():
                    self._reset_requested.clear()
                    self._reset_recognizer()

                audio16 = _resample(raw, self._mic_rate, self._vosk_rate) if needs_resample else raw
                energy = _rms_energy(audio16)
                self._log_energy(energy)

                current = self.get_state()
                if current == VoiceState.SPEAKING:
                    # JARVIS is talking — normally we drop frames so the
                    # mic doesn't hear itself. With barge-in enabled, we
                    # run a tiny VAD that lets the user interrupt by
                    # speaking sustained energy over the speech
                    # threshold. See `_maybe_barge_in` for the gating.
                    if self._barge_in_enabled:
                        self._maybe_barge_in(audio16, energy)
                    continue
                if current == VoiceState.PROCESSING:
                    continue

                if current == VoiceState.IDLE:
                    remainder = self._process_idle_audio(audio16, energy)
                    if remainder and self.get_state() == VoiceState.LISTENING:
                        self._process_listening_audio(remainder, energy)
                elif current == VoiceState.LISTENING:
                    self._process_listening_audio(audio16, energy)

    def _process_idle_audio(self, audio16: bytes, energy: float) -> bytes:
        self._update_ambient_energy(energy)

        # ── Continuous conversation: skip the wake word ASAP ──
        # If we are still inside the post-reply window AND the user
        # produces speech-level energy, transition straight to
        # LISTENING and let the rest of this frame feed Vosk. This is
        # what makes follow-ups feel seamless: "What about tomorrow?"
        # right after JARVIS finishes a weather reply.
        if self._conversation_active_until > 0:
            now = time.time()
            if now <= self._conversation_active_until:
                if energy > self._speech_threshold():
                    print(
                        "[VOICE] [CONV] continuation detected (energy=%.1f, "
                        "threshold=%.1f, remaining=%.1fs)"
                        % (energy, self._speech_threshold(),
                           self._conversation_active_until - now)
                    )
                    logger.info("[VOICE] Conversation continuation detected")
                    self._conversation_active_until = 0.0
                    self._begin_listening(
                        source="conversation",
                        text="(continuing)",
                        confidence=0.9,
                    )
                    # Return the same frame so the LISTENING handler
                    # can immediately consume it as the first audio of
                    # the follow-up command.
                    return audio16
            else:
                # Window expired without speech — fall back to wake-word.
                self._conversation_active_until = 0.0
                self._emit("conversation_expired", {})
                logger.info("[VOICE] Conversation window expired")

        if self._porcupine is not None:
            return self._process_porcupine(audio16)
        self._process_vosk_wake(audio16)
        return b""

    def _process_porcupine(self, audio16: bytes) -> bytes:
        frame_length = int(self._porcupine.frame_length)
        frame_bytes = frame_length * 2
        self._wake_frame_buffer.extend(audio16)

        while len(self._wake_frame_buffer) >= frame_bytes:
            frame = bytes(self._wake_frame_buffer[:frame_bytes])
            del self._wake_frame_buffer[:frame_bytes]
            pcm = np.frombuffer(frame, dtype=np.int16)
            try:
                keyword_index = self._porcupine.process(pcm)
            except Exception as exc:
                logger.exception("[VOICE] Porcupine process failed")
                raise RuntimeError("porcupine failed: %s" % exc) from exc

            if keyword_index >= 0:
                now = time.time()
                if now - self._last_wake_at < self._wake_cooldown:
                    logger.debug("[VOICE] Wake ignored during cooldown")
                    continue
                print(
                    "[VOICE] [WAKE] Porcupine hit index=%d confidence=1.00 sensitivity=%.2f"
                    % (keyword_index, self._porcupine_sensitivity)
                )
                logger.info(
                    "[VOICE] Wake detected source=porcupine index=%s confidence=1.00 sensitivity=%.2f",
                    keyword_index,
                    self._porcupine_sensitivity,
                )
                remainder = bytes(self._wake_frame_buffer)
                self._wake_frame_buffer.clear()
                self._begin_listening(source="porcupine", text="jarvis", confidence=1.0)
                return remainder

        return b""

    def _process_vosk_wake(self, audio16: bytes) -> None:
        final, text = self._feed_vosk(audio16)
        if not text:
            return

        confidence = 0.74 if final else 0.58
        if _has_wake(text):
            cmd = _strip_wake(text)
            print("[VOICE] [WAKE] Vosk fallback confidence=%.2f text=\"%s\"" % (confidence, text))
            logger.info("[VOICE] Wake detected source=vosk confidence=%.2f text=%s", confidence, text)
            self._begin_listening(source="vosk", text=text, confidence=confidence)
            if cmd and len(cmd) > 2:
                self._emit_command(cmd)

    # Tokens at the END of a partial transcript that signal "the user
    # is mid-thought, give them more breathing room before we cut".
    # Lowercased, whitespace-stripped.
    _CONJUNCTION_CUES = frozenset({
        "and", "or", "but", "so", "because", "however", "with",
        "from", "to", "for", "of", "in", "on", "if", "while", "when",
        "then", "as", "by", "the", "a", "an", "my", "our", "your",
        "is", "are", "was", "were", "be",
    })

    def _adaptive_silence_timeout(self) -> float:
        """How long to wait after the user stops talking before we
        finalise the command. Depends on what they JUST said."""
        partial = (self._last_partial or "").strip().lower()
        if not partial:
            return self._silence_base
        last = partial.rsplit(" ", 1)[-1]
        # If they trail off on a connector ("and", "with", "because"),
        # they're almost certainly mid-thought. Wait longer.
        if last in self._CONJUNCTION_CUES:
            return self._silence_conj
        # Very short utterances ("yes", "no", "stop", "ok") are usually
        # complete on their own — don't make the user wait.
        if len(partial) <= 4:
            return max(0.55, self._silence_base * 0.6)
        return self._silence_base

    def _process_listening_audio(self, audio16: bytes, energy: float) -> None:
        now = time.time()
        threshold = self._speech_threshold()
        if energy > threshold:
            self._command_started = True
            self._last_voice_at = now

        final, text = self._feed_vosk(audio16)
        if text:
            clean = _strip_wake(text)
            if clean:
                self._command_started = True
                self._last_voice_at = now
                if final:
                    self._pending_parts.append(clean)
                    self._last_partial = ""
                    self._emit_interim(clean, final=True)
                    self._emit_command(self._collect_command())
                    return
                self._last_partial = clean
                self._emit_interim(clean, final=False)

        age = now - self._listen_start
        if not self._command_started:
            # Pre-voice grace window — short so a misfire wake doesn't
            # leave the orb in LISTENING for 8 full seconds.
            if age > self._silence_pre_voice:
                self._listening_timeout("no speech detected after wake")
            return

        silence_age = now - self._last_voice_at if self._last_voice_at else 0.0
        effective_timeout = self._adaptive_silence_timeout()
        if silence_age > effective_timeout:
            command = self._collect_command()
            if command and len(command) >= 2:
                print(
                    "[VOICE] [QUERY] finalised by silence (%.2fs): \"%s\""
                    % (effective_timeout, command)
                )
                logger.info(
                    "[VOICE] Query finalised by silence (%.2fs): %s",
                    effective_timeout, command,
                )
                self._emit_command(command)
            elif age > self._listen_timeout:
                self._listening_timeout("speech was too short")

        # Hard cap so a stuck loop or never-ending partial cannot
        # keep the mic open forever.
        if age > self._listen_total_max:
            self._listening_timeout("command capture timed out")

    # ------------------------------------------------------------------
    # State and recognition helpers
    # ------------------------------------------------------------------

    def set_state(self, new_state: str) -> None:
        with self._lock:
            old = self.state
            self.state = new_state
            self._state_changed_at = time.time()
        if old != new_state:
            print("[VOICE] [%s] -> [%s]" % (old, new_state))
            logger.info("[VOICE] State: %s -> %s", old, new_state)
            self._emit("voice_state", {"state": new_state, "prev": old})

    def get_state(self) -> str:
        with self._lock:
            return self.state

    def _begin_listening(self, source: str, text: str, confidence: float) -> None:
        current = self.get_state()
        if current in (VoiceState.PROCESSING, VoiceState.SPEAKING):
            logger.info("[VOICE] Ignoring wake while state=%s", current)
            return

        now = time.time()
        self._last_wake_at = now
        self._listen_start = now
        self._last_voice_at = 0.0
        self._command_started = False
        self._clear_command_buffers()
        self._reset_recognizer()
        self.set_state(VoiceState.LISTENING)
        self._emit(
            "wake_detected",
            {"text": text, "source": source, "confidence": round(confidence, 3)},
        )
        self._emit("voice_interim", {"text": "Yes?"})
        self._emit(
            "voice_status",
            {
                "active": True,
                "status": "Wake detected; listening for command",
                "wake_source": source,
                "wake_confidence": round(confidence, 3),
            },
        )

    # ── Barge-in detection (during SPEAKING) ────────────────────────────
    def _maybe_barge_in(self, audio16: bytes, energy: float) -> None:
        """Run only while state == SPEAKING. Counts consecutive frames
        whose energy exceeds (speech_threshold * energy_mult). Once we
        cross `_barge_in_threshold_frames`, fire the interrupt.

        We slowly DECAY the streak instead of resetting on a single
        quiet frame — micro-pauses inside the user's interruption
        ("Wait… actually…") shouldn't kill the detection.
        """
        now = time.time()
        # Cooldown: don't double-fire during the cancellation handshake.
        if now - self._barge_in_last_at < self._barge_in_cooldown_s:
            return

        bi_threshold = self._speech_threshold() * self._barge_in_energy_mult
        if energy >= bi_threshold:
            self._barge_in_voiced_frames += 1
        elif self._barge_in_voiced_frames > 0:
            self._barge_in_voiced_frames -= 1

        if self._barge_in_voiced_frames >= self._barge_in_threshold_frames:
            self._trigger_barge_in()

    def _trigger_barge_in(self) -> None:
        """User started talking while JARVIS was speaking. Cancel the
        active TTS stream via the registered callback, flip to
        LISTENING, and emit `barge_in` so the UI can finalize the
        partial bubble."""
        now = time.time()
        self._barge_in_last_at = now
        self._barge_in_voiced_frames = 0
        print("[VOICE] [BARGE-IN] User interrupted JARVIS")
        logger.info("[VOICE] Barge-in detected at %.3f", now)

        self._emit("barge_in", {"at": now})

        # Notify app.py: cancel TTS stream + abort the AI generator.
        if self._barge_in_callback is not None:
            try:
                self._barge_in_callback()
            except Exception as exc:
                logger.exception("[VOICE] Barge-in callback failed: %s", exc)

        # Flip to LISTENING IMMEDIATELY so the user's continuing speech
        # lands on the command capture path. We do NOT call
        # `_begin_listening` because that would emit `wake_detected` —
        # this isn't a wake; it's a continuation.
        self._listen_start = now
        self._last_voice_at = now
        self._command_started = True   # the first frame already had voice
        self._clear_command_buffers()
        self._reset_recognizer()
        self.set_state(VoiceState.LISTENING)
        # Tell the UI we're listening to the interruption.
        self._emit("voice_status", {
            "active": True,
            "status": "Interruption captured — listening",
            "barge_in": True,
        })

    def _emit_command(self, command: str) -> None:
        # Step 1: collapse whitespace.
        command = re.sub(r"\s+", " ", (command or "")).strip()
        if not command or len(command) < 2:
            self._listening_timeout("empty command")
            return

        # Step 2: post-process the raw Vosk transcription. Fixes the
        # "open vs cold" / "java script" / "git hub" / "javis" class
        # of mistranscriptions, and applies memory-aware casing for
        # topics the user talks about often.
        hints = self._build_transcription_hints()
        try:
            cleaned = clean_transcription(command, hints=hints)
            if cleaned and len(cleaned) >= 2:
                if cleaned != command:
                    logger.info(
                        "[VOICE] Cleaned: %r -> %r (hints=%d)",
                        command, cleaned, len(hints) if hints else 0,
                    )
                command = cleaned
        except Exception as exc:
            # Post-processing must never break voice. Fall back to raw.
            logger.warning("[VOICE] post-process failed: %s", exc)

        now = time.time()
        if command == self._last_command and now - self._last_command_at < 1.5:
            logger.info("[VOICE] Duplicate command suppressed: %s", command)
            self._listening_timeout("duplicate")
            return

        # ── ECHO DETECTION: reject if STT heard JARVIS's own speech ──
        # Compare recognized words against the last AI response. If >60%
        # of words match, this is almost certainly the mic picking up TTS
        # output — discard it to prevent the self-conversation loop.
        try:
            import app as _app_mod
            last_ai = getattr(_app_mod, 'get_last_ai_response', lambda: '')()
            if last_ai and len(command) > 3:
                cmd_words = set(re.sub(r'[^a-z0-9 ]', ' ', command.lower()).split())
                ai_words = set(re.sub(r'[^a-z0-9 ]', ' ', last_ai.lower()).split())
                if cmd_words and ai_words:
                    overlap = len(cmd_words & ai_words)
                    ratio = overlap / max(1, len(cmd_words))
                    if ratio > 0.60:
                        logger.warning(
                            "[VOICE] [ECHO-BLOCKED] STT matched %.0f%% of last AI response, "
                            "discarding: %r", ratio * 100, command
                        )
                        print("[VOICE] [ECHO-BLOCKED] Rejected self-echo: %s" % command[:60])
                        self._listening_timeout("echo detected")
                        return
        except Exception as exc:
            logger.debug("[VOICE] Echo detection failed (non-fatal): %s", exc)

        self._last_command = command
        self._last_command_at = now
        confidence = round(float(self._last_confidence or 0.0), 3)
        print("[VOICE] [COMMAND] \"%s\" (conf=%.2f)" % (command, confidence))
        logger.info("[VOICE] Command emitted: %s (conf=%.2f)", command, confidence)
        self._emit(
            "voice_command",
            {"text": command, "source": "local", "confidence": confidence},
        )
        self.set_state(VoiceState.PROCESSING)
        self._clear_command_buffers()
        self._wake_frame_buffer.clear()
        self._reset_requested.set()

    def _build_transcription_hints(self) -> list[str]:
        """Pull the user's active topics from the memory layer to
        bias transcription post-processing toward correct casing.

        Falls back to an empty list if memory isn't reachable so the
        voice pipeline never breaks because of a memory error. Cached
        for 30s so we don't hammer the DB on every utterance.
        """
        now = time.time()
        cache = getattr(self, "_hints_cache", None)
        if cache and (now - cache[0]) < 30.0:
            return cache[1]

        hints: list[str] = []
        try:
            import memory  # local import to avoid circular load at module init
            mem = getattr(memory, "memory", None)
            if mem is not None and hasattr(mem, "top_topics"):
                rows = mem.top_topics(n=8) or []
                for row in rows:
                    cat = (row.get("category") or "").strip()
                    if cat and cat.lower() != "general":
                        hints.append(cat)
        except Exception as exc:
            logger.debug("[VOICE] hint build skipped: %s", exc)

        # Always include the canonical brand/tool words so they never
        # render lowercase even for users with no memory yet.
        baseline = ["Jarvis", "VS Code", "GitHub", "JavaScript", "Python",
                    "JSON", "API", "URL", "HTML", "CSS", "AI"]
        for word in baseline:
            if word not in hints:
                hints.append(word)

        self._hints_cache = (now, hints)
        return hints

    def _emit_interim(self, text: str, final: bool) -> None:
        now = time.time()
        if not final and now - self._last_interim_emit < 0.25:
            return
        self._last_interim_emit = now
        self._emit("voice_interim", {"text": text if final else text + "..."})

    def _collect_command(self) -> str:
        if self._pending_parts:
            text = " ".join(self._pending_parts)
            if self._last_partial and self._last_partial not in text:
                text = text + " " + self._last_partial
        else:
            text = self._last_partial
        return _strip_wake(text)

    def _feed_vosk(self, audio16: bytes) -> tuple[bool, str]:
        """Feed one PCM frame to Vosk and return (is_final, text).

        Side effect: when a FINAL result is produced, also captures
        the mean word-level confidence into `self._last_confidence`.
        Vosk emits a per-word `conf` array when `SetWords(True)` is
        on, which is how we get a quality estimate without shipping
        a heavier engine like Whisper. The confidence is only mean-
        ingful for finals; partials get a static 1.0.
        """
        if not audio16:
            return False, ""
        with self._rec_lock:
            if self._recognizer is None:
                return False, ""
            try:
                if self._recognizer.AcceptWaveform(audio16):
                    result = json.loads(self._recognizer.Result())
                    text = (result.get("text") or "").strip()
                    # Average per-word confidence. If the recogniser
                    # did not include the per-word array (e.g. SetWords
                    # was never called), fall back to a neutral 0.85.
                    words = result.get("result") or []
                    if words:
                        confs = [float(w.get("conf", 0.0)) for w in words]
                        self._last_confidence = (
                            sum(confs) / len(confs) if confs else 0.85
                        )
                    else:
                        self._last_confidence = 0.85 if text else 0.0
                    return True, text
                partial = json.loads(self._recognizer.PartialResult())
                return False, (partial.get("partial") or "").strip()
            except Exception as exc:
                logger.exception("[VOICE] Vosk recognition failed")
                raise RuntimeError("vosk recognition failed: %s" % exc) from exc

    def _reset_recognizer(self) -> None:
        if self._model is None:
            return
        try:
            from vosk import KaldiRecognizer

            with self._rec_lock:
                self._recognizer = KaldiRecognizer(self._model, self._vosk_rate)
                self._recognizer.SetWords(True)
            logger.debug("[VOICE] Vosk recognizer reset")
        except Exception as exc:
            print("[VOICE] [WARN] Recognizer reset failed: %s" % exc)
            logger.exception("[VOICE] Recognizer reset failed")

    def _listening_timeout(self, reason: str) -> None:
        print("[VOICE] [TIMEOUT] %s; back to idle" % reason)
        logger.warning("[VOICE] Listening timeout: %s", reason)
        self._clear_command_buffers()
        self._wake_frame_buffer.clear()
        self._reset_requested.set()
        self.set_state(VoiceState.IDLE)
        self._emit("voice_timeout", {"reason": reason})

    def _clear_command_buffers(self) -> None:
        self._pending_parts.clear()
        self._last_partial = ""
        self._last_interim_emit = 0.0
        self._command_started = False
        self._last_voice_at = 0.0

    def _drain_queue(self) -> int:
        drained = 0
        while True:
            try:
                self._audio_queue.get_nowait()
                drained += 1
            except queue.Empty:
                return drained

    # ------------------------------------------------------------------
    # Health, logging, and watchdogs
    # ------------------------------------------------------------------

    def _update_ambient_energy(self, energy: float) -> None:
        # Track the ambient noise floor with a leaky integrator. We
        # only consider frames that look like background (well below
        # the current speech threshold) so loud TTS or actual speech
        # can't poison the average.
        if energy < self._speech_threshold() * 0.9:
            # Faster adaptation when state is IDLE — this is when the
            # user just opened the app in a new acoustic environment
            # and we need to calibrate to "quiet bedroom" or "noisy
            # cafe" within a couple of seconds. Once we're listening,
            # we track more slowly so a brief silence between words
            # doesn't push the floor up mid-utterance.
            alpha = 0.08 if self.state == VoiceState.IDLE else 0.03
            self._ambient_energy = (
                self._ambient_energy * (1.0 - alpha) + energy * alpha
            )

    def _speech_threshold(self) -> float:
        # Floor lowered from 150 → 80 RMS so cheap laptop mics in quiet
        # rooms (where typical speech RMS is 90-200) actually clear the
        # gate. Multiplier lowered from 3.2 → 2.4 so we're 1.4× more
        # sensitive overall. Cap kept at ~800 to avoid pathological
        # hot-mic readings dominating the threshold. All values are
        # env-tunable for users with unusual hardware.
        return max(
            self._energy_floor,
            min(self._energy_ceiling, self._ambient_energy * self._energy_mult),
        )

    def _log_energy(self, energy: float) -> None:
        self._total_chunks += 1
        if energy < 8.0:
            self._silent_chunks += 1

        now = time.time()
        if now - self._last_energy_log < 8.0:
            return

        silence_pct = (self._silent_chunks / max(1, self._total_chunks)) * 100.0
        threshold = self._speech_threshold()
        print(
            "[VOICE] [AUDIO] energy=%.1f threshold=%.1f silent=%.0f%% state=%s device=%s"
            % (energy, threshold, silence_pct, self.get_state(), self._device_index)
        )
        logger.info(
            "[VOICE] Audio energy=%.1f threshold=%.1f silent=%.0f state=%s device=%s",
            energy,
            threshold,
            silence_pct,
            self.get_state(),
            self._device_index,
        )
        if silence_pct > 98.0 and self._total_chunks > 80:
            print("[VOICE] [WARN] Mic stream is almost entirely silent; check mute/privacy settings")
            logger.warning("[VOICE] Mic stream appears silent")

        self._last_energy_log = now
        self._silent_chunks = 0
        self._total_chunks = 0

    def _state_watchdog(self) -> None:
        logger.info("[VOICE] State watchdog started")
        while self._running:
            time.sleep(3.0)

            if self._thread is not None and not self._thread.is_alive() and self._running:
                print("[VOICE] [WATCHDOG] Audio thread died; restarting")
                logger.error("[VOICE] Audio thread died; restarting")
                self._thread = threading.Thread(target=self._audio_loop, daemon=True, name="voice-audio")
                self._thread.start()

            if self._last_chunk_at and time.time() - self._last_chunk_at > 7.0:
                print("[VOICE] [WATCHDOG] No mic frames recently; requesting stream restart")
                logger.warning("[VOICE] No mic frames recently; requesting stream restart")
                self._restart_requested.set()

            cur = self.get_state()
            age = time.time() - self._state_changed_at
            if cur == VoiceState.LISTENING and age > self._listen_timeout + 4:
                self._listening_timeout("watchdog reset")
            elif cur == VoiceState.PROCESSING and age > 50:
                print("[VOICE] [WATCHDOG] Processing stuck; returning to idle")
                logger.warning("[VOICE] Processing stuck; returning to idle")
                self.reset_to_idle("Processing watchdog reset")
            elif cur == VoiceState.SPEAKING and age > 70:
                print("[VOICE] [WATCHDOG] Speaking stuck; returning to idle")
                logger.warning("[VOICE] Speaking stuck; returning to idle")
                self.notify_speaking_end()

        logger.info("[VOICE] State watchdog stopped")

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if not self.socketio:
            return
        try:
            self.socketio.emit(event, data, namespace="/")
        except Exception as exc:
            logger.error("[VOICE] Socket emit failed event=%s error=%s", event, exc)


_server: Optional[VoiceServer] = None
_server_lock = threading.RLock()
_socketio = None


def init(socketio=None) -> bool:
    """Initialize and start the singleton voice server."""
    return ensure_started(socketio=socketio)


def ensure_started(socketio=None) -> bool:
    """Create/start the singleton voice server when the main UI needs it."""
    global _server
    global _socketio
    with _server_lock:
        if socketio is not None:
            _socketio = socketio
        if _server is None:
            _server = VoiceServer(socketio=_socketio)
            # Replay any callback registered before the server existed.
            if _pending_barge_in_callback is not None:
                _server.register_barge_in_callback(_pending_barge_in_callback)
        elif socketio is not None:
            _server.socketio = socketio

        if _server.get_status().get("active"):
            return True
        if _server._model is None and not _server.init():
            return False
        return _server.start()


def release_microphone(reason: str = "browser microphone flow") -> None:
    """Release the OS microphone so browser setup/verification can use it."""
    with _server_lock:
        if _server is not None:
            _server.release_microphone(reason)


def get_server() -> Optional[VoiceServer]:
    return _server


def get_status() -> dict[str, Any]:
    if _server is None:
        return {"active": False, "status": "Voice server not initialized"}
    return _server.get_status()


def notify_speaking_start() -> None:
    if _server is not None:
        _server.notify_speaking_start()


def notify_speaking_end() -> None:
    if _server is not None:
        _server.notify_speaking_end()


def start_manual_listening() -> None:
    if _server is not None:
        _server.start_manual_listening()


def reset_to_idle(reason: str = "manual reset") -> None:
    if _server is not None:
        _server.reset_to_idle(reason)


def register_barge_in_callback(cb: Optional[Callable[[], None]]) -> None:
    """Module-level shim: forward registration to the singleton voice
    server. If the server is not yet initialised, the callback is held
    on a small registry and replayed once the server starts."""
    global _pending_barge_in_callback
    if _server is not None:
        _server.register_barge_in_callback(cb)
    else:
        _pending_barge_in_callback = cb


def is_in_conversation_window() -> bool:
    if _server is None:
        return False
    return _server.is_in_conversation_window()


_pending_barge_in_callback: Optional[Callable[[], None]] = None
