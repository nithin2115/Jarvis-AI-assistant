# JARVIS Quick Start

## Prerequisites

1. **Python 3.10+**
2. **Ollama** - Download from https://ollama.ai

## Installation

```bash
# 1. Create virtual environment (recommended)
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Pull Ollama model
ollama pull mistral

# Or run the setup script
python setup.py
```

## Usage

```bash
# Start JARVIS with full UI and voice
python main.py

# Headless mode (no UI)
python main.py --headless

# No voice mode (text only)
python main.py --no-voice

# Debug mode
python main.py --debug

# Ingest documents for RAG
python main.py --ingest ./my_documents
```

## Voice Commands

Say "Hey Jarvis" followed by:
- "Open Chrome" - Launch applications
- "Set volume to 50%" - System controls
- "What's the weather?" - Weather info
- "What's the news?" - News headlines
- "Play music" - Spotify control
- "Search for Python courses" - Web search
- "Remember my password is xyz" - Store information
- "Create command study mode - open Spotify, VS Code, and Notion"

## Configuration

Set environment variables (optional):
```bash
# Windows
set NEWSAPI_KEY=your_key
set SPOTIFY_CLIENT_ID=your_id
set SPOTIFY_CLIENT_SECRET=your_secret

# macOS/Linux
export NEWSAPI_KEY=your_key
```

## Project Structure

```
jarvis/
├── main.py                 # Entry point
├── setup.py               # Setup script
├── requirements.txt       # Dependencies
├── config/               # Configuration
├── voice_engine/         # Speech recognition & TTS
├── ai_brain/            # LLM integration
├── task_executor/       # Command execution
├── memory_system/       # Vector DB & storage
├── automation/         # Browser automation
├── vision_module/       # Computer vision
├── integrations/       # APIs (weather, news, etc.)
├── ui_interface/       # PyQt5 interface
└── utils/              # Utilities
```

## Troubleshooting

**"Ollama not available"**
- Make sure Ollama is running: `ollama serve`
- Pull a model: `ollama pull mistral`

**"No module named X"**
- Reinstall dependencies: `pip install -r requirements.txt`

**"Microphone not working"**
- Check system microphone permissions
- Try: `pip install pyaudio --force-reinstall`

**"UI doesn't show up"**
- Ensure PyQt5 is installed: `pip install pyqt5`
- Try running with `--headless` for testing
