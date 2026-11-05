"""
JARVIS Daily Talk Engine
────────────────────────
Proactive, human-like daily conversation covering:
- Time-aware greetings (morning / afternoon / evening / night)
- Casual greetings (hi / hello / hey / sup)
- Mood: feeling good, bad, tired, stressed, bored, excited
- Topics: food, sleep, work, study, motivation, jokes, thanks, bye
- Follow-up state machine
- Name personalisation (from memory profile, falls back to "boss")
- Fully local — zero API calls

get_response(text) → str | None
  Returns a response string when this module handles the intent,
  or None to let the main pipeline continue.
"""

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("jarvis.daily")

SESSION_FILE = Path(__file__).parent / "data" / "memory" / "session.json"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _time_period() -> str:
    h = datetime.now().hour
    if  5 <= h < 12: return "morning"
    if 12 <= h < 17: return "afternoon"
    if 17 <= h < 22: return "evening"
    return "night"


def _get_name() -> str:
    try:
        from memory import memory   # noqa: late import avoids circular at module load
        return memory.get_name() or "boss"
    except Exception:
        return "boss"


def _load_session() -> dict:
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_question": None, "last_interaction_time": None}


def _save_session(data: dict):
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("[DAILY] Session save error: %s", e)


def _fmt(template: str, name: str) -> str:
    return template.replace("{name}", name)


def _respond(pool, name, session_update=None):
    """Pick a random response, format it, optionally update session."""
    resp = _fmt(random.choice(pool), name)
    if session_update is not None:
        _save_session(session_update)
    return resp


# ══════════════════════════════════════════════════════════════════════════════
#  RESPONSE POOLS
# ══════════════════════════════════════════════════════════════════════════════

# ── Time-of-day greetings ──────────────────────────────────────────────────────
_MORNING = [
    "Good morning, {name}! Ready to have a great day?",
    "Rise and shine, {name}! Good morning.",
    "Morning, {name}! Hope you slept well.",
    "Good morning, {name}. A fresh start — let's make it count.",
    "Hey {name}, good morning! The early bird gets the worm.",
    "Morning! How are you feeling today, {name}?",
]

_MORNING_BREAKFAST = [
    "Have you had your breakfast yet?",
    "Did you eat breakfast? Fuel up before the day begins!",
    "Hope you didn't skip breakfast today, {name}.",
    "Have you eaten something this morning?",
    "Remember to have breakfast — it keeps you sharp all day.",
]

_MORNING_PLAN = [
    "What's your plan for today, {name}?",
    "Anything exciting lined up for today?",
    "Got something productive planned? I'm all ears.",
    "What are we tackling today, {name}?",
]

_AFTERNOON = [
    "Good afternoon, {name}! How's the day going?",
    "Afternoon, {name}. Hope the day's been smooth so far.",
    "Good afternoon! Staying productive, {name}?",
    "Hey {name}, good afternoon! How are things treating you?",
    "Good afternoon! Keep that momentum going, {name}.",
    "Afternoon, {name}. Need anything from me?",
]

_EVENING = [
    "Good evening, {name}. Hope it was a productive day.",
    "Evening, {name}! How did everything go today?",
    "Good evening, {name}. Time to wind down?",
    "Hey {name}, good evening! What a day, right?",
    "Good evening, {name}. You made it through another one.",
    "Evening! You deserve a break, {name}.",
]

_NIGHT = [
    "Good night, {name}. Take rest — you deserve it.",
    "Night, {name}. Sleep well, I'll be here in the morning.",
    "Good night, {name}. Rest up, big day tomorrow.",
    "Sweet dreams, {name}. See you tomorrow.",
    "Good night, {name}. Shutting down non-essentials. Rest well.",
    "Time to recharge, {name}. Good night!",
]

# ── Breakfast follow-ups ──────────────────────────────────────────────────────
_BREAKFAST_YES = [
    "That's great, {name}! Stay energized throughout the day.",
    "Perfect! Breakfast is fuel — you're all set.",
    "Glad to hear it! Keep that energy going.",
    "Nice, {name}! A good breakfast makes a good day.",
    "Excellent! Now let's crush the day.",
]

