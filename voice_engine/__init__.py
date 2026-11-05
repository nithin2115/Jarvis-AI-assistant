"""Voice Engine - Speech-to-Text, Text-to-Speech, Wake Word Detection (Fixed)"""
import asyncio
import threading
import queue
import time
import speech_recognition as sr
import pyttsx3
import pyaudio
import numpy as np
from pathlib import Path
from typing import Callable, Optional, List
import logging
from dataclasses import dataclass
from enum import Enum

# Conditional import for Porcupine
try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False

from config.settings import voice_config, system_config, JARVIS_PERSONALITY
from utils.logger import get_logger

logger = get_logger("voice_engine")

class VoiceState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"

@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    format: int = None
    
    def __post_init__(self):
        if self.format is None:
            self.format = pyaudio.paInt16

class TextToSpeech:
    """TTS with pyttsx3 as primary (offline) engine"""
    
    def __init__(self, engine: str = "pyttsx3"):
        self.engine_name = engine
        self._speaking = False
        self._interrupt_event = threading.Event()
        self.tts_engine = None
        self._initialized = False
        
        # Initialize pyttsx3
        self._init_pyttsx3()
    
    def _init_pyttsx3(self):
        """Initialize pyttsx3 engine with error handling"""
        try:
            print("[JARVIS] TTS: Initializing pyttsx3 engine...")
            self.tts_engine = pyttsx3.init()
            voices = self.tts_engine.getProperty('voices')
            
            # Try to find a male voice
            for voice in voices:
                if 'male' in voice.name.lower() or 'guy' in voice.name.lower() or 'david' in voice.name.lower():
                    self.tts_engine.setProperty('voice', voice.id)
                    print(f"[JARVIS] TTS: Selected voice: {voice.name}")
                    break
            else:
                # Use default voice if no male voice found
                if voices:
                    self.tts_engine.setProperty('voice', voices[0].id)
                    print(f"[JARVIS] TTS: Using default voice: {voices[0].name}")
            
            self.tts_engine.setProperty('rate', voice_config.tts_rate)
            self.tts_engine.setProperty('volume', 1.0)
            self._initialized = True
            print("[JARVIS] TTS: pyttsx3 initialized successfully")
            
        except Exception as e:
            logger.error(f"TTS initialization error: {e}")
            print(f"[JARVIS] TTS ERROR: Failed to initialize pyttsx3: {e}")
            self._initialized = False
    
    async def speak(self, text: str, on_start: Optional[Callable] = None, 
                   on_end: Optional[Callable] = None) -> bool:
        """
        Speak text with interrupt support
        Returns True if completed, False if interrupted or failed
        """
        if not self._initialized:
            print("[JARVIS] TTS ERROR: TTS not initialized, cannot speak")
            return False
        
        if not text or not text.strip():
            print("[JARVIS] TTS: Empty text, skipping")
            return False
        
        # Clear any previous interrupt
        if self._interrupt_event.is_set():
            self._interrupt_event.clear()
        
        self._speaking = True
        
        if on_start:
            on_start()
        
        print(f"[JARVIS] TTS: Speaking started: '{text[:50]}...' " if len(text) > 50 else f"[JARVIS] TTS: Speaking started: '{text}'")
        
        try:
            result = await self._speak_pyttsx3(text)
            
            if on_end and not self._interrupt_event.is_set():
                on_end()
            
            success = not self._interrupt_event.is_set() and result
            if success:
                print("[JARVIS] TTS: Speaking finished successfully")
            else:
                print("[JARVIS] TTS: Speaking interrupted or failed")
            
            return success
            
        except Exception as e:
            logger.error(f"TTS speak error: {e}")
            print(f"[JARVIS] TTS ERROR: {e}")
            return False
        finally:
            self._speaking = False
    
    async def _speak_pyttsx3(self, text: str) -> bool:
        """pyttsx3 implementation with proper async handling"""
        def run_tts():
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
                return True
            except Exception as e:
                logger.error(f"pyttsx3 runtime error: {e}")
                print(f"[JARVIS] TTS ERROR during speech: {e}")
                return False
        
        # Run in executor to not block
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_tts)
        return result if result else False
    
    def interrupt(self):
        """Interrupt current speech"""
        print("[JARVIS] TTS: Interrupting speech")
        self._interrupt_event.set()
        self._speaking = False
        # Try to stop the engine
        if self.tts_engine and self._initialized:
            try:
                self.tts_engine.stop()
            except:
                pass
    
    def is_speaking(self) -> bool:
        return self._speaking

