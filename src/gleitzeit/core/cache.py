"""
LRU Cache implementation for Gleitzeit.

Provides bounded caching with automatic eviction to prevent memory leaks.
"""

import time
import logging
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)


class LRUCache:
    """
    Thread-safe LRU (Least Recently Used) cache with TTL support.

    Features:
    - Bounded size with automatic eviction
    - Optional TTL per entry
    - Thread-safe operations
    - Cache hit/miss statistics
    """

    def __init__(self, max_size: int = 1000, default_ttl: Optional[int] = None):
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds (None for no expiry)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, Tuple[Any, Optional[float]]] = OrderedDict()
        self._lock = Lock()

        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get value from cache.

        Args:
            key: Cache key
            default: Default value if not found or expired

        Returns:
            Cached value or default
        """
        with self._lock:
            if key not in self._cache:
                self.misses += 1
                return default

            value, expiry = self._cache[key]

            # Check if expired
            if expiry and time.time() > expiry:
                del self._cache[key]
                self.misses += 1
                logger.debug(f"Cache entry expired: {key}")
                return default

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (overrides default_ttl)
        """
        with self._lock:
            # Calculate expiry
            if ttl is not None:
                expiry = time.time() + ttl
            elif self.default_ttl is not None:
                expiry = time.time() + self.default_ttl
            else:
                expiry = None

            # If key exists, move to end
            if key in self._cache:
                self._cache.move_to_end(key)

            # Set value
            self._cache[key] = (value, expiry)

            # Evict if over size limit
            while len(self._cache) > self.max_size:
                evicted_key = next(iter(self._cache))
                del self._cache[evicted_key]
                self.evictions += 1
                logger.debug(f"Evicted cache entry: {evicted_key}")

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            logger.info(f"Cache cleared. Stats - hits: {self.hits}, misses: {self.misses}, evictions: {self.evictions}")

    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "hit_rate": f"{hit_rate:.1f}%",
                "total_requests": total_requests
            }

    def cleanup_expired(self) -> int:
        """
        Remove expired entries.

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            current_time = time.time()
            expired_keys = []

            for key, (_, expiry) in self._cache.items():
                if expiry and current_time > expiry:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)


class AsyncLRUCache:
    """
    Async-friendly LRU cache wrapper.

    Uses the synchronous LRUCache internally but provides
    an async interface for compatibility with async code.
    """

    def __init__(self, max_size: int = 1000, default_ttl: Optional[int] = None):
        """
        Initialize async LRU cache.

        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
        """
        self._cache = LRUCache(max_size, default_ttl)

    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        return self._cache.get(key, default)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache."""
        self._cache.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        return self._cache.delete(key)

    async def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    async def size(self) -> int:
        """Get current cache size."""
        return self._cache.size()

    async def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return self._cache.stats()

    async def cleanup_expired(self) -> int:
        """Remove expired entries."""
        return self._cache.cleanup_expired()


# Global workflow cache instance
_workflow_cache: Optional[LRUCache] = None


def get_workflow_cache(max_size: int = 1000, ttl: int = 3600) -> LRUCache:
    """
    Get or create the global workflow cache.

    Args:
        max_size: Maximum cache size
        ttl: Default TTL in seconds (1 hour default)

    Returns:
        LRUCache instance
    """
    global _workflow_cache
    if _workflow_cache is None:
        _workflow_cache = LRUCache(max_size=max_size, default_ttl=ttl)
        logger.info(f"Created workflow cache with max_size={max_size}, ttl={ttl}")
    return _workflow_cache