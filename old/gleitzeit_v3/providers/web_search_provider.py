"""
Web Search Provider for Gleitzeit V3

This provider demonstrates how to add a new provider with custom functions.
It supports web search functionality using a simple HTTP-based search API.
"""

import asyncio
import logging
import aiohttp
from typing import Dict, Any, List
import json
from urllib.parse import quote

from .base import BaseProvider

logger = logging.getLogger(__name__)


class WebSearchProvider(BaseProvider):
    """
    Web Search Provider - demonstrates adding new functionality
    
    Supported functions:
    - web_search: Search the web for information
    - web_summarize: Get and summarize a webpage
    """
    
    # Provider metadata for automatic discovery
    PROVIDER_TYPE = "web_search"
    SUPPORTED_FUNCTIONS = ["web_search", "web_summarize", "url_fetch"]
    
    def __init__(
        self, 
        provider_id: str = "web_search_provider",
        server_url: str = "http://localhost:8000"
    ):
        # Initialize base provider with our capabilities
        super().__init__(
            provider_id=provider_id,
            provider_name="Web Search Provider",
            provider_type="web_search",
            supported_functions=[
                "web_search",      # Search the web
                "web_summarize",   # Summarize webpage content
                "url_fetch"        # Fetch URL content
            ],
            max_concurrent_tasks=3,  # Limit concurrent web requests
            server_url=server_url
        )
        
        # Provider-specific configuration
        self.session: aiohttp.ClientSession = None
        self.search_engine = "duckduckgo"  # Could be configurable
        
        logger.info("WebSearchProvider initialized")
    
    async def start(self):
        """Start the provider and initialize HTTP session"""
        # Create HTTP session for web requests
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Gleitzeit-WebSearch/1.0)'
            }
        )
        
        # Call parent start to handle server connection
        await super().start()
        
        logger.info("🌐 Web Search Provider started")
    
    async def stop(self):
        """Stop the provider and cleanup resources"""
        if self.session:
            await self.session.close()
            self.session = None
        
        await super().stop()
        logger.info("🛑 Web Search Provider stopped")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check for the web search provider
        
        Returns:
            Health status information
        """
        try:
            # Test basic HTTP connectivity
            if self.session:
                # Try a simple request to check internet connectivity
                async with self.session.get("https://httpbin.org/status/200", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        return {
                            "status": "healthy",
                            "http_session": "active",
                            "internet_connectivity": "ok"
                        }
                    else:
                        return {
                            "status": "degraded",
                            "http_session": "active",
                            "internet_connectivity": "limited",
                            "details": f"Test request returned status {response.status}"
                        }
            else:
                return {
                    "status": "unhealthy",
                    "http_session": "inactive",
                    "details": "No active HTTP session"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "details": "Health check failed"
            }
    
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """
        Execute a task - main entry point for task execution
        
        Args:
            task_type: Type of task (should be 'function' for function-based tasks)
            parameters: Task parameters including 'function' and function-specific params
            
        Returns:
            Task result based on the function executed
        """
        function = parameters.get("function")
        
        if not function:
            raise ValueError("Missing 'function' parameter")
        
        logger.info(f"Executing web search function: {function}")
        
        # Route to specific function handlers
        if function == "web_search":
            return await self._web_search(parameters)
        elif function == "web_summarize":
            return await self._web_summarize(parameters)
        elif function == "url_fetch":
            return await self._url_fetch(parameters)
        else:
            raise ValueError(f"Unsupported function: {function}")
    
    async def _web_search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform web search
        
        Parameters:
        - query: Search query string
        - max_results: Maximum number of results (default: 5)
        
        Returns:
        - results: List of search results with title, url, snippet
        """
        query = parameters.get("query")
        if not query:
            raise ValueError("Missing 'query' parameter for web search")
        
        max_results = parameters.get("max_results", 5)
        
        logger.info(f"Searching web for: '{query}' (max {max_results} results)")
        
        try:
            # Using DuckDuckGo Instant Answer API (simple example)
            # In production, you'd use a proper search API like Google Custom Search
            search_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            
            async with self.session.get(search_url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    
                    # Extract instant answer if available
                    if data.get("Answer"):
                        results.append({
                            "title": "Instant Answer",
                            "url": data.get("AnswerURL", ""),
                            "snippet": data["Answer"][:200],
                            "type": "instant_answer"
                        })
                    
                    # Extract related topics
                    for topic in data.get("RelatedTopics", [])[:max_results-len(results)]:
                        if isinstance(topic, dict) and "Text" in topic:
                            results.append({
                                "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                                "url": topic.get("FirstURL", ""),
                                "snippet": topic["Text"][:200],
                                "type": "related_topic"
                            })
                    
                    # If no good results, add a basic response
                    if not results:
                        results = [{
                            "title": f"Search: {query}",
                            "url": f"https://duckduckgo.com/?q={quote(query)}",
                            "snippet": f"Search results for '{query}' - please visit the URL for full results",
                            "type": "search_link"
                        }]
                    
                    return {
                        "query": query,
                        "results": results[:max_results],
                        "total_results": len(results),
                        "search_engine": "duckduckgo"
                    }
                else:
                    raise Exception(f"Search API returned status {response.status}")
        
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            # Return a fallback result instead of failing completely
            return {
                "query": query,
                "results": [{
                    "title": f"Search: {query}",
                    "url": f"https://duckduckgo.com/?q={quote(query)}",
                    "snippet": f"Unable to fetch search results. Please visit the URL manually. Error: {str(e)}",
                    "type": "error_fallback"
                }],
                "total_results": 0,
                "search_engine": "fallback",
                "error": str(e)
            }
    
    async def _url_fetch(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch content from a URL
        
        Parameters:
        - url: URL to fetch
        - max_length: Maximum content length (default: 5000 chars)
        
        Returns:
        - content: Text content of the page
        - title: Page title if available
        - status: HTTP status code
        """
        url = parameters.get("url")
        if not url:
            raise ValueError("Missing 'url' parameter for URL fetch")
        
        max_length = parameters.get("max_length", 5000)
        
        logger.info(f"Fetching URL: {url}")
        
        try:
            async with self.session.get(url) as response:
                content = await response.text()
                
                # Simple HTML parsing (in production, use BeautifulSoup or similar)
                title = ""
                if "<title>" in content.lower():
                    start = content.lower().find("<title>") + 7
                    end = content.lower().find("</title>", start)
                    if end > start:
                        title = content[start:end].strip()
                
                # Remove HTML tags (basic cleanup)
                import re
                clean_content = re.sub(r'<[^>]+>', ' ', content)
                clean_content = re.sub(r'\s+', ' ', clean_content).strip()
                
                if len(clean_content) > max_length:
                    clean_content = clean_content[:max_length] + "..."
                
                return {
                    "url": url,
                    "title": title,
                    "content": clean_content,
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                    "content_length": len(clean_content)
                }
        
        except Exception as e:
            logger.error(f"URL fetch failed for {url}: {e}")
            return {
                "url": url,
                "title": "",
                "content": f"Failed to fetch URL: {str(e)}",
                "status": 0,
                "error": str(e)
            }
    
    async def _web_summarize(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch and summarize webpage content
        
        Parameters:
        - url: URL to summarize
        - summary_length: Target summary length (default: 200 chars)
        
        Returns:
        - summary: Summarized content
        - title: Page title
        - url: Original URL
        """
        url = parameters.get("url")
        if not url:
            raise ValueError("Missing 'url' parameter for web summarize")
        
        summary_length = parameters.get("summary_length", 200)
        
        logger.info(f"Summarizing webpage: {url}")
        
        # First fetch the content
        fetch_result = await self._url_fetch({
            "url": url,
            "max_length": 2000  # Get more content for better summary
        })
        
        if fetch_result.get("error"):
            return {
                "url": url,
                "title": "",
                "summary": f"Could not fetch webpage for summarization: {fetch_result['error']}",
                "error": fetch_result["error"]
            }
        
        # Simple extractive summary (take first few sentences)
        content = fetch_result["content"]
        sentences = content.split('. ')
        
        summary = ""
        for sentence in sentences:
            if len(summary) + len(sentence) + 2 <= summary_length:
                summary += sentence + ". "
            else:
                break
        
        if not summary and content:
            # Fallback: just take first N characters
            summary = content[:summary_length].rsplit(' ', 1)[0] + "..."
        
        return {
            "url": url,
            "title": fetch_result.get("title", ""),
            "summary": summary.strip(),
            "original_length": len(content),
            "summary_length": len(summary)
        }