class WakeWordDetector:
    """Wake word detection with fallback to manual listening"""
    
    def __init__(self, wake_word: str = "jarvis"):
        self.wake_word = wake_word.lower()
        self.callbacks: List[Callable] = []
        self._running = False
        self._porcupine = None
        self._audio = None
        self._stream = None
        self._use_porcupine = False
        self._use_simple_detection = False
        
        # Check if we should use Porcupine
        self._try_init_porcupine()
    
    def _try_init_porcupine(self):
        """Try to initialize Porcupine, disable if key file not found"""
        if not PORCUPINE_AVAILABLE:
            print("[JARVIS] Wake Word: Porcupine not installed, using manual mode")
            return
        
        key_file = Path("config/porcupine_key.txt")
        if not key_file.exists():
            print(f"[JARVIS] Wake Word: Key file not found at {key_file}, disabling wake word system")
            print("[JARVIS] Wake Word: Use manual voice input instead")
            self._porcupine = None
            self._use_porcupine = False
            return
        
        try:
            access_key = key_file.read_text().strip()
            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=["jarvis"],  # Use built-in keyword
                model_path=None
            )
            self._use_porcupine = True
            print("[JARVIS] Wake Word: Porcupine initialized successfully")
            logger.info("Porcupine wake word engine initialized")
        except Exception as e:
            logger.warning(f"Could not initialize Porcupine: {e}")
            print(f"[JARVIS] Wake Word: Porcupine init failed: {e}")
            print("[JARVIS] Wake Word: Falling back to manual mode")
            self._porcupine = None
            self._use_porcupine = False
    
    def is_available(self) -> bool:
        """Check if wake word detection is available"""
        return self._use_porcupine or self._use_simple_detection
    
    def add_callback(self, callback: Callable):
        """Add callback for wake word detection"""
        self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """Remove callback"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def start(self):
        """Start wake word detection"""
        if self._running:
            return
        
        if not self._use_porcupine and not self._use_simple_detection:
            print("[JARVIS] Wake Word: No wake word detection available, manual mode only")
            return
        
        self._running = True
        self._detection_thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._detection_thread.start()
        logger.info("Wake word detection started")
        print("[JARVIS] Wake Word: Detection started")
    
    def stop(self):
        """Stop wake word detection"""
        self._running = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except:
                pass
        if self._audio:
            try:
                self._audio.terminate()
            except:
                pass
        logger.info("Wake word detection stopped")
        print("[JARVIS] Wake Word: Detection stopped")
    
    def _detection_loop(self):
        """Main detection loop"""
        if self._use_porcupine:
            self._porcupine_detection()
        elif self._use_simple_detection:
            self._simple_detection()
    
    def _porcupine_detection(self):
        """Porcupine-based detection"""
        try:
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                rate=self._porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self._porcupine.frame_length
            )
            
            print("[JARVIS] Wake Word: Porcupine listening...")
            
            while self._running:
                try:
                    pcm = self._stream.read(self._porcupine.frame_length, exception_on_overflow=False)
                    pcm = np.frombuffer(pcm, dtype=np.int16)
                    keyword_index = self._porcupine.process(pcm)
                    
                    if keyword_index >= 0:
                        print("[JARVIS] Wake Word: Detected!")
                        logger.info("Wake word detected!")
                        for callback in self.callbacks:
                            try:
                                callback()
                            except Exception as e:
                                logger.error(f"Wake word callback error: {e}")
                                
                except Exception as e:
                    logger.error(f"Detection error: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Porcupine detection failed: {e}")
            print(f"[JARVIS] Wake Word ERROR: {e}")
    
    def _simple_detection(self):
        """Simple audio-based detection (fallback) - uses keyword in speech"""
        recognizer = sr.Recognizer()
        
        print(f"[JARVIS] Wake Word: Simple detection listening for '{self.wake_word}'...")
        
        while self._running:
            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, phrase_time_limit=3)
                
                try:
                    text = recognizer.recognize_google(audio).lower()
                    if self.wake_word in text:
                        print(f"[JARVIS] Wake Word: Detected via speech: '{text}'")
                        logger.info(f"Wake word detected via fallback: {text}")
                        for callback in self.callbacks:
                            try:
                                callback()
                            except Exception as e:
                                logger.error(f"Wake word callback error: {e}")
                except sr.UnknownValueError:
                    pass
                except Exception as e:
                    logger.debug(f"Recognition error: {e}")
                    
            except Exception as e:
                logger.error(f"Simple detection error: {e}")
                time.sleep(1)

class SpeechToText:
    """Speech-to-text with error handling and initialization check"""
    
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = voice_config.energy_threshold
        self.recognizer.pause_threshold = voice_config.pause_threshold
        self.recognizer.phrase_threshold = voice_config.phrase_threshold
        self.microphone = None
        self._initialized = False
        
        # Try to initialize microphone
        self._init_microphone()
    
    def _init_microphone(self):
        """Initialize microphone with error handling"""
        try:
            print("[JARVIS] STT: Initializing microphone...")
            self.microphone = sr.Microphone()
            
            # Calibrate
            with self.microphone as source:
                print("[JARVIS] STT: Calibrating for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print(f"[JARVIS] STT: Energy threshold set to {self.recognizer.energy_threshold}")
            
            self._initialized = True
            print("[JARVIS] STT: Microphone initialized successfully")
            
        except Exception as e:
            logger.error(f"Microphone initialization error: {e}")
            print(f"[JARVIS] STT ERROR: Microphone not available: {e}")
            self._initialized = False
    
    def is_available(self) -> bool:
        """Check if microphone is available"""
        return self._initialized
    
    def listen(self, timeout: Optional[float] = None, 
               phrase_time_limit: Optional[float] = None) -> Optional[str]:
        """
        Listen and transcribe speech
        Returns transcribed text or None if failed
        """
        if not self._initialized:
            print("[JARVIS] STT ERROR: Microphone not initialized")
            return None
        
        try:
            print("[JARVIS] STT: Listening...")
            with self.microphone as source:
                audio = self.recognizer.listen(
                    source, 
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit
                )
            
            # Try multiple recognition services
            text = self._recognize(audio)
            if text:
                print(f"[JARVIS] STT: Recognized: '{text}'")
                logger.info(f"Recognized: {text}")
            else:
                print("[JARVIS] STT: Could not recognize speech")
            return text
            
        except sr.WaitTimeoutError:
            print("[JARVIS] STT: Listening timeout")
            return None
        except Exception as e:
            logger.error(f"STT error: {e}")
            print(f"[JARVIS] STT ERROR: {e}")
            return None
    
    def _recognize(self, audio: sr.AudioData) -> Optional[str]:
        """Try multiple recognition services"""
        # Try Google first (free, accurate)
        try:
            return self.recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            pass
        except Exception as e:
            logger.debug(f"Google recognition failed: {e}")
        
        return None
    
    def listen_continuous(self, callback: Callable[[str], None], 
                         interrupt_check: Callable[[], bool] = None):
        """Continuous listening in background"""
        if not self._initialized:
            print("[JARVIS] STT ERROR: Cannot start continuous listening - mic not available")
            return None
        
        def listen_loop():
            print("[JARVIS] STT: Continuous listening started")
            while True:
                if interrupt_check and interrupt_check():
                    break
                
                text = self.listen(timeout=1, phrase_time_limit=5)
                if text:
                    callback(text)
        
        thread = threading.Thread(target=listen_loop, daemon=True)
        thread.start()
        return thread

class VoiceEngine:
    """Main voice engine orchestrating STT, TTS, and wake word"""
    
    def __init__(self):
        print("[JARVIS] Voice Engine: Initializing...")
        
        # Initialize TTS with pyttsx3 (offline)
        self.tts = TextToSpeech(engine="pyttsx3")
        
        # Initialize STT
        self.stt = SpeechToText()
        
        # Initialize wake word detector (may be disabled if no key file)
        self.wake_detector = WakeWordDetector(voice_config.wake_word)
        
        self.state = VoiceState.IDLE
        self._on_state_change: Optional[Callable[[VoiceState], None]] = None
        self._on_command: Optional[Callable[[str], None]] = None
        self._manual_mode = not self.wake_detector.is_available()
        
        if self._manual_mode:
            print("[JARVIS] Voice Engine: Wake word disabled, using manual mode")
        
        # Setup wake word callback if available
        if self.wake_detector.is_available():
            self.wake_detector.add_callback(self._on_wake_word)
        
        print("[JARVIS] Voice Engine: Initialization complete")
    
    def is_available(self) -> bool:
        """Check if voice engine is functional"""
        return self.tts._initialized or self.stt.is_available()
    
    def set_state_callback(self, callback: Callable[[VoiceState], None]):
        """Set callback for state changes"""
        self._on_state_change = callback
    
    def set_command_callback(self, callback: Callable[[str], None]):
        """Set callback for voice commands"""
        self._on_command = callback
    
    def _set_state(self, state: VoiceState):
        """Update state and notify"""
        self.state = state
        if self._on_state_change:
            self._on_state_change(state)
        logger.info(f"Voice state: {state.value}")
        print(f"[JARVIS] Voice State: {state.value}")
    
    def _on_wake_word(self):
        """Handle wake word detection"""
        print("[JARVIS] Wake word triggered, listening for command...")
        self._set_state(VoiceState.LISTENING)
        
        # Listen for command
        text = self.stt.listen(timeout=5, phrase_time_limit=10)
        
        if text:
            self._set_state(VoiceState.PROCESSING)
            if self._on_command:
                self._on_command(text)
        else:
            self._set_state(VoiceState.IDLE)
    
    async def speak(self, text: str) -> bool:
        """Speak text with state management"""
        if not text or not text.strip():
            print("[JARVIS] Voice Engine: Empty text, not speaking")
            return False
        
        self._set_state(VoiceState.SPEAKING)
        
        try:
            completed = await self.tts.speak(
                text,
                on_start=None,
                on_end=lambda: self._set_state(VoiceState.IDLE)
            )
            return completed
        except Exception as e:
            logger.error(f"Speak error: {e}")
            print(f"[JARVIS] Voice Engine ERROR during speak: {e}")
            self._set_state(VoiceState.IDLE)
            return False
    
    def interrupt(self):
        """Interrupt current speech"""
        print("[JARVIS] Voice Engine: Interrupting")
        self.tts.interrupt()
        self._set_state(VoiceState.IDLE)
    
    def start(self):
        """Start voice engine"""
        print("[JARVIS] Voice Engine: Starting...")
        
        if self.wake_detector.is_available():
            self.wake_detector.start()
        else:
            print("[JARVIS] Voice Engine: Wake word not available, use manual listening")
        
        logger.info("Voice engine started")
        print("[JARVIS] Voice Engine: Started")
    
    def stop(self):
        """Stop voice engine"""
        print("[JARVIS] Voice Engine: Stopping...")
        self.interrupt()
        self.wake_detector.stop()
        logger.info("Voice engine stopped")
        print("[JARVIS] Voice Engine: Stopped")
    
    def listen_once(self, timeout: float = 10) -> Optional[str]:
        """Single listening session (manual mode)"""
        if not self.stt.is_available():
            print("[JARVIS] Voice Engine ERROR: Microphone not available")
            return None
        
        print("[JARVIS] Voice Engine: Manual listening...")
        self._set_state(VoiceState.LISTENING)
        text = self.stt.listen(timeout=timeout)
        self._set_state(VoiceState.IDLE if not text else VoiceState.PROCESSING)
        
        if text and self._on_command:
            self._on_command(text)
        
        return text
