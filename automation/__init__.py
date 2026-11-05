"""Automation - Browser Automation and Web Operations"""
import asyncio
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup
import requests

from config.settings import system_config
from utils.logger import get_logger

logger = get_logger("automation")

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str

class BrowserAutomation:
    """Playwright-based browser automation"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize browser"""
        if self._initialized:
            return
        
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,  # Show browser for transparency
                args=['--disable-blink-features=AutomationControlled']
            )
            self._initialized = True
            logger.info("Browser automation initialized")
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise
    
    async def close(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self._initialized = False
    
    async def new_page(self) -> Page:
        """Create new browser page"""
        if not self._initialized:
            await self.initialize()
        
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        return page
    
    async def search(self, query: str, engine: str = "google") -> Dict:
        """Perform web search and return results"""
        try:
            page = await self.new_page()
            
            if engine == "google":
                search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            else:
                search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            
            await page.goto(search_url, wait_until="domcontentloaded")
            await asyncio.sleep(1)  # Allow results to load
            
            # Extract search results
            results = await self._extract_search_results(page)
            
            await page.close()
            
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "message": f"Found {len(results)} results for '{query}'"
            }
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Search failed: {e}"
            }
    
    async def _extract_search_results(self, page: Page) -> List[Dict]:
        """Extract search results from page"""
        results = []
        
        try:
            # Try Google selectors
            selectors = [
                'div.g',  # Classic Google
                'div[data-ved]',  # Modern Google
                '.g .yuRUbf',  # Alternative
            ]
            
            for selector in selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements[:5]:  # Top 5 results
                        try:
                            title_el = await el.query_selector('h3')
                            link_el = await el.query_selector('a')
                            snippet_el = await el.query_selector('.VwiC3b, .s3v94d, .st')
                            
                            if title_el and link_el:
                                title = await title_el.inner_text()
                                href = await link_el.get_attribute('href')
                                snippet = await snippet_el.inner_text() if snippet_el else ""
                                
                                results.append({
                                    "title": title,
                                    "url": href,
                                    "snippet": snippet
                                })
                        except:
                            continue
                    
                    if results:
                        break
                        
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"Extraction error: {e}")
        
        return results
    
    async def navigate(self, url: str) -> Dict:
        """Navigate to URL"""
        try:
            if not self.page:
                self.page = await self.new_page()
            
            await self.page.goto(url, wait_until="domcontentloaded")
            
            return {
                "success": True,
                "url": url,
                "title": await self.page.title(),
                "message": f"Navigated to {url}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Navigation failed: {e}"
            }
    
    async def click(self, selector: str) -> Dict:
        """Click element by selector"""
        try:
            if not self.page:
                return {"success": False, "message": "No active page"}
            
            await self.page.click(selector)
            return {"success": True, "message": f"Clicked {selector}"}
        except Exception as e:
            return {"success": False, "message": f"Click failed: {e}"}
    
    async def type_text(self, selector: str, text: str, submit: bool = False) -> Dict:
        """Type text into element"""
        try:
            if not self.page:
                return {"success": False, "message": "No active page"}
            
            await self.page.fill(selector, text)
            if submit:
                await self.page.press(selector, "Enter")
            
            return {"success": True, "message": f"Typed text into {selector}"}
        except Exception as e:
            return {"success": False, "message": f"Type failed: {e}"}
    
    async def extract_data(self, selector: str = None) -> Dict:
        """Extract data from current page"""
        try:
            if not self.page:
                return {"success": False, "message": "No active page"}
            
            if selector:
                elements = await self.page.query_selector_all(selector)
                data = []
                for el in elements:
                    text = await el.inner_text()
                    data.append(text)
                return {
                    "success": True,
                    "data": data,
                    "count": len(data)
                }
            else:
                # Extract page text
                content = await self.page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                # Remove script/style
                for script in soup(["script", "style"]):
                    script.decompose()
                
                text = soup.get_text(separator='\n', strip=True)
                return {
                    "success": True,
                    "title": await self.page.title(),
                    "text_preview": text[:1000],
                    "url": self.page.url
                }
                
        except Exception as e:
            return {"success": False, "message": f"Extraction failed: {e}"}
    
    async def fill_form(self, form_data: Dict[str, str]) -> Dict:
        """Fill form fields"""
        try:
            if not self.page:
                return {"success": False, "message": "No active page"}
            
            for selector, value in form_data.items():
                await self.page.fill(selector, value)
            
            return {
                "success": True,
                "message": f"Filled {len(form_data)} form fields"
            }
        except Exception as e:
            return {"success": False, "message": f"Form fill failed: {e}"}
    
    async def execute_browser_action(self, action: str, target: str) -> Dict:
        """Execute browser action by type"""
        action_map = {
            "click": lambda: self.click(target),
            "type": lambda: self.type_text("input", target),
            "navigate": lambda: self.navigate(target),
            "search": lambda: self.search(target),
            "extract": lambda: self.extract_data(target),
        }
        
        handler = action_map.get(action)
        if handler:
            return await handler()
        
        return {"success": False, "message": f"Unknown action: {action}"}
    
    async def find_and_open(self, query: str, result_index: int = 0) -> Dict:
        """Search and open specific result"""
        try:
            search_results = await self.search(query)
            
            if not search_results.get("success") or not search_results.get("results"):
                return {"success": False, "message": "No results found"}
            
            results = search_results["results"]
            if result_index >= len(results):
                result_index = 0
            
            target_url = results[result_index].get("url")
            if target_url:
                nav_result = await self.navigate(target_url)
                return {
                    "success": True,
                    "message": f"Opened: {results[result_index].get('title', target_url)}",
                    "url": target_url,
                    "search_results": results
                }
            
            return {"success": False, "message": "Could not extract URL from results"}
            
        except Exception as e:
            return {"success": False, "message": f"Find and open failed: {e}"}

