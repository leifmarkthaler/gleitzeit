"""
Result Cache System for Gleitzeit

Provides consistent caching and retrieval of workflow results
for further processing, analysis, and data pipeline integration.
"""

import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import asyncio

from .redis_client import RedisClient


class ResultCache:
    """
    Unified result caching system for Gleitzeit workflows
    
    Supports multiple storage backends:
    - Redis (primary, fast access)
    - File system (backup, serialization)
    - In-memory (fast lookup)
    """
    
    def __init__(
        self,
        redis_client: Optional[RedisClient] = None,
        cache_dir: Optional[Path] = None,
        enable_file_backup: bool = True
    ):
        self.redis_client = redis_client
        self.cache_dir = cache_dir or Path("./workflow_cache")
        self.enable_file_backup = enable_file_backup
        self.memory_cache: Dict[str, Dict] = {}
        
        # Ensure cache directory exists
        if self.enable_file_backup:
            self.cache_dir.mkdir(exist_ok=True)
    
    async def store_workflow_result(
        self, 
        workflow_id: str, 
        workflow_result: Dict[str, Any],
        tags: Optional[List[str]] = None
    ) -> bool:
        """Store workflow result in all enabled backends"""
        
        # Add metadata
        result_data = {
            "workflow_id": workflow_id,
            "stored_at": datetime.utcnow().isoformat(),
            "tags": tags or [],
            "result": workflow_result
        }
        
        success = True
        
        # Store in Redis
        if self.redis_client:
            try:
                await self.redis_client.redis.hset(
                    f"cached_result:{workflow_id}",
                    mapping={
                        "data": json.dumps(result_data),
                        "stored_at": result_data["stored_at"]
                    }
                )
                await self.redis_client.redis.expire(f"cached_result:{workflow_id}", 86400 * 30)  # 30 days
                
                # Add to index
                await self.redis_client.redis.sadd("cached_results:index", workflow_id)
                
            except Exception as e:
                print(f"⚠️  Redis storage failed: {e}")
                success = False
        
        # Store in file system
        if self.enable_file_backup:
            try:
                cache_file = self.cache_dir / f"{workflow_id}.json"
                with open(cache_file, 'w') as f:
                    json.dump(result_data, f, indent=2)
                    
                # Also store as pickle for complex objects
                pickle_file = self.cache_dir / f"{workflow_id}.pkl"
                with open(pickle_file, 'wb') as f:
                    pickle.dump(result_data, f)
                    
            except Exception as e:
                print(f"⚠️  File storage failed: {e}")
                success = False
        
        # Store in memory cache
        self.memory_cache[workflow_id] = result_data
        
        return success
    
    async def get_workflow_result(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve workflow result from cache"""
        
        # Try memory cache first (fastest)
        if workflow_id in self.memory_cache:
            return self.memory_cache[workflow_id]
        
        # Try Redis (fast)
        if self.redis_client:
            try:
                data = await self.redis_client.redis.hget(f"cached_result:{workflow_id}", "data")
                if data:
                    result_data = json.loads(data)
                    self.memory_cache[workflow_id] = result_data  # Cache in memory
                    return result_data
            except Exception as e:
                print(f"⚠️  Redis retrieval failed: {e}")
        
        # Try file system (backup)
        if self.enable_file_backup:
            try:
                cache_file = self.cache_dir / f"{workflow_id}.json"
                if cache_file.exists():
                    with open(cache_file, 'r') as f:
                        result_data = json.load(f)
                        self.memory_cache[workflow_id] = result_data  # Cache in memory
                        return result_data
            except Exception as e:
                print(f"⚠️  File retrieval failed: {e}")
        
        return None
    
    async def list_cached_results(
        self, 
        tags: Optional[List[str]] = None,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """List all cached results with optional filtering"""
        
        results = []
        
        # Get from Redis index
        if self.redis_client:
            try:
                workflow_ids = await self.redis_client.redis.smembers("cached_results:index")
                for workflow_id in workflow_ids:
                    result = await self.get_workflow_result(workflow_id.decode() if isinstance(workflow_id, bytes) else workflow_id)
                    if result:
                        # Apply filters
                        if tags and not any(tag in result.get("tags", []) for tag in tags):
                            continue
                        if since and datetime.fromisoformat(result["stored_at"]) < since:
                            continue
                        results.append(result)
            except Exception as e:
                print(f"⚠️  Redis listing failed: {e}")
        
        # Fallback to file system
        if not results and self.enable_file_backup:
            try:
                for cache_file in self.cache_dir.glob("*.json"):
                    workflow_id = cache_file.stem
                    result = await self.get_workflow_result(workflow_id)
                    if result:
                        # Apply filters
                        if tags and not any(tag in result.get("tags", []) for tag in tags):
                            continue
                        if since and datetime.fromisoformat(result["stored_at"]) < since:
                            continue
                        results.append(result)
            except Exception as e:
                print(f"⚠️  File listing failed: {e}")
        
        # Sort by stored_at (newest first)
        results.sort(key=lambda x: x["stored_at"], reverse=True)
        return results
    
    async def get_results_by_tags(self, tags: List[str]) -> List[Dict[str, Any]]:
        """Get all results with specific tags"""
        return await self.list_cached_results(tags=tags)
    
    async def get_recent_results(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get results from the last N hours"""
        since = datetime.utcnow() - timedelta(hours=hours)
        return await self.list_cached_results(since=since)
    
    def get_task_results(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract individual task results from workflow result"""
        return result_data.get("result", {}).get("results", {})
    
    def get_task_result(self, result_data: Dict[str, Any], task_name: str) -> Optional[Any]:
        """Get specific task result by name"""
        task_results = self.get_task_results(result_data)
        return task_results.get(task_name)
    
    async def export_results(
        self, 
        output_file: Path,
        format: str = "json",
        tags: Optional[List[str]] = None
    ) -> bool:
        """Export cached results to file"""
        
        results = await self.list_cached_results(tags=tags)
        
        try:
            if format.lower() == "json":
                with open(output_file, 'w') as f:
                    json.dump(results, f, indent=2)
            elif format.lower() == "pickle":
                with open(output_file, 'wb') as f:
                    pickle.dump(results, f)
            else:
                raise ValueError(f"Unsupported format: {format}")
                
            print(f"✅ Exported {len(results)} results to {output_file}")
            return True
            
        except Exception as e:
            print(f"❌ Export failed: {e}")
            return False
    
    async def clear_cache(self, older_than_days: Optional[int] = None) -> int:
        """Clear cache entries, optionally only older ones"""
        
        cleared = 0
        cutoff_date = None
        if older_than_days:
            cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
        
        # Clear from Redis
        if self.redis_client:
            try:
                workflow_ids = await self.redis_client.redis.smembers("cached_results:index")
                for workflow_id in workflow_ids:
                    workflow_id_str = workflow_id.decode() if isinstance(workflow_id, bytes) else workflow_id
                    
                    if cutoff_date:
                        # Check if old enough to delete
                        result = await self.get_workflow_result(workflow_id_str)
                        if result and datetime.fromisoformat(result["stored_at"]) > cutoff_date:
                            continue
                    
                    # Delete from Redis
                    await self.redis_client.redis.delete(f"cached_result:{workflow_id_str}")
                    await self.redis_client.redis.srem("cached_results:index", workflow_id_str)
                    cleared += 1
                    
            except Exception as e:
                print(f"⚠️  Redis clearing failed: {e}")
        
        # Clear from file system
        if self.enable_file_backup:
            try:
                for cache_file in self.cache_dir.glob("*.json"):
                    if cutoff_date:
                        # Check file modification time
                        if cache_file.stat().st_mtime > cutoff_date.timestamp():
                            continue
                    
                    cache_file.unlink()  # Delete JSON
                    pickle_file = self.cache_dir / f"{cache_file.stem}.pkl"
                    if pickle_file.exists():
                        pickle_file.unlink()  # Delete pickle
                    cleared += 1
                    
            except Exception as e:
                print(f"⚠️  File clearing failed: {e}")
        
        # Clear memory cache
        if cutoff_date:
            to_remove = []
            for workflow_id, result_data in self.memory_cache.items():
                if datetime.fromisoformat(result_data["stored_at"]) < cutoff_date:
                    to_remove.append(workflow_id)
            for workflow_id in to_remove:
                del self.memory_cache[workflow_id]
        else:
            self.memory_cache.clear()
        
        print(f"🗑️  Cleared {cleared} cached results")
        return cleared


# Convenience functions for easy access
async def store_result(workflow_id: str, result: Dict[str, Any], tags: List[str] = None) -> bool:
    """Quick function to store a workflow result"""
    cache = ResultCache()
    return await cache.store_workflow_result(workflow_id, result, tags)

async def get_result(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a workflow result"""
    cache = ResultCache()
    return await cache.get_workflow_result(workflow_id)

async def list_results(tags: List[str] = None) -> List[Dict[str, Any]]:
    """Quick function to list workflow results"""
    cache = ResultCache()
    return await cache.list_cached_results(tags=tags)