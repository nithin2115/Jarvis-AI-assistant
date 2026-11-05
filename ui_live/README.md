# JARVIS Live UI

A futuristic, Iron Man-style Jarvis interface with a glowing AI brain animation and real-time state transitions.

## Features

- **Center AI Brain Animation**: Glowing circular core with smooth rotation
- **Animated Energy Lines**: Orbiting lines and pulsing waves around the brain
- **State Transitions**: 
  - Idle → slow rotation (blue)
  - Listening → glowing pulse (green)
  - Thinking → fast rotation (orange)
  - Speaking → wave expansion (purple)
- **Performance**: Lightweight CSS animations, no 3D engines
- **Real-time Communication**: WebSocket connection to Python backend
- **Voice Input**: Web Speech API support for voice commands
- **AI Integration**: Direct connection to Ollama (phi model)

## Architecture

```
Frontend (HTML/CSS/JS)  ←→  Backend (Flask + SocketIO)  ←→  Ollama AI
        ↑                           ↑
   index.html                 server.py
   - CSS animations           - WebSocket handlers
   - WebSocket client         - Ollama API integration
   - Voice recognition        - State management
```

## Quick Start

### 1. Install Dependencies

```bash
cd ui_live
pip install flask flask-socketio requests
```

### 2. Start Ollama (in separate terminal)

```bash
ollama serve
```

Make sure you have the phi model:
```bash
ollama pull phi
```

### 3. Start the Backend Server

```bash
python server.py
```

The server will start on `http://localhost:5000`

### 4. Open the UI

Open your browser and go to: `http://localhost:5000`

## How It Works

1. **Idle State**: The brain slowly rotates with a gentle cyan glow
2. **Listening State**: Click the mic button or start speaking - the brain pulses green
3. **Thinking State**: After you send a command, the brain rotates faster (orange) while AI processes
4. **Speaking State**: When AI responds, the brain turns purple with wave animations

## Commands

- **Text Input**: Type in the input box and press Enter or click the arrow button
- **Voice Input**: Click the microphone button and speak (requires browser support)

## Customization

### Change Colors

Edit the CSS gradients in `index.html`:

```css
/* Brain core colors */
.brain-core {
    background: radial-gradient(circle at 30% 30%, #00ffff, #0080ff, #001a33);
}

/* Listening - change to your preferred color */
.jarvis-container.listening .brain-core {
    background: radial-gradient(circle at 30% 30%, #00ff88, #00cc66, #003311);
}
```

### Change Animation Speed

Adjust the animation durations:

```css
/* Slow down rotation */
.outer-ring {
    animation: rotate 30s linear infinite; /* was 20s */
}

/* Speed up brain pulse */
.brain-core {
    animation: brainPulse 1s ease-in-out infinite; /* was 2s */
}
```

### Change AI Model

In `server.py`, change the default model:

```python
def ask_ollama(prompt: str, model: str = "llama2") -> str:  # change from "phi"
```

## Integration with Existing JARVIS

To connect this UI to your existing JARVIS system:

1. Copy the `ui_live` folder to your JARVIS project
2. Import and use the state management in your main code:

```python
from ui_live.server import state, socketio

# In your voice recognition callback:
state.set_state('listening')

# When AI starts processing:
state.set_state('thinking')

# When TTS starts speaking:
state.set_state('speaking')

# When done:
state.set_state('idle')
```

## API Endpoints

- `GET /` - Main UI page
- `GET /health` - Health check (returns Ollama status)
- `WS /ws` - WebSocket for real-time communication

## WebSocket Events

### Client → Server
- `command` - Send text command: `{text: "hello"}`
- `start_listening` - Start voice listening
- `stop_listening` - Stop voice listening

### Server → Client
- `state` - State change: `{state: "thinking"}`
- `response` - AI response text: `{text: "Hello!"}`
- `status` - Connection status: `{connected: true}`

## Performance Tips

- The UI uses CSS transforms and opacity for smooth 60fps animations
- No Canvas or WebGL - purely CSS-based for maximum compatibility
- Background grid uses low opacity to reduce GPU load
- Animations use `will-change` implicitly via transforms

## Browser Support

- Chrome/Edge: Full support (including Web Speech API)
- Firefox: Full support (may need permissions for mic)
- Safari: Full support (Web Speech API may vary)

## Troubleshooting

### "Disconnected" status
- Make sure `server.py` is running
- Check that port 5000 is not blocked by firewall
- Try refreshing the browser

### AI not responding
- Verify Ollama is running: `ollama serve`
- Check phi model is installed: `ollama list`
- Test Ollama directly: `ollama run phi`

### Microphone not working
- Ensure HTTPS or localhost (browsers block mic on HTTP)
- Grant microphone permissions in browser
- Check browser console for errors

## Credits

Built for JARVIS AI Assistant with performance and aesthetics in mind.