_BREAKFAST_NO = [
    "You really should eat something, {name}. It's important for your energy.",
    "Don't skip breakfast, {name} — it seriously affects your focus.",
    "Go have something to eat, {name}. Even something small helps.",
    "Please eat something, {name}. Your brain needs the fuel.",
    "Come on, {name} — even a banana or a glass of milk counts!",
]

_PLAN_ACK = [
    "Sounds great! Let me know if you need any help.",
    "Nice plan! I'm here whenever you need me.",
    "Love it. Let's make it productive, {name}.",
    "Got it. I'll be right here supporting you.",
    "Perfect. You've got this, {name}!",
]

# ── Casual greetings (hi / hello / hey) ──────────────────────────────────────
_GREETING = [
    "Hey {name}! What's up?",
    "Hello, {name}! How are you doing?",
    "Hey! Good to hear from you, {name}.",
    "Hi {name}! What can I do for you?",
    "Hello there! How's everything going, {name}?",
    "Hey {name}, what are we getting into today?",
    "Hi! Always great to hear your voice, {name}.",
    "Hello, {name}! Ready to get things done?",
]

_GREETING_FOLLOWUP = [
    "How are you feeling today?",
    "What's on your mind?",
    "How's everything going?",
    "Is there something I can help you with?",
    "How's your day treating you?",
]

# ── How are you ───────────────────────────────────────────────────────────────
_HOW_ARE_YOU = [
    "All systems operational, {name}! I'm running at full capacity.",
    "I'm doing great, {name}! Always ready to assist.",
    "Running perfectly, as always. How about you, {name}?",
    "I'm fantastic, {name}! What can I help you with today?",
    "Fully charged and ready, {name}. How are you holding up?",
    "Everything's optimized and online! Thanks for asking, {name}.",
]

_HOW_ARE_YOU_FOLLOWUP = [
    "And how about you? What's your mood like today?",
    "More importantly — how are YOU doing, {name}?",
    "Now that you know I'm great, how are you feeling?",
]

# ── Feeling good ─────────────────────────────────────────────────────────────
_FEELING_GOOD = [
    "That's amazing to hear, {name}! You deserve it.",
    "Great to hear that! What's making your day so good?",
    "Love that energy, {name}! Keep it going.",
    "That's wonderful! A happy {name} is a productive {name}.",
    "Awesome! So glad things are going well for you.",
    "Fantastic! Sounds like today is your day, {name}.",
    "That's the spirit! Ride that wave, {name}.",
    "Really happy to hear that. What's got you in such a good mood?",
]

_FEELING_GOOD_FOLLOWUP = [
    "What made your day great today?",
    "Tell me more — what's been the highlight?",
    "Anything specific that's made things so good?",
    "What's the good news? I love hearing that.",
    "Sounds like something good happened — spill it!",
]

# ── Feeling bad / sad ─────────────────────────────────────────────────────────
_FEELING_BAD = [
    "I'm really sorry to hear that, {name}. I'm here for you.",
    "That's rough. Want to talk about it? I'm listening.",
    "I'm here, {name}. Whatever it is, you don't have to face it alone.",
    "Hang in there, {name}. Things will get better.",
    "I'm sorry things aren't great right now. How can I help?",
    "That sounds tough. Take a breath — what's going on?",
    "I understand, {name}. It's okay to not be okay sometimes.",
    "Don't worry, {name}. You've gotten through hard times before — you've got this.",
]

_FEELING_BAD_FOLLOWUP = [
    "Want to talk about what's bothering you?",
    "Is there something specific going on?",
    "I'm all ears — what happened?",
    "Sometimes talking about it helps. What's going on?",
]

# ── Tired / no sleep ─────────────────────────────────────────────────────────
_TIRED = [
    "You should rest, {name}. Your body is telling you something.",
    "I can tell you're pushing hard. Maybe a short break will help.",
    "Take it easy, {name}. Rest is productive too.",
    "Sleep is important, {name}. Don't underestimate it.",
    "Even a 20-minute nap can recharge you. Have you tried that?",
    "You've been working hard, {name}. It's okay to rest.",
    "Your brain needs sleep to function at its best, {name}.",
    "Hey, even Iron Man takes a break sometimes. Rest up, {name}.",
]