class SmartSearcher:
    """High-level search with result processing"""
    
    def __init__(self, browser: BrowserAutomation):
        self.browser = browser
    
    async def smart_search(self, query: str, intent: str = None) -> Dict:
        """
        Perform intelligent search based on intent
        """
        # Enhance query based on intent
        enhanced_query = self._enhance_query(query, intent)
        
        # Perform search
        results = await self.browser.search(enhanced_query)
        
        if not results.get("success"):
            return results
        
        # Process and rank results
        processed = self._process_results(results["results"], intent)
        
        return {
            "success": True,
            "query": enhanced_query,
            "results": processed,
            "best_result": processed[0] if processed else None,
            "message": f"Found {len(processed)} relevant results"
        }
    
    def _enhance_query(self, query: str, intent: str = None) -> str:
        """Enhance search query"""
        enhancements = {
            "course": "best tutorial course learn",
            "documentation": "official documentation reference",
            "news": "latest news today",
            "product": "review best buy",
            "recipe": "recipe how to make",
        }
        
        if intent and intent in enhancements:
            return f"{query} {enhancements[intent]}"
        return query
    
    def _process_results(self, results: List[Dict], intent: str = None) -> List[Dict]:
        """Process and rank results"""
        # Add relevance scoring
        for r in results:
            score = 0
            
            # Prefer certain domains based on intent
            url = r.get("url", "")
            if intent == "course":
                if any(d in url for d in ["coursera", "udemy", "youtube", "tutorial"]):
                    score += 2
            elif intent == "documentation":
                if any(d in url for d in ["docs.", "documentation", "api.", "dev."]):
                    score += 2
            
            # Prefer results with meaningful snippets
            if len(r.get("snippet", "")) > 50:
                score += 1
            
            r["relevance_score"] = score
        
        # Sort by relevance
        results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return results

# Convenience function for quick searches
async def quick_search(query: str) -> List[Dict]:
    """Quick search without persistent browser"""
    automation = BrowserAutomation()
    try:
        await automation.initialize()
        results = await automation.search(query)
        return results.get("results", [])
    finally:
        await automation.close()
