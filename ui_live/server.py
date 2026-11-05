"""
JARVIS Live UI Backend
Flask + WebSocket server for real-time communication with the frontend
"""

from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit
import asyncio
import threading
import requests
import json
import os
import sys
from typing import Optional

# Add parent directory to path to import existing JARVIS modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'jarvis-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
class JarvisState:
    def __init__(self):
        self.current_state = "idle"
        self.is_listening = False
        self.is_speaking = False
        self.ollama_available = False
        self.last_response = ""
        
    def set_state(self, state: str):
        """Set JARVIS state and notify all clients"""
        self.current_state = state
        socketio.emit('state', {'state': state})
        print(f"[JARVIS] State changed to: {state}")
        
    def send_response(self, text: str):
        """Send AI response to all clients"""
        self.last_response = text
        socketio.emit('response', {'text': text})
        print(f"[JARVIS] Response sent: {text[:100]}...")

state = JarvisState()

# ===== Ollama Integration =====

def check_ollama() -> bool:
    """Check if Ollama is running"""
    try:
        res = requests.get("http://localhost:11434", timeout=5)
        return res.status_code == 200
    except:
        return False

def ask_ollama(prompt: str, model: str = "phi") -> str:
    """Send prompt to Ollama and get response"""
    try:
        res = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=60
        )
        
        if res.status_code == 200:
            return res.json().get("response", "No response from AI")
        else:
            return f"Error: Ollama returned status {res.status_code}"
            
    except requests.exceptions.Timeout:
        return "AI is taking too long to respond. Please try again."
    except Exception as e:
        return f"Error communicating with AI: {str(e)}"

# ===== WebSocket Event Handlers =====

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f"[JARVIS] Client connected: {request.sid if 'request' in globals() else 'unknown'}")
    
    # Send current state to new client
    emit('state', {'state': state.current_state})
    emit('status', {'connected': True})
    
    # Check Ollama status
    state.ollama_available = check_ollama()
    if state.ollama_available:
        emit('response', {'text': 'JARVIS online. Ready for your commands.'})
    else:
        emit('response', {'text': 'JARVIS online. AI Brain offline - please start Ollama.'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"[JARVIS] Client disconnected")

@socketio.on('command')
def handle_command(data):
    """Handle text command from client"""
    text = data.get('text', '').strip()
    if not text:
        return
    
    print(f"[JARVIS] Command received: {text}")
    
    # Set thinking state
    state.set_state('thinking')
    
    # Process in background thread to not block WebSocket
    def process_command():
        # Check Ollama
        if not check_ollama():
            state.set_state('speaking')
            state.send_response("AI Brain is offline. Please start Ollama with: ollama serve")
            socketio.sleep(0.5)
            state.set_state('idle')
            return
        
        # Get AI response
        response = ask_ollama(text)
        
        # Set speaking state and send response
        state.set_state('speaking')
        state.send_response(response)
        
        # Simulate speaking duration (adjust based on TTS)
        word_count = len(response.split())
        speak_duration = min(max(word_count * 0.3, 2), 10)  # 0.3s per word, min 2s, max 10s
        socketio.sleep(speak_duration)
        
        # Return to idle
        state.set_state('idle')
    
    socketio.start_background_task(process_command)

@socketio.on('start_listening')
def handle_start_listening():
    """Handle start listening event"""
    print("[JARVIS] Started listening")
    state.is_listening = True
    state.set_state('listening')

@socketio.on('stop_listening')
def handle_stop_listening():
    """Handle stop listening event"""
    print("[JARVIS] Stopped listening")
    state.is_listening = False
    if state.current_state == 'listening':
        state.set_state('idle')

@socketio.on('state_change')
def handle_state_change(data):
    """Handle state change from client (for sync)"""
    new_state = data.get('state', 'idle')
    state.current_state = new_state
    print(f"[JARVIS] State synced to: {new_state}")

# ===== Flask Routes =====

@app.route('/')
def index():
    """Serve the main UI"""
    return send_from_directory('.', 'index.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    return {
        'status': 'ok',
        'ollama': check_ollama(),
        'state': state.current_state
    }

# ===== Background Tasks =====

def status_monitor():
    """Monitor system status in background"""
    while True:
        socketio.sleep(5)  # Use socketio.sleep for background tasks
        
        # Check Ollama status
        was_available = state.ollama_available
        state.ollama_available = check_ollama()
        
        if state.ollama_available and not was_available:
            print("[JARVIS] Ollama is now available")
            socketio.emit('response', {'text': 'AI Brain is now online.'})
        elif not state.ollama_available and was_available:
            print("[JARVIS] Ollama is now offline")
            socketio.emit('response', {'text': 'AI Brain is offline.'})

# ===== Main Entry Point =====

def run_server(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask-SocketIO server"""
    print(f"""
╔══════════════════════════════════════════════════════════╗
║                    JARVIS LIVE UI                        ║
╠══════════════════════════════════════════════════════════╣
║  Server: http://{host}:{port:<4}                         ║
║  WebSocket: ws://{host}:{port}/ws                        ║
╠══════════════════════════════════════════════════════════╣
║  Commands:                                               ║
║    - Open browser at http://localhost:{port}             ║
║    - Ensure Ollama is running: ollama serve             ║
║    - Pull model: ollama pull phi                         ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # Start status monitor
    socketio.start_background_task(status_monitor)
    
    # Run server
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='JARVIS Live UI Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    run_server(host=args.host, port=args.port, debug=args.debug)
