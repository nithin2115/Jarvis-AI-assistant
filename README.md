# Jarvis AI Assistant

A production-level personal AI assistant inspired by Tony Stark's JARVIS from Iron Man.

## Features

- **Voice Interaction**: Real-time speech-to-text, natural text-to-speech, wake word detection
- **AI Brain**: Local LLM via Ollama with JARVIS personality
- **Task Execution**: Smart command routing, app control, system operations
- **Multi-step Planning**: Agent-like behavior for complex tasks
- **Browser Automation**: Playwright-powered web navigation and data extraction
- **Memory System**: Vector database for semantic memory and conversation history
- **RAG System**: Document processing and context-aware answering
- **Vision Module**: Face detection, object recognition, scene understanding
- **Futuristic UI**: PyQt5-based HUD with animations and voice waveforms
- **Integrations**: Weather, news, Spotify, email automation
- **Self-learning**: Custom command definitions and execution

## Prerequisites

1. **Python 3.10+**
2. **Ollama** - Install from https://ollama.ai and pull a model:
   ```bash
   ollama pull mistral
   ```
3. **Porcupine Access Key** - Get free key from https://console.picovoice.ai

## Installation

```bash
# Clone or navigate to the project directory
cd C:\Users\Windows\Desktop\jarvis

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set environment variables (optional)
set PICOVOICE_ACCESS_KEY=your_key_here
set NEWSAPI_KEY=your_key_here
set SPOTIFY_CLIENT_ID=your_id
set SPOTIFY_CLIENT_SECRET=your_secret
set EMAIL_ADDRESS=your_email
set EMAIL_PASSWORD=your_app_password
```

## Usage

```bash
# Start Jarvis
python main.py

# With specific options
python main.py --no-voice --debug
```

## Commands

Say "Hey Jarvis" followed by:
- "Open Chrome" - Launch applications
- "Set volume to 50%" - System controls
- "Find Python courses online" - Web search and automation
- "What's the weather?" - Weather information
- "Play my focus playlist on Spotify" - Media control
- "Remember my GitHub token is xyz" - Store information
- "When I say 'work mode', open VS Code, Chrome, and Spotify" - Custom commands

## Architecture

```
jarvis/
├── ai_brain/          # LLM integration and personality
├── automation/        # Browser and system automation
├── config/           # Configuration settings
├── data/             # Memory, documents, logs
├── integrations/     # Third-party API integrations
├── memory_system/    # Vector DB and conversation memory
├── task_executor/    # Command routing and execution
├── ui_interface/     # PyQt5 futuristic HUD
├── utils/            # Shared utilities
├── vision_module/    # Computer vision capabilities
├── voice_engine/     # STT, TTS, wake word detection
└── main.py          # Entry point
```

## License

MIT License - For personal use and experimentation.