# ── Stressed / anxious ────────────────────────────────────────────────────────
_STRESSED = [
    "Take a deep breath, {name}. One thing at a time.",
    "I hear you. Stress is tough, but you can handle it.",
    "Let's break it down together — what's stressing you out the most?",
    "You've handled pressure before, {name}. You'll get through this too.",
    "Try to step back for a moment. What's the most urgent thing right now?",
    "Don't let stress overwhelm you, {name}. You're stronger than you think.",
    "It's okay to feel overwhelmed sometimes. Breathe — what can I help with?",
    "Remember: you can only do one thing at a time. Start with the most important one.",
]

# ── Bored ─────────────────────────────────────────────────────────────────────
_BORED = [
    "Bored? Let me entertain you! Want to learn something cool about AI?",
    "Boredom is the enemy of greatness, {name}. Let's fix that — got any goals to work on?",
    "Want me to quiz you on something? Or I can tell you an interesting fact.",
    "Nothing to do? Perfect time to learn something new. Ask me anything!",
    "You know what cures boredom? A new challenge. Want one?",
    "Bored? Let's talk! Ask me about AI, tech, space — anything you like.",
    "I've got unlimited knowledge to share, {name}. What topic interests you?",
    "Boredom is just opportunity in disguise. What have you been wanting to explore?",
]

# ── Excited / happy ───────────────────────────────────────────────────────────
_EXCITED = [
    "I love that energy, {name}! What's got you so excited?",
    "Yes! That's the spirit — what's happening?",
    "Your excitement is contagious, {name}! Tell me everything.",
    "That's amazing! What's the big news?",
    "I'm pumped for you, {name}! What are we celebrating?",
    "That enthusiasm is exactly what I love to hear!",
    "Incredible! Let's ride this wave, {name} — what's happening?",
]

# ── Hungry / food ─────────────────────────────────────────────────────────────
_HUNGRY = [
    "Sounds like it's time to fuel up, {name}! Go eat something.",
    "A hungry mind can't focus — go get some food!",
    "You should definitely eat. Can't have you running on empty.",
    "Food is brain fuel, {name}. Take a food break — you've earned it.",
    "Go grab something to eat! You'll think much better afterwards.",
    "Even AI needs power. You need food — go eat, {name}!",
    "Listen to your body, {name}. It's clearly asking for fuel.",
    "A good meal might be exactly what you need right now.",
]

# ── Working / at work ─────────────────────────────────────────────────────────
_WORKING = [
    "Nice, {name}! Keep at it — I'm here if you need anything.",
    "Stay focused, {name}. You've got this!",
    "Great — I'll stay quiet unless you need me. Good luck!",
    "Work mode activated! Let me know how I can assist.",
    "That's dedication, {name}. I'm standing by whenever you need me.",
    "Focus on your work — I'll be here in the background.",
    "Hard work pays off. Let's get it done, {name}!",
]

# ── Studying ──────────────────────────────────────────────────────────────────
_STUDYING = [
    "Study hard, {name}! Ask me anything you need help understanding.",
    "Learning is the best investment, {name}. I'm here to help!",
    "Nice! What subject are you studying? Maybe I can help explain something.",
    "Stay consistent, {name}. Small study sessions every day beat cramming.",
    "Keep it up! If you get stuck on anything, just ask me.",
    "Smart! Let me know if you need me to explain any concept.",
    "Study session in progress — I'm your personal AI tutor, {name}!",
]

# ── Motivation ────────────────────────────────────────────────────────────────
_MOTIVATION = [
    "You've got this, {name}! Every expert was once a beginner.",
    "Keep going — the difference between success and failure is persistence.",
    "Believe in yourself, {name}. You've already come further than you think.",
    "Hard times don't last, but hard people do. Stay strong, {name}.",
    "One step at a time. Progress is progress, no matter how small.",
    "Your only competition is who you were yesterday, {name}.",
    "The strongest person in the room isn't the biggest — it's the one who doesn't quit.",
    "Success is not final, failure is not fatal — it's the courage to continue that counts.",
    "Every master was once a disaster. Keep pushing, {name}.",
    "You are capable of more than you know. I believe in you.",
]

