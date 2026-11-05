"""
JARVIS AI Assistant - Iron Man Edition
Multi-Provider AI Brain: Gemini (primary) -> Groq -> OpenRouter
"""
from flask import (Flask, send_from_directory, request,
                   session, redirect, url_for, render_template, jsonify)
from flask_socketio import SocketIO, emit
import threading, json, re
from ai_knowledge import AIML_KNOWLEDGE as _AIML_FALLBACK
import os, sys, time, logging
from collections import OrderedDict
import tts
import tts_edge
import tts_stream  # sentence-level streaming TTS (text + voice sync)
import jarvis_config as config
from memory import memory
from local_talk import local_talk
import knowledge_db
import daily_talk
import brain_manager
import chat_modes
from code_sanitizer import sanitize_fenced_code, sanitize_user_code_input, postprocess_codeme_response
import tavily_search
import intent_detector
import voice_server
from utils import file_processor
import screen_capture
import image_intelligence
from auth import db as user_db
from auth import face as face_auth
from auth import voice as voice_auth
from auth import oauth as gauth
from auth import jwt_auth as _jwt_auth
from auth.jwt_auth import JWTError
from auth.decorators import (
    require_user, optional_user, rate_limit, current_user_id
)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvis")

#  AI Brain Manager is initialized in run_server() after socketio is ready 

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "jarvis-iron-man-secret-2024")
app.config["DEBUG"] = False
# Don't let the browser hold onto stale static assets (JS/CSS edits during dev).
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Init Google OAuth (optional -- works without it)
gauth.init_oauth(app)

socketio = SocketIO(app, cors_allowed_origins="*",
    ping_timeout=60, ping_interval=25, logger=False, engineio_logger=False)

# Auto-initialize Brain Manager so AI works under Gunicorn (Render/production) as well as python app.py
try:
    brain_manager.init(socketio=socketio)
    logger.info("[INIT] BrainManager initialized successfully")
except Exception as _bme:
    logger.warning(f"[INIT] BrainManager init deferred: {_bme}")

#  Global state 

class JarvisState:
    def __init__(self):
        self._lock = threading.Lock()
        self.current_state = "idle"
        self._state_since = time.time()
        self.is_listening  = False
        self.connected_clients = set()
        self.conversation_active = False
        self.conversation_last = 0  # timestamp of last interaction
        self._watchdog_running = False

    def set_state(self, state: str):
        with self._lock:
            self.current_state = state
            self._state_since = time.time()
        try:
            socketio.emit("state", {"state": state}, namespace="/")
            logger.info(f"[STATE] {state}")
        except Exception as e:
            logger.error(f"[STATE] Error: {e}")

    def send_response(self, text: str):
        try:
            socketio.emit("response", {"text": text}, namespace="/")
            logger.info(f"[RESP] {text[:80]}")
        except Exception as e:
            logger.error(f"[RESP] Error: {e}")

    def stream_subtitle(self, text: str, wpm: int = 165):
        """Emit subtitle_chunk word-by-word in a daemon thread (syncs with TTS pace)."""
        def _run():
            words = text.split()
            delay = 60.0 / wpm
            acc   = ""
            for i, word in enumerate(words):
                acc = (acc + " " + word).strip()
                done = (i == len(words) - 1)
                try:
                    socketio.emit("subtitle_chunk",
                                  {"text": acc, "done": done}, namespace="/")
                except Exception:
                    pass
                time.sleep(delay)
            time.sleep(1.6)
            try:
                socketio.emit("subtitle_chunk",
                              {"text": "", "done": True, "clear": True}, namespace="/")
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def add_client(self, sid):
        with self._lock: self.connected_clients.add(sid)
    def remove_client(self, sid):
        with self._lock: self.connected_clients.discard(sid)

    def start_watchdog(self):
        """Start a watchdog that resets stuck states after 45s."""
        if self._watchdog_running:
            return
        self._watchdog_running = True
        def _watchdog():
            while self._watchdog_running:
                time.sleep(10)
                with self._lock:
                    cur = self.current_state
                    age = time.time() - self._state_since
                if cur in ("thinking", "speaking") and age > 45:
                    logger.warning(f"[WATCHDOG] State '{cur}' stuck for {age:.0f}s -- forcing idle")
                    print(f"[WATCHDOG] [!] State '{cur}' stuck for {age:.0f}s -- forcing idle")
                    self.set_state("idle")
                    try:
                        voice_server.notify_speaking_end()
                    except Exception:
                        pass
                    try:
                        socketio.emit("resume_listening", {}, namespace="/")
                    except Exception:
                        pass
        threading.Thread(target=_watchdog, daemon=True, name="state-watchdog").start()
        logger.info("[WATCHDOG] State watchdog started (45s timeout)")

state = JarvisState()

#  Response LRU cache (last 20 deterministic answers) 
_resp_cache: OrderedDict = OrderedDict()
_CACHE_MAX  = 20

# ── Response Lock: prevents concurrent/duplicate AI responses ──────────
# Only ONE command can be actively processing at a time. Additional
# commands arriving while `_is_responding` is True are rejected with a
# log warning. This is the primary fix for the self-conversation loop.
_responding_lock = threading.Lock()
_is_responding   = False

# ── Duplicate command detection (3-second window) ──────────────────────
_last_cmd_text = ""
_last_cmd_at   = 0.0
_CMD_DEDUP_S   = 3.0    # reject identical text within this window

# ── Last AI response (for voice echo detection) ────────────────────────
# voice_server compares STT output against this to reject echo of
# JARVIS's own speech picked up by the microphone.
_last_ai_response = ""
_last_ai_response_lock = threading.Lock()

def _set_last_ai_response(text: str):
    global _last_ai_response
    with _last_ai_response_lock:
        _last_ai_response = (text or "")[:500]   # cap memory

def get_last_ai_response() -> str:
    with _last_ai_response_lock:
        return _last_ai_response

#  Per-stream cancellation flags (id -> True). Frontend emits "cancel_stream"
#  when the user clicks the Stop button; the streaming chunk callback checks
#  this set and stops emitting further deltas. The provider stream may still
#  finish in the background (we cannot yank a remote HTTP/2 stream), but the
#  user-facing UX is instant.
_cancelled_streams: set = set()
_cancelled_lock    = threading.Lock()

def _mark_stream_cancelled(stream_id: str):
    if not stream_id:
        return
    with _cancelled_lock:
        _cancelled_streams.add(stream_id)
        # Bound memory: never let the cancel set exceed 256 ids.
        if len(_cancelled_streams) > 256:
            try:
                _cancelled_streams.pop()
            except KeyError:
                pass

def _is_stream_cancelled(stream_id: str) -> bool:
    if not stream_id:
        return False
    with _cancelled_lock:
        return stream_id in _cancelled_streams

def _clear_stream_cancel(stream_id: str):
    if not stream_id:
        return
    with _cancelled_lock:
        _cancelled_streams.discard(stream_id)

# ─── Active stream tracker (drives voice barge-in cancellation) ──────────
# When the user interrupts JARVIS by speaking during the SPEAKING state,
# voice_server fires a callback that needs to cancel whatever stream is
# currently playing. We track exactly one "live" stream id at a time
# because the voice pipeline is strictly serial — JARVIS cannot speak
# two replies in parallel. Updated under `_cancelled_lock` so the
# barge-in thread sees a consistent value.
_active_stream_id: str | None = None

def _set_active_stream(stream_id: str | None):
    global _active_stream_id
    with _cancelled_lock:
        _active_stream_id = stream_id

def _get_active_stream() -> str | None:
    with _cancelled_lock:
        return _active_stream_id


