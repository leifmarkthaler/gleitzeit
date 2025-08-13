"""
Event Store for Gleitzeit V3

Persistent storage for events with support for:
- Event replay and auditing
- Event querying and filtering
- Event stream processing
- Debugging and troubleshooting
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import json

import redis.asyncio as redis

from .schemas import EventEnvelope, EventType, EventFilter

logger = logging.getLogger(__name__)


class EventStore(ABC):
    """Abstract base class for event storage"""
    
    @abstractmethod
    async def store_event(self, event: EventEnvelope):
        """Store an event"""
        pass
    
    @abstractmethod
    async def get_events(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_filter: Optional[EventFilter] = None,
        limit: Optional[int] = None
    ) -> List[EventEnvelope]:
        """Retrieve events matching criteria"""
        pass
    
    @abstractmethod
    async def get_event_by_id(self, event_id: str) -> Optional[EventEnvelope]:
        """Get a specific event by ID"""
        pass
    
    @abstractmethod
    async def get_workflow_events(self, workflow_id: str) -> List[EventEnvelope]:
        """Get all events for a specific workflow"""
        pass
    
    @abstractmethod
    async def get_task_events(self, task_id: str) -> List[EventEnvelope]:
        """Get all events for a specific task"""
        pass


class RedisEventStore(EventStore):
    """
    Redis-based event store with:
    - Sorted sets for time-based queries
    - Hash storage for event data
    - Secondary indexes for workflows/tasks
    - Stream processing support
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "gleitzeit_v3:events:",
        retention_days: int = 30,
        max_events_per_query: int = 10000
    ):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.retention_days = retention_days
        self.max_events_per_query = max_events_per_query
        
        self.redis_client: Optional[redis.Redis] = None
        
        # Redis key patterns
        self.events_sorted_set = f"{key_prefix}by_time"
        self.events_hash = f"{key_prefix}data"
        self.workflow_index = f"{key_prefix}by_workflow:"
        self.task_index = f"{key_prefix}by_task:"
        self.provider_index = f"{key_prefix}by_provider:"
        self.component_index = f"{key_prefix}by_component:"
        self.event_stream = f"{key_prefix}stream"
    
    async def connect(self):
        """Connect to Redis"""
        self.redis_client = redis.from_url(self.redis_url)
        
        # Test connection
        await self.redis_client.ping()
        logger.info(f"Connected to Redis event store: {self.redis_url}")
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
    
    async def store_event(self, event: EventEnvelope):
        """Store event in Redis with multiple indexes"""
        if not self.redis_client:
            await self.connect()
        
        try:
            # Serialize event
            event_data = event.json()
            timestamp_score = event.timestamp.timestamp()
            
            # Use Redis pipeline for atomic operation
            pipe = self.redis_client.pipeline()
            
            # 1. Add to time-ordered sorted set
            pipe.zadd(self.events_sorted_set, {event.event_id: timestamp_score})
            
            # 2. Store event data
            pipe.hset(self.events_hash, event.event_id, event_data)
            
            # 3. Add to workflow index
            if event.workflow_id:
                pipe.zadd(
                    f"{self.workflow_index}{event.workflow_id}",
                    {event.event_id: timestamp_score}
                )
            
            # 4. Add to task index
            if event.task_id:
                pipe.zadd(
                    f"{self.task_index}{event.task_id}",
                    {event.event_id: timestamp_score}
                )
            
            # 5. Add to provider index
            if event.provider_id:
                pipe.zadd(
                    f"{self.provider_index}{event.provider_id}",
                    {event.event_id: timestamp_score}
                )
            
            # 6. Add to component index
            pipe.zadd(
                f"{self.component_index}{event.source_component}",
                {event.event_id: timestamp_score}
            )
            
            # 7. Add to Redis stream for real-time processing
            stream_data = {
                'event_id': event.event_id,
                'event_type': event.event_type.value,
                'workflow_id': event.workflow_id or '',
                'task_id': event.task_id or '',
                'component': event.source_component,
                'severity': event.severity.value,
                'data': event_data
            }
            pipe.xadd(self.event_stream, stream_data)
            
            # 8. Set expiration for data retention
            expire_time = int(timedelta(days=self.retention_days).total_seconds())
            pipe.expire(f"{self.workflow_index}{event.workflow_id}", expire_time)
            pipe.expire(f"{self.task_index}{event.task_id}", expire_time)
            
            # Execute pipeline
            await pipe.execute()
            
            logger.debug(f"Stored event: {event.event_type} ({event.event_id})")
            
        except Exception as e:
            logger.error(f"Failed to store event {event.event_id}: {e}")
            raise
    
    async def get_events(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_filter: Optional[EventFilter] = None,
        limit: Optional[int] = None
    ) -> List[EventEnvelope]:
        """Get events within time range with optional filtering"""
        if not self.redis_client:
            await self.connect()
        
        try:
            # Convert timestamps to scores
            start_score = start_time.timestamp()
            end_score = (end_time or datetime.utcnow()).timestamp()
            
            # Get event IDs from sorted set
            event_ids = await self.redis_client.zrangebyscore(
                self.events_sorted_set,
                start_score,
                end_score,
                start=0,
                num=limit or self.max_events_per_query
            )
            
            if not event_ids:
                return []
            
            # Get event data
            events = []
            event_data_list = await self.redis_client.hmget(
                self.events_hash,
                *event_ids
            )
            
            for event_data in event_data_list:
                if event_data:
                    event = EventEnvelope.parse_raw(event_data)
                    
                    # Apply filter if provided
                    if event_filter is None or event_filter.matches(event):
                        events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to get events: {e}")
            raise
    
    async def get_event_by_id(self, event_id: str) -> Optional[EventEnvelope]:
        """Get specific event by ID"""
        if not self.redis_client:
            await self.connect()
        
        try:
            event_data = await self.redis_client.hget(self.events_hash, event_id)
            if event_data:
                return EventEnvelope.parse_raw(event_data)
            return None
            
        except Exception as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            raise
    
    async def get_workflow_events(self, workflow_id: str) -> List[EventEnvelope]:
        """Get all events for a workflow"""
        if not self.redis_client:
            await self.connect()
        
        try:
            # Get event IDs from workflow index
            event_ids = await self.redis_client.zrange(
                f"{self.workflow_index}{workflow_id}",
                0, -1  # All events
            )
            
            if not event_ids:
                return []
            
            # Get event data
            events = []
            event_data_list = await self.redis_client.hmget(
                self.events_hash,
                *event_ids
            )
            
            for event_data in event_data_list:
                if event_data:
                    events.append(EventEnvelope.parse_raw(event_data))
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to get workflow events for {workflow_id}: {e}")
            raise
    
    async def get_task_events(self, task_id: str) -> List[EventEnvelope]:
        """Get all events for a task"""
        if not self.redis_client:
            await self.connect()
        
        try:
            # Get event IDs from task index
            event_ids = await self.redis_client.zrange(
                f"{self.task_index}{task_id}",
                0, -1  # All events
            )
            
            if not event_ids:
                return []
            
            # Get event data
            events = []
            event_data_list = await self.redis_client.hmget(
                self.events_hash,
                *event_ids
            )
            
            for event_data in event_data_list:
                if event_data:
                    events.append(EventEnvelope.parse_raw(event_data))
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to get task events for {task_id}: {e}")
            raise
    
    async def get_event_stream(
        self,
        consumer_group: str,
        consumer_name: str,
        count: int = 10,
        block: int = 1000
    ) -> List[Dict[str, Any]]:
        """Read from Redis stream for real-time event processing"""
        if not self.redis_client:
            await self.connect()
        
        try:
            # Create consumer group if it doesn't exist
            try:
                await self.redis_client.xgroup_create(
                    self.event_stream,
                    consumer_group,
                    id='0',
                    mkstream=True
                )
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            
            # Read from stream
            messages = await self.redis_client.xreadgroup(
                consumer_group,
                consumer_name,
                {self.event_stream: '>'},
                count=count,
                block=block
            )
            
            return messages
            
        except Exception as e:
            logger.error(f"Failed to read event stream: {e}")
            raise
    
    async def cleanup_old_events(self):
        """Remove events older than retention period"""
        if not self.redis_client:
            await self.connect()
        
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=self.retention_days)
            cutoff_score = cutoff_time.timestamp()
            
            # Get old event IDs
            old_event_ids = await self.redis_client.zrangebyscore(
                self.events_sorted_set,
                0,
                cutoff_score
            )
            
            if old_event_ids:
                # Remove from all indexes
                pipe = self.redis_client.pipeline()
                
                # Remove from time index
                pipe.zremrangebyscore(self.events_sorted_set, 0, cutoff_score)
                
                # Remove event data
                pipe.hdel(self.events_hash, *old_event_ids)
                
                await pipe.execute()
                
                logger.info(f"Cleaned up {len(old_event_ids)} old events")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old events: {e}")
            raise


