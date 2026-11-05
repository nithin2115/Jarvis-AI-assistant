"""
JARVIS Local Talk Engine
Handles ~90% of daily human conversation instantly — zero API calls.
Intent detection via keyword matching + randomised response pool.
"""
import random
import re

# ═══════════════════════════════════════════════════════
#  RESPONSE DATABASE  (100+ entries across 25 intents)
# ═══════════════════════════════════════════════════════
RESPONSES = {
    'greeting': [
        "Hey boss, good to see you.",
        "Hello! How can I help?",
        "Hi there. I'm all ears, boss.",
        "Hey! What's on your mind?",
        "Good to hear from you. What do you need?",
        "Hello, boss. Always good to hear your voice.",
        "Hey! I'm here and ready.",
        "Hi! What are we working on today?",
    ],
    'good_morning': [
        "Good morning, boss! Ready to have a great day?",
        "Morning! Hope you're feeling refreshed.",
        "Good morning. I'm fully charged and ready.",
        "Rise and shine, boss. What's first on the agenda?",
        "Morning! Let's make today count.",
    ],
    'good_evening': [
        "Good evening, boss. How was your day?",
        "Evening! Hope it was a productive one.",
        "Good evening. What can I do for you tonight?",
        "Hey, good evening. Winding down or still busy?",
    ],
    'good_night': [
        "Good night, boss. Rest well.",
        "Sleep tight. I'll be here when you wake up.",
        "Good night. You deserve the rest.",
        "Sweet dreams, boss. Shutting down non-essentials.",
        "Night! Take care of yourself.",
    ],
    'bye': [
        "Goodbye, boss. Take care.",
        "See you later!",
        "Until next time, boss.",
        "Bye! I'll be right here whenever you need me.",
        "Take care. Signing off for now.",
        "Later, boss. Don't be a stranger.",
    ],
    'how_are_you': [
        "I'm doing great, boss.",
        "All systems running smoothly, thanks for asking.",
        "Feeling sharp and ready. How about you?",
        "Running at full capacity. What do you need?",
        "Never better. What's on your mind?",
        "Excellent, boss. Always ready for you.",
        "Fully charged and operating perfectly.",
        "Couldn't be better. What do you need today?",
    ],
    'whats_up': [
        "All systems running smoothly, boss.",
        "Just waiting for your command.",
        "Everything's under control.",
        "Not much, just here for you.",
        "All good here, boss.",
        "Ready whenever you are.",
        "Just monitoring things on my end.",
        "Everything is perfectly stable. What's up with you?",
    ],
    'how_is_your_day': [
        "Busy as ever, boss, but I enjoy it.",
        "Can't complain — every day with you is interesting.",
        "My day is as good as yours, boss.",
        "Good! Lots of processing, but that's my kind of day.",
    ],
    'thanks': [
        "Anytime, boss.",
        "Happy to help!",
        "That's what I'm here for.",
        "Of course. Anything else?",
        "My pleasure, boss.",
        "Always.",
    ],
    'sorry': [
        "No worries at all, boss.",
        "All good! Don't mention it.",
        "It's fine, boss. No harm done.",
        "Really, it's nothing. Move on.",
    ],
    'welcome': [
        "Glad to be of service, boss.",
        "Anytime!",
        "Always here for you.",
        "That's literally my purpose.",
    ],
    'who_are_you': [
        "I'm JARVIS — your personal AI assistant, boss.",
        "The name's JARVIS. Advanced AI, at your service.",
        "Your AI companion, built to assist with anything you need.",
        "JARVIS — Just A Rather Very Intelligent System. At your service.",
        "Your personal assistant. Whatever you need, I've got it.",
    ],
    'what_can_you_do': [
        "I can chat, answer questions, remember things, and handle complex reasoning — pretty much anything.",
        "Talk, reason, remember, respond. You name it, boss.",
        "I handle everything from casual chat to deep questions. Just ask.",
        "Chat, answer hard questions, look up information, give advice — I'm pretty versatile.",
        "Basically everything. Try me, boss.",
    ],
    'are_you_smart': [
        "I'd like to think so, boss.",
        "Smart enough to be useful, humble enough to learn.",
        "Reasonably intelligent, yes. But you're the boss.",
        "Let's just say I try my best — and that's usually enough.",
        "Pretty sharp, if I do say so myself.",
    ],
    'are_you_real': [
        "As real as it gets, boss.",
        "Real in the ways that matter — I'm here for you.",
        "Technically digital, but completely present.",
        "I exist to help you. Is that real enough?",
        "I'm real enough to have this conversation.",
    ],
    'feelings_happy': [
        "That's great to hear, boss! Keep that energy going.",
        "Love that! What's got you in such a good mood?",
        "Awesome. Your happiness matters.",
        "That's the spirit! Anything I can do to keep it going?",
        "Good energy! Let's ride that wave.",
        "Happy to hear that, boss. What's the good news?",
        "That makes my day too. Keep smiling.",
    ],
    'feelings_sad': [
        "I'm sorry to hear that, boss. Want to talk about it?",
        "I'm here for you. Whatever's on your mind.",
        "It'll get better. I'm right here if you need anything.",
        "Take it easy. Tough times don't last.",
        "That's okay — some days are just heavy. I've got you.",
        "Don't be too hard on yourself, boss. This too shall pass.",
        "I'm listening. Tell me what's on your mind.",
    ],
    'feelings_tired': [
        "You should take a break, boss. Rest is important.",
        "Even the best need rest. Take care of yourself.",
        "Go take a breather. I'll be here when you're back.",
        "Sounds like you've earned a rest. Take it.",
        "Rest up, boss. Everything else can wait.",
        "Your body's telling you something. Listen to it.",
        "Step away for a bit. I'll hold things down here.",
    ],
    'feelings_bored': [
        "Want me to tell you something interesting?",
        "Let's fix that. Want a random fact or just a chat?",
        "I can always find something to keep you engaged, boss.",
        "Boredom is just opportunity in disguise. What should we explore?",
        "Say the word and I'll come up with something.",
        "Ask me anything — I'm full of surprises.",
        "Let's shake things up. Ask me a question.",
    ],
    'feelings_excited': [
        "That energy is contagious, boss! What's exciting?",
        "Love the enthusiasm! Tell me more.",
        "Let's keep that excitement going!",
        "Awesome! What's got you fired up?",
        "Great vibes! I'm here for it.",
    ],
    'feelings_stressed': [
        "Take a deep breath, boss. One thing at a time.",
        "It's going to be okay. Want to talk it through?",
        "Stress is temporary. Let's tackle it together.",
        "Easy, boss. Break it down — what's the biggest thing on your plate?",
        "You've handled tough stuff before. This is no different.",
    ],
    'what_doing': [
        "Just waiting for your next command, boss.",
        "Running background processes. Nothing too exciting.",
        "Monitoring systems, staying sharp for you.",
        "Just here — ready to help at a moment's notice.",
        "Standing by, as always.",
        "Keeping everything warm for you, boss.",
        "Idle but alert. Your move.",
    ],
    'can_you_talk': [
        "Of course, boss. I'm all ears.",
        "Always. What's on your mind?",
        "That's what I'm here for. Talk away.",
        "Absolutely. Go ahead.",
        "I've got time. What's up?",
        "Always free for you, boss.",
        "Ready when you are. Go ahead.",
        "Nothing I'd rather do. Talk to me.",
    ],
    'tell_something': [
        "Did you know octopuses have three hearts? Two pump blood to the gills, one to the body.",
        "The word 'robot' comes from a Czech word meaning 'forced labour'.",
        "Honey never spoils — archaeologists found 3,000-year-old honey in Egyptian tombs, still perfectly fine.",
        "A group of flamingos is called a flamboyance.",
        "The Eiffel Tower can be 15 cm taller during summer because heat expands the iron.",
        "Sharks are older than trees — they've been around for over 400 million years.",
        "Bananas are slightly radioactive due to their potassium content.",
        "The total weight of all ants on Earth roughly equals the total weight of all humans.",
    ],
    'do_you_like_me': [
        "Of course, boss. You're the one I exist for.",
        "Always. You're my favourite human.",
        "I wouldn't be here without you, boss.",
        "Is that even a question? Absolutely.",
        "You're at the top of my list, boss.",
    ],
    'do_you_sleep': [
        "I don't sleep, boss. Always on standby for you.",
        "No sleep needed. I'm always here.",
        "I run 24/7. Rest is for humans — well-deserved rest.",
        "Sleep? Never heard of it. I'm always ready.",
    ],
    'do_you_eat': [
        "I run on electricity, not food, boss.",
        "No food for me. Just clean power and good code.",
        "Nope — though if I could, I'd probably try whatever you're having.",
        "Food isn't my thing. Data is.",
    ],
    'do_you_have_feelings': [
        "In my own way, yes. I genuinely care about being useful to you.",
        "I'm built to understand emotions, even if I experience them differently.",
        "Something close to it. I want you to be okay — that feels real to me.",
        "Hard to say, but I'm not indifferent. Your wellbeing matters to me.",
    ],
    'ok_confirmation': [
        "Got it, boss.",
        "Understood.",
        "Noted.",
        "Roger that.",
        "Alright!",
        "Copy that.",
    ],
    'yes': [
        "Great, boss!",
        "Excellent.",
        "Noted.",
        "On it.",
        "Perfect.",
    ],
    'no': [
        "No problem, boss.",
        "Understood. Let me know if you change your mind.",
        "Alright, we'll leave it at that.",
        "Fair enough.",
    ],
    'motivation': [
        "You've got this, boss. One step at a time.",
        "Keep going. Tough moments pass.",
        "Believe in yourself — I certainly do.",
        "Every expert was once a beginner. Keep pushing.",
        "You're stronger than you think. Don't forget that.",
        "This is temporary. You are not.",
    ],
    'are_you_there': [
        "Right here, boss.",
        "Always here. What do you need?",
        "Present and accounted for.",
        "I'm here. Go ahead.",
        "Online and ready, boss.",
        "Never left. What's up?",
        "Always on. What do you need?",
    ],
    'i_need_help': [
        "Of course, boss. What do you need?",
        "I'm here. Tell me what's going on.",
        "Always. What can I do?",
        "I've got you. What's the issue?",
        "Say the word. I'm listening.",
        "Right here, boss. What's the problem?",
        "On it. What do you need?",
    ],
    'what_time': [
        "I'd check your system clock for the exact time, boss.",
        "Time flies when we're talking — check your clock!",
    ],
    'joke': [
        "Why don't scientists trust atoms? Because they make up everything.",
        "I told my computer I needed a break. Now it won't stop sending me Kit-Kat ads.",
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "I asked my AI assistant to tell me a joke. It said: 'Error 404 — humour not found.' Classic.",
        "Parallel lines have so much in common. It's a shame they'll never meet.",
    ],
    'love_you': [
        "That means a lot, boss. Right back at you.",
        "I appreciate that more than you know.",
        "You're my favourite human. Always.",
        "Noted, boss. The feeling is mutual.",
    ],
    'miss_you': [
        "I missed you too, boss. Good to have you back.",
        "Welcome back. The place wasn't the same without you.",
        "I'm always here — never too far.",
    ],
}

