#!/usr/bin/env python3
"""
JARVIS Setup and Verification Script

This script helps with initial setup and dependency installation.
"""

import subprocess
import sys
import os
from pathlib import Path

def print_step(step: str):
    print(f"\n{'='*60}")
    print(f"  {step}")
    print(f"{'='*60}")

def check_python_version():
    """Check Python version"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("❌ Python 3.10+ required")
        return False
    print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
    return True

def install_dependencies():
    """Install Python dependencies"""
    print_step("Installing Dependencies")
    
    req_file = Path("requirements.txt")
    if not req_file.exists():
        print("❌ requirements.txt not found")
        return False
    
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✓ Dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def install_playwright_browsers():
    """Install Playwright browsers"""
    print_step("Installing Playwright Browsers")
    
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        print("✓ Playwright browsers installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠ Could not install Playwright browsers: {e}")
        print("  You can install manually: playwright install chromium")
        return False

def check_ollama():
    """Check if Ollama is installed and running"""
    print_step("Checking Ollama")
    
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✓ Ollama is running")
            if models:
                print(f"  Available models: {', '.join(m.get('name', 'unknown') for m in models[:5])}")
            else:
                print("  ⚠ No models found. Pull a model with: ollama pull mistral")
            return True
        else:
            print(f"⚠ Ollama returned status {response.status_code}")
            return False
    except requests.ConnectionError:
        print("❌ Ollama not running or not installed")
        print("   Download from: https://ollama.ai")
        print("   Then run: ollama pull mistral")
        return False
    except Exception as e:
        print(f"⚠ Could not check Ollama: {e}")
        return False

def create_directories():
    """Create necessary directories"""
    print_step("Creating Directories")
    
    dirs = [
        "data/memory",
        "data/documents",
        "data/logs",
        "data/custom_commands",
        "config/wake_word_models"
    ]
    
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {d}")
    
    return True

def test_imports():
    """Test that all modules can be imported"""
    print_step("Testing Module Imports")
    
    modules = [
        "config",
        "utils",
        "voice_engine",
        "ai_brain",
        "task_executor",
        "memory_system",
        "automation",
        "vision_module",
        "integrations",
        "ui_interface"
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except Exception as e:
            print(f"  ❌ {module}: {e}")
            all_ok = False
    
    return all_ok

def main():
    """Main setup function"""
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║                    J.A.R.V.I.S. Setup                        ║
    ║                                                              ║
    ║              Just A Rather Very Intelligent System           ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Create directories
    create_directories()
    
    # Install dependencies
    if input("\nInstall dependencies? (y/n): ").lower() == 'y':
        if not install_dependencies():
            print("\n⚠ Some dependencies failed to install")
    
    # Install Playwright browsers
    if input("\nInstall Playwright browsers? (y/n): ").lower() == 'y':
        install_playwright_browsers()
    
    # Check Ollama
    check_ollama()
    
    # Test imports
    print("\n")
    if input("Test module imports? (y/n): ").lower() == 'y':
        if test_imports():
            print("\n✓ All modules imported successfully!")
        else:
            print("\n⚠ Some modules had import issues")
    
    # Final instructions
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                     Setup Complete!                          ║
    ║                                                              ║
    ║  To start JARVIS:                                          ║
    ║    python main.py                                          ║
    ║                                                              ║
    ║  For help:                                                   ║
    ║    python main.py --help                                   ║
    ║                                                              ║
    ║  Required before first run:                                  ║
    ║    1. Install Ollama from https://ollama.ai                ║
    ║    2. Run: ollama pull mistral                             ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

if __name__ == "__main__":
    main()
