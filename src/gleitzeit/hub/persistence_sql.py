"""
SQL-based Hub Persistence Adapter using SQLite

Provides SQL persistence for hub resource state, metrics, and distributed locking.
Alternative to Redis for environments preferring SQL databases.
"""

import json
import logging
import aiosqlite
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

from gleitzeit.hub.persistence import HubPersistenceAdapter
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)


class SQLiteHubAdapter(HubPersistenceAdapter):
    """SQLite-based persistence for hub state"""
    
    def __init__(self, db_path: str = "gleitzeit_hub.db"):
        """
        Initialize SQLite adapter
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize SQLite connection and create tables"""
        if self._initialized:
            return
        
        try:
            # Ensure parent directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Connect to database
            self.db = await aiosqlite.connect(self.db_path)
            self.db.row_factory = aiosqlite.Row
            
            # Enable WAL mode for better concurrency
            await self.db.execute("PRAGMA journal_mode=WAL")
            
            # Create tables
            await self._create_tables()
            await self.db.commit()
            
            self._initialized = True
            logger.info(f"SQLite hub adapter initialized: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize SQLite adapter: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Close SQLite connection"""
        if self.db:
            await self.db.close()
            self.db = None
            self._initialized = False
            logger.info("SQLite hub adapter shut down")
    
    async def _create_tables(self) -> None:
        """Create database tables for hub persistence"""
        
        # Resource instances table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS resource_instances (
                instance_id TEXT PRIMARY KEY,
                hub_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata TEXT,      -- JSON
                tags TEXT,          -- JSON array
                capabilities TEXT,  -- JSON array
                health_checks_failed INTEGER DEFAULT 0,
                last_health_check TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Metrics time series table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS resource_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                cpu_percent REAL DEFAULT 0.0,
                memory_percent REAL DEFAULT 0.0,
                memory_mb REAL DEFAULT 0.0,
                disk_io_mb REAL DEFAULT 0.0,
                network_io_mb REAL DEFAULT 0.0,
                request_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                avg_response_time_ms REAL DEFAULT 0.0,
                p95_response_time_ms REAL DEFAULT 0.0,
                p99_response_time_ms REAL DEFAULT 0.0,
                active_connections INTEGER DEFAULT 0,
                queued_requests INTEGER DEFAULT 0,
                custom_metrics TEXT,  -- JSON
                FOREIGN KEY (instance_id) REFERENCES resource_instances(instance_id) ON DELETE CASCADE
            )
        """)
        
        # Distributed locks table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS resource_locks (
                resource_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for better performance
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_hub_instances ON resource_instances(hub_id)
        """)
        
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_instance_status ON resource_instances(status)
        """)
        
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_instance ON resource_metrics(instance_id, timestamp)
        """)
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            # Convert instance to dict for storage
            instance_data = {
                'instance_id': instance.id,
                'hub_id': hub_id,
                'name': instance.name,
                'type': instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
                'endpoint': instance.endpoint,
                'status': instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
                'metadata': json.dumps(instance.metadata),
                'tags': json.dumps(list(instance.tags)),
                'capabilities': json.dumps(list(instance.capabilities)),
                'health_checks_failed': instance.health_checks_failed,
                'last_health_check': instance.last_health_check.isoformat() if instance.last_health_check else None,
                'created_at': instance.created_at.isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            # Upsert instance
            await self.db.execute("""
                INSERT OR REPLACE INTO resource_instances 
                (instance_id, hub_id, name, type, endpoint, status, metadata, tags, 
                 capabilities, health_checks_failed, last_health_check, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                instance_data['instance_id'],
                instance_data['hub_id'],
                instance_data['name'],
                instance_data['type'],
                instance_data['endpoint'],
                instance_data['status'],
                instance_data['metadata'],
                instance_data['tags'],
                instance_data['capabilities'],
                instance_data['health_checks_failed'],
                instance_data['last_health_check'],
                instance_data['created_at'],
                instance_data['updated_at']
            ))
            
            await self.db.commit()
            logger.debug(f"Saved instance {instance.id} to SQLite")
            
        except Exception as e:
            logger.error(f"Failed to save instance {instance.id}: {e}")
            raise
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            cursor = await self.db.execute("""
                SELECT * FROM resource_instances WHERE instance_id = ?
            """, (instance_id,))
            
            row = await cursor.fetchone()
            if row:
                return {
                    'id': row['instance_id'],
                    'hub_id': row['hub_id'],
                    'name': row['name'],
                    'type': row['type'],
                    'endpoint': row['endpoint'],
                    'status': row['status'],
                    'metadata': json.loads(row['metadata']) if row['metadata'] else {},
                    'tags': json.loads(row['tags']) if row['tags'] else [],
                    'capabilities': json.loads(row['capabilities']) if row['capabilities'] else [],
                    'health_checks_failed': row['health_checks_failed'],
                    'last_health_check': row['last_health_check'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None
            
        except Exception as e:
            logger.error(f"Failed to load instance {instance_id}: {e}")
            return None
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            cursor = await self.db.execute("""
                SELECT * FROM resource_instances WHERE hub_id = ?
            """, (hub_id,))
            
            rows = await cursor.fetchall()
            instances = []
            
            for row in rows:
                instances.append({
                    'id': row['instance_id'],
                    'hub_id': row['hub_id'],
                    'name': row['name'],
                    'type': row['type'],
                    'endpoint': row['endpoint'],
                    'status': row['status'],
                    'metadata': json.loads(row['metadata']) if row['metadata'] else {},
                    'tags': json.loads(row['tags']) if row['tags'] else [],
                    'capabilities': json.loads(row['capabilities']) if row['capabilities'] else [],
                    'health_checks_failed': row['health_checks_failed'],
                    'last_health_check': row['last_health_check'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                })
            
            return instances
            
        except Exception as e:
            logger.error(f"Failed to list instances for hub {hub_id}: {e}")
            return []
    
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            # Delete instance (metrics will cascade delete)
            await self.db.execute("""
                DELETE FROM resource_instances WHERE instance_id = ?
            """, (instance_id,))
            
            await self.db.commit()
            logger.debug(f"Deleted instance {instance_id} from SQLite")
            
        except Exception as e:
            logger.error(f"Failed to delete instance {instance_id}: {e}")
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            await self.db.execute("""
                INSERT INTO resource_metrics 
                (instance_id, timestamp, cpu_percent, memory_percent, memory_mb,
                 disk_io_mb, network_io_mb, request_count, error_count,
                 avg_response_time_ms, p95_response_time_ms, p99_response_time_ms,
                 active_connections, queued_requests, custom_metrics)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                instance_id,
                datetime.utcnow().isoformat(),
                metrics.cpu_percent,
                metrics.memory_percent,
                metrics.memory_mb,
                metrics.disk_io_mb,
                metrics.network_io_mb,
                metrics.request_count,
                metrics.error_count,
                metrics.avg_response_time_ms,
                metrics.p95_response_time_ms,
                metrics.p99_response_time_ms,
                metrics.active_connections,
                metrics.queued_requests,
                json.dumps(metrics.custom_metrics)
            ))
            
            # Clean up old metrics (keep last 24 hours)
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            await self.db.execute("""
                DELETE FROM resource_metrics 
                WHERE instance_id = ? AND timestamp < ?
            """, (instance_id, cutoff))
            
            await self.db.commit()
            logger.debug(f"Saved metrics for instance {instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to save metrics for {instance_id}: {e}")
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            cursor = await self.db.execute("""
                SELECT * FROM resource_metrics 
                WHERE instance_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (
                instance_id,
                start_time.isoformat(),
                end_time.isoformat()
            ))
            
            rows = await cursor.fetchall()
            metrics_list = []
            
            for row in rows:
                metrics_list.append({
                    'timestamp': row['timestamp'],
                    'cpu_percent': row['cpu_percent'],
                    'memory_percent': row['memory_percent'],
                    'memory_mb': row['memory_mb'],
                    'request_count': row['request_count'],
                    'error_count': row['error_count'],
                    'avg_response_time_ms': row['avg_response_time_ms'],
                    'p95_response_time_ms': row['p95_response_time_ms'],
                    'p99_response_time_ms': row['p99_response_time_ms'],
                    'active_connections': row['active_connections'],
                    'queued_requests': row['queued_requests'],
                    'custom': json.loads(row['custom_metrics']) if row['custom_metrics'] else {}
                })
            
            return metrics_list
            
        except Exception as e:
            logger.error(f"Failed to get metrics history for {instance_id}: {e}")
            return []
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for resource allocation"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            now = datetime.utcnow()
            expires_at = now + timedelta(seconds=timeout)
            
            # Clean up expired locks first
            await self.db.execute("""
                DELETE FROM resource_locks WHERE expires_at < ?
            """, (now.isoformat(),))
            
            # Try to acquire lock
            try:
                await self.db.execute("""
                    INSERT INTO resource_locks (resource_id, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                """, (resource_id, owner_id, now.isoformat(), expires_at.isoformat()))
                
                await self.db.commit()
                logger.debug(f"Acquired lock for {resource_id} by {owner_id}")
                return True
                
            except aiosqlite.IntegrityError:
                # Lock already exists
                return False
                
        except Exception as e:
            logger.error(f"Failed to acquire lock for {resource_id}: {e}")
            return False
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            # Only release if we own the lock
            await self.db.execute("""
                DELETE FROM resource_locks 
                WHERE resource_id = ? AND owner_id = ?
            """, (resource_id, owner_id))
            
            await self.db.commit()
            logger.debug(f"Released lock for {resource_id} by {owner_id}")
            
        except Exception as e:
            logger.error(f"Failed to release lock for {resource_id}: {e}")
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            new_expires = (datetime.utcnow() + timedelta(seconds=timeout)).isoformat()
            
            # Update expiration if we own the lock
            cursor = await self.db.execute("""
                UPDATE resource_locks 
                SET expires_at = ?
                WHERE resource_id = ? AND owner_id = ?
            """, (new_expires, resource_id, owner_id))
            
            await self.db.commit()
            
            # Check if update affected any rows
            if cursor.rowcount > 0:
                logger.debug(f"Extended lock for {resource_id} by {owner_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to extend lock for {resource_id}: {e}")
            return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        if not self.db:
            raise RuntimeError("SQLite adapter not initialized")
        
        try:
            # Clean up expired locks first
            now = datetime.utcnow().isoformat()
            await self.db.execute("""
                DELETE FROM resource_locks WHERE expires_at < ?
            """, (now,))
            await self.db.commit()
            
            # Get current owner
            cursor = await self.db.execute("""
                SELECT owner_id FROM resource_locks 
                WHERE resource_id = ? AND expires_at >= ?
            """, (resource_id, now))
            
            row = await cursor.fetchone()
            return row['owner_id'] if row else None
            
        except Exception as e:
            logger.error(f"Failed to get lock owner for {resource_id}: {e}")
            return None