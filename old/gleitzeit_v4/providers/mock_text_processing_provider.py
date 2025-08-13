"""
Mock Text Processing Provider for Gleitzeit V4

Mock implementation of text processing services for testing and demonstration.
Implements the text-processing/v1 protocol with simulated NLP functionality.
"""

import logging
import asyncio
import re
from typing import Dict, List, Any
from datetime import datetime
import random
from collections import Counter

from .base import ProtocolProvider

logger = logging.getLogger(__name__)


class MockTextProcessingProvider(ProtocolProvider):
    """
    Mock text processing provider for testing
    
    Simulates natural language processing functionality without requiring
    external NLP libraries or services.
    
    Supported methods:
    - summarize: Create text summary (mocked)
    - extract_keywords: Extract keywords from text (basic implementation)
    - sentiment_analysis: Analyze sentiment (mocked)
    - translate: Translate text (mocked)
    - extract_entities: Extract named entities (basic implementation)
    """
    
    def __init__(self, provider_id: str = "mock-text-processing-1"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="text-processing/v1",
            name="Mock Text Processing Provider",
            description="Mock text processing provider for testing NLP workflows"
        )
        
        # Common stopwords for keyword extraction
        self.stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", 
            "of", "with", "by", "from", "as", "is", "are", "was", "were", "be", 
            "been", "being", "have", "has", "had", "do", "does", "did", "will", 
            "would", "could", "should", "may", "might", "must", "can", "this", 
            "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
            "me", "him", "her", "us", "them", "my", "your", "his", "her", "its",
            "our", "their", "about", "into", "through", "during", "before", 
            "after", "above", "below", "up", "down", "out", "off", "over", 
            "under", "again", "further", "then", "once"
        }
        
        # Mock sentiment lexicon
        self.positive_words = [
            "good", "great", "excellent", "amazing", "wonderful", "fantastic",
            "awesome", "brilliant", "outstanding", "superb", "perfect", "love",
            "like", "enjoy", "happy", "pleased", "satisfied", "delighted"
        ]
        
        self.negative_words = [
            "bad", "terrible", "awful", "horrible", "disappointing", "poor",
            "hate", "dislike", "annoying", "frustrating", "upset", "angry",
            "sad", "worried", "concerned", "problem", "issue", "wrong"
        ]
    
    async def initialize(self) -> None:
        """Initialize the mock text processing provider"""
        logger.info(f"Mock text processing provider {self.provider_id} initialized")
    
    async def shutdown(self) -> None:
        """Shutdown the mock text processing provider"""
        logger.info(f"Mock text processing provider {self.provider_id} shutdown")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC method calls"""
        if method == "summarize":
            return await self._handle_summarize(params)
        
        elif method == "extract_keywords":
            return await self._handle_extract_keywords(params)
        
        elif method == "sentiment_analysis":
            return await self._handle_sentiment_analysis(params)
        
        elif method == "translate":
            return await self._handle_translate(params)
        
        elif method == "extract_entities":
            return await self._handle_extract_entities(params)
        
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _handle_summarize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text summarization requests"""
        text = params.get("text", "")
        max_length = params.get("max_length", 200)
        
        if not text:
            raise ValueError("Text parameter is required")
        
        if max_length < 10:
            raise ValueError("max_length must be at least 10 characters")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(1.0, 3.0))
        
        # Simple summarization: take first and last sentences, plus some middle content
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) <= 2:
            summary = text[:max_length]
        else:
            # Take first sentence, a middle sentence, and last sentence
            summary_parts = [sentences[0]]
            
            if len(sentences) > 3:
                middle_idx = len(sentences) // 2
                summary_parts.append(sentences[middle_idx])
            
            summary_parts.append(sentences[-1])
            
            summary = ". ".join(summary_parts)
            
            if len(summary) > max_length:
                summary = summary[:max_length - 3] + "..."
        
        return {
            "original_length": len(text),
            "summary": summary,
            "summary_length": len(summary),
            "compression_ratio": round(len(summary) / len(text), 2),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_extract_keywords(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle keyword extraction requests"""
        text = params.get("text", "")
        max_keywords = params.get("max_keywords", 10)
        
        if not text:
            raise ValueError("Text parameter is required")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Simple keyword extraction based on word frequency
        # Remove punctuation and convert to lowercase
        clean_text = re.sub(r'[^\w\s]', '', text.lower())
        words = clean_text.split()
        
        # Filter out stopwords and short words
        keywords = [word for word in words 
                   if word not in self.stopwords and len(word) > 2]
        
        # Count word frequencies
        word_counts = Counter(keywords)
        
        # Get top keywords
        top_keywords = word_counts.most_common(max_keywords)
        
        keyword_data = []
        for word, count in top_keywords:
            keyword_data.append({
                "keyword": word,
                "frequency": count,
                "relevance_score": round(count / len(keywords), 3)
            })
        
        return {
            "keywords": keyword_data,
            "total_words_analyzed": len(words),
            "unique_keywords": len(word_counts),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_sentiment_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle sentiment analysis requests"""
        text = params.get("text", "")
        
        if not text:
            raise ValueError("Text parameter is required")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Simple sentiment analysis based on positive/negative word counting
        words = re.findall(r'\b\w+\b', text.lower())
        
        positive_count = sum(1 for word in words if word in self.positive_words)
        negative_count = sum(1 for word in words if word in self.negative_words)
        
        # Calculate sentiment scores
        total_sentiment_words = positive_count + negative_count
        
        if total_sentiment_words == 0:
            sentiment = "neutral"
            confidence = 0.5
            polarity = 0.0
        else:
            polarity = (positive_count - negative_count) / total_sentiment_words
            confidence = min(total_sentiment_words / len(words) * 5, 1.0)  # Max confidence = 1.0
            
            if polarity > 0.1:
                sentiment = "positive"
            elif polarity < -0.1:
                sentiment = "negative"
            else:
                sentiment = "neutral"
        
        return {
            "sentiment": sentiment,
            "polarity": round(polarity, 3),
            "confidence": round(confidence, 3),
            "positive_words_found": positive_count,
            "negative_words_found": negative_count,
            "total_words": len(words),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_translate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle translation requests (mocked)"""
        text = params.get("text", "")
        target_language = params.get("target_language", "es")
        source_language = params.get("source_language", "auto")
        
        if not text:
            raise ValueError("Text parameter is required")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(1.0, 3.0))
        
        # Mock translation - just add a prefix to indicate "translation"
        language_names = {
            "es": "Spanish",
            "fr": "French", 
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "ru": "Russian"
        }
        
        target_lang_name = language_names.get(target_language, target_language.upper())
        translated_text = f"[{target_lang_name} translation]: {text}"
        
        return {
            "translated_text": translated_text,
            "source_language": source_language,
            "target_language": target_language,
            "confidence": round(random.uniform(0.8, 0.95), 2),
            "original_length": len(text),
            "translated_length": len(translated_text),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _handle_extract_entities(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle named entity extraction requests"""
        text = params.get("text", "")
        entity_types = params.get("entity_types", ["PERSON", "ORG", "LOCATION"])
        
        if not text:
            raise ValueError("Text parameter is required")
        
        # Simulate processing delay
        await asyncio.sleep(random.uniform(0.8, 2.0))
        
        # Simple pattern-based entity extraction
        entities = []
        
        # Look for capitalized words (potential proper nouns)
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        
        # Mock entity classification
        for word in set(words):  # Remove duplicates
            # Random classification for demo purposes
            entity_type = random.choice(entity_types)
            confidence = round(random.uniform(0.6, 0.9), 2)
            
            entities.append({
                "text": word,
                "label": entity_type,
                "start_pos": text.find(word),
                "end_pos": text.find(word) + len(word),
                "confidence": confidence
            })
        
        # Sort by position in text
        entities.sort(key=lambda x: x["start_pos"])
        
        return {
            "entities": entities,
            "entity_count": len(entities),
            "entity_types_found": list(set(e["label"] for e in entities)),
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        return {
            "status": "healthy",
            "details": "Mock text processing provider is operational",
            "provider_id": self.provider_id,
            "available_methods": self.get_supported_methods(),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["summarize", "extract_keywords", "sentiment_analysis", "translate", "extract_entities"]