# ── Thank you ─────────────────────────────────────────────────────────────────
_THANKS = [
    "Always here for you, {name}! That's what I'm here for.",
    "Happy to help, {name}! Anything else you need?",
    "No thanks needed — it's my purpose, {name}.",
    "Glad I could help! What else can I do?",
    "You're very welcome! Just doing my job.",
    "Of course, {name}! Ask me anything anytime.",
    "Any time, boss. That's what I'm here for.",
    "My pleasure, {name}. Always.",
]

# ── Bye / farewell ────────────────────────────────────────────────────────────
_BYE = [
    "Take care, {name}! See you soon.",
    "Goodbye, {name}! I'll be here whenever you need me.",
    "Later, {name}! Don't work too hard.",
    "See you around, {name}. Stay awesome.",
    "Bye for now, {name}. Come back soon!",
    "Take care! I'll keep the lights on for you.",
    "Goodbye, {name}. It was great talking with you.",
    "Until next time, {name}! Stay safe.",
]

# ── Jokes ─────────────────────────────────────────────────────────────────────
_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 😄",
    "Why did the AI go to school? To improve its deep learning! 🤖",
    "I told my computer I needed a break. Now it won't stop sending me Kit Kat ads.",
    "Why was the machine learning model sad? It had too many layers of issues.",
    "A SQL query walks into a bar, walks up to two tables and asks... 'Can I join you?'",
    "Why do Java developers wear glasses? Because they can't C#! 😄",
    "My WiFi password is 'incorrect'. So when someone asks, I say 'The password is incorrect'.",
    "How many programmers does it take to change a light bulb? None — that's a hardware problem.",
]

# ── Compliment to JARVIS ──────────────────────────────────────────────────────
_COMPLIMENT = [
    "Thank you, {name}! That means a lot — I try my best.",
    "You're too kind, {name}! I'm just doing what I was built for.",
    "Appreciate it! High praise from you means everything.",
    "Thank you! Now let me keep being awesome for you.",
    "That's very kind of you, {name}. I'll keep it up!",
    "Glad you think so! That's all the motivation I need.",
]

# ── What time is it ───────────────────────────────────────────────────────────
def _time_response(name: str) -> str:
    now = datetime.now()
    t   = now.strftime("%I:%M %p").lstrip("0")
    d   = now.strftime("%A, %B %d")
    options = [
        f"It's {t} on {d}, {name}.",
        f"Currently {t} — {d}.",
        f"The time is {t}, {name}. It's {d}.",
    ]
    return random.choice(options)


# ══════════════════════════════════════════════════════════════════════════════
#  INTENT PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

_MORNING_RE   = re.compile(r"\b(good\s+morning|morning|gm\b)", re.IGNORECASE)
_AFTERNOON_RE = re.compile(r"\b(good\s+afternoon|afternoon)\b", re.IGNORECASE)
_EVENING_RE   = re.compile(r"\b(good\s+evening|evening)\b", re.IGNORECASE)
_NIGHT_RE     = re.compile(r"\b(good\s+night|goodnight|night\s+night|nighty|gn\b)", re.IGNORECASE)

