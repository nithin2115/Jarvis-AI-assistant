"""Task Executor - Command Routing and System Execution"""
import os
import subprocess
import psutil
import pyautogui
import asyncio
import platform
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import screen_brightness_control as sbc

from config.settings import system_config, voice_config
from utils.logger import get_logger

logger = get_logger("task_executor")

class CommandType(Enum):
    SYSTEM = "system"
    APPLICATION = "application"
    FILE = "file"
    BROWSER = "browser"
    MEDIA = "media"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

@dataclass
class CommandResult:
    success: bool
    message: str
    data: Dict = None
    action_taken: str = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}

class SystemController:
    """Control system settings and operations"""
    
    def __init__(self):
        self.system = platform.system()
    
    def set_volume(self, level: int) -> CommandResult:
        """Set system volume (0-100)"""
        try:
            if self.system == "Windows":
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(level / 100, None)
            else:
                # macOS/Linux implementation
                pass
            
            return CommandResult(True, f"Volume set to {level}%", action_taken="set_volume")
        except Exception as e:
            logger.error(f"Volume control error: {e}")
            return CommandResult(False, f"Failed to set volume: {e}")
    
    def set_brightness(self, level: int) -> CommandResult:
        """Set screen brightness (0-100)"""
        try:
            sbc.set_brightness(level)
            return CommandResult(True, f"Brightness set to {level}%", action_taken="set_brightness")
        except Exception as e:
            logger.error(f"Brightness control error: {e}")
            return CommandResult(False, f"Failed to set brightness: {e}")
    
    def mute(self, muted: bool = True) -> CommandResult:
        """Mute/unmute system"""
        try:
            if self.system == "Windows":
                import keyboard
                keyboard.send('volume mute' if muted else 'volume up')
            return CommandResult(True, "System muted" if muted else "System unmuted", 
                               action_taken="mute")
        except Exception as e:
            return CommandResult(False, f"Failed to toggle mute: {e}")
    
    def shutdown(self) -> CommandResult:
        """Shutdown system"""
        return CommandResult(False, "Shutdown requires confirmation", 
                           action_taken="shutdown_request")
    
    def restart(self) -> CommandResult:
        """Restart system"""
        return CommandResult(False, "Restart requires confirmation",
                           action_taken="restart_request")
    
    def lock(self) -> CommandResult:
        """Lock workstation"""
        try:
            if self.system == "Windows":
                subprocess.run("rundll32.exe user32.dll,LockWorkStation", check=True)
            elif self.system == "Darwin":
                subprocess.run("pmset displaysleepnow", shell=True, check=True)
            return CommandResult(True, "Workstation locked", action_taken="lock")
        except Exception as e:
            return CommandResult(False, f"Failed to lock: {e}")

class ApplicationController:
    """Control applications"""
    
    APP_MAP = {
        # Common Windows applications
        "chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "vscode": "code.exe",
        "spotify": "spotify.exe",
        "discord": "discord.exe",
        "steam": "steam.exe",
        # Generic names
        "browser": "chrome.exe",
        "editor": "notepad.exe",
        "terminal": "cmd.exe",
    }
    
    def __init__(self):
        self.running_apps: Dict[str, int] = {}
    
    def open_application(self, app_name: str) -> CommandResult:
        """Open an application"""
        app_name_lower = app_name.lower()
        
        # Check if in app map
        exe_name = self.APP_MAP.get(app_name_lower)
        
        if not exe_name:
            # Try to find in common locations
            return self._try_open_unknown(app_name)
        
        try:
            # Check if already running
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'].lower() == exe_name.lower():
                    # Bring to front
                    self._bring_to_front(proc.info['pid'])
                    return CommandResult(True, f"{app_name} brought to front", 
                                       action_taken="focus_app",
                                       data={"pid": proc.info['pid']})
            
            # Start new instance
            if exe_name.endswith('.exe'):
                subprocess.Popen(exe_name, shell=True)
            else:
                subprocess.Popen([exe_name])
            
            return CommandResult(True, f"{app_name} opened", action_taken="open_app")
            
        except Exception as e:
            logger.error(f"Failed to open {app_name}: {e}")
            return CommandResult(False, f"Failed to open {app_name}: {e}")
    
    def close_application(self, app_name: str) -> CommandResult:
        """Close an application"""
        app_name_lower = app_name.lower()
        exe_name = self.APP_MAP.get(app_name_lower, app_name_lower)
        
        closed = []
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if (exe_name.lower() in proc.info['name'].lower() or 
                    (proc.info['exe'] and exe_name.lower() in proc.info['exe'].lower())):
                    proc.terminate()
                    closed.append(proc.info['name'])
            except:
                pass
        
        if closed:
            return CommandResult(True, f"Closed: {', '.join(closed)}", 
                             action_taken="close_app")
        return CommandResult(False, f"Could not find {app_name}")
    
    def _try_open_unknown(self, app_name: str) -> CommandResult:
        """Try to open unknown application"""
        try:
            # Try various methods
            methods = [
                lambda: subprocess.Popen([app_name], shell=True),
                lambda: subprocess.Popen(f"start {app_name}", shell=True),
                lambda: subprocess.Popen(["start", app_name], shell=True),
            ]
            
            for method in methods:
                try:
                    method()
                    return CommandResult(True, f"{app_name} opened", 
                                       action_taken="open_app")
                except:
                    continue
                    
            return CommandResult(False, f"Could not find or open {app_name}")
            
        except Exception as e:
            return CommandResult(False, f"Failed to open {app_name}: {e}")
    
    def _bring_to_front(self, pid: int):
        """Bring window to front"""
        try:
            import win32gui
            import win32con
            
            def callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    _, found_pid = win32gui.GetWindowThreadProcessId(hwnd)
                    if found_pid == pid:
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        return False
                return True
            
            win32gui.EnumWindows(callback, None)
        except:
            pass
    
    def list_running(self) -> List[Dict]:
        """List currently running applications"""
        apps = []
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['exe']:  # Has a window
                    apps.append({
                        "pid": proc.info['pid'],
                        "name": proc.info['name'],
                        "exe": proc.info['exe']
                    })
            except:
                pass
        return apps

