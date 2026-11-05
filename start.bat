@echo off
chcp 65001 >nul
title JARVIS AI Launcher
cls

echo ╔══════════════════════════════════════════════════════════╗
echo ║                    JARVIS AI SYSTEM                      ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)
echo [✓] Python detected

:: Check dependencies
echo [+] Checking dependencies...
python -c "import flask" 2>nul || (
    echo [+] Installing Flask...
    pip install flask flask-socketio requests pyttsx3 -q
)
echo [✓] Dependencies ready

:: Check Ollama
echo.
echo [+] Checking Ollama...
curl -s http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama not detected. Please run: ollama serve
    echo [!] Then pull model: ollama pull phi
    echo.
    choice /C YN /M "Continue anyway"
    if errorlevel 2 exit /b 1
)

echo.
echo [+] Starting JARVIS...
echo [+] Open browser at: http://localhost:5000
echo [+] Press Ctrl+C to stop
echo.

python app.py --port 5000

pause