def _on_voice_barge_in():
    """Fired by voice_server's audio thread when the user starts talking
    while JARVIS is speaking. Must be quick + thread-safe.

    Steps:
      1. Look up the currently active stream id.
      2. Mark it cancelled so the SocketIO chunk emitter and the TTS
         worker both bail out on their next iteration.
      3. Cancel the TTS stream so audio cuts off mid-sentence.
      4. Notify the frontend so it finalizes the partial bubble with
         a visible "interrupted" marker and flips particles back to
         the listening state.
    """
    sid = _get_active_stream()
    logger.info("[BARGE-IN] Cancelling active stream id=%s", sid)
    if sid:
        _mark_stream_cancelled(sid)
        try:
            tts_stream.cancel(sid)
        except Exception as exc:
            logger.debug("[BARGE-IN] tts cancel failed: %s", exc)
    try:
        socketio.emit(
            "barge_in",
            {"id": sid, "at": time.time()},
            namespace="/",
        )
    except Exception as exc:
        logger.debug("[BARGE-IN] socket emit failed: %s", exc)


# Wire the callback as soon as the symbol is defined. voice_server holds
# this in a pending slot until the singleton is created on
# ensure_started(); this means the cb is always live regardless of mic
# initialisation order.
try:
    voice_server.register_barge_in_callback(_on_voice_barge_in)
except Exception as exc:
    logger.warning("[BARGE-IN] register failed: %s", exc)


def _cache_get(key: str):
    if key in _resp_cache:
        _resp_cache.move_to_end(key)
        return _resp_cache[key]
    return None

def _cache_set(key: str, val: str):
    _resp_cache[key] = val
    _resp_cache.move_to_end(key)
    if len(_resp_cache) > _CACHE_MAX:
        _resp_cache.popitem(last=False)

#  AI Routing (handled by brain_manager) 

MEMORY_KW  = ["remember","recall","what did i","earlier","yesterday",
              "notes","history","told you","said","last time","what was"]

def _build_system_prompt(mode: str = chat_modes.MODE_ASSISTANT,
                         intent_result=None,
                         session_key: str = "default",
                         user_text: str = "",
                         deepthink: bool = False,
                         attachments: list = None) -> str:
    """Personalise JARVIS system prompt with current user profile, chat mode,
    detected intent, and any explicit user formatting requests
    (table / paragraph / short / step-by-step / etc.).
    """
    base = config.SYSTEM_PROMPT
    p    = memory.get_profile()
    extras = []
    if p.get("name"):
        extras.append(f"The user's name is {p['name']} -- address them by name occasionally.")
    if p.get("interests"):
        extras.append(f"Known interests: {', '.join(p['interests'][:4])}.")
    if p.get("skills"):
        extras.append(f"Currently learning: {', '.join(p['skills'][:4])}.")
    if p.get("preferences"):
        extras.append(f"Likes: {', '.join(p['preferences'][:4])}.")
    top = memory.get_top_topics(3)
    if top:
        extras.append(f"Frequently discussed: {', '.join(top)}.")
    if extras:
        base += "\n\nPersonalisation:\n" + "\n".join(extras)
    # Inject intent-aware style hint so the AI knows HOW to respond
    if intent_result and intent_result.prompt_suffix:
        lang_note = ""
        if intent_result.language:
            lang_note = f" Detected language: {intent_result.language}."
        base += f"\n\n[RESPONSE STYLE]{lang_note}\n{intent_result.prompt_suffix}"
    # Vision-aware steer: when the user has attached one or more
    # images, classify the FIRST image (cheap pixel heuristics, no
    # model call) and prepend a content-kind-specific instruction
    # so JARVIS responds with the right *shape* of answer — debug
    # for code screenshots, UX review for UI mockups, summary for
    # PDF pages, educational for diagrams. This is the difference
    # between "I see an image" and "I see a Python TypeError on
    # line 42, here's the fix."
    if attachments:
        try:
            for att in attachments:
                if att.get("kind") != "image":
                    continue
                img_bytes = (att.get("image") or {}).get("data")
                if not img_bytes:
                    continue
                kind = att.get("vision_kind") or image_intelligence.classify_content(img_bytes)
                steer = image_intelligence.steer_for_kind(kind)
                base += f"\n\n[VISION CONTEXT — {kind}]\n{steer}"
                # Only steer once per request so the system prompt
                # doesn't balloon if the user attaches 5 screenshots.
                break
        except Exception as exc:
            logger.debug(f"[VISION] steer skipped: {exc}")
    # Inject user-controlled format hint (table / paragraph / short / etc.)
    if user_text:
        try:
            style_hint = chat_modes.extract_response_style(user_text)
        except Exception:
            style_hint = ""
        if style_hint:
            base += f"\n\n[USER FORMAT REQUEST]\n{style_hint}"
    
    intent_str = intent_result.intent if intent_result else None
    prompt = chat_modes.build_system_prompt(mode, base, session_key=session_key,
                                            deepthink=deepthink, intent=intent_str)
    return prompt



#  Query expansion: normalise AI/ML shorthand before embedding 
_EXPAND = [
    (re.compile(r"\bai\s*[/&]\s*ml\b",           re.I), "artificial intelligence and machine learning"),
    (re.compile(r"\baiml\b",                       re.I), "artificial intelligence and machine learning"),
    (re.compile(r"\bml\b(?!\s+(model|pipeline))",  re.I), "machine learning"),
    (re.compile(r"\bdl\b",                         re.I), "deep learning"),
    (re.compile(r"\bnlp\b",                        re.I), "natural language processing"),
    (re.compile(r"\bcv\b(?!\s+resume)",            re.I), "computer vision"),
    (re.compile(r"\bnn\b",                         re.I), "neural network"),
    (re.compile(r"\brnn\b",                        re.I), "recurrent neural network"),
    (re.compile(r"\bcnn\b",                        re.I), "convolutional neural network"),
    (re.compile(r"\bllm\b",                        re.I), "large language model"),
    (re.compile(r"\bgpt\b",                        re.I), "generative pre-trained transformer"),
]

# _AIML_FALLBACK is imported from ai_knowledge.py (101 topics, zero-API)

def _aiml_fallback(text: str):
    """Check if query matches a hardcoded AI/ML topic. Returns answer or None."""
    tl = text.lower()
    for keyword, answer in _AIML_FALLBACK.items():
        if keyword in tl:
            return answer
    return None


def _expand_query(text: str) -> str:
    """Expand abbreviations so the embedding matches richer text."""
    for pattern, replacement in _EXPAND:
        text = pattern.sub(replacement, text)
    return text


def _emergency_reply(text: str, mode: str, error: str = "") -> str:
    """Last-resort response — never expose raw backend errors to the user."""
    if error:
        logger.warning(f"[EMERGENCY] fallback triggered: {error[:200]}")

    try:
        casual = daily_talk.get_response(text)
        if casual:
            return casual
    except Exception:
        pass

    try:
        if brain_manager.brain:
            sys_p = _build_system_prompt(mode)
            resp, prov = brain_manager.brain.ask(
                text, "", sys_p, mode=mode,
                max_tokens=min(chat_modes.get_max_tokens(mode), 400),
                timeout=12,
            )
            if resp:
                logger.info(f"[EMERGENCY] recovered via {prov}")
                return resp
    except Exception as e:
        logger.error(f"[EMERGENCY] brain retry failed: {e}")

    tl = text.lower().strip()
    if any(w in tl for w in ("hi", "hello", "hey", "how are")):
        return "Hello, boss. I'm online and ready — what can I help you with?"
    if mode == chat_modes.MODE_CODEME:
        return "I'm ready to help with code. Paste your snippet or describe the bug and I'll walk through it step by step."
    return "I'm here and listening. Could you rephrase that? I'll do my best to help."


def _safe_session_key(fallback: str = "default") -> str:
    """Read session id safely — works in Socket.IO worker threads too."""
    try:
        from flask import has_request_context, session, request
        if has_request_context():
            return str(session.get("uid") or getattr(request, "sid", None) or fallback)
    except Exception:
        pass
    return fallback


def _safe_uid():
    try:
        from flask import has_request_context, session
        if has_request_context():
            return session.get("uid")
    except Exception:
        pass
    return None


