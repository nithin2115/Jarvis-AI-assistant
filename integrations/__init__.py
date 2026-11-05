"""Integrations - Weather, News, Spotify, Email"""
import asyncio
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
from datetime import datetime

from config.settings import integration_config
from utils.logger import get_logger

logger = get_logger("integrations")

@dataclass
class WeatherInfo:
    temperature: float
    feels_like: float
    humidity: int
    description: str
    location: str
    wind_speed: float
    timestamp: datetime

@dataclass
class NewsArticle:
    title: str
    description: str
    url: str
    source: str
    published_at: datetime

class WeatherIntegration:
    """Open-Meteo weather integration (free, no API key needed)"""
    
    API_URL = "https://api.open-meteo.com/v1/forecast"
    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # location -> (timestamp, data)
        self._cache_duration = 300  # 5 minutes
    
    def _get_cached(self, location: str) -> Optional[WeatherInfo]:
        """Get cached weather if fresh"""
        if location in self._cache:
            timestamp, data = self._cache[location]
            if (datetime.now() - timestamp).seconds < self._cache_duration:
                return data
        return None
    
    def _get_coordinates(self, location: str) -> Optional[tuple]:
        """Get lat/lon for location name"""
        try:
            response = requests.get(
                self.GEO_URL,
                params={"name": location, "count": 1},
                timeout=5
            )
            data = response.json()
            
            if data.get("results"):
                result = data["results"][0]
                return (result["latitude"], result["longitude"])
            return None
            
        except Exception as e:
            logger.error(f"Geocoding error: {e}")
            return None
    
    def get_weather(self, location: str = None, lat: float = None, lon: float = None) -> Optional[WeatherInfo]:
        """Get current weather"""
        if not integration_config.openmeteo_enabled:
            return None
        
        # Check cache
        cache_key = f"{lat},{lon}" if lat else location
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            # Get coordinates if needed
            if lat is None and location:
                coords = self._get_coordinates(location)
                if coords:
                    lat, lon = coords
                else:
                    return None
            
            # Fetch weather
            response = requests.get(
                self.API_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": ["temperature_2m", "relative_humidity_2m", 
                              "apparent_temperature", "weather_code", "wind_speed_10m"],
                    "timezone": "auto"
                },
                timeout=5
            )
            data = response.json()
            
            current = data.get("current", {})
            
            # Map weather code to description
            weather_codes = {
                0: "Clear sky",
                1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Fog", 48: "Depositing rime fog",
                51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                95: "Thunderstorm"
            }
            
            weather_code = current.get("weather_code", 0)
            description = weather_codes.get(weather_code, "Unknown")
            
            weather = WeatherInfo(
                temperature=current.get("temperature_2m", 0),
                feels_like=current.get("apparent_temperature", 0),
                humidity=current.get("relative_humidity_2m", 0),
                description=description,
                location=location or f"{lat:.2f}, {lon:.2f}",
                wind_speed=current.get("wind_speed_10m", 0),
                timestamp=datetime.now()
            )
            
            # Cache result
            self._cache[cache_key] = (datetime.now(), weather)
            
            return weather
            
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
            return None
    
    def format_weather(self, weather: WeatherInfo) -> str:
        """Format weather for voice output"""
        return (
            f"Current weather in {weather.location}: {weather.description}, "
            f"{weather.temperature:.0f} degrees. "
            f"Feels like {weather.feels_like:.0f} degrees. "
            f"Humidity is {weather.humidity} percent."
        )

