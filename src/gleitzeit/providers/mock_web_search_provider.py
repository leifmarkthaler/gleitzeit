"""
Mock Web Search Provider for Gleitzeit V4

Mock implementation of a web search service for testing and demonstration.
Implements the web-search/v1 protocol with simulated search functionality.
"""

import logging
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import hashlib
import random

from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class MockWebSearchProvider(ProtocolProvider):
    """
    Mock web search provider for testing
    
    Simulates web search functionality without making actual HTTP requests.
    Useful for testing workflows and system functionality.
    
    Supported methods:
    - search: Perform web search (mocked)
    - suggest: Get search suggestions (mocked)
    - trending: Get trending topics (mocked)
    """
    
    def __init__(self, provider_id: str = "mock-web-search-1"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="web-search/v1",
            name="Mock Web Search Provider",
            description="Mock web search provider for testing and development"
        )
        
        # Mock data
        self.trending_topics = [
            "artificial intelligence",
            "climate change",
            "space exploration",
            "renewable energy",
            "quantum computing",
            "machine learning",
            "blockchain technology",
            "virtual reality",
            "biotechnology",
            "robotics"
        ]
        
        self.sample_domains = [
            "example.com",
            "techblog.net", 
            "sciencenews.org",
            "innovate.co",
            "futuretech.io",
            "researchhub.edu",
            "digitalworld.com",
            "techreview.org"
        ]
    
    async def initialize(self) -> None:
        """Initialize the mock web search provider"""
        logger.info(f"Mock web search provider {self.provider_id} initialized")
    
    async def shutdown(self) -> None:
        """Shutdown the mock web search provider"""
        logger.info(f"Mock web search provider {self.provider_id} shutdown")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC method calls"""
        if method == "search":
            return await self._handle_search(params)
        
        elif method == "suggest":
            return await self._handle_suggest(params)
        
        elif method == "trending":
            return await self._handle_trending(params)
        
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _handle_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle search requests"""
        query = params.get("query", "")
        max_results = params.get("max_results", 10)
        safe_search = params.get("safe_search", True)
        
        if not query:
            raise ValueError("Query parameter is required")
        
        if max_results > 100:
            raise ValueError("max_results cannot exceed 100")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Generate deterministic but varied results based on query
        query_hash = hashlib.md5(query.encode()).hexdigest()
        random.seed(int(query_hash[:8], 16))  # Use hash for deterministic randomness
        
        results = []
        for i in range(min(max_results, random.randint(3, 15))):
            domain = random.choice(self.sample_domains)
            
            result = {
                "title": f"{query.title()} - Result {i + 1}",
                "url": f"https://{domain}/article/{query_hash[:8]}-{i}",
                "snippet": f"This article discusses {query} and related topics. "
                          f"Learn more about {query} and its applications in modern technology. "
                          f"Updated information about {query} from {domain}.",
                "domain": domain,
                "last_updated": datetime.utcnow().isoformat(),
                "relevance_score": round(random.uniform(0.6, 1.0), 2)
            }
            results.append(result)
        
        # Sort by relevance score
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        # Create combined text for downstream processing
        combined_text = " ".join([r["title"] + " " + r["snippet"] for r in results])
        
        return {
            "query": query,
            "results": results,
            "total_found": len(results),
            "search_time_ms": random.randint(100, 800),
            "safe_search": safe_search,
            "combined_text": combined_text,
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_suggest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle search suggestion requests"""
        query = params.get("query", "")
        max_suggestions = params.get("max_suggestions", 5)
        
        if not query:
            raise ValueError("Query parameter is required")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # Generate suggestions based on query
        suggestions = []
        
        # Add query variations
        if len(query) > 2:
            base_suggestions = [
                f"{query} tutorial",
                f"{query} examples", 
                f"{query} best practices",
                f"how to {query}",
                f"{query} guide",
                f"learn {query}",
                f"{query} tools",
                f"{query} 2024"
            ]
            
            # Add some trending topics that might relate
            for topic in random.sample(self.trending_topics, min(3, len(self.trending_topics))):
                if topic.lower() != query.lower():
                    suggestions.append(f"{query} {topic}")
            
            suggestions.extend(base_suggestions)
            
            # Limit and randomize
            suggestions = random.sample(suggestions, min(max_suggestions, len(suggestions)))
        
        return {
            "query": query,
            "suggestions": suggestions,
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_trending(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trending topics requests"""
        category = params.get("category", "all")
        max_topics = params.get("max_topics", 10)
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.2, 0.8))
        
        # Return trending topics (shuffled for variety)
        topics = random.sample(self.trending_topics, min(max_topics, len(self.trending_topics)))
        
        trending_data = []
        for i, topic in enumerate(topics):
            trending_data.append({
                "topic": topic,
                "rank": i + 1,
                "search_volume": random.randint(10000, 1000000),
                "change_percent": round(random.uniform(-50, 200), 1),
                "category": random.choice(["technology", "science", "general"])
            })
        
        return {
            "category": category,
            "trending_topics": trending_data,
            "total_topics": len(trending_data),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        return {
            "status": "healthy",
            "details": "Mock web search provider is operational",
            "provider_id": self.provider_id,
            "available_methods": self.get_supported_methods(),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["web/search", "web/suggest", "web/trending"]