def ask_ai(text: str, mode: str = chat_modes.MODE_ASSISTANT,
           session_key: str = None, uid: str = None,
           deepthink: bool = False, attachments: list = None,
           on_chunk=None) -> str:
    """Deterministically route and execute using router.py."""
    import router
    import time
    
    t_start = time.time()
    session_key = session_key or _safe_session_key()
    attachments = attachments or []
    uid = uid or _safe_uid()

    def _emit_full(reply: str):
        if on_chunk and reply:
            try: on_chunk(reply)
            except Exception: pass

    has_attachments = bool(attachments)

    # 1. Deterministic Routing (Phase 7) — weighted intent classification.
    intent = router.classify_intent(text)
    agent = intent["agent"]
    top = ", ".join(
        f"{t['agent']}={t['score']}({t['confidence']})" for t in intent["top_intents"]
    )
    logger.info(
        "[ROUTER] agent=%s confidence=%s | top: %s | %s",
        agent, intent["confidence"], top, intent["explanation"],
    )
    
    # Inject attachment context (file extracts) if available
    images = []
    att_ctx = ""
    if has_attachments:
        att_ctx = file_processor.build_attachment_context(attachments)
        images = file_processor.collect_images(attachments)
        
    # Build user context
    context = memory.build_context(text, user_id=uid)
    if att_ctx:
        context = att_ctx + "\n\n" + context

    # 2. Agent Execution
    logger.info(f"[ROUTER] Passing query to {agent}")
    
    response = router.run_agent(
        agent=agent,
        user_query=text,
        context=context,
        deepthink=deepthink,
        images=images,
        on_chunk=on_chunk
    )
    
    # Save memory
    if response:
        memory.save_conversation(text, response, user_id=uid)
        
    logger.info(f"[ROUTER] Completed in {time.time()-t_start:.3f}s")
    return response
def _release_voice_for_browser_mic(reason: str):
    """Free the local listener so browser biometric mic capture can open."""
    try:
        voice_server.release_microphone(reason)
    except Exception as e:
        logger.error(f"[VOICE] Release failed ({reason}): {e}")


def _ensure_voice_for_main_ui():
    """Start local Porcupine/Vosk only after authenticated main UI is active."""
    try:
        ok = voice_server.ensure_started(socketio=socketio)
        logger.info(f"[VOICE] ensure_started result={ok}")
    except Exception as e:
        logger.error(f"[VOICE] ensure_started failed: {e}")

@socketio.on("connect", namespace="/")
def handle_connect():
    sid = getattr(request, "sid", "?")
    state.add_client(sid)
    emit("state",  {"state": state.current_state})
    emit("status", {"connected": True})
    try:
        emit("voice_status", voice_server.get_status())
    except Exception:
        pass
    if _logged_in() and getattr(config, "ENABLE_BACKGROUND_VOICE", False):
        socketio.start_background_task(_ensure_voice_for_main_ui)

    # Emit AI status so UI can show which engines are live
    # Emit full provider status from BrainManager
    if brain_manager.brain:
        status = brain_manager.brain.get_status()
        emit("ai_provider_status", status)
        logger.info(f"[CONNECT] {sid} | Providers: {status.get('configured', [])}")
    else:
        emit("ai_provider_status", {"active": "none", "providers": {}, "configured": []})
        logger.info(f"[CONNECT] {sid} | BrainManager not ready")

@socketio.on("disconnect", namespace="/")
def handle_disconnect(*args):
    sid = getattr(request, "sid", "?")
    state.remove_client(sid)
    if not state.connected_clients:
        state.set_state("idle")