class FileSystemController:
    """File system operations"""
    
    def create_file(self, path: str, content: str = "") -> CommandResult:
        """Create a new file"""
        try:
            with open(path, 'w') as f:
                f.write(content)
            return CommandResult(True, f"Created file: {path}", action_taken="create_file")
        except Exception as e:
            return CommandResult(False, f"Failed to create file: {e}")
    
    def delete_file(self, path: str) -> CommandResult:
        """Delete a file"""
        try:
            if os.path.isfile(path):
                os.remove(path)
                return CommandResult(True, f"Deleted file: {path}")
            return CommandResult(False, f"File not found: {path}")
        except Exception as e:
            return CommandResult(False, f"Failed to delete: {e}")
    
    def create_folder(self, path: str) -> CommandResult:
        """Create a folder"""
        try:
            os.makedirs(path, exist_ok=True)
            return CommandResult(True, f"Created folder: {path}")
        except Exception as e:
            return CommandResult(False, f"Failed to create folder: {e}")
    
    def open_folder(self, path: str) -> CommandResult:
        """Open folder in explorer"""
        try:
            if os.path.exists(path):
                subprocess.Popen(f'explorer "{path}"')
                return CommandResult(True, f"Opened folder: {path}")
            return CommandResult(False, f"Folder not found: {path}")
        except Exception as e:
            return CommandResult(False, f"Failed to open folder: {e}")

