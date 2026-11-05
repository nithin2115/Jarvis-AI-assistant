"""AI Brain - LLM Integration using Ollama with requests"""
import json
import re
import requests
from typing import List, Dict, Optional, AsyncGenerator, Any
from dataclasses import dataclass
from datetime import datetime
import asyncio

from config.settings import ai_config, JARVIS_PERSONALITY, system_config
from utils.logger import get_logger

logger = get_logger("ai_brain")


# Global ask_ai function for Ollama integration
def ask_ai(prompt: str, model: str = "phi") -> str:
    """
    Send prompt to Ollama API and return response.
    Uses phi model by default for low RAM usage.
    """
    try:
        response = requests.post(
            f"{ai_config.ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json().get("response", "No response from AI")
        else:
            return f"Error: Ollama returned status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return "AI Brain is offline or Ollama is not running"
    except Exception as e:
        return f"AI error: {str(e)}"


def check_ollama_available() -> bool:
    """Check if Ollama server is running and phi model is available."""
    try:
        response = requests.get(f"{ai_config.ollama_host}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            for m in models:
                if m.get("name") == "phi" or m.get("name", "").startswith("phi"):
                    return True
        return False
    except:
        return False

@dataclass
class Thought:
    """Represents a structured thought/plan"""
    type: str  # "analysis", "plan", "action", "observation"
    content: str
    confidence: float = 1.0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class AIResponse:
    """Structured AI response"""
    text: str
    thoughts: List[Thought] = None
    actions: List[Dict] = None
    requires_confirmation: bool = False
    emotion: str = "neutral"
    
    def __post_init__(self):
        if self.thoughts is None:
            self.thoughts = []
        if self.actions is None:
            self.actions = []

class IntentDetector:
    """Detect user intent from text"""
    
    INTENTS = {
        "search": ["search", "find", "look up", "google", "lookup"],
        "open_app": ["open", "launch", "start", "run"],
        "close_app": ["close", "exit", "quit", "kill"],
        "system_control": ["volume", "brightness", "mute", "shutdown", "restart"],
        "file_operation": ["create", "delete", "move", "copy", "rename", "file"],
        "weather": ["weather", "temperature", "forecast"],
        "news": ["news", "headlines", "what's happening"],
        "music": ["play", "music", "song", "spotify", "pause", "skip"],
        "reminder": ["remind", "remember", "note", "save"],
        "custom": ["study mode", "work mode", "gaming mode"],
        "conversation": ["chat", "talk", "tell me", "explain"],
        "browser": ["browse", "website", "url", "navigate"],
        "vision": ["see", "look", "camera", "face", "scan"],
    }
    
    def detect(self, text: str) -> Dict[str, Any]:
        """Detect intent and return structured result"""
        text_lower = text.lower()
        
        detected = []
        for intent, keywords in self.INTENTS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected.append({
                        "intent": intent,
                        "confidence": 0.9,
                        "matched_keyword": keyword
                    })
                    break
        
        # Sort by confidence and return best match
        if detected:
            detected.sort(key=lambda x: x["confidence"], reverse=True)
            return {
                "primary_intent": detected[0]["intent"],
                "confidence": detected[0]["confidence"],
                "all_intents": detected,
                "requires_complex_processing": detected[0]["intent"] in 
                    ["search", "browser", "custom", "file_operation"]
            }
        
        return {
            "primary_intent": "conversation",
            "confidence": 0.5,
            "all_intents": [],
            "requires_complex_processing": False
        }

class TaskPlanner:
    """Break complex tasks into executable steps"""
    
    async def plan(self, task: str, context: Dict) -> List[Dict]:
        """
        Create execution plan for complex task
        Returns list of steps with actions
        """
        planning_prompt = f"""You are JARVIS task planner. Break down the following task into clear, executable steps.

Task: {task}
Context: {json.dumps(context, indent=2)}

Create a JSON array of steps. Each step should have:
- "action": The action type (search, open_browser, extract_data, click, type, etc.)
- "target": What to act on
- "description": Human-readable description
- "expected_outcome": What should happen

Respond ONLY with valid JSON array, no other text."""

        try:
            response = ask_ai(planning_prompt)
            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                steps = json.loads(json_match.group())
                return steps
        except Exception as e:
            logger.error(f"Task planning failed: {e}")
        
        # Fallback: simple single-step plan
        return [{
            "action": "execute",
            "target": task,
            "description": f"Execute: {task}",
            "expected_outcome": "Task completed"
        }]

class ContextManager:
    """Manage conversation context and memory"""
    
    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.conversation_history: List[Dict] = []
        self.system_context: Dict = {
            "user_preferences": {},
            "session_start": datetime.now().isoformat(),
            "current_location": None,
            "active_applications": [],
            "current_task": None
        }
    
    def add_message(self, role: str, content: str, metadata: Dict = None):
        """Add message to history"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.conversation_history.append(message)
        
        # Trim history
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]
    
    def get_context_window(self, n: int = 10) -> str:
        """Get last n messages formatted for context"""
        recent = self.conversation_history[-n:]
        formatted = []
        for msg in recent:
            role_label = "User" if msg["role"] == "user" else "JARVIS"
            formatted.append(f"{role_label}: {msg['content']}")
        return "\n".join(formatted)
    
    def update_system_context(self, key: str, value: Any):
        """Update system context"""
        self.system_context[key] = value
    
    def get_full_context(self) -> str:
        """Get full context for prompt"""
        context_parts = [
            f"Session started: {self.system_context['session_start']}",
            f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        
        if self.system_context.get('current_task'):
            context_parts.append(f"Current task: {self.system_context['current_task']}")
        
        if self.system_context.get('active_applications'):
            context_parts.append(f"Active apps: {', '.join(self.system_context['active_applications'])}")
        
        return "\n".join(context_parts)

class AIBrain:
    """Main AI Brain orchestrating all components"""
    
    def __init__(self):
        self.model = ai_config.model  # "phi"
        self.temperature = ai_config.temperature
        self.max_tokens = ai_config.max_tokens
        
        self.intent_detector = IntentDetector()
        self.context_manager = ContextManager()
        self.task_planner = TaskPlanner()
        
        self._available = False
        self._check_availability()
    
    def _check_availability(self):
        """Check if Ollama is available"""
        self._available = check_ollama_available()
        if self._available:
            print(f"[JARVIS] AI Brain online. Model: {self.model}")
            logger.info(f"Ollama available. Using model: {self.model}")
        else:
            print("[JARVIS] AI Brain Offline - Ollama not running or phi model not installed")
            print("[JARVIS] Run: ollama pull phi")
            logger.warning("Ollama not available or phi model missing")
    
    def is_available(self) -> bool:
        return self._available
    
    def refresh_availability(self):
        """Re-check if Ollama is available"""
        self._check_availability()
        return self._available
    
    async def generate(self, prompt: str, system_prompt: str = None, 
                      stream: bool = True, context: Dict = None) -> AIResponse:
        """
        Generate AI response with full context
        """
        if not self._available:
            return AIResponse(
                text="I'm currently offline. Please ensure Ollama is running with the phi model.",
                emotion="concerned"
            )
        
        # Build system prompt
        if system_prompt is None:
            system_prompt = JARVIS_PERSONALITY
        
        # Add context
        full_prompt = f"""{system_prompt}

CURRENT CONTEXT:
{self.context_manager.get_full_context()}

CONVERSATION HISTORY:
{self.context_manager.get_context_window(5)}

{context.get('rag_context', '') if context else ''}

User: {prompt}
JARVIS:"""
        
        try:
            # Use ask_ai function
            response_text = ask_ai(full_prompt, model=self.model)
            
            # Check for error responses
            if response_text.startswith("AI Brain is offline") or response_text.startswith("Error:") or response_text.startswith("AI error:"):
                self._available = False
                print("[JARVIS] Lost connection to Ollama")
                return AIResponse(
                    text="I'm experiencing connectivity issues. Please check if Ollama is running.",
                    emotion="concerned"
                )
            
            return self._process_response(response_text)
                
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return AIResponse(
                text="I'm experiencing a temporary malfunction. Please try again.",
                emotion="concerned"
            )
    
    def _process_response(self, text: str) -> AIResponse:
        """Process raw LLM response into structured format"""
        # Extract thoughts if present
        thoughts = []
        thought_pattern = r'\[THOUGHT\](.*?)\[/THOUGHT\]'
        thought_matches = re.findall(thought_pattern, text, re.DOTALL)
        for match in thought_matches:
            thoughts.append(Thought(type="analysis", content=match.strip()))
        
        # Clean text
        clean_text = re.sub(thought_pattern, '', text, flags=re.DOTALL).strip()
        
        # Detect emotion
        emotion = self._detect_emotion(clean_text)
        
        return AIResponse(
            text=clean_text,
            thoughts=thoughts,
            emotion=emotion
        )
    
    def _detect_emotion(self, text: str) -> str:
        """Detect emotional tone from text"""
        text_lower = text.lower()
        
        if any(w in text_lower for w in ["excellent", "outstanding", "perfect", "done"]):
            return "satisfied"
        elif any(w in text_lower for w in ["error", "failed", "unable", "sorry"]):
            return "concerned"
        elif any(w in text_lower for w in ["humor", "joke", "witty", "sarcasm", "suggest"]):
            return "witty"
        elif "?" in text:
            return "inquisitive"
        
        return "neutral"
    
    async def process_input(self, text: str, context: Dict = None) -> AIResponse:
        """
        Main entry point for processing user input
        """
        # Debug print
        print("User:", text)
        
        # Detect intent
        intent = self.intent_detector.detect(text)
        
        # Add to history
        self.context_manager.add_message("user", text, {"intent": intent})
        
        # Check for complex task
        if intent.get("requires_complex_processing"):
            # Generate plan
            plan = await self.task_planner.plan(text, context or {})
            
            # Store in context
            self.context_manager.update_system_context("current_task", {
                "description": text,
                "plan": plan
            })
        
        # Generate response
        response = await self.generate(text, context=context)
        
        # Debug print
        print("AI:", response.text)
        
        # Add to history
        self.context_manager.add_message("assistant", response.text, {
            "emotion": response.emotion,
            "actions": response.actions
        })
        
        return response
    
    async def generate_stream(self, text: str) -> AsyncGenerator[str, None]:
        """Stream response chunks - for phi model we yield the full response"""
        if not self._available:
            yield "I'm currently offline. Please ensure Ollama is running."
            return
        
        try:
            # For phi model with non-streaming API, just yield the full response
            full_prompt = f"{JARVIS_PERSONALITY}\n\nUser: {text}\nJARVIS:"
            response = ask_ai(full_prompt, model=self.model)
            yield response
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield "Error occurred during generation."