class NewsIntegration:
    """NewsAPI integration"""
    
    API_URL = "https://newsapi.org/v2"
    
    def __init__(self):
        self.api_key = integration_config.newsapi_key
        self._cache: List[NewsArticle] = []
        self._cache_time: Optional[datetime] = None
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def get_top_headlines(self, category: str = "general", 
                         country: str = "us", 
                         count: int = 5) -> List[NewsArticle]:
        """Get top news headlines"""
        if not self.api_key:
            logger.warning("NewsAPI key not configured")
            return []
        
        # Check cache (15 min)
        if self._cache and self._cache_time:
            if (datetime.now() - self._cache_time).seconds < 900:
                return self._cache[:count]
        
        try:
            response = requests.get(
                f"{self.API_URL}/top-headlines",
                params={
                    "category": category,
                    "country": country,
                    "pageSize": count,
                    "apiKey": self.api_key
                },
                timeout=10
            )
            data = response.json()
            
            articles = []
            for item in data.get("articles", []):
                article = NewsArticle(
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    source=item.get("source", {}).get("name", "Unknown"),
                    published_at=datetime.fromisoformat(
                        item.get("publishedAt", "").replace("Z", "+00:00")
                    ) if item.get("publishedAt") else datetime.now()
                )
                articles.append(article)
            
            self._cache = articles
            self._cache_time = datetime.now()
            
            return articles
            
        except Exception as e:
            logger.error(f"News fetch error: {e}")
            return []
    
    def search_news(self, query: str, count: int = 5) -> List[NewsArticle]:
        """Search news by query"""
        if not self.api_key:
            return []
        
        try:
            response = requests.get(
                f"{self.API_URL}/everything",
                params={
                    "q": query,
                    "pageSize": count,
                    "sortBy": "relevancy",
                    "apiKey": self.api_key
                },
                timeout=10
            )
            data = response.json()
            
            articles = []
            for item in data.get("articles", []):
                article = NewsArticle(
                    title=item.get("title", ""),
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    source=item.get("source", {}).get("name", "Unknown"),
                    published_at=datetime.fromisoformat(
                        item.get("publishedAt", "").replace("Z", "+00:00")
                    ) if item.get("publishedAt") else datetime.now()
                )
                articles.append(article)
            
            return articles
            
        except Exception as e:
            logger.error(f"News search error: {e}")
            return []
    
    def format_news(self, articles: List[NewsArticle]) -> str:
        """Format news for voice output"""
        if not articles:
            return "I couldn't fetch the news at the moment."
        
        parts = ["Here are the top headlines:"]
        for i, article in enumerate(articles[:3], 1):
            parts.append(f"{i}. {article.title} from {article.source}")
        
        return " ".join(parts)