class CommandRouter:
    """Route commands to appropriate handlers"""
    
    def __init__(self):
        self.system = SystemController()
        self.apps = ApplicationController()
        self.files = FileSystemController()
        self.custom_commands: Dict[str, Callable] = {}
        
        # Command patterns
        self.patterns = {
            r'open (\w+)': self._handle_open,
            r'close (\w+)': self._handle_close,
            r'volume (\d+)': self._handle_volume,
            r'brightness (\d+)': self._handle_brightness,
            r'mute': self._handle_mute,
            r'unmute': self._handle_unmute,
            r'shutdown': self._handle_shutdown,
            r'restart': self._handle_restart,
            r'lock': self._handle_lock,
            r'create (?:file|folder) (.+)': self._handle_create,
            r'delete (.+)': self._handle_delete,
        }
    
    def register_custom_command(self, trigger: str, handler: Callable, description: str):
        """Register a custom command"""
        self.custom_commands[trigger.lower()] = {
            "handler": handler,
            "description": description
        }
        logger.info(f"Registered custom command: {trigger}")
    
    async def execute(self, command: str, command_type: CommandType = None) -> CommandResult:
        """Execute a command"""
        command_lower = command.lower()
        
        # Check custom commands first
        for trigger, data in self.custom_commands.items():
            if trigger in command_lower:
                try:
                    result = await data["handler"](command)
                    return CommandResult(True, result, action_taken=f"custom:{trigger}")
                except Exception as e:
                    return CommandResult(False, f"Custom command failed: {e}")
        
        # Check for direct matches in patterns
        import re
        for pattern, handler in self.patterns.items():
            match = re.search(pattern, command_lower)
            if match:
                return await handler(*match.groups())
        
        # Try to infer command type
        if command_type is None:
            command_type = self._infer_type(command)
        
        # Route based on type
        if command_type == CommandType.APPLICATION:
            # Extract app name
            words = command_lower.split()
            for i, word in enumerate(words):
                if word in ['open', 'launch', 'start'] and i + 1 < len(words):
                    return self.apps.open_application(words[i + 1])
        
        elif command_type == CommandType.SYSTEM:
            # Try system commands
            if 'volume' in command_lower:
                # Extract number
                nums = re.findall(r'\d+', command)
                if nums:
                    return self.system.set_volume(int(nums[0]))
        
        return CommandResult(False, "Command not recognized")
    
    def _infer_type(self, command: str) -> CommandType:
        """Infer command type from text"""
        cmd_lower = command.lower()
        
        if any(w in cmd_lower for w in ['open', 'launch', 'start', 'run']):
            return CommandType.APPLICATION
        elif any(w in cmd_lower for w in ['volume', 'brightness', 'mute', 'shutdown', 'restart']):
            return CommandType.SYSTEM
        elif any(w in cmd_lower for w in ['file', 'folder', 'create', 'delete', 'move']):
            return CommandType.FILE
        elif any(w in cmd_lower for w in ['browse', 'website', 'search', 'google']):
            return CommandType.BROWSER
        elif any(w in cmd_lower for w in ['play', 'pause', 'music', 'song', 'spotify']):
            return CommandType.MEDIA
        
        return CommandType.UNKNOWN
    
    # Pattern handlers
    async def _handle_open(self, app_name: str) -> CommandResult:
        return self.apps.open_application(app_name)
    
    async def _handle_close(self, app_name: str) -> CommandResult:
        return self.apps.close_application(app_name)
    
    async def _handle_volume(self, level: str) -> CommandResult:
        return self.system.set_volume(int(level))
    
    async def _handle_brightness(self, level: str) -> CommandResult:
        return self.system.set_brightness(int(level))
    
    async def _handle_mute(self) -> CommandResult:
        return self.system.mute(True)
    
    async def _handle_unmute(self) -> CommandResult:
        return self.system.mute(False)
    
    async def _handle_shutdown(self) -> CommandResult:
        return self.system.shutdown()
    
    async def _handle_restart(self) -> CommandResult:
        return self.system.restart()
    
    async def _handle_lock(self) -> CommandResult:
        return self.system.lock()
    
    async def _handle_create(self, path: str) -> CommandResult:
        if '.' in path:
            return self.files.create_file(path)
        return self.files.create_folder(path)
    
    async def _handle_delete(self, path: str) -> CommandResult:
        return self.files.delete_file(path)

class TaskExecutor:
    """Main task execution orchestrator"""
    
    def __init__(self):
        self.router = CommandRouter()
        self.automation = None  # Will be set from automation module
        self.on_progress: Optional[Callable[[str, int], None]] = None
    
    def set_automation(self, automation_module):
        """Set browser automation module"""
        self.automation = automation_module
    
    def set_progress_callback(self, callback: Callable[[str, int], None]):
        """Set progress callback for long operations"""
        self.on_progress = callback
    
    async def execute_task(self, task: str, plan: List[Dict] = None) -> List[CommandResult]:
        """
        Execute a task with optional plan
        Returns list of results for each step
        """
        results = []
        
        if plan is None:
            # Simple single command
            result = await self.router.execute(task)
            results.append(result)
        else:
            # Multi-step plan execution
            for i, step in enumerate(plan):
                if self.on_progress:
                    self.on_progress(step.get("description", f"Step {i+1}"), 
                                   int((i / len(plan)) * 100))
                
                result = await self._execute_step(step)
                results.append(result)
                
                if not result.success:
                    logger.error(f"Step {i+1} failed: {result.message}")
                    # Continue or stop based on criticality
                    if step.get("critical", False):
                        break
        
        return results
    
    async def _execute_step(self, step: Dict) -> CommandResult:
        """Execute a single plan step"""
        action = step.get("action", "").lower()
        target = step.get("target", "")
        
        # Route to appropriate handler
        if action in ["search", "browse"]:
            if self.automation:
                result = await self.automation.search(target)
                return CommandResult(True, result.get("message", "Search completed"),
                                   action_taken=action, data=result)
        
        elif action in ["open", "launch", "start"]:
            return await self.router.execute(f"open {target}", CommandType.APPLICATION)
        
        elif action in ["click", "type", "extract", "navigate"]:
            if self.automation:
                result = await self.automation.execute_browser_action(action, target)
                return CommandResult(result.get("success", False),
                                  result.get("message", ""),
                                  action_taken=action)
        
        elif action == "execute":
            return await self.router.execute(target)
        
        return CommandResult(False, f"Unknown action: {action}")
    
    def get_available_commands(self) -> List[Dict]:
        """Get list of available commands"""
        return [
            {"type": "system", "commands": ["volume <0-100>", "brightness <0-100>", 
                                            "mute", "unmute", "lock", "shutdown", "restart"]},
            {"type": "application", "commands": ["open <app>", "close <app>"]},
            {"type": "file", "commands": ["create file <path>", "create folder <path>", 
                                          "delete <path>", "open folder <path>"]},
            {"type": "custom", "commands": list(self.router.custom_commands.keys())},
        ]
