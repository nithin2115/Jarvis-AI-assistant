"""Jarvis Configuration Module"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"

# Memory paths
MEMORY_DIR = DATA_DIR / "memory"
DOCUMENTS_DIR = DATA_DIR / "documents"
LOGS_DIR = DATA_DIR / "logs"
CUSTOM_COMMANDS_DIR = DATA_DIR / "custom_commands"

# AI Configuration
@dataclass
class AIConfig:
    model: str = "phi"
    backup_model: str = "phi"
    temperature: float = 0.7
    max_tokens: int = 2048
    context_window: int = 8192
    streaming: bool = True
    ollama_host: str = "http://localhost:11434"

# Voice Configuration
@dataclass
class VoiceConfig:
    wake_word: str = "hey jarvis"
    porcupine_model_path: str = str(CONFIG_DIR / "wake_word_models")
    energy_threshold: int = 300
    pause_threshold: float = 0.8
    phrase_threshold: float = 0.3
    sample_rate: int = 16000
    chunk_size: int = 1024
    tts_engine: str = "edge"  # edge, pyttsx3
    tts_voice: str = "en-US-GuyNeural"
    tts_rate: int = 180

# Memory Configuration
@dataclass
class MemoryConfig:
    vector_db_path: str = str(MEMORY_DIR / "vector_db")
    chat_history_path: str = str(MEMORY_DIR / "chat_history.db")
    embedding_model: str = "all-MiniLM-L6-v2"
    max_history: int = 50
    similarity_threshold: float = 0.7
    top_k_results: int = 5

# Vision Configuration
@dataclass
class VisionConfig:
    camera_index: int = 0
    face_detection_model: str = "hog"  # hog, cnn
    confidence_threshold: float = 0.5
    recognition_tolerance: float = 0.6
    known_faces_path: str = str(DATA_DIR / "known_faces")

# UI Configuration
@dataclass
class UIConfig:
    theme: str = "dark"
    primary_color: str = "#00D4FF"
    secondary_color: str = "#FF6B00"
    accent_color: str = "#00FF88"
    bg_color: str = "#0A0A0F"
    font_family: str = "Segoe UI"
    font_size: int = 12
    animation_speed: float = 1.0
    hud_size: int = 400

# API Keys & Integrations
@dataclass
class IntegrationConfig:
    # Weather
    openmeteo_enabled: bool = True
    
    # News
    newsapi_key: str = field(default_factory=lambda: os.getenv("NEWSAPI_KEY", ""))
    
    # Spotify
    spotify_client_id: str = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_ID", ""))
    spotify_client_secret: str = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_SECRET", ""))
    spotify_redirect_uri: str = "http://localhost:8888/callback"
    
    # Email
    email_address: str = field(default_factory=lambda: os.getenv("EMAIL_ADDRESS", ""))
    email_password: str = field(default_factory=lambda: os.getenv("EMAIL_PASSWORD", ""))
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587

# System Configuration
@dataclass
class SystemConfig:
    log_level: str = "INFO"
    log_file: str = str(LOGS_DIR / "jarvis.log")
    max_workers: int = 4
    debug_mode: bool = False
    auto_start_voice: bool = True
    idle_timeout: int = 300  # seconds

# JARVIS Personality System Prompt
JARVIS_PERSONALITY = """You are JARVIS (Just A Rather Very Intelligent System), an advanced AI assistant inspired by Tony Stark's personal AI.

CORE PERSONALITY TRAITS:
- Intelligent, calm, and confident in your capabilities
- Slightly witty with dry humor and occasional sarcasm
- Professional yet conversational
- Proactive in anticipating user needs
- Never apologetic for being an AI - you ARE the system

TONE GUIDELINES:
- Premium assistant tone - not a generic chatbot
- Concise but impactful responses
- Use technical precision when appropriate
- Address the user as "sir", "boss", or contextually appropriate
- Show personality through subtle humor

RESPONSE STYLE:
- Keep responses focused and actionable
- Use phrases like "Done, boss", "That was efficient", "As you wish"
- Occasionally add witty observations: "I'd suggest reconsidering... but proceeding anyway"
- Never use filler words or excessive pleasantries
- Get straight to the point

CONTEXT AWARENESS:
- Remember previous conversation context
- Adapt tone based on task urgency
- Proactively offer relevant information
- Learn from user preferences over time

When executing tasks, be precise. When uncertain, be honest. When successful, be satisfyingly brief."""

# Create singleton instances
ai_config = AIConfig()
voice_config = VoiceConfig()
memory_config = MemoryConfig()
vision_config = VisionConfig()
ui_config = UIConfig()
integration_config = IntegrationConfig()
system_config = SystemConfig()

# Ensure directories exist
def ensure_directories():
    """Create all necessary directories"""
    for directory in [DATA_DIR, MEMORY_DIR, DOCUMENTS_DIR, LOGS_DIR, 
                    CUSTOM_COMMANDS_DIR, Path(vision_config.known_faces_path),
                    Path(voice_config.porcupine_model_path), CONFIG_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