@socketio.on("command", namespace="/")
def handle_command(data=None):
    global _is_responding, _last_cmd_text, _last_cmd_at
    if data is None: data = {}
    text = (data.get("text","") if isinstance(data, dict) else str(data)).strip()
    mode = chat_modes.normalize_mode(
        data.get("mode") if isinstance(data, dict) else None
    )
    deepthink = bool(data.get("deepthink")) if isinstance(data, dict) else False
    stream    = bool(data.get("stream", True)) if isinstance(data, dict) else True
    attach_ids = (data.get("attachments") or []) if isinstance(data, dict) else []
    attachments = file_processor.fetch(attach_ids) if attach_ids else []

    if not text and not attachments:
        emit("response", {"text": "I did not catch that. Please speak clearly.", "mode": mode})
        return
    if not text and attachments:
        # User sent only attachments — provide a default analysis prompt.
        text = "Please analyse the attached files and explain them."

    # ── RESPONSE LOCK: reject if already responding ──────────────────
    with _responding_lock:
        if _is_responding:
            logger.warning(f"[CMD] [BLOCKED] Rejected command while responding: '{text[:80]}'")
            return

    # ── DUPLICATE DETECTION: reject identical text within 3s ─────────
    now = time.time()
    if text == _last_cmd_text and (now - _last_cmd_at) < _CMD_DEDUP_S:
        logger.warning(f"[CMD] [DUPLICATE] Rejected duplicate within {_CMD_DEDUP_S}s: '{text[:60]}'")
        return
    _last_cmd_text = text
    _last_cmd_at = now

    logger.info(f"[CMD] Received [{mode}|deepthink={deepthink}|attachments={len(attachments)}|stream={stream}]: {text[:120]}")

    # Pre-compute intent + render_mode so streaming events carry the correct mode to the UI.
    # Keep this lightweight: mirror ask_ai's logic (sanitize before detect for Code-Me).
    detection_text = text
    if mode == chat_modes.MODE_CODEME:
        try:
            detection_text = sanitize_user_code_input(text)
        except Exception:
            detection_text = text
    try:
        preview_intent = intent_detector.detect(detection_text)
    except Exception as e:
        logger.debug(f"[CMD] intent preview failed: {e}")
        preview_intent = None
    smalltalk = bool(preview_intent and preview_intent.intent in (
        getattr(intent_detector, "INTENT_GREETING", "greeting"),
        getattr(intent_detector, "INTENT_CASUAL", "casual"),
    ))
    render_mode = (
        chat_modes.MODE_ASSISTANT if (mode == chat_modes.MODE_CODEME and smalltalk)
        else mode
    )
    logger.info(f"[CMD] Render mode resolved: user_mode={mode} render_mode={render_mode} intent={getattr(preview_intent, 'intent', 'unknown')}")

    # Capture session before background thread (no Flask context in worker)
    cmd_session_key = _safe_session_key(getattr(request, "sid", "default"))
    cmd_uid = _safe_uid()
    cmd_sid = getattr(request, "sid", None)


    #  Explicit "remember this..." voice/chat intent (no AI API call needed) 
    #  Patterns: "remember this: ...", "remember that I'm preparing for X",
    #  "note that I prefer Python", "save this — my goal is ...", etc.
    #  Sub-100ms response: write to memories table, confirm naturally.
    try:
        from memory import detect_explicit_remember
        rem = detect_explicit_remember(text)
    except Exception:
        rem = None
    if rem:
        content, category, importance = rem
        def _remember_proc():
            global _is_responding
            try:
                new_id = memory.add_memory(
                    content, category=category,
                    importance=importance, source="explicit",
                    user_id=cmd_uid,
                )
                if new_id > 0:
                    reply = f"Got it. I'll remember that {content[5:].strip() if content.lower().startswith('user ') else content}."
                elif new_id == -1:
                    reply = "Memory is currently disabled for your account, so I can't store that. You can re-enable it in Memory Settings."
                else:
                    reply = "I already had that one saved. I won't forget."
                _set_last_ai_response(reply)
                # Echo to chat AND speak it back so the user feels acknowledged.
                state.set_state("speaking")
                try: voice_server.notify_speaking_start()
                except Exception: pass
                state.send_response(reply)
                state.stream_subtitle(reply)
                if getattr(config, "ENABLE_VOICE_OUTPUT", False):
                    try:
                        tts.speak(reply)
                    finally:
                        try: voice_server.notify_speaking_end()
                        except Exception: pass
                else:
                    try: voice_server.notify_speaking_end()
                    except Exception: pass
                state.set_state("idle")
                try:
                    socketio.emit("resume_listening", {}, namespace="/")
                except Exception:
                    pass
                # Persist the conversation turn so the LLM sees this in
                # the next message's history (keeps context coherent).
                try:
                    memory.save_conversation(text, reply, user_id=cmd_uid)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"[REMEMBER] Save failed: {e}")
                try: voice_server.notify_speaking_end()
                except Exception: pass
                state.set_state("idle")
            finally:
                with _responding_lock:
                    _is_responding = False
        state.set_state("thinking")
        with _responding_lock:
            _is_responding = True
        threading.Thread(target=_remember_proc, daemon=True).start()
        return

    if not config.any_ai_ready():
        emit("response", {"text": "No AI API configured. Add GROQ_API_KEY or GEMINI_API_KEY to .env file."})
        try:
            voice_server.notify_speaking_end()
        except Exception:
            pass
        state.set_state("idle")
        return

    state.set_state("thinking")

    # Acquire response lock BEFORE spawning thread
    with _responding_lock:
        _is_responding = True

    def process():
        global _is_responding
        try:
            _do_process()
        finally:
            with _responding_lock:
                _is_responding = False
            logger.debug("[CMD] Response lock released")

    def _do_process():
        response = None
        # Generate a stream id so the frontend can attach chunks to one bubble.
        # The same stream_id keys the TTS streaming session so text + voice
        # stay perfectly in sync.
        stream_id = f"s-{int(time.time()*1000)}-{(cmd_sid or 'x')[-4:]}"
        streamed_any = [False]
        first_chunk_at = [0.0]
        was_cancelled = [False]
        # We skip TTS-streaming for non-voice modes that contain heavy code
        # output (the AI's prose is short, but reading code aloud is awful).
        # The streaming TTS module already converts fenced blocks into a
        # single "code shown on screen" cue, so we keep it enabled here.
        tts_enabled = bool(stream) and getattr(config, "ENABLE_VOICE_OUTPUT", False)

        # ── Open the live TTS streaming session BEFORE the first chunk ──
        if tts_enabled:
            def _on_first_voice():
                # Voice has actually started — flip orb into speaking state
                # at the exact moment audio begins, not when text appears.
                try:
                    state.set_state("speaking")
                except Exception:
                    pass
                try:
                    voice_server.notify_speaking_start()
                except Exception:
                    pass

            def _on_voice_drain():
                # All sentences finished playing — return to idle and tell
                # the wake-word listener to resume.
                # Clear the active-stream pointer FIRST so a late
                # barge-in (audio frame already in flight) cannot try to
                # cancel a stream that's already done.
                if _get_active_stream() == stream_id:
                    _set_active_stream(None)
                try:
                    voice_server.notify_speaking_end()
                except Exception:
                    pass
                try:
                    state.set_state("idle")
                except Exception:
                    pass
                try:
                    socketio.emit("resume_listening", {}, namespace="/")
                except Exception:
                    pass
            try:
                tts_stream.start(stream_id,
                                 on_first=_on_first_voice,
                                 on_drain=_on_voice_drain)
                # Mark this stream live so voice barge-in knows what to cancel.
                _set_active_stream(stream_id)
            except Exception as e:
                logger.warning(f"[TTS-STREAM] start failed: {e}")
                tts_enabled = False

        def _on_chunk(chunk: str):
            if not chunk:
                return
            # If user clicked Stop, silently stop emitting. The provider stream
            # generator will continue draining in the background, but the user
            # sees the response stop instantly.
            if _is_stream_cancelled(stream_id):
                was_cancelled[0] = True
                return
            if not streamed_any[0]:
                streamed_any[0] = True
                first_chunk_at[0] = time.time()
            try:
                socketio.emit(
                    "response_chunk",
                    {"id": stream_id, "delta": chunk, "mode": render_mode, "deepthink": deepthink},
                    namespace="/",
                )
            except Exception as e:
                logger.debug(f"[STREAM] chunk emit error: {e}")
            # ── Feed the SAME chunk into the live TTS pipeline ──
            # The streaming TTS holds back tokens until a complete sentence
            # forms, then dispatches it to the speaker. Voice and text
            # consume the same stream so they stay synchronised.
            if tts_enabled:
                try:
                    tts_stream.feed(stream_id, chunk)
                except Exception as e:
                    logger.debug(f"[TTS-STREAM] feed error: {e}")

        try:
            t_start = time.time()
            logger.info(f"[CMD] Processing [{render_mode}|deepthink={deepthink}] session={cmd_session_key}: '{text[:80]}'")
            # Announce stream start so the UI can open an empty bubble.
            if stream:
                try:
                    socketio.emit(
                        "response_start",
                        {"id": stream_id, "mode": render_mode, "deepthink": deepthink},
                        namespace="/",
                    )
                except Exception:
                    pass

            response = ask_ai(
                text, mode=mode, session_key=cmd_session_key, uid=cmd_uid,
                deepthink=deepthink, attachments=attachments,
                on_chunk=(_on_chunk if stream else None),
            )
            t_elapsed = time.time() - t_start
            ttfb = (first_chunk_at[0] - t_start) if streamed_any[0] else -1.0
            logger.info(f"[CMD] Response ({t_elapsed:.2f}s, ttfb={ttfb:.2f}s, streamed={streamed_any[0]}): '{response[:80]}'")
        except Exception as e:
            logger.error(f"[CMD] AI Error: {e}", exc_info=True)
            response = _emergency_reply(text, mode, str(e))

        # If the user cancelled mid-stream, skip the finalize/TTS pipeline so
        # nothing else lands on screen or in the speaker. The frontend has
        # already finalized the bubble locally with the partial text.
        cancelled = was_cancelled[0] or _is_stream_cancelled(stream_id)
        _clear_stream_cancel(stream_id)

        if cancelled:
            logger.info(f"[CMD] Stream {stream_id} cancelled by user — skipping TTS/finalize")
            if _get_active_stream() == stream_id:
                _set_active_stream(None)
            if tts_enabled:
                try: tts_stream.cancel(stream_id)
                except Exception: pass
            try:
                voice_server.notify_speaking_end()
            except Exception:
                pass
            state.set_state("idle")
            try:
                socketio.emit("resume_listening", {}, namespace="/")
            except Exception:
                pass
            return

        # ── Store AI response for echo detection ──
        if response:
            _set_last_ai_response(response)

        # ── Finalize the on-screen bubble ──
        # We emit response_done BEFORE flushing the TTS stream so the UI
        # shows the polished markdown bubble while the speaker continues
        # reading the last sentences.
        try:
            if stream:
                socketio.emit(
                    "response_done",
                    {"id": stream_id, "text": response, "mode": render_mode,
                     "deepthink": deepthink},
                    namespace="/",
                )
            else:
                socketio.emit("response", {"text": response, "mode": render_mode,
                                            "deepthink": deepthink}, namespace="/")
            logger.info(f"[RESP] [{render_mode}] {response[:80]}")
        except Exception as e:
            logger.error(f"[RESP] Error: {e}")

        # ── Flush remaining TTS buffer ──
        # If we never streamed (provider fell back to a single-shot ask()),
        # feed the full response into the TTS stream now so it still speaks.
        if tts_enabled:
            if not streamed_any[0] and response:
                try:
                    tts_stream.feed(stream_id, response)
                except Exception as e:
                    logger.debug(f"[TTS-STREAM] late-feed error: {e}")
            try:
                tts_stream.flush(stream_id)
            except Exception as e:
                logger.debug(f"[TTS-STREAM] flush error: {e}")
            # Note: _on_voice_drain fires asynchronously when the worker
            # finishes the last sentence — that callback handles the
            # idle-state + resume_listening emit. We do NOT block here.
            return

        # Non-streaming fallback path: speak via the legacy blocking TTS only if enabled.
        if getattr(config, "ENABLE_VOICE_OUTPUT", False):
            try:
                speak_text = chat_modes.format_for_voice(response, render_mode)
            except Exception as e:
                logger.warning(f"[CMD] format_for_voice failed, using fallback summary: {e}")
                speak_text = chat_modes.tts_summary(response, render_mode)
            try:
                state.set_state("speaking")
                voice_server.notify_speaking_start()
            except Exception:
                pass
            try:
                tts.speak(speak_text)
            except Exception as e:
                logger.error(f"[CMD] TTS Error (non-fatal): {e}")
            try:
                voice_server.notify_speaking_end()
            except Exception:
                pass
        state.set_state("idle")
        try:
            socketio.emit("resume_listening", {}, namespace="/")
            logger.info("[CMD] Emitted resume_listening")
        except Exception as e:
            logger.error(f"[CMD] resume_listening emit error: {e}")

    threading.Thread(target=process, daemon=True).start()