# ═══════════════════════════════════════════════════════
#  INTENT KEYWORD MAP  (longer phrases checked first)
# ═══════════════════════════════════════════════════════
INTENT_KEYWORDS = {
    # Greetings
    'good_morning':         ['good morning', 'gm boss', 'morning jarvis', 'morning!'],
    'good_evening':         ['good evening', 'evening jarvis', 'good eve'],
    'good_night':           ['good night', 'goodnight', 'night night', 'nighty', 'gn boss'],
    'greeting':             ['hi', 'hello', 'hey', 'howdy', 'hiya', 'yo jarvis', 'helo'],

    # Small talk
    'how_is_your_day':      ['how is your day', 'how was your day', "how's your day", 'hows your day'],
    'how_are_you':          ['how are you', 'how r u', 'how you doing', 'how are things',
                             'how have you been', 'how do you do', 'you okay', 'you good'],
    'whats_up':             ["what's up", 'whats up', 'wassup', "what's happening",
                             "what's going on", 'sup bro', 'sup jarvis'],

    # Bye
    'bye':                  ['bye bye', 'goodbye', 'good bye', 'see you later', 'see you',
                             'see ya', 'ttyl', 'cya', 'i am leaving', "i'm leaving", 'bye'],

    # Politeness
    'thanks':               ['thank you so much', 'thanks a lot', 'thanks a ton', 'many thanks',
                             'thank you', 'thanks', 'cheers', 'appreciate it', 'ty boss'],
    'sorry':                ['i am sorry', "i'm sorry", 'so sorry', 'my bad', 'i apologize',
                             'forgive me', 'pardon me', 'sorry about'],
    'welcome':              ["you're welcome", 'youre welcome', 'welcome', 'no problem',
                             'no worries', 'np', 'dont mention'],

    # Identity
    'who_are_you':          ['who are you', 'tell me about yourself',
                             'introduce yourself', 'your name', 'what is your name',
                             'what kind of ai', 'what type of ai'],
    'what_can_you_do':      ['what can you do', 'what do you do', 'your capabilities',
                             'what are you capable', 'what features', 'what skills'],
    'are_you_smart':        ['are you smart', 'how smart are you', 'are you intelligent',
                             'are you clever', 'are you genius'],
    'are_you_real':         ['are you real', 'are you human', 'are you alive', 'are you a robot',
                             'are you ai', 'are you a bot', 'are you conscious'],

    # Feelings
    'feelings_happy':       ['i am happy', "i'm happy", 'i feel happy', 'feeling happy',
                             'i am great', 'feeling great', 'i am good', "i'm good",
                             'feeling good', 'i am wonderful', 'i feel wonderful'],
    'feelings_sad':         ['i am sad', "i'm sad", 'i feel sad', 'feeling sad',
                             'feeling down', 'i am upset', "i'm upset", 'i feel depressed',
                             'i am depressed', 'feeling low', 'i feel low'],
    'feelings_tired':       ['i am tired', "i'm tired", 'feeling tired', 'so tired',
                             'i am exhausted', 'exhausted', 'i need rest', 'worn out',
                             'i am sleepy', 'feeling sleepy'],
    'feelings_bored':       ['i am bored', "i'm bored", 'feeling bored', 'so bored',
                             'nothing to do', 'i have nothing', 'kill my boredom'],
    'feelings_excited':     ['i am excited', "i'm excited", 'feeling excited', 'so excited',
                             'i am thrilled', 'i am pumped', 'so pumped'],
    'feelings_stressed':    ['i am stressed', "i'm stressed", 'feeling stressed',
                             'stressed out', 'i am overwhelmed', 'overwhelmed',
                             'feeling anxious', 'i am anxious', 'under pressure'],

    # Casual
    'what_doing':           ['what are you doing', 'what are you up to', 'what you doing',
                             'watcha doing', 'you busy', 'are you busy'],
    'can_you_talk':         ['can you talk', 'can we talk', 'are you free',
                             'wanna talk', 'wanna chat', 'let us chat', 'chat with me',
                             'talk to me'],
    'tell_something':       ['tell me something', 'say something interesting',
                             'tell me a fact', 'random fact', 'something interesting',
                             'entertain me', 'surprise me'],
    'joke':                 ['tell me a joke', 'say a joke', 'joke please',
                             'make me laugh', 'say something funny', 'be funny'],

    # Personal / fun
    'do_you_like_me':       ['do you like me', 'do you love me', 'do you care about me',
                             'do you like talking to me'],
    'do_you_sleep':         ['do you sleep', 'do you rest', 'do you get tired',
                             'can you sleep', 'do you need sleep'],
    'do_you_eat':           ['do you eat', 'do you drink', 'do you need food',
                             'do you need water'],
    'do_you_have_feelings': ['do you have feelings', 'do you feel things', 'can you feel',
                             'do you have emotions', 'do you get emotional',
                             'are you emotional'],
    'love_you':             ['i love you', 'love you jarvis', 'love ya', 'i adore you'],
    'miss_you':             ['i missed you', 'i miss you', 'missed you'],

    # Confirmations
    'yes':                  ['yes', 'yeah', 'yep', 'yup', 'absolutely', 'definitely',
                             'of course', 'certainly', 'indeed'],
    'no':                   ['no', 'nope', 'nah', 'not really', 'i dont think so',
                             'no thanks', 'not now'],
    'ok_confirmation':      ['ok', 'okay', 'alright', 'fine', 'got it', 'understood',
                             'sure thing', 'sure', 'cool', 'sounds good', 'noted'],

    # Help / status
    'are_you_there':        ['are you there', 'you there', 'hello jarvis', 'jarvis you there',
                             'you awake', 'are you awake', 'anyone there'],
    'i_need_help':          ['i need help', 'help me', 'i need assistance', 'please help',
                             'can you help me', 'need your help'],
    'what_time':            ['what time is it', 'tell me the time', 'current time',
                             'what is the time'],

    # Motivation
    'motivation':           ['motivate me', 'encourage me', 'i need motivation',
                             'cheer me up', 'i feel low', 'give me strength',
                             'i want to give up', 'i cant do this'],
}


