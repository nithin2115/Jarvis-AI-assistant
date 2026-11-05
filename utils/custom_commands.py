"""Self-Learning Command System - Custom Command Definition and Execution"""
import json
import re
from typing import Dict, List, Callable, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

from config.settings import CUSTOM_COMMANDS_DIR
from utils.logger import get_logger

logger = get_logger("custom_commands")

@dataclass
class CustomCommand:
    """Definition of a custom command"""
    id: str
    name: str
    triggers: List[str]  # Phrases that activate this command
    description: str
    actions: List[Dict]  # List of actions to execute
    created_at: str
    usage_count: int = 0
    last_used: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CustomCommand":
        return cls(**data)

class CommandParser:
    """Parse natural language command definitions"""
    
    ACTION_PATTERNS = {
        "open_app": r"open (.+?)(?:\s+and|\s+then|$)",
        "close_app": r"close (.+?)(?:\s+and|\s+then|$)",
        "set_volume": r"set volume to (\d+)",
        "set_brightness": r"set brightness to (\d+)",
        "open_website": r"(?:go to|open|visit) (.+?\.\w+)(?:\s+and|\s+then|$)",
        "search": r"search for (.+?)(?:\s+and|\s+then|$)",
        "play_music": r"play (.+?)(?:\s+and|\s+then|$)",
        "system_command": r"(shutdown|restart|lock|mute|unmute)",
        "wait": r"wait (\d+) seconds?",
    }
    
    def parse_command_definition(self, natural_language: str) -> Optional[CustomCommand]:
        """
        Parse natural language command definition into structured command
        Example: "When I say study mode, open Spotify, VS Code, and Notion"
        """
        # Extract trigger phrase
        trigger_patterns = [
            r"when (?:i |we )?say ['\"]?(.+?)['\"]?[,\s]",
            r"['\"]?(.+?)['\"]? means",
            r"create (?:a )?command ['\"]?(.+?)['\"]?",
        ]
        
        trigger = None
        for pattern in trigger_patterns:
            match = re.search(pattern, natural_language.lower())
            if match:
                trigger = match.group(1).strip()
                break
        
        if not trigger:
            # Try to infer from structure
            if " - " in natural_language:
                parts = natural_language.split(" - ", 1)
                if len(parts) == 2:
                    trigger = parts[0].strip()
                    action_part = parts[1]
                else:
                    return None
            else:
                return None
        else:
            # Get the action part (everything after trigger definition)
            action_match = re.search(r"(?:then|,)\s*(.+)$", natural_language, re.IGNORECASE)
            if action_match:
                action_part = action_match.group(1)
            else:
                return None
        
        # Parse actions
        actions = self._parse_actions(action_part)
        
        if not actions:
            return None
        
        # Create command
        command_id = re.sub(r'[^\w]', '_', trigger.lower())
        
        return CustomCommand(
            id=command_id,
            name=trigger.title(),
            triggers=[trigger, trigger.lower(), trigger.title()],
            description=f"Custom command: {trigger}",
            actions=actions,
            created_at=datetime.now().isoformat()
        )
    
    def _parse_actions(self, action_text: str) -> List[Dict]:
        """Parse action text into structured actions"""
        actions = []
        
        # Split by common separators
        parts = re.split(r',\s+and\s+|\s+then\s+|,\s+', action_text)
        
        for part in parts:
            part = part.strip().lower()
            if not part:
                continue
            
            # Try to match patterns
            for action_type, pattern in self.ACTION_PATTERNS.items():
                match = re.search(pattern, part)
                if match:
                    action = {"type": action_type}
                    
                    if action_type in ["open_app", "close_app"]:
                        action["app"] = match.group(1).strip()
                    elif action_type in ["set_volume", "set_brightness", "wait"]:
                        action["value"] = int(match.group(1))
                    elif action_type == "open_website":
                        url = match.group(1).strip()
                        if not url.startswith("http"):
                            url = "https://" + url
                        action["url"] = url
                    elif action_type == "search":
                        action["query"] = match.group(1).strip()
                    elif action_type == "play_music":
                        action["query"] = match.group(1).strip()
                    elif action_type == "system_command":
                        action["command"] = match.group(1)
                    
                    actions.append(action)
                    break
            else:
                # Unknown action - store as generic
                actions.append({
                    "type": "unknown",
                    "text": part
                })
        
        return actions