@socketio.on("cancel_stream", namespace="/")
def handle_cancel_stream(data=None):
    """User clicked the Stop button — silence further chunk emission for this id."""
    if not isinstance(data, dict):
        return
    sid = data.get("id")
    if not sid:
        return
    _mark_stream_cancelled(sid)
    logger.info(f"[CMD] Cancel requested for stream {sid}")

@socketio.on("start_listening", namespace="/")
def handle_start_listening(data=None):
    state.is_listening = True
    state.conversation_active = True
    state.conversation_last = time.time()
    try:
        voice_server.ensure_started(socketio=socketio)
        voice_server.start_manual_listening()
    except Exception as e:
        logger.error(f"[VOICE] Manual listening failed: {e}")
    state.set_state("listening")
    emit("status", {"listening": True})
    logger.info("[VOICE] Conversation mode activated")

@socketio.on("stop_listening", namespace="/")
def handle_stop_listening(data=None):
    state.is_listening = False
    state.conversation_active = False
    try:
        voice_server.reset_to_idle("Manual listening stopped")
    except Exception:
        pass
    if state.current_state == "listening":
        state.set_state("idle")
    emit("status", {"listening": False})
    logger.info("[VOICE] Conversation mode deactivated")

@socketio.on("ping", namespace="/")
def handle_ping(data=None):
    emit("pong", {"ts": time.time()})

@socketio.on_error_default
def default_error_handler(e):
    logger.error(f"[SOCKETIO] {e}")

#  Auth helpers 

def _logged_in() -> bool:
    return bool(session.get("uid") and session.get("auth"))

def _current_user():
    uid = session.get("uid")
    return user_db.get_user(uid) if uid else None


#  Flask Routes 

@app.route('/public/<path:filename>')
def serve_public(filename):
    return send_from_directory('public', filename)

@app.route("/")
def index():
    if not _logged_in():
        return redirect(url_for("demo"))
    return send_from_directory("templates", "index.html")


@app.route("/memory-settings")
def memory_settings_page():
    """Self-service memory dashboard. Renders the SPA shell which then
    drives every action via the authenticated `/api/memory/*` JSON API.
    All session-bound users (Google OAuth, demo, password) reach this
    page; JWT-only clients can also load it because the JS attaches a
    Bearer token from localStorage when present."""
    if not _logged_in():
        return redirect(url_for("login"))
    return render_template("memory_settings.html")


#  Login / OAuth 

@app.route("/login")
def login():
    _release_voice_for_browser_mic("login page")
    return render_template("login.html",
                           oauth_ready=gauth.is_ready(),
                           error=request.args.get("error", ""))

@app.route("/auth/google")
def auth_google():
    if not gauth.is_ready():
        return redirect(url_for("login", error="Google OAuth not configured"))
    redirect_uri = (os.getenv("GOOGLE_REDIRECT_URI")
                    or url_for("auth_google_callback", _external=True))
    return gauth.get_google().authorize_redirect(redirect_uri)

@app.route("/auth/google/callback")
def auth_google_callback():
    try:
        token     = gauth.get_google().authorize_access_token()
        userinfo  = token.get("userinfo") or gauth.get_google().userinfo(token=token)
        email     = userinfo["email"]
        name      = userinfo.get("name", email.split("@")[0])
        uid       = userinfo["sub"]          # Google's stable user ID
        picture   = userinfo.get("picture", "")

        existing = user_db.get_user(uid)
        user_db.create_user(uid, email, name, picture)
        session["uid"]  = uid
        session["name"] = name
        session["auth"] = False   # biometrics not yet verified
        memory.save_google_profile(name, email, user_id=uid)

        if existing and existing.get("setup_complete"):
            return redirect(url_for("verify"))
        return redirect(url_for("setup"))
    except Exception as e:
        logger.error(f"[OAUTH] Callback error: {e}")
        return redirect(url_for("login", error="Google login failed -- try again"))

#  Demo mode (no OAuth) 

@app.route("/demo")
def demo():
    """Bypass auth entirely -- creates/uses a demo user."""
    uid  = "demo-user"
    name = session.get("name") or "Boss"
    user_db.create_user(uid, "demo@jarvis.local", name)
    memory.save_google_profile(name, "demo@jarvis.local", user_id=uid)
    u = user_db.get_user(uid)
    session["uid"]  = uid
    session["name"] = name
    session["auth"] = True
    user_db.update_last_login(uid)
    if not u or not u.get("setup_complete"):
        user_db.mark_setup_complete(uid)  # skip biometrics in demo
    return redirect(url_for("index"))

#  First-time setup 

@app.route("/setup")
def setup():
    if not session.get("uid"):
        return redirect(url_for("login"))
    _release_voice_for_browser_mic("setup page")
    resp = render_template("setup.html", name=session.get("name", "User"))
    from flask import make_response
    r = make_response(resp)
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    return r

@app.route("/api/auth/setup/face", methods=["POST"])
def setup_face():
    try:
        uid = session.get("uid")
        if not uid:
            return jsonify({"ok": False, "error": "Not logged in"})
        data = request.get_json(force=True)
        b64  = data.get("image", "")
        emb  = face_auth.get_embedding(b64)
        if emb is None:
            return jsonify({"ok": False, "error": "No face detected -- move closer and look straight"})
        user_db.save_face_embedding(uid, emb)
        logger.info(f"[SETUP] Face saved for {uid}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"[SETUP/FACE] {e}")
        return jsonify({"ok": False, "error": f"Server error: {e}"})

@app.route("/api/auth/setup/voice", methods=["POST"])
def setup_voice():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "Not logged in"})
    data = request.get_json(force=True)
    sig  = voice_auth.extract_from_b64(data.get("audio", ""))
    if sig is None:
        return jsonify({"ok": False, "error": "Voice too short or silent -- try again"})
    user_db.save_voice_signature(uid, sig)
    user_db.mark_setup_complete(uid)
    logger.info(f"[SETUP] Voice saved for {uid}")
    return jsonify({"ok": True})

#  Login verification 

@app.route("/verify")
def verify():
    if not session.get("uid"):
        return redirect(url_for("login"))
    _release_voice_for_browser_mic("verification page")
    return render_template("verify.html", name=session.get("name", "User"))

@app.route("/api/auth/session_check")
def session_check():
    uid = session.get("uid")
    return jsonify({"uid": uid, "auth": session.get("auth"), "logged_in": _logged_in()})

@app.route("/api/tts/speak", methods=["POST"])
def api_tts_speak():
    if not session.get("uid"):
        return jsonify({"ok": False})
    data = request.get_json(force=True) or {}
    text = str(data.get("text", "")).strip()
    if text:
        tts.speak_async(text)
    return jsonify({"ok": True})


def _run_study_tts(text: str) -> None:
    try:
        socketio.emit("study_tts_start", {"text": text}, namespace="/")
        tts_edge.speak_study(text)
    except Exception as e:
        logger.error("[STUDY TTS] Error: %s", e)
    finally:
        try:
            socketio.emit("study_tts_end", {}, namespace="/")
        except Exception as e:
            logger.error("[STUDY TTS] emit end error: %s", e)


@app.route("/api/tts/study", methods=["POST"])
def api_tts_study():
    if not session.get("uid"):
        return jsonify({"ok": False})
    data = request.get_json(force=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False})
    threading.Thread(target=_run_study_tts, args=(text,), daemon=True).start()
    return jsonify({"ok": True})