class SpotifyIntegration:
    """Spotify integration for music control"""
    
    def __init__(self):
        self.client_id = integration_config.spotify_client_id
        self.client_secret = integration_config.spotify_client_secret
        self.redirect_uri = integration_config.spotify_redirect_uri
        self.sp = None
        self._initialized = False
    
    def is_available(self) -> bool:
        return bool(self.client_id and self.client_secret)
    
    def _init_spotify(self):
        """Initialize Spotify client"""
        if self._initialized or not self.is_available():
            return
        
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
            
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope="user-read-playback-state,user-modify-playback-state,user-read-currently-playing"
            ))
            self._initialized = True
            logger.info("Spotify integration initialized")
            
        except Exception as e:
            logger.error(f"Spotify init error: {e}")
    
    def play(self, uri: str = None, search_query: str = None) -> Dict:
        """Start playback"""
        self._init_spotify()
        if not self._initialized:
            return {"success": False, "message": "Spotify not configured"}
        
        try:
            # Get available devices
            devices = self.sp.devices()
            if not devices.get("devices"):
                return {"success": False, "message": "No Spotify devices found"}
            
            device_id = devices["devices"][0]["id"]
            
            if search_query:
                # Search and play
                results = self.sp.search(search_query, type="track", limit=1)
                if results["tracks"]["items"]:
                    uri = results["tracks"]["items"][0]["uri"]
                    self.sp.start_playback(device_id=device_id, uris=[uri])
                    track_name = results["tracks"]["items"][0]["name"]
                    artist = results["tracks"]["items"][0]["artists"][0]["name"]
                    return {"success": True, "message": f"Playing {track_name} by {artist}"}
                else:
                    return {"success": False, "message": "No results found"}
            
            elif uri:
                self.sp.start_playback(device_id=device_id, uris=[uri])
                return {"success": True, "message": "Playback started"}
            
            else:
                self.sp.start_playback(device_id=device_id)
                return {"success": True, "message": "Resuming playback"}
                
        except Exception as e:
            logger.error(f"Spotify play error: {e}")
            return {"success": False, "message": str(e)}
    
    def pause(self) -> Dict:
        """Pause playback"""
        self._init_spotify()
        if not self._initialized:
            return {"success": False, "message": "Spotify not configured"}
        
        try:
            self.sp.pause_playback()
            return {"success": True, "message": "Playback paused"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def skip(self) -> Dict:
        """Skip to next track"""
        self._init_spotify()
        if not self._initialized:
            return {"success": False, "message": "Spotify not configured"}
        
        try:
            self.sp.next_track()
            return {"success": True, "message": "Skipped to next track"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def get_current_track(self) -> Optional[Dict]:
        """Get currently playing track"""
        self._init_spotify()
        if not self._initialized:
            return None
        
        try:
            current = self.sp.current_playback()
            if current and current.get("item"):
                return {
                    "name": current["item"]["name"],
                    "artist": current["item"]["artists"][0]["name"],
                    "album": current["item"]["album"]["name"],
                    "is_playing": current["is_playing"]
                }
            return None
        except Exception as e:
            logger.error(f"Get current track error: {e}")
            return None

class EmailIntegration:
    """Email automation integration"""
    
    def __init__(self):
        self.email_address = integration_config.email_address
        self.password = integration_config.email_password
        self.smtp_server = integration_config.smtp_server
        self.smtp_port = integration_config.smtp_port
        self._available = bool(self.email_address and self.password)
    
    def is_available(self) -> bool:
        return self._available
    
    def send_email(self, to: str, subject: str, body: str, 
                  attachments: List[str] = None) -> Dict:
        """Send email"""
        if not self._available:
            return {"success": False, "message": "Email not configured"}
        
        try:
            import yagmail
            
            yag = yagmail.SMTP(self.email_address, self.password)
            
            yag.send(
                to=to,
                subject=subject,
                contents=body,
                attachments=attachments or []
            )
            
            return {"success": True, "message": f"Email sent to {to}"}
            
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return {"success": False, "message": str(e)}
    
    def draft_email(self, to: str, subject: str, body: str) -> str:
        """Create email draft (save locally or open email client)"""
        draft = f"To: {to}\nSubject: {subject}\n\n{body}"
        return draft

class IntegrationsManager:
    """Manage all integrations"""
    
    def __init__(self):
        self.weather = WeatherIntegration()
        self.news = NewsIntegration()
        self.spotify = SpotifyIntegration()
        self.email = EmailIntegration()
    
    def get_status(self) -> Dict:
        """Get integration status"""
        return {
            "weather": integration_config.openmeteo_enabled,
            "news": self.news.is_available(),
            "spotify": self.spotify.is_available(),
            "email": self.email.is_available()
        }
    
    async def handle_command(self, command: str, intent: str, params: Dict = None) -> Dict:
        """Handle integration-specific commands"""
        params = params or {}
        
        if intent == "weather":
            location = params.get("location", "New York")  # Default location
            weather = self.weather.get_weather(location=location)
            if weather:
                return {
                    "success": True,
                    "message": self.weather.format_weather(weather),
                    "data": weather
                }
            return {"success": False, "message": "Could not fetch weather"}
        
        elif intent == "news":
            category = params.get("category", "general")
            articles = self.news.get_top_headlines(category=category)
            return {
                "success": True,
                "message": self.news.format_news(articles),
                "data": articles
            }
        
        elif intent == "music":
            action = params.get("action", "play")
            query = params.get("query")
            
            if action == "play":
                return self.spotify.play(search_query=query)
            elif action == "pause":
                return self.spotify.pause()
            elif action == "skip":
                return self.spotify.skip()
            elif action == "current":
                track = self.spotify.get_current_track()
                if track:
                    return {
                        "success": True,
                        "message": f"Currently playing: {track['name']} by {track['artist']}"
                    }
                return {"success": False, "message": "No track currently playing"}
        
        elif intent == "email":
            action = params.get("action", "draft")
            if action == "send":
                return self.email.send_email(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body")
                )
        
        return {"success": False, "message": "Unknown integration command"}