class CustomCommandManager:
    """Manage custom commands storage and execution"""
    
    def __init__(self):
        self.commands: Dict[str, CustomCommand] = {}
        self.parser = CommandParser()
        self.storage_path = CUSTOM_COMMANDS_DIR / "commands.json"
        self._load_commands()
    
    def _load_commands(self):
        """Load commands from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for cmd_data in data.get("commands", []):
                        cmd = CustomCommand.from_dict(cmd_data)
                        self.commands[cmd.id] = cmd
                logger.info(f"Loaded {len(self.commands)} custom commands")
            except Exception as e:
                logger.error(f"Failed to load commands: {e}")
    
    def _save_commands(self):
        """Save commands to storage"""
        try:
            data = {
                "commands": [cmd.to_dict() for cmd in self.commands.values()],
                "updated_at": datetime.now().isoformat()
            }
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save commands: {e}")
    
    def create_command(self, natural_language: str) -> Optional[CustomCommand]:
        """Create a new custom command from natural language"""
        command = self.parser.parse_command_definition(natural_language)
        
        if command:
            self.commands[command.id] = command
            self._save_commands()
            logger.info(f"Created custom command: {command.name}")
            return command
        
        return None
    
    def delete_command(self, command_id: str) -> bool:
        """Delete a custom command"""
        if command_id in self.commands:
            del self.commands[command_id]
            self._save_commands()
            return True
        return False
    
    def get_command(self, command_id: str) -> Optional[CustomCommand]:
        """Get a specific command"""
        return self.commands.get(command_id)
    
    def find_matching_command(self, text: str) -> Optional[CustomCommand]:
        """Find command matching the input text"""
        text_lower = text.lower()
        
        for cmd in self.commands.values():
            for trigger in cmd.triggers:
                if trigger.lower() in text_lower:
                    return cmd
        
        return None
    
    def get_all_commands(self) -> List[CustomCommand]:
        """Get all custom commands"""
        return list(self.commands.values())
    
    def record_usage(self, command_id: str):
        """Record command usage"""
        if command_id in self.commands:
            self.commands[command_id].usage_count += 1
            self.commands[command_id].last_used = datetime.now().isoformat()
            self._save_commands()
    
    def generate_commands_list_text(self) -> str:
        """Generate text list of available commands"""
        if not self.commands:
            return "No custom commands defined yet."
        
        lines = ["Custom Commands:"]
        for cmd in self.commands.values():
            lines.append(f"  • {cmd.name}: {cmd.description}")
        
        return "\n".join(lines)

class CommandExecutor:
    """Execute custom command actions"""
    
    def __init__(self, task_executor, integrations_manager):
        self.task_executor = task_executor
        self.integrations = integrations_manager
    
    async def execute_command(self, command: CustomCommand) -> List[Dict]:
        """Execute a custom command's actions"""
        results = []
        
        for action in command.actions:
            result = await self._execute_action(action)
            results.append(result)
            
            # If action failed and it's critical, stop
            if not result.get("success") and action.get("critical"):
                break
        
        return results
    
    async def _execute_action(self, action: Dict) -> Dict:
        """Execute a single action"""
        action_type = action.get("type")
        
        try:
            if action_type == "open_app":
                app = action.get("app", "")
                result = await self.task_executor.router.execute(f"open {app}")
                return {"success": result.success, "message": result.message}
            
            elif action_type == "close_app":
                app = action.get("app", "")
                result = await self.task_executor.router.execute(f"close {app}")
                return {"success": result.success, "message": result.message}
            
            elif action_type == "set_volume":
                value = action.get("value", 50)
                result = await self.task_executor.router.execute(f"volume {value}")
                return {"success": result.success, "message": result.message}
            
            elif action_type == "set_brightness":
                value = action.get("value", 50)
                result = await self.task_executor.router.execute(f"brightness {value}")
                return {"success": result.success, "message": result.message}
            
            elif action_type == "open_website":
                url = action.get("url", "")
                if self.task_executor.automation:
                    result = await self.task_executor.automation.navigate(url)
                    return result
                return {"success": False, "message": "Browser automation not available"}
            
            elif action_type == "search":
                query = action.get("query", "")
                if self.task_executor.automation:
                    result = await self.task_executor.automation.search(query)
                    return result
                return {"success": False, "message": "Browser automation not available"}
            
            elif action_type == "play_music":
                query = action.get("query", "")
                result = await self.integrations.handle_command(
                    "", "music", {"action": "play", "query": query}
                )
                return result
            
            elif action_type == "wait":
                seconds = action.get("value", 1)
                await asyncio.sleep(seconds)
                return {"success": True, "message": f"Waited {seconds} seconds"}
            
            else:
                return {"success": False, "message": f"Unknown action type: {action_type}"}
                
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return {"success": False, "message": str(e)}