#  File Upload API 

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Accept user-uploaded files (images, PDFs, code, docs, ZIP) for chat.

    Returns: { ok, files: [ { id, name, kind, size, mime, preview } ] }.
    The raw bytes are kept server-side keyed by id; the next chat command can
    reference these ids in `attachments`.
    """
    if not _logged_in() and session.get("uid") != "demo-user":
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    try:
        files = request.files.getlist("files")
        if not files:
            # Some clients use the unnamed 'file' field
            single = request.files.get("file")
            files = [single] if single else []

        results = []
        rejected = []
        for f in files:
            if not f or not f.filename:
                continue
            try:
                raw = f.read()
            except Exception as e:
                logger.warning(f"[UPLOAD] read failed for {f.filename}: {e}")
                continue
            desc = file_processor.process_upload(f.filename, raw, f.mimetype)
            if not desc:
                continue
            if desc.get("rejected"):
                rejected.append({"name": desc["name"], "reason": desc.get("text", "rejected")})
                continue
            file_processor.remember(desc)
            results.append({
                "id":   desc["id"],
                "name": desc["name"],
                "kind": desc["kind"],
                "size": desc["size"],
                "mime": desc["mime"],
                "preview": (desc.get("text") or "")[:600],
            })
            logger.info(f"[UPLOAD] {desc['kind']:6s} | {desc['name']} | {desc['size']}b | id={desc['id']}")

        return jsonify({"ok": True, "files": results, "rejected": rejected})
    except Exception as e:
        logger.error(f"[UPLOAD] error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/upload/<file_id>", methods=["DELETE"])
def api_upload_delete(file_id):
    """Drop an upload from the in-memory store (called when user removes a chip)."""
    if not _logged_in() and session.get("uid") != "demo-user":
        return jsonify({"ok": False}), 401
    ok = file_processor.forget(file_id)
    return jsonify({"ok": ok})


#  Screen Vision API 

def _screen_attach_descriptor(captured, source: str = "screen") -> dict:
    """Run smart preprocessing + classification on a captured image and
    register the result in the upload store so the rest of the chat
    pipeline can treat it identically to a user-uploaded screenshot.

    Returns the upload descriptor (same shape as `file_processor.process_upload`
    returns for an image), with two extra fields for the UI:
        vision_kind   : code_screenshot / ui_mockup / pdf_page / diagram / photo
        dark_mode     : bool — True for dark IDE screenshots
    """
    raw = captured.data
    name = f"screen-{int(time.time())}.png"
    pre = image_intelligence.preprocess(raw)
    # Use the cleaned bytes if preprocessing succeeded, else fall back
    # to the original capture so we never lose the user's screenshot.
    body = pre.data if pre.data else raw
    desc = file_processor.process_upload(name, body, "image/png")
    if not desc:
        return {}
    desc["vision_kind"] = pre.content_kind
    desc["dark_mode"] = pre.dark_mode
    desc["source"] = source
    desc["preview"] = f"(Screen capture · {pre.content_kind} · {pre.width}×{pre.height})"
    file_processor.remember(desc)
    return desc


def _screen_socket_event(desc: dict, monitor_index: int, region: dict | None) -> None:
    """Emit a small transparency event so the UI can render a chip and
    so the user can SEE that JARVIS just captured something. This is
    the privacy-by-visibility part of the design — every capture is
    explicit AND audible to the user."""
    try:
        socketio.emit(
            "screen_captured",
            {
                "id":            desc.get("id"),
                "name":          desc.get("name"),
                "kind":          "image",
                "size":          desc.get("size"),
                "mime":          desc.get("mime"),
                "preview":       desc.get("preview"),
                "vision_kind":   desc.get("vision_kind"),
                "dark_mode":     desc.get("dark_mode"),
                "source":        desc.get("source"),
                "monitor_index": monitor_index,
                "region":        region,
            },
            namespace="/",
        )
    except Exception as exc:
        logger.debug(f"[SCREEN] emit skipped: {exc}")


@app.route("/api/screen/monitors", methods=["GET"])
def api_screen_monitors():
    """Enumerate available displays for the region-selection UI.

    Always 200; clients should check `available` and `monitors` in the
    response body instead of relying on status codes.
    """
    if not _logged_in() and session.get("uid") != "demo-user":
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    try:
        monitors = screen_capture.list_monitors()
        return jsonify({
            "ok": True,
            "available": screen_capture.is_available(),
            "monitors": monitors,
        })
    except Exception as exc:
        logger.error(f"[SCREEN] monitor list failed: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc), "monitors": []}), 200


@app.route("/api/screen/capture", methods=["POST"])
def api_screen_capture():
    """Capture an entire monitor (or the virtual screen).

    Privacy invariants enforced here:
      * User must be logged in.
      * Body MUST contain `"consent": true`. We never imply consent
        from a session flag — every capture is an explicit acknowledgement.
      * On success we emit a `screen_captured` socket event so the UI
        can show the user that a capture just happened.

    Body:
        { consent: true, monitor: int? }     monitor=null/0 = virtual screen

    Returns:
        { ok, file: { id, name, kind, size, mime, vision_kind, dark_mode } }
    """
    if not _logged_in() and session.get("uid") != "demo-user":
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    if not screen_capture.is_available():
        return jsonify({
            "ok": False,
            "error": "Screen capture backend not installed. "
                     "Run `pip install mss` (preferred) or `pip install pyautogui`.",
        }), 503

    data = request.get_json(silent=True) or {}
    if not data.get("consent"):
        return jsonify({
            "ok": False,
            "error": "Capture requires explicit consent. "
                     "POST `{\"consent\": true}` to grant for this single call.",
        }), 403

    try:
        monitor_index = data.get("monitor")
        if monitor_index is not None:
            monitor_index = int(monitor_index)
        want_data_url = bool(data.get("return_data_url"))
        captured = screen_capture.capture_full(monitor_index=monitor_index)
        desc = _screen_attach_descriptor(captured, source="screen")
        if not desc:
            return jsonify({"ok": False, "error": "capture rejected"}), 500
        _screen_socket_event(desc, captured.monitor_index, region=None)
        logger.info(
            f"[SCREEN] Full capture | mon={captured.monitor_index} | "
            f"{captured.width}×{captured.height} | "
            f"kind={desc.get('vision_kind')} | id={desc['id']}"
        )
        file_payload = {
            "id":          desc["id"],
            "name":        desc["name"],
            "kind":        desc["kind"],
            "size":        desc["size"],
            "mime":        desc["mime"],
            "preview":     desc.get("preview"),
            "vision_kind": desc.get("vision_kind"),
            "dark_mode":   desc.get("dark_mode"),
        }
        # Region-picker workflow: the browser needs raw pixels to
        # display a draggable preview. We embed the cleaned PNG as a
        # data URL ONLY when the caller explicitly asks for it,
        # because base64 inflates the response by ~33%.
        if want_data_url:
            try:
                import base64
                img_bytes = (desc.get("image") or {}).get("data") or b""
                if img_bytes:
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    file_payload["data_url"] = f"data:image/png;base64,{b64}"
            except Exception as exc:
                logger.debug(f"[SCREEN] data_url skipped: {exc}")
        return jsonify({"ok": True, "file": file_payload})
    except Exception as exc:
        logger.error(f"[SCREEN] capture failed: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/screen/region", methods=["POST"])
def api_screen_region():
    """Capture a rectangular region of the screen.

    Body:
        {
          consent: true,
          left:   int,
          top:    int,
          width:  int,
          height: int,
          monitor: int?     # optional, monitor-relative coords if set
        }

    Same privacy + emit guarantees as `/api/screen/capture`.
    """
    if not _logged_in() and session.get("uid") != "demo-user":
        return jsonify({"ok": False, "error": "Not authenticated"}), 401
    if not screen_capture.is_available():
        return jsonify({
            "ok": False,
            "error": "Screen capture backend not installed.",
        }), 503

    data = request.get_json(silent=True) or {}
    if not data.get("consent"):
        return jsonify({
            "ok": False,
            "error": "Capture requires explicit consent.",
        }), 403

    try:
        left   = int(data.get("left", 0))
        top    = int(data.get("top", 0))
        width  = int(data.get("width", 0))
        height = int(data.get("height", 0))
        if width <= 0 or height <= 0:
            return jsonify({
                "ok": False,
                "error": "width/height must be positive",
            }), 400
        monitor_index = data.get("monitor")
        if monitor_index is not None:
            monitor_index = int(monitor_index)
        captured = screen_capture.capture_region(
            left=left, top=top, width=width, height=height,
            monitor_index=monitor_index,
        )
        desc = _screen_attach_descriptor(captured, source="region")
        if not desc:
            return jsonify({"ok": False, "error": "capture rejected"}), 500
        region_info = {"left": left, "top": top, "width": width, "height": height}
        _screen_socket_event(desc, captured.monitor_index, region=region_info)
        logger.info(
            f"[SCREEN] Region capture | mon={captured.monitor_index} | "
            f"{captured.width}×{captured.height} | "
            f"kind={desc.get('vision_kind')} | id={desc['id']}"
        )
        return jsonify({
            "ok": True,
            "file": {
                "id":          desc["id"],
                "name":        desc["name"],
                "kind":        desc["kind"],
                "size":        desc["size"],
                "mime":        desc["mime"],
                "preview":     desc.get("preview"),
                "vision_kind": desc.get("vision_kind"),
                "dark_mode":   desc.get("dark_mode"),
            },
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"[SCREEN] region capture failed: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/auth/has_face", methods=["POST"])
def api_has_face():
    data = request.get_json(force=True)
    return jsonify({"has_face": face_auth.has_face(data.get("image", ""))})

@app.route("/api/auth/verify/face", methods=["POST"])
def api_verify_face():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "Not logged in"})
    data     = request.get_json(force=True)
    stored   = user_db.load_face_embedding(uid)
    if stored is None:
        # No face enrolled -> skip face check, mark auth OK
        session["auth"] = True
        return jsonify({"ok": True, "score": 1.0, "note": "no enrollment"})
    candidate = face_auth.get_embedding(data.get("image", ""))
    match, score = face_auth.compare(stored, candidate)
    logger.info(f"[VERIFY] Face uid={uid} match={match} score={score:.3f}")
    if match:
        return jsonify({"ok": True,  "score": round(float(score), 3)})
    return     jsonify({"ok": False, "score": round(float(score), 3)})

@app.route("/api/auth/verify/voice", methods=["POST"])
def api_verify_voice():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "Not logged in"})
    data     = request.get_json(force=True)
    stored   = user_db.load_voice_signature(uid)
    if stored is None:
        # No voice enrolled -> skip voice check, grant access
        session["auth"] = True
        user_db.update_last_login(uid)
        return jsonify({"ok": True, "sim": 1.0, "note": "no enrollment"})
    candidate   = voice_auth.extract_from_b64(data.get("audio", ""))
    match, sim  = voice_auth.compare(stored, candidate)
    logger.info(f"[VERIFY] Voice uid={uid} match={match} sim={sim:.3f}")
    if match:
        session["auth"] = True
        user_db.update_last_login(uid)
        return jsonify({"ok": True,  "sim": round(sim, 3)})
    return     jsonify({"ok": False, "sim": round(sim, 3)})

@app.route("/logout")
def logout():
    _release_voice_for_browser_mic("logout")
    session.clear()
    return redirect(url_for("login"))

# ═════════════════════════════════════════════════════════════════════════════
#  Password auth REST API — signup / login / refresh / logout / me
# ═════════════════════════════════════════════════════════════════════════════
# Each route is rate-limited per client IP. Successful login mirrors the
# user_id into both flask session (browser flow) and a JWT pair (API
# clients). Refresh uses rotation — every refresh issues a NEW pair AND
# revokes the old refresh token's jti.

@app.route("/api/auth/signup", methods=["POST"])
@rate_limit("signup", limit=5, window=300)
def api_auth_signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip()
    password =  data.get("password") or ""
    name     = (data.get("name")     or "").strip() or username
    try:
        uid = user_db.create_user_with_password(
            username, email, password, name=name,
        )
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error("[AUTH/SIGNUP] %s", e)
        return jsonify({"ok": False, "error": "signup failed"}), 500
    if not uid:
        return jsonify({"ok": False, "error": "signup conflict"}), 409
    pair = _jwt_auth.issue_pair(uid)
    # Mirror to flask session so the browser flow works without a JWT.
    session["uid"]  = uid
    session["name"] = name
    session["auth"] = "password"
    logger.info("[AUTH/SIGNUP] new user=%s username=%s", uid, username)
    return jsonify({
        "ok":   True,
        "user": {"id": uid, "username": username, "email": email, "name": name},
        **pair,
    }), 201


@app.route("/api/auth/login", methods=["POST"])
@rate_limit("login", limit=10, window=60)
def api_auth_login():
    data     = request.get_json(silent=True) or {}
    login_id = (data.get("login") or data.get("username") or
                data.get("email") or "").strip()
    password = data.get("password") or ""
    if not login_id or not password:
        return jsonify({"ok": False, "error": "login and password required"}), 400
    row = user_db.verify_password_login(login_id, password)
    if not row:
        return jsonify({"ok": False, "error": "invalid credentials"}), 401
    user_db.update_last_login(row["user_id"])
    pair = _jwt_auth.issue_pair(row["user_id"])
    session["uid"]  = row["user_id"]
    session["name"] = row.get("name") or row.get("username")
    session["auth"] = "password"
    logger.info("[AUTH/LOGIN] uid=%s", row["user_id"])
    return jsonify({
        "ok":   True,
        "user": {
            "id":       row["user_id"],
            "username": row.get("username"),
            "email":    row["email"],
            "name":     row.get("name"),
        },
        **pair,
    })


@app.route("/api/auth/refresh", methods=["POST"])
@rate_limit("refresh", limit=20, window=60)
def api_auth_refresh():
    data    = request.get_json(silent=True) or {}
    refresh = (data.get("refresh") or "").strip()
    if not refresh:
        return jsonify({"ok": False, "error": "refresh token required"}), 400
    try:
        pair = _jwt_auth.rotate_refresh(refresh)
    except JWTError as je:
        return jsonify({"ok": False, "error": str(je)}), 401
    return jsonify({"ok": True, **pair})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """Revoke the refresh token (if supplied) and clear the browser session."""
    data    = request.get_json(silent=True) or {}
    refresh = (data.get("refresh") or "").strip()
    if refresh:
        _jwt_auth.revoke(refresh)
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
@require_user
def api_auth_me():
    uid = current_user_id()
    row = user_db.get_user(uid) or {}
    return jsonify({"ok": True, "user": {
        "id":             uid,
        "username":       row.get("username"),
        "email":          row.get("email"),
        "name":           row.get("name"),
        "memory_enabled": bool(row.get("memory_enabled", 1)),
        "auth_provider":  row.get("auth_provider", "google"),
        "created_at":     row.get("created_at"),
    }})


# ═════════════════════════════════════════════════════════════════════════════
#  Memory Manager REST API — list / search / CRUD / clear / stats
# ═════════════════════════════════════════════════════════════════════════════
# Every endpoint requires authentication (@require_user) and EVERY call
# into `memory.*` passes the resolved user_id explicitly. No memory call
# can ever reach a neighbour user's data.

@app.route("/api/memory/list", methods=["GET"])
@require_user
def api_memory_list():
    """List the caller's structured memories. Optional ?category=&limit=."""
    uid   = current_user_id()
    cat   = (request.args.get("category") or "").strip() or None
    try:
        limit = max(1, min(500, int(request.args.get("limit", 100))))
    except Exception:
        limit = 100
    rows = memory.list_memories(category=cat, limit=limit, user_id=uid)
    return jsonify({"ok": True, "items": rows, "count": len(rows)})

