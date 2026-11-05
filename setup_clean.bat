@echo off
echo ========================================
echo   JARVIS Clean Setup - Windows
echo ========================================
echo.

REM Check if virtual environment exists
if exist venv (
    echo Removing existing virtual environment...
    rmdir /s /q venv
)

REM Create fresh virtual environment
echo Creating fresh virtual environment...
python -m venv venv

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies with specific order to avoid conflicts
echo.
echo Installing core dependencies first...
pip install langchain-core==0.1.45
pip install langsmith==0.1.38
pip install langchain==0.1.16
pip install langchain-community==0.0.32

echo.
echo Installing remaining dependencies...
pip install -r requirements.txt

REM Install Playwright browsers
echo.
echo Installing Playwright browsers...
playwright install chromium

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo To start JARVIS:
echo   1. Ensure Ollama is running: ollama serve
echo   2. Pull model: ollama pull mistral:7b-instruct-q4
echo   3. Run: python main.py
echo.
echo Activate environment anytime with:
echo   venv\Scripts\activate.bat
echo.

pause