class InMemoryEventStore(EventStore):
    """In-memory event store for testing and development"""
    
    def __init__(self, max_events: int = 100000):
        self.max_events = max_events
        self.events: List[EventEnvelope] = []
        self.events_by_id: Dict[str, EventEnvelope] = {}
        self.workflow_events: Dict[str, List[EventEnvelope]] = {}
        self.task_events: Dict[str, List[EventEnvelope]] = {}
    
    async def store_event(self, event: EventEnvelope):
        """Store event in memory"""
        # Add to main list
        self.events.append(event)
        self.events_by_id[event.event_id] = event
        
        # Add to indexes
        if event.workflow_id:
            if event.workflow_id not in self.workflow_events:
                self.workflow_events[event.workflow_id] = []
            self.workflow_events[event.workflow_id].append(event)
        
        if event.task_id:
            if event.task_id not in self.task_events:
                self.task_events[event.task_id] = []
            self.task_events[event.task_id].append(event)
        
        # Limit memory usage
        if len(self.events) > self.max_events:
            # Remove oldest events
            old_event = self.events.pop(0)
            del self.events_by_id[old_event.event_id]
    
    async def get_events(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_filter: Optional[EventFilter] = None,
        limit: Optional[int] = None
    ) -> List[EventEnvelope]:
        """Get events within time range"""
        end_time = end_time or datetime.utcnow()
        
        matching_events = [
            event for event in self.events
            if start_time <= event.timestamp <= end_time
            and (event_filter is None or event_filter.matches(event))
        ]
        
        if limit:
            matching_events = matching_events[:limit]
        
        return matching_events
    
    async def get_event_by_id(self, event_id: str) -> Optional[EventEnvelope]:
        """Get specific event by ID"""
        return self.events_by_id.get(event_id)
    
    async def get_workflow_events(self, workflow_id: str) -> List[EventEnvelope]:
        """Get all events for a workflow"""
        return self.workflow_events.get(workflow_id, [])
    
    async def get_task_events(self, task_id: str) -> List[EventEnvelope]:
        """Get all events for a task"""
        return self.task_events.get(task_id, [])