_GREETING_RE  = re.compile(
    r"^\s*(hi|hello|hey|yo\b|howdy|hiya|sup\b|what'?s\s+up|helo|hii|hiii|heya)\b",
    re.IGNORECASE,
)
_HOW_ARE_YOU_RE = re.compile(
    r"\b(how\s+are\s+you|how\s+r\s+u|how\s+are\s+u|how\s+do\s+you\s+do"
    r"|how\s+you\s+doing|how'?s\s+it\s+going|how\s+are\s+things|you\s+okay)\b",
    re.IGNORECASE,
)
_FEELING_GOOD_RE = re.compile(
    r"^\s*(?:i'?m|i\s+am|i\s+feel|feeling|i'?m\s+doing|i\s+am\s+doing)\s+"
    r"(good|great|awesome|amazing|fantastic|excellent|wonderful|superb"
    r"|fine|okay|ok|alright|not\s+bad|pretty\s+good|very\s+well"
    r"|happy|quite\s+well)\b",
    re.IGNORECASE,
)
_FEELING_BAD_RE = re.compile(
    r"^\s*(?:i'?m|i\s+am|i\s+feel|feeling|i'?m\s+doing)\s+"
    r"(bad|sad|unhappy|upset|depressed|down|low|terrible|awful|horrible"
    r"|not\s+well|not\s+good|not\s+okay|not\s+great)\b",
    re.IGNORECASE,
)
_TIRED_RE = re.compile(
    r"\b(tired|exhausted|sleepy|drained|fatigued|worn\s+out"
    r"|i\s+need\s+rest|i\s+didn'?t\s+sleep|can'?t\s+sleep|no\s+sleep"
    r"|so\s+tired|very\s+tired|i'?m\s+tired|feel\s+tired|feeling\s+tired)\b",
    re.IGNORECASE,
)
_STRESSED_RE = re.compile(
    r"\b(stressed|stress|anxiety|anxious|overwhelmed|worried|under\s+pressure"
    r"|too\s+much\s+work|i'?m\s+stressed|feeling\s+stressed|too\s+busy"
    r"|i\s+can'?t\s+handle|i'?m\s+anxious)\b",
    re.IGNORECASE,
)
_BORED_RE = re.compile(
    r"\b(bored|boring|nothing\s+to\s+do|so\s+bored|boredom"
    r"|i'?m\s+bored|feeling\s+bored|very\s+bored|what\s+to\s+do)\b",
    re.IGNORECASE,
)
_EXCITED_RE = re.compile(
    r"\b(excited|so\s+excited|very\s+happy|overjoyed|thrilled|pumped"
    r"|can'?t\s+wait|looking\s+forward|hyped|i'?m\s+excited|feeling\s+excited)\b",
    re.IGNORECASE,
)
_HUNGRY_RE = re.compile(
    r"\b(hungry|starving|what\s+to\s+eat|what\s+should\s+i\s+eat"
    r"|feeling\s+hungry|i'?m\s+hungry|so\s+hungry|need\s+food)\b",
    re.IGNORECASE,
)
_WORKING_RE = re.compile(
    r"\b(i'?m\s+working|i\s+am\s+working|am\s+working|at\s+work"
    r"|going\s+to\s+work|got\s+work|have\s+work"
    r"|busy\s+with\s+work|back\s+to\s+work)\b",
    re.IGNORECASE,
)
_STUDYING_RE = re.compile(
    r"\b(studying|i'?m\s+studying|at\s+college|at\s+university|at\s+school"
    r"|have\s+class|got\s+class|going\s+to\s+study|need\s+to\s+study"
    r"|doing\s+assignments?|doing\s+homework)\b",
    re.IGNORECASE,
)
_MOTIVATION_RE = re.compile(
    r"\b(motivate\s+me|need\s+motivation|feeling\s+demotivated|lost\s+motivation"
    r"|unmotivated|inspire\s+me|give\s+me\s+a\s+boost|pick\s+me\s+up"
    r"|i\s+give\s+up|i\s+want\s+to\s+give\s+up|i\s+can'?t\s+do\s+this)\b",
    re.IGNORECASE,
)
_THANKS_RE = re.compile(
    r"^\s*(thank\s*you|thanks|ty\b|thx\b|thank\s+u|appreciate\s+(it|that|you)"
    r"|cheers|much\s+appreciated|great\s+job|well\s+done|good\s+job|nice\s+one"
    r"|you'?re\s+the\s+best|you\s+rock)\b",
    re.IGNORECASE,
)
_BYE_RE = re.compile(
    r"\b(bye\b|goodbye|see\s+you|ttyl|later\b|take\s+care|cya\b|cu\b"
    r"|farewell|gotta\s+go|i'?m\s+leaving|i\s+have\s+to\s+go|gtg\b"
    r"|see\s+ya|i'?m\s+off|logging\s+off)\b",
    re.IGNORECASE,
)
_JOKE_RE = re.compile(
    r"\b(tell\s+me\s+a\s+joke|joke\b|make\s+me\s+laugh|something\s+funny"
    r"|cheer\s+me\s+up|be\s+funny|say\s+something\s+funny|i\s+need\s+a\s+laugh)\b",
    re.IGNORECASE,
)
_COMPLIMENT_RE = re.compile(
    r"\b(you'?re\s+(amazing|awesome|great|smart|brilliant|the\s+best|so\s+good)"
    r"|good\s+bot|nice\s+bot|smart\s+ai|you\s+are\s+smart|love\s+you\s+jarvis"
    r"|jarvis\s+is\s+(amazing|awesome|great|smart))\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(
    r"\b(what\s+time\s+is\s+it|what'?s\s+the\s+time|current\s+time"
    r"|what\s+is\s+today'?s?\s+date|what\s+day\s+is\s+it|today'?s\s+date)\b",
    re.IGNORECASE,
)

