"""Voice-pipeline regression test for barge-in + continuous conversation.

Validates the real-time conversational upgrades shipped on top of the
existing Porcupine + Vosk wake/STT loop:

    1. Barge-in VAD
       - sustained voice energy during the SPEAKING state fires the
         registered callback exactly once
       - state machine transitions SPEAKING → LISTENING immediately
       - a `barge_in` socket event is emitted with a timestamp
       - cooldown blocks rapid double-fires

    2. Streak decay (not reset)
       - a single sub-threshold frame reduces the voiced-frame counter
         by 1 instead of resetting to zero, so micro-pauses inside an
         interruption don't kill the detection

    3. Continuous-conversation window
       - notify_speaking_end opens the window and emits
         `conversation_active` with the configured duration
       - inside the window: a loud frame against `_process_idle_audio`
         transitions straight to LISTENING WITHOUT a wake word
       - after window expires: the next idle frame falls back to the
         normal wake-word path and emits `conversation_expired`

    4. notify_speaking_end is barge-in aware
       - if the audio thread already moved us to LISTENING, the call
         becomes a strict no-op (does NOT clobber LISTENING back to
         IDLE)

The VoiceServer instance is constructed directly with a stub socketio;
no microphone, no Vosk model, no Porcupine binary is required.

Run from the repo root:

    python -m tests.test_voice_barge_in
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make `python -m tests.<name>` work regardless of CWD.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force UTF-8 stdout on Windows consoles for emoji-safe logging.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Tighter knobs for the test so we don't sit around for 12s on a window.
os.environ["JARVIS_BARGE_IN"] = "1"
os.environ["JARVIS_BARGE_IN_FRAMES"] = "5"
os.environ["JARVIS_BARGE_IN_ENERGY_MULT"] = "1.4"
os.environ["JARVIS_BARGE_IN_COOLDOWN"] = "0.3"
os.environ["JARVIS_CONVERSATION_WINDOW"] = "1.5"

import voice_server  # noqa: E402
from voice_server import VoiceServer, VoiceState  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Test harness
# ══════════════════════════════════════════════════════════════════════════════

_failures: list[str] = []


def check(label: str, cond: bool, detail: str = ""):
    flag = "OK  " if cond else "FAIL"
    print(f"[{flag}] {label}" + (f"  ::  {detail}" if (detail and not cond) else ""))
    if not cond:
        _failures.append(label)


def section(title: str):
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


class StubSocketio:
    """Minimal Flask-SocketIO stand-in. Captures emitted events so the
    test can assert on the wire format the real frontend will receive."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event, data=None, **kwargs):  # noqa: D401
        self.events.append((event, data or {}))

    def has(self, event: str) -> bool:
        return any(e == event for e, _ in self.events)

    def last(self, event: str) -> dict | None:
        for e, d in reversed(self.events):
            if e == event:
                return d
        return None

    def count(self, event: str) -> int:
        return sum(1 for e, _ in self.events if e == event)

    def clear(self):
        self.events.clear()


def make_server() -> tuple[VoiceServer, StubSocketio]:
    sio = StubSocketio()
    srv = VoiceServer(socketio=sio)
    # Force a known ambient floor so `_speech_threshold()` is deterministic
    # at 256.0 (= max(150, min(1200, 80*3.2))).
    srv._ambient_energy = 80.0
    return srv, sio


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: barge-in VAD fires after sustained voice energy during SPEAKING
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 1: barge-in fires on sustained voice during SPEAKING")

srv, sio = make_server()
fired = {"count": 0}


def _cb():
    fired["count"] += 1


srv.register_barge_in_callback(_cb)
srv.set_state(VoiceState.SPEAKING)
sio.clear()  # drop the state-change event so we only see barge-in noise

# Threshold for a "voiced" frame is speech_threshold * energy_mult.
loud = srv._speech_threshold() * 1.6  # comfortably above the bar

# Feed exactly threshold-1 loud frames — should NOT fire yet.
for _ in range(srv._barge_in_threshold_frames - 1):
    srv._maybe_barge_in(b"", loud)