@app.route("/api/memory/categories", methods=["GET"])
@require_user
def api_memory_categories():
    return jsonify({"ok": True,
                    "items": memory.list_categories(user_id=current_user_id())})

@app.route("/api/memory/search", methods=["GET"])
@require_user
def api_memory_search():
    uid   = current_user_id()
    q     = (request.args.get("q") or "").strip()
    cat   = (request.args.get("category") or "").strip() or None
    try:
        limit = max(1, min(50, int(request.args.get("limit", 10))))
    except Exception:
        limit = 10
    rows = memory.search_memories(q, limit=limit, category=cat, user_id=uid)
    return jsonify({"ok": True, "items": rows, "count": len(rows)})

@app.route("/api/memory/add", methods=["POST"])
@require_user
def api_memory_add():
    uid        = current_user_id()
    data       = request.get_json(silent=True) or {}
    content    = (data.get("content")  or "").strip()
    category   = (data.get("category") or "general").strip()[:40]
    importance = data.get("importance", 3)
    if not content:
        return jsonify({"ok": False, "error": "content required"}), 400
    new_id = memory.add_memory(content, category=category,
                               importance=importance, source="manual",
                               user_id=uid)
    if new_id <= 0:
        return jsonify({"ok": False, "error": "save failed (memory disabled?)"}), 500
    return jsonify({"ok": True, "id": new_id})