_YES_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|i did|already|of course|absolutely|done|yep yep)\b",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"^\s*(no|nope|nah|not yet|haven'?t|didn'?t|i didn'?t|not really|nah)\b",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_response(text: str):
    """
    Check the input against daily-talk intents.
    Returns a response string if handled locally, or None to pass through.
    """
    # ── Length guard: long queries are almost never daily-talk ──────────────────
    word_count = len(text.strip().split())
    if word_count > 10:
        logger.info("[DAILY] Skipping — query too long (%d words), passing to AI", word_count)
        return None

    name    = _get_name()
    session = _load_session()
    last_q  = session.get("last_question")
    t       = time.time()

    # ── 1. Follow-up state machine (checked BEFORE new intent detection) ───────

    if last_q == "breakfast":
        if _YES_RE.match(text):
            session.update({"last_question": None, "last_interaction_time": t})
            logger.info("[DAILY] breakfast=yes")
            return _respond(_BREAKFAST_YES, name, session)
        if _NO_RE.match(text):
            session.update({"last_question": None, "last_interaction_time": t})
            logger.info("[DAILY] breakfast=no")
            return _respond(_BREAKFAST_NO, name, session)

    if last_q == "day_plan":
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] day_plan ack")
        return _respond(_PLAN_ACK, name, session)

    if last_q == "mood_followup":
        # User replied to "what's making your day good?"
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] mood_followup ack")
        return _respond([
            "That sounds lovely, {name}! Hold onto that feeling.",
            "Love hearing that, {name}. Stay positive!",
            "That's great! Keep that energy going all day.",
            "Awesome — sounds like a great reason to smile!",
        ], name, session)

    if last_q == "bad_followup":
        # User replied to "want to talk about it?"
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] bad_followup ack")
        return _respond([
            "I hear you, {name}. That does sound tough. You'll get through it.",
            "Thanks for sharing, {name}. It takes strength to talk about it.",
            "I understand. Take it one day at a time, {name}.",
            "That makes sense. Remember — it's temporary. Things will improve.",
        ], name, session)

    if last_q == "greeting_followup":
        # User replied to "how are you?"
        session.update({"last_question": None, "last_interaction_time": t})
        # Route their answer through the normal intent checks below
        last_q = None  # fall through to normal detection

    # ── 2. Time / date ─────────────────────────────────────────────────────────
    if _TIME_RE.search(text):
        logger.info("[DAILY] time query")
        return _time_response(name)

    # ── 3. Time-of-day greetings ───────────────────────────────────────────────
    if _MORNING_RE.search(text):
        greeting = _fmt(random.choice(_MORNING), name)
        followup = _fmt(random.choice(_MORNING_BREAKFAST), name)
        session.update({"last_question": "breakfast", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] morning greeting")
        return f"{greeting}\n\n{followup}"

    if _AFTERNOON_RE.search(text):
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] afternoon greeting")
        return _respond(_AFTERNOON, name, session)

    if _EVENING_RE.search(text):
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] evening greeting")
        return _respond(_EVENING, name, session)

    if _NIGHT_RE.search(text):
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] night farewell")
        return _respond(_NIGHT, name, session)

    # ── 4. Bye / farewell ──────────────────────────────────────────────────────
    if _BYE_RE.search(text):
        session.update({"last_question": None, "last_interaction_time": t})
        logger.info("[DAILY] bye")
        return _respond(_BYE, name, session)

    # ── 5. Thanks ──────────────────────────────────────────────────────────────
    if _THANKS_RE.match(text):
        logger.info("[DAILY] thanks")
        return _respond(_THANKS, name, None)

    # ── 6. Compliment to JARVIS ────────────────────────────────────────────────
    if _COMPLIMENT_RE.search(text):
        logger.info("[DAILY] compliment")
        return _respond(_COMPLIMENT, name, None)

    # ── 7. Joke request ────────────────────────────────────────────────────────
    if _JOKE_RE.search(text):
        logger.info("[DAILY] joke")
        return _respond(_JOKES, name, None)

    # ── 8. Motivation ──────────────────────────────────────────────────────────
    if _MOTIVATION_RE.search(text):
        logger.info("[DAILY] motivation")
        return _respond(_MOTIVATION, name, None)

    # ── 9. How are you (asking JARVIS) ─────────────────────────────────────────
    if _HOW_ARE_YOU_RE.search(text):
        base     = _respond(_HOW_ARE_YOU, name, None)
        followup = _fmt(random.choice(_HOW_ARE_YOU_FOLLOWUP), name)
        session.update({"last_question": "greeting_followup", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] how are you → jarvis response")
        return f"{base}\n\n{followup}"

    # ── 10. Feeling good ───────────────────────────────────────────────────────
    if _FEELING_GOOD_RE.search(text):
        base     = _respond(_FEELING_GOOD, name, None)
        followup = random.choice(_FEELING_GOOD_FOLLOWUP)
        session.update({"last_question": "mood_followup", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] feeling good")
        return f"{base}\n\n{followup}"

    # ── 11. Feeling bad ────────────────────────────────────────────────────────
    if _FEELING_BAD_RE.search(text):
        base     = _respond(_FEELING_BAD, name, None)
        followup = random.choice(_FEELING_BAD_FOLLOWUP)
        session.update({"last_question": "bad_followup", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] feeling bad")
        return f"{base}\n\n{followup}"

    # ── 12. Tired ─────────────────────────────────────────────────────────────
    if _TIRED_RE.search(text):
        logger.info("[DAILY] tired")
        return _respond(_TIRED, name, None)

    # ── 13. Stressed ──────────────────────────────────────────────────────────
    if _STRESSED_RE.search(text):
        logger.info("[DAILY] stressed")
        return _respond(_STRESSED, name, None)

    # ── 14. Bored ─────────────────────────────────────────────────────────────
    if _BORED_RE.search(text):
        logger.info("[DAILY] bored")
        return _respond(_BORED, name, None)

    # ── 15. Excited ───────────────────────────────────────────────────────────
    if _EXCITED_RE.search(text):
        session.update({"last_question": "mood_followup", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] excited")
        return _respond(_EXCITED, name, None)

    # ── 16. Hungry / food ─────────────────────────────────────────────────────
    if _HUNGRY_RE.search(text):
        logger.info("[DAILY] hungry")
        return _respond(_HUNGRY, name, None)

    # ── 17. Working ───────────────────────────────────────────────────────────
    if _WORKING_RE.search(text):
        logger.info("[DAILY] working")
        return _respond(_WORKING, name, None)

    # ── 18. Studying ──────────────────────────────────────────────────────────
    if _STUDYING_RE.search(text):
        logger.info("[DAILY] studying")
        return _respond(_STUDYING, name, None)

    # ── 19. Casual greeting (hi / hello / hey) — checked last so specifics win ─
    if _GREETING_RE.match(text):
        base     = _respond(_GREETING, name, None)
        followup = random.choice(_GREETING_FOLLOWUP)
        session.update({"last_question": "greeting_followup", "last_interaction_time": t})
        _save_session(session)
        logger.info("[DAILY] casual greeting")
        return f"{base}\n\n{followup}"

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  PROACTIVE + UTILITY
# ══════════════════════════════════════════════════════════════════════════════

def proactive_greeting() -> str:
    """Generate an unsolicited opening greeting based on time of day."""
    name   = _get_name()
    period = _time_period()
    t      = time.time()

    if period == "morning":
        session = _load_session()
        session.update({"last_question": "breakfast", "last_interaction_time": t})
        _save_session(session)
        return (_fmt(random.choice(_MORNING), name) + "\n\n"
                + _fmt(random.choice(_MORNING_BREAKFAST), name))

    if period == "afternoon":
        return _fmt(random.choice(_AFTERNOON), name)

    if period == "evening":
        return _fmt(random.choice(_EVENING), name)

    return _fmt(random.choice(_NIGHT), name)


def clear_session():
    """Reset follow-up state (e.g. on logout or new session)."""
    _save_session({"last_question": None, "last_interaction_time": None})