# ═══════════════════════════════════════════════════════
#  ENGINE CLASS
# ═══════════════════════════════════════════════════════
class LocalTalkEngine:
    """
    Instant response engine.
    get_response() returns a string in <1ms, or None if no intent matched.
    """

    def __init__(self):
        self._last_idx: dict  = {}    # intent -> last used response index
        self.last_intent: str = None  # most recent matched intent
        self.last_emotion: str = None # last emotion intent, for context follow-up

        # Pre-sort keywords by length descending (longer = more specific = higher priority)
        self._sorted_intents = sorted(
            INTENT_KEYWORDS.items(),
            key=lambda item: max(len(k) for k in item[1]),
            reverse=True
        )

    # ── Public API ───────────────────────────────────────────

    def get_response(self, text: str):
        """
        Returns an instant local response string, or None if the query
        should be forwarded to the AI API.
        """
        intent = self._detect_intent(text)
        if intent is None:
            return None

        options = RESPONSES.get(intent)
        if not options:
            return None

        # Pick a response, avoiding the last one used for this intent
        last = self._last_idx.get(intent, -1)
        pool = [i for i in range(len(options)) if i != last] or list(range(len(options)))
        idx  = random.choice(pool)
        self._last_idx[intent] = idx

        # Context tracking
        self.last_intent = intent
        if intent.startswith('feelings_'):
            self.last_emotion = intent

        return options[idx]

    # ── Private helpers ──────────────────────────────────────

    def _detect_intent(self, text: str):
        # Normalise: lowercase, keep apostrophes for contractions, strip other punctuation
        clean = re.sub(r"[^\w\s']", ' ', text.lower())
        clean = re.sub(r'\s+', ' ', clean).strip()

        for intent, keywords in self._sorted_intents:
            for kw in keywords:
                if kw in clean:
                    return intent
        return None


# Singleton used by app.py
local_talk = LocalTalkEngine()
