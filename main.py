"""
Jarvis AI Assistant - Main Orchestrator

This is the central orchestration module that coordinates all components:
- Voice Engine (STT, TTS, Wake Word)
- AI Brain (LLM, Context, Intent Detection)
- Task Executor (System Commands, Apps, Files)
- Memory System (Vector DB, Chat History)
- RAG System (Document Processing)
- Automation (Browser Control)
- Vision Module (Face/Object Detection)
- Integrations (Weather, News, Spotify, Email)
- UI Interface (PyQt5 HUD)
- Custom Commands (Self-Learning)
"""

import asyncio
import threading
import signal
import sys
from typing import Optional, Dict, Any
from datetime import datetime

# Import all modules
from config.settings import (
    ensure_directories, system_config, voice_config, 
    ai_config, JARVIS_PERSONALITY
)
from utils.logger import setup_logging, get_logger
from utils.helpers import clean_text_for_speech
from utils.custom_commands import CustomCommandManager, CommandExecutor
from voice_engine import VoiceEngine, VoiceState
from ai_brain import AIBrain, AIResponse
from task_executor import TaskExecutor, CommandRouter
from memory_system import MemorySystem
from memory_system.rag_system import RAGSystem
from automation import BrowserAutomation
from vision_module import VisionModule
from integrations import IntegrationsManager
from ui_interface import UIInterface

# Setup logging first
setup_logging()
logger = get_logger("jarvis")