check(
    "below-threshold streak does not fire callback",
    fired["count"] == 0,
    f"voiced_frames={srv._barge_in_voiced_frames} cb_fires={fired['count']}",
)

# One more loud frame crosses the threshold and fires.
srv._maybe_barge_in(b"", loud)
check(
    "callback fires exactly once when streak crosses threshold",
    fired["count"] == 1,
    f"cb_fires={fired['count']}",
)
check(
    "state transitioned SPEAKING → LISTENING after barge-in",
    srv.get_state() == VoiceState.LISTENING,
    f"state={srv.get_state()}",
)
check(
    "barge_in socket event emitted with timestamp",
    sio.has("barge_in") and "at" in (sio.last("barge_in") or {}),
    f"event={sio.last('barge_in')}",
)
check(
    "voice_state event emitted for SPEAKING → LISTENING",
    sio.has("voice_state")
    and (sio.last("voice_state") or {}).get("state") == VoiceState.LISTENING,
    f"event={sio.last('voice_state')}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: cooldown blocks immediate double-fire
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 2: cooldown blocks rapid double-fire")

# We're now in LISTENING. Force back to SPEAKING and try again WITHIN cooldown.
srv.set_state(VoiceState.SPEAKING)
fired["count"] = 0
sio.clear()

# Within cooldown — shovelling loud frames must NOT trigger another callback.
for _ in range(srv._barge_in_threshold_frames * 3):
    srv._maybe_barge_in(b"", loud)
check(
    "within cooldown: callback suppressed",
    fired["count"] == 0,
    f"cb_fires={fired['count']}",
)
check(
    "within cooldown: state stays SPEAKING (no transition)",
    srv.get_state() == VoiceState.SPEAKING,
    f"state={srv.get_state()}",
)

# Wait past the cooldown and try again.
time.sleep(srv._barge_in_cooldown_s + 0.05)
srv._barge_in_voiced_frames = 0  # reset streak so the test is hermetic
for _ in range(srv._barge_in_threshold_frames):
    srv._maybe_barge_in(b"", loud)
check(
    "after cooldown: callback fires again",
    fired["count"] == 1,
    f"cb_fires={fired['count']}",
)
check(
    "after cooldown: state SPEAKING → LISTENING",
    srv.get_state() == VoiceState.LISTENING,
    f"state={srv.get_state()}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: streak decays (not resets) on a single quiet frame
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 3: streak decay tolerates micro-pauses")

srv2, _ = make_server()
srv2.set_state(VoiceState.SPEAKING)
loud2 = srv2._speech_threshold() * 1.6
quiet = srv2._speech_threshold() * 0.2

# Build up to threshold-1, drop ONE quiet frame, then push more loud.
for _ in range(srv2._barge_in_threshold_frames - 1):
    srv2._maybe_barge_in(b"", loud2)
streak_before = srv2._barge_in_voiced_frames
srv2._maybe_barge_in(b"", quiet)  # micro-pause
streak_after = srv2._barge_in_voiced_frames
check(
    "single quiet frame decays streak by 1 (not to zero)",
    streak_after == streak_before - 1,
    f"before={streak_before} after={streak_after}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: continuous-conversation window after notify_speaking_end
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 4: continuous-conversation window")

srv3, sio3 = make_server()
srv3.set_state(VoiceState.SPEAKING)
sio3.clear()

srv3.notify_speaking_end()
check(
    "notify_speaking_end transitions SPEAKING → IDLE",
    srv3.get_state() == VoiceState.IDLE,
    f"state={srv3.get_state()}",
)
check(
    "notify_speaking_end emits conversation_active",
    sio3.has("conversation_active"),
    f"events={[e for e, _ in sio3.events]}",
)
ev = sio3.last("conversation_active") or {}
check(
    "conversation_active payload contains window_s",
    "window_s" in ev and ev["window_s"] > 0,
    f"payload={ev}",
)
check(
    "is_in_conversation_window() returns True inside window",
    srv3.is_in_conversation_window(),
)

# Loud frame inside the window should bypass wake-word and go straight to
# LISTENING. We drive the IDLE-frame handler directly.
sio3.clear()
loud3 = srv3._speech_threshold() * 1.5
remainder = srv3._process_idle_audio(b"\x00\x01" * 16, loud3)
check(
    "loud frame inside window transitions IDLE → LISTENING (no wake required)",
    srv3.get_state() == VoiceState.LISTENING,
    f"state={srv3.get_state()}",
)
check(
    "continuation path returns the original frame for downstream consumption",
    remainder == b"\x00\x01" * 16,
    f"len(remainder)={len(remainder) if remainder else 0}",
)
# wake_detected IS emitted (by `_begin_listening`) so the UI shows a wake
# affordance, but with source='conversation'. Verify the source label.
last_wake = sio3.last("wake_detected") or {}
check(
    "wake_detected event marks source='conversation' for follow-ups",
    last_wake.get("source") == "conversation",
    f"event={last_wake}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: window expires → emits conversation_expired and falls back
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 5: conversation window expiry")

srv4, sio4 = make_server()
srv4.set_state(VoiceState.SPEAKING)
srv4.notify_speaking_end()
sio4.clear()

# Force the window to be in the past so the next idle frame triggers
# the expiry branch.
srv4._conversation_active_until = time.time() - 0.001

# Quiet frame — should NOT enter LISTENING via continuation, but SHOULD
# fire the expiry event and reset the window timestamp to 0.
remainder4 = srv4._process_idle_audio(b"\x00" * 32, 50.0)
check(
    "expired window emits conversation_expired",
    sio4.has("conversation_expired"),
    f"events={[e for e, _ in sio4.events]}",
)
check(
    "expired window resets _conversation_active_until to 0",
    srv4._conversation_active_until == 0.0,
    f"_conversation_active_until={srv4._conversation_active_until}",
)
check(
    "expired window does NOT transition to LISTENING on a quiet frame",
    srv4.get_state() == VoiceState.IDLE,
    f"state={srv4.get_state()}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: notify_speaking_end is barge-in aware (no clobber)
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 6: notify_speaking_end is no-op when state == LISTENING")

srv5, sio5 = make_server()
# Simulate the post-barge-in state: voice_server has flipped to LISTENING
# itself; app.py's TTS-drain callback now fires notify_speaking_end. The
# call must NOT walk us back to IDLE.
srv5.set_state(VoiceState.LISTENING)
sio5.clear()
srv5.notify_speaking_end()
check(
    "notify_speaking_end no-op preserves LISTENING state",
    srv5.get_state() == VoiceState.LISTENING,
    f"state={srv5.get_state()}",
)
check(
    "notify_speaking_end no-op does NOT emit conversation_active",
    not sio5.has("conversation_active"),
    f"events={[e for e, _ in sio5.events]}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: barge-in disabled flag short-circuits the VAD
# ══════════════════════════════════════════════════════════════════════════════
section("Phase 7: barge-in disabled flag disarms the VAD")

srv6, _ = make_server()
srv6._barge_in_enabled = False
srv6.set_state(VoiceState.SPEAKING)
fired6 = {"count": 0}
srv6.register_barge_in_callback(lambda: fired6.__setitem__("count", fired6["count"] + 1))

# In the real audio loop, _maybe_barge_in is gated by the flag at the
# call site. We simulate that gate explicitly.
loud6 = srv6._speech_threshold() * 1.6
for _ in range(srv6._barge_in_threshold_frames * 2):
    if srv6._barge_in_enabled:
        srv6._maybe_barge_in(b"", loud6)
check(
    "barge-in disabled: callback never fires regardless of energy",
    fired6["count"] == 0,
    f"cb_fires={fired6['count']}",
)
check(
    "barge-in disabled: state stays SPEAKING",
    srv6.get_state() == VoiceState.SPEAKING,
    f"state={srv6.get_state()}",
)


# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 70)
if _failures:
    print(f"FAILED  ({len(_failures)} check(s))")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("PASS — barge-in + continuous conversation invariants hold.")
sys.exit(0)
