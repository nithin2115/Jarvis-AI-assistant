"""Utils - Helper functions and shared utilities"""
import os
import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import asyncio
from functools import wraps

from config.settings import DATA_DIR, CUSTOM_COMMANDS_DIR
from utils.logger import get_logger

logger = get_logger("utils")

def generate_id(text: str) -> str:
    """Generate unique ID from text"""
    return hashlib.md5(text.encode()).hexdigest()[:12]

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    return re.sub(r'[^\w\-_.]', '_', filename)

def format_time_ago(dt: datetime) -> str:
    """Format datetime as 'X time ago'"""
    now = datetime.now()
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return "just now"
    elif diff < timedelta(hours=1):
        return f"{diff.seconds // 60} minutes ago"
    elif diff < timedelta(days=1):
        return f"{diff.seconds // 3600} hours ago"
    else:
        return f"{diff.days} days ago"

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."

def extract_urls(text: str) -> List[str]:
    """Extract URLs from text"""
    url_pattern = r'https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?'
    return re.findall(url_pattern, text)

def extract_numbers(text: str) -> List[int]:
    """Extract numbers from text"""
    return [int(n) for n in re.findall(r'\d+', text)]

def async_retry(max_retries: int = 3, delay: float = 1.0):
    """Decorator for async function retry"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
                    await asyncio.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

def safe_json_loads(text: str, default: Any = None) -> Any:
    """Safely load JSON"""
    try:
        return json.loads(text)
    except:
        return default

def clean_text_for_speech(text: str) -> str:
    """Clean text for TTS (remove markdown, URLs, etc.)"""
    # Remove markdown
    text = re.sub(r'\*\*?|\`\`\`?', '', text)
    # Remove URLs
    text = re.sub(r'https?://\S+', 'link', text)
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text

def parse_time_string(time_str: str) -> Optional[datetime]:
    """Parse time string like 'in 5 minutes' or 'at 3 PM'"""
    time_str = time_str.lower()
    now = datetime.now()
    
    # "in X minutes/hours"
    match = re.match(r'in (\d+) (minute|hour|day)s?', time_str)
    if match:
        value, unit = int(match.group(1)), match.group(2)
        if unit == 'minute':
            return now + timedelta(minutes=value)
        elif unit == 'hour':
            return now + timedelta(hours=value)
        elif unit == 'day':
            return now + timedelta(days=value)
    
    return None

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """Split list into chunks"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def merge_dicts(*dicts: Dict) -> Dict:
    """Merge multiple dictionaries"""
    result = {}
    for d in dicts:
        result.update(d)
    return result

def estimate_tokens(text: str) -> int:
    """Rough token count estimation"""
    # Roughly 4 characters per token for English
    return len(text) // 4

def save_json(data: Any, path: str):
    """Save data to JSON file"""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save JSON: {e}")

def load_json(path: str, default: Any = None) -> Any:
    """Load data from JSON file"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default

class Timer:
    """Simple timer utility"""
    
    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, *args):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        logger.debug(f"{self.name} took {elapsed:.2f}s")

class RateLimiter:
    """Rate limiter for API calls"""
    
    def __init__(self, max_calls: int, period: int):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
    
    def can_call(self) -> bool:
        """Check if call is allowed"""
        now = datetime.now()
        # Remove old calls
        self.calls = [c for c in self.calls if (now - c).seconds < self.period]
        return len(self.calls) < self.max_calls
    
    def record_call(self):
        """Record a call"""
        self.calls.append(datetime.now())
    
    async def wait_if_needed(self):
        """Wait if rate limited"""
        while not self.can_call():
            await asyncio.sleep(1)
        self.record_call()
