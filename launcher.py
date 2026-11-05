"""
JARVIS Desktop Launcher
Opens the Flask app in a native fullscreen window via pywebview.
Run this instead of app.py for the desktop experience.
"""
import threading
import time
import sys
import os

def start_flask():
    """Start Flask server in background thread"""
    from app import run_server
    run_server(host="127.0.0.1", port=5000, debug=False)

def main():
    try:
        import webview
    except ImportError:
        print("[LAUNCHER] pywebview not installed. Run: pip install pywebview")
        print("[LAUNCHER] Falling back to browser mode...")
        import webbrowser
        t = threading.Thread(target=start_flask, daemon=True)
        t.start()
        time.sleep(2)
        webbrowser.open("http://localhost:5000")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    # Start Flask in background
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Wait for Flask to be ready
    import urllib.request
    for _ in range(20):
        try:
            urllib.request.urlopen("http://127.0.0.1:5000/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # Launch native window
    window = webview.create_window(
        title="JARVIS Neural AI",
        url="http://127.0.0.1:5000",
        width=1280,
        height=800,
        fullscreen=False,          # Set True for full immersive mode
        resizable=True,
        frameless=False,
        on_top=False,
        background_color="#020408",
    )
    webview.start(debug=False)

if __name__ == "__main__":
    main()