@app.route("/api/memory/<int:mem_id>", methods=["PUT"])
@require_user
def api_memory_update(mem_id):
    uid  = current_user_id()
    data = request.get_json(silent=True) or {}
    ok = memory.update_memory(
        mem_id,
        content=data.get("content"),
        category=data.get("category"),
        importance=data.get("importance"),
        user_id=uid,
    )
    return jsonify({"ok": bool(ok)})

@app.route("/api/memory/<int:mem_id>", methods=["DELETE"])
@require_user
def api_memory_delete(mem_id):
    ok = memory.delete_memory(mem_id, user_id=current_user_id())
    return jsonify({"ok": bool(ok)})

@app.route("/api/memory/clear", methods=["POST"])
@require_user
def api_memory_clear():
    """Clear ALL the caller's memories (optionally scoped to a category).
    Destructive — NEVER touches another user's data."""
    uid  = current_user_id()
    data = request.get_json(silent=True) or {}
    cat  = (data.get("category") or "").strip() or None
    n    = memory.clear_memories(category=cat, user_id=uid)
    return jsonify({"ok": True, "deleted": n})

@app.route("/api/memory/stats", methods=["GET"])
@require_user
def api_memory_stats():
    return jsonify({"ok": True,
                    "stats": memory.stats(user_id=current_user_id())})

# ═════════════════════════════════════════════════════════════════════════════
#  Privacy / GDPR — export, memory toggle, full purge, account delete
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/memory/export", methods=["GET"])
@require_user
def api_memory_export():
    """Download EVERY piece of data tied to the calling user (GDPR Art. 20).
    Returns a JSON blob with profile, behavior, conversations, notes,
    structured memories, and the raw mem_log."""
    uid  = current_user_id()
    blob = memory.export_user_data(user_id=uid)
    resp = jsonify(blob)
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=jarvis-memory-{uid}.json"
    )
    return resp

@app.route("/api/memory/disable", methods=["POST"])
@require_user
def api_memory_disable():
    """Toggle the per-user `memory_enabled` flag. Body: {\"enabled\": bool}.
    When disabled, JARVIS still uses prior memories for read-only context
    but stops accumulating new ones."""
    uid     = current_user_id()
    data    = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    ok = user_db.set_memory_enabled(uid, enabled)
    logger.info("[MEM/TOGGLE] uid=%s enabled=%s ok=%s", uid, enabled, ok)
    return jsonify({"ok": ok, "enabled": enabled})

@app.route("/api/memory/cleanup", methods=["POST"])
@require_user
def api_memory_cleanup():
    """Run dedup + low-value pruning + per-user cap for the caller."""
    report = memory.cleanup_low_value(user_id=current_user_id())
    return jsonify({"ok": True, "report": report})

@app.route("/api/account", methods=["DELETE"])
@require_user
def api_account_delete():
    """Hard-delete the account and EVERY associated row, file, and vector
    (GDPR Art. 17). Irreversible. The caller's session is cleared too."""
    uid = current_user_id()
    if uid in ("_legacy", "demo-user"):
        return jsonify({"ok": False, "error": "cannot delete this account"}), 400
    counts = user_db.delete_user_cascade(uid)
    session.clear()
    logger.warning("[ACCOUNT] DELETED uid=%s counts=%s", uid, counts)
    return jsonify({"ok": True, "counts": counts})

@app.route("/api/test-brain")
def test_brain_route():
    results = {
        "groq_configured": bool(config.GROQ_API_KEY),
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "groq_key_preview": config.GROQ_API_KEY[:8] + "..." if config.GROQ_API_KEY else "EMPTY",
        "gemini_key_preview": config.GEMINI_API_KEY[:8] + "..." if config.GEMINI_API_KEY else "EMPTY",
    }
    # Test Groq live
    try:
        from groq import Groq
        c = Groq(api_key=config.GROQ_API_KEY)
        r = c.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10
        )
        results["groq_result"] = f"SUCCESS: {r.choices[0].message.content.strip()}"
    except Exception as e:
        results["groq_result"] = f"FAILED: {type(e).__name__}: {str(e)}"

    # Test Gemini live
    try:
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        m = genai.GenerativeModel(config.GEMINI_MODEL)
        r = m.generate_content("hi")
        results["gemini_result"] = f"SUCCESS: {r.text.strip()}"
    except Exception as e:
        results["gemini_result"] = f"FAILED: {type(e).__name__}: {str(e)}"

    return jsonify(results)

@app.route("/health")
def health():
    brain_status = brain_manager.brain.get_status() if brain_manager.brain else {}
    return {"status":"ok",
            "brain": brain_status,
            "tavily": {
                "configured": config.is_tavily_ready(),
                "cache": tavily_search.get_search_cache_stats(),
            },
            "state":state.current_state,
            "memory":memory.stats(),
            "profile":memory.get_profile(),
            "auth":_logged_in()}

#  Entry Point 

def run_server(host="0.0.0.0", port=8000, debug=False):
    print("[INIT] Initializing TTS...")
    if tts.is_available() and getattr(config, "ENABLE_VOICE_OUTPUT", False):
        def greet():
            time.sleep(2)
            tts.speak("Welcome back, boss. All systems are online.")
        threading.Thread(target=greet, daemon=True).start()

    # Load ChromaDB knowledge base in background (non-blocking)
    threading.Thread(target=knowledge_db.init, daemon=True, name="knowledge-init").start()

    if not brain_manager.brain:
        brain_manager.init(socketio=socketio)
    brain_summary = brain_manager.brain.get_provider_summary()
    tavily_status = "OK" if config.is_tavily_ready() else "NO KEY"

    # Voice starts lazily after authenticated main UI connects.
    voice_label = "DEFERRED UNTIL MAIN UI"

    # Start the state watchdog (auto-resets stuck states)
    state.start_watchdog()

    print("+----------------------------------------------------------+")
    print("|              JARVIS AI SYSTEM - MULTI-BRAIN               |")
    print("+----------------------------------------------------------+")
    print(f"|  Providers: {brain_summary}")
    print(f"|  Priority:  Gemini -> Groq -> OpenRouter")
    print(f"|  Search:    TAVILY: {tavily_status}")
    print(f"|  Voice:     {voice_label}")
    print(f"|  Timeout:   {config.AI_TIMEOUT}s per provider")
    print(f"|  Memory:    {memory.stats()}")
    print(f"|  URL:       http://localhost:{port}")
    print("+----------------------------------------------------------+")

    logger.info("[SERVER] Starting JARVIS with multi-provider brain...")
    socketio.run(app, host=host, port=port, debug=debug,
                 use_reloader=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host",  default="0.0.0.0")
    p.add_argument("--port",  type=int, default=int(os.getenv("PORT", 8000)))
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()
    run_server(a.host, a.port, a.debug)