class JarvisOrchestrator:
    """
    Main JARVIS orchestrator - coordinates all subsystems
    """
    
    def __init__(self):
        # Ensure directories exist
        ensure_directories()
        
        # Initialize state
        self._running = False
        self._voice_enabled = system_config.auto_start_voice
        self._current_task: Optional[str] = None
        
        # Component references
        self.voice: Optional[VoiceEngine] = None
        self.brain: Optional[AIBrain] = None
        self.task_executor: Optional[TaskExecutor] = None
        self.memory: Optional[MemorySystem] = None
        self.rag: Optional[RAGSystem] = None
        self.automation: Optional[BrowserAutomation] = None
        self.vision: Optional[VisionModule] = None
        self.integrations: Optional[IntegrationsManager] = None
        self.ui: Optional[UIInterface] = None
        self.custom_commands: Optional[CustomCommandManager] = None
        self.command_executor: Optional[CommandExecutor] = None
        
        # Event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._executor_thread: Optional[threading.Thread] = None
        
        logger.info("JARVIS Orchestrator initialized")
    
    def initialize(self, headless: bool = False, no_voice: bool = False):
        """Initialize all components"""
        logger.info("Initializing JARVIS components...")
        
        # 1. Memory System (needed by others)
        logger.info("Memory System")
        self.memory = MemorySystem()
        
        # 2. RAG System
        logger.info("RAG System")
        self.rag = RAGSystem()
        
        # 3. AI Brain
        logger.info("AI Brain")
        self.brain = AIBrain()
        
        # 4. Task Executor
        logger.info("Task Executor")
        self.task_executor = TaskExecutor()
        
        # 5. Browser Automation
        logger.info("Browser Automation")
        self.automation = BrowserAutomation()
        self.task_executor.set_automation(self.automation)
        
        # 6. Integrations
        logger.info("Integrations")
        self.integrations = IntegrationsManager()
        
        # 7. Custom Commands
        logger.info("Custom Commands")
        self.custom_commands = CustomCommandManager()
        self.command_executor = CommandExecutor(self.task_executor, self.integrations)
        
        # 8. Vision Module
        logger.info("Vision Module")
        self.vision = VisionModule()
        
        # 10. UI - Initialize FIRST so it shows immediately
        if not headless:
            logger.info("UI Interface")
            self.ui = UIInterface()
            self.ui.set_command_handler(self._on_ui_command)
            self.ui.set_interrupt_handler(self._on_interrupt)
        
        # 9. Voice Engine - Initialize in background thread to prevent UI freeze
        if not no_voice:
            logger.info("Voice Engine (starting in background)")
            self._voice_enabled = system_config.auto_start_voice
            # Start voice init in background
            voice_thread = threading.Thread(target=self._init_voice_engine, daemon=True)
            voice_thread.start()
        
        # Check AI availability and update UI
        self._update_ai_status()
        
        # Start background status updater
        status_thread = threading.Thread(target=self._status_updater_loop, daemon=True)
        status_thread.start()
        
        logger.info("JARVIS initialization complete")
    
    def _check_ollama(self) -> bool:
        """Check if Ollama is running"""
        try:
            import requests
            res = requests.get("http://localhost:11434", timeout=5)
            return res.status_code == 200
        except:
            return False
    
    def _update_ai_status(self):
        """Update AI Brain status in UI"""
        if self.brain and self.brain.is_available():
            self._update_ui_status("AI Brain", "Active")
            print("[JARVIS] AI Brain status: Active")
            if self.ui:
                self.ui.add_message("system", "AI Brain connected")
        else:
            self._update_ui_status("AI Brain", "Offline")
            print("[JARVIS] AI Brain status: Offline")
            if self.ui:
                self.ui.add_message("system", "AI Brain offline - checking Ollama...")
    
    def _status_updater_loop(self):
        """Background thread to periodically update status"""
        import time
        time.sleep(3)  # Wait for systems to initialize
        
        # Check and update AI status
        if self._check_ollama():
            print("[JARVIS] Ollama detected, updating AI Brain status")
            self._update_ui_status("AI Brain", "Active")
            if self.ui:
                self.ui.add_message("system", "AI Brain is now Active")
        
        # Check voice status
        if self.voice and self.voice.is_available():
            print("[JARVIS] Voice engine detected, updating status")
            self._update_ui_status("Voice Engine", "Standby")
    
    def _init_voice_engine(self):
        """Initialize voice engine in background thread"""
        import time
        try:
            print("[JARVIS] Initializing voice engine in background...")
            self.voice = VoiceEngine()
            self.voice.set_state_callback(self._on_voice_state_change)
            self.voice.set_command_callback(self._on_voice_command)
            
            # Update UI status
            if self.ui:
                self.ui.add_message("system", "Voice engine ready")
                self._update_ui_status("Voice Engine", "Standby")
            
            print("[JARVIS] Voice engine initialized successfully")
            print("[JARVIS] Voice Engine status updated to: Standby")
            
            # Auto-start if enabled
            if self._voice_enabled:
                time.sleep(0.5)  # Brief delay
                self.voice.start()
                self._update_ui_status("Voice Engine", "Active")
                print("[JARVIS] Voice Engine status updated to: Active")
                
        except Exception as e:
            logger.error(f"Voice engine initialization failed: {e}")
            print(f"[JARVIS] Voice engine failed: {e}")
            if self.ui:
                self.ui.add_message("system", f"Voice unavailable: {e}")
    
    async def start(self):
        """Start JARVIS"""
        self._running = True
        
        # Start async executor
        self._loop = asyncio.get_event_loop()
        
        # Initialize UI FIRST (so window shows immediately)
        if self.ui:
            self.ui.initialize()
            self.ui.show()
        
        # Wait briefly for background systems
        import time
        time.sleep(1)
        
        # Check Ollama and update status
        if self._check_ollama():
            self._update_ui_status("AI Brain", "Active")
            print("[JARVIS] AI Brain status updated to: Active")
        
        # Welcome message (text only if voice not ready yet)
        if self.voice and self.voice.is_available():
            await self._speak("JARVIS online. Ready for your commands, boss.")
        else:
            if self.ui:
                self.ui.add_message("system", "JARVIS online. Ready for your commands.")
        
        # Main loop
        if self.ui:
            self.ui.run()
        else:
            # Headless mode - keep running
            while self._running:
                await asyncio.sleep(1)
    
    def stop(self):
        """Stop JARVIS"""
        logger.info("Shutting down JARVIS...")
        self._running = False
        
        if self.voice:
            self.voice.stop()
        
        if self.vision:
            self.vision.stop_camera()
        
        if self.automation:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.automation.close())
            except RuntimeError:
                # No event loop running, skip async cleanup
                pass
        
        if self.memory:
            self.memory.close()
        
        if self.ui:
            self.ui.close()
        
        logger.info("JARVIS shutdown complete")
    
    # ===== Event Handlers =====
    
    def _on_voice_state_change(self, state: VoiceState):
        """Handle voice state changes"""
        if self.ui:
            self.ui.set_voice_state(state.value)
        
        # Update status panel based on voice state
        if state.value == "speaking":
            self._update_ui_status("Voice Engine", "Speaking")
        elif state.value == "listening":
            self._update_ui_status("Voice Engine", "Listening")
        elif state.value == "processing":
            self._update_ui_status("AI Brain", "Processing")
        elif state.value == "idle":
            if self.voice and self.voice.is_available():
                self._update_ui_status("Voice Engine", "Standby")
            if self.brain and self.brain.is_available():
                self._update_ui_status("AI Brain", "Active")
        
        logger.debug(f"Voice state: {state.value}")
    
    def _on_voice_command(self, text: str):
        """Handle voice command"""
        self._process_input(text, source="voice")
    
    def _on_ui_command(self, text: str):
        """Handle UI text command"""
        if text == "__WAKE__":
            # Voice wake button pressed
            if self.voice and self.voice.is_available():
                text = self.voice.listen_once()
                if text:
                    self._process_input(text, source="voice")
            else:
                if self.ui:
                    self.ui.add_message("system", "Voice not available - type your command instead")
        else:
            self._process_input(text, source="ui")
    
    def _on_interrupt(self):
        """Handle interrupt request"""
        if self.voice:
            self.voice.interrupt()
        
        if self.ui:
            self.ui.add_message("system", "Interrupted")
        
        logger.info("Command interrupted")
    
    # ===== Core Processing =====
    
    def _process_input(self, text: str, source: str = "ui"):
        """Process user input"""
        # Update UI
        if self.ui:
            self.ui.add_message("user", text)
        
        # Log
        logger.info(f"Input [{source}]: {text}")
        
        # Run async processing
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._process_input_async(text, source),
                self._loop
            )
    
    async def _process_input_async(self, text: str, source: str):
        """Async input processing"""
        try:
            # Check for custom commands first
            custom_cmd = self.custom_commands.find_matching_command(text)
            if custom_cmd:
                await self._execute_custom_command(custom_cmd)
                return
            
            # Get relevant context from memory
            context = self._build_context(text)
            
            # Process with AI Brain
            response = await self.brain.process_input(text, context)
            
            # Check for actions in response
            if response.actions:
                await self._execute_ai_actions(response.actions)
            
            # Check for integration intents
            intent = self.brain.intent_detector.detect(text)
            if intent["primary_intent"] in ["weather", "news", "music", "email"]:
                integration_result = await self.integrations.handle_command(
                    text, intent["primary_intent"], intent
                )
                if integration_result.get("success"):
                    response.text = integration_result.get("message", response.text)
            
            # Handle browser/search intents
            if intent["primary_intent"] in ["search", "browser"]:
                if self.automation:
                    # Initialize browser if needed
                    if not self.automation._initialized:
                        await self.automation.initialize()
                    
                    search_result = await self.automation.find_and_open(text)
                    if search_result.get("success"):
                        response.text += f"\n\n{search_result.get('message', '')}"
            
            # Store interaction
            self.memory.add_interaction(text, response.text, {
                "source": source,
                "intent": intent["primary_intent"],
                "emotion": response.emotion
            })
            
            # Output response
            await self._output_response(response, source)
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            await self._speak("I'm experiencing a temporary malfunction. Please try again.")
    
    def _build_context(self, query: str) -> Dict:
        """Build context for AI processing"""
        context = {}
        
        # Get relevant memories
        if self.memory:
            memory_context = self.memory.get_relevant_context(query)
            if memory_context:
                context["memory_context"] = memory_context
        
        # Get RAG context if documents available
        if self.rag and self.rag.get_document_list():
            rag_result = self.rag.query(query, top_k=3)
            if rag_result.get("success") and rag_result.get("answer_context"):
                context["rag_context"] = rag_result["answer_context"]
        
        # Get vision context if available
        if self.vision:
            scene_info = self.vision.get_last_scene_info()
            if scene_info:
                context["vision_context"] = f"Visual scene: {scene_info.description}"
        
        return context
    
    async def _execute_custom_command(self, command):
        """Execute a custom command"""
        logger.info(f"Executing custom command: {command.name}")
        
        # Record usage
        self.custom_commands.record_usage(command.id)
        
        # Execute
        results = await self.command_executor.execute_command(command)
        
        # Report results
        success_count = sum(1 for r in results if r.get("success"))
        total = len(results)
        
        message = f"Custom command '{command.name}' executed. {success_count}/{total} actions completed."
        
        if self.ui:
            self.ui.add_message("jarvis", message, "satisfied")
        
        await self._speak(message)
    
    async def _execute_ai_actions(self, actions: list):
        """Execute actions from AI response"""
        for action in actions:
            action_type = action.get("type")
            
            if action_type == "command":
                cmd = action.get("command")
                await self.task_executor.execute_task(cmd)
            
            elif action_type == "search":
                query = action.get("query")
                if self.automation:
                    await self.automation.search(query)
            
            elif action_type == "open_url":
                url = action.get("url")
                if self.automation:
                    await self.automation.navigate(url)
            
            elif action_type == "vision_scan":
                if self.vision:
                    scene = self.vision.get_last_scene_info()
                    if scene:
                        return scene.description
    
    async def _output_response(self, response: AIResponse, source: str):
        """Output AI response through appropriate channels"""
        # Update UI
        if self.ui:
            self.ui.add_message("jarvis", response.text, response.emotion)
        
        # Speak if voice-enabled and source is voice
        if source == "voice" or self._voice_enabled:
            await self._speak(response.text)
    
    async def _speak(self, text: str):
        """Speak text using TTS"""
        if self.voice and self.voice.is_available():
            # Clean text for speech
            clean_text = clean_text_for_speech(text)
            await self.voice.speak(clean_text)
    
    def _update_ui_status(self, component: str, status: str):
        """Update UI status"""
        if self.ui:
            self.ui.update_status(component, status)
    
    # ===== Public API =====
    
    def ingest_documents(self, directory: str) -> Dict:
        """Ingest documents for RAG"""
        if self.rag:
            return self.rag.ingest_directory(directory)
        return {"success": [], "failed": []}
    
    def create_custom_command(self, definition: str) -> bool:
        """Create a new custom command"""
        if self.custom_commands:
            cmd = self.custom_commands.create_command(definition)
            return cmd is not None
        return False
    
    def register_face(self, name: str) -> bool:
        """Register a face"""
        if self.vision:
            return self.vision.register_new_face(name)
        return False

# ===== Main Entry Point =====

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="JARVIS AI Assistant")
    parser.add_argument("--headless", action="store_true", help="Run without UI")
    parser.add_argument("--no-voice", action="store_true", help="Disable voice")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--ingest", type=str, help="Ingest documents from directory")
    
    args = parser.parse_args()
    
    # Handle document ingestion
    if args.ingest:
        ensure_directories()
        setup_logging()
        rag = RAGSystem()
        result = rag.ingest_directory(args.ingest)
        print(f"Ingestion complete: {len(result['success'])} success, {len(result['failed'])} failed")
        return
    
    # Create orchestrator
    jarvis = JarvisOrchestrator()
    
    # Initialize
    try:
        jarvis.initialize(
            headless=args.headless,
            no_voice=args.no_voice
        )
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        sys.exit(1)
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        print("\nShutting down JARVIS...")
        jarvis.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start
    try:
        if sys.platform == "win32":
            # Windows requires specific asyncio setup
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        asyncio.run(jarvis.start())
    except KeyboardInterrupt:
        jarvis.stop()
    except Exception as e:
        logger.error(f"Runtime error: {e}")
        jarvis.stop()
        raise

if __name__ == "__main__":
    main()
