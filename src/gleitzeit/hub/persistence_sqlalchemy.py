"""
SQLAlchemy-based Hub Persistence Adapter

Production-ready SQL persistence using SQLAlchemy ORM with support for
multiple database backends (SQLite, PostgreSQL, MySQL, etc.)
"""

import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, 
    Boolean, Text, Index, ForeignKey, and_, or_, select, delete
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from gleitzeit.hub.persistence import HubPersistenceAdapter
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)

Base = declarative_base()


class DBResourceInstance(Base):
    """Resource instance ORM model"""
    __tablename__ = 'resource_instances'
    
    instance_id = Column(String(255), primary_key=True)
    hub_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    endpoint = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    instance_metadata = Column('metadata', Text)  # JSON - renamed to avoid conflict
    tags = Column(Text)  # JSON array
    capabilities = Column(Text)  # JSON array
    health_checks_failed = Column(Integer, default=0)
    last_health_check = Column(DateTime)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    
    # Relationship to metrics
    metrics = relationship("DBResourceMetrics", back_populates="instance", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_hub_status', 'hub_id', 'status'),
    )


class DBResourceMetrics(Base):
    """Resource metrics ORM model"""
    __tablename__ = 'resource_metrics'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String(255), ForeignKey('resource_instances.instance_id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    cpu_percent = Column(Float, default=0.0)
    memory_percent = Column(Float, default=0.0)
    memory_mb = Column(Float, default=0.0)
    disk_io_mb = Column(Float, default=0.0)
    network_io_mb = Column(Float, default=0.0)
    request_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    avg_response_time_ms = Column(Float, default=0.0)
    p95_response_time_ms = Column(Float, default=0.0)
    p99_response_time_ms = Column(Float, default=0.0)
    active_connections = Column(Integer, default=0)
    queued_requests = Column(Integer, default=0)
    custom_metrics = Column(Text)  # JSON
    
    # Relationship
    instance = relationship("DBResourceInstance", back_populates="metrics")
    
    __table_args__ = (
        Index('idx_instance_time', 'instance_id', 'timestamp'),
    )


class DBResourceLock(Base):
    """Distributed lock ORM model"""
    __tablename__ = 'resource_locks'
    
    resource_id = Column(String(255), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    acquired_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class SQLAlchemyHubAdapter(HubPersistenceAdapter):
    """SQLAlchemy-based persistence for hub state"""
    
    def __init__(self, connection_string: str = None, **engine_kwargs):
        """
        Initialize SQLAlchemy adapter
        
        Args:
            connection_string: Database URL (e.g., 'sqlite+aiosqlite:///hub.db',
                             'postgresql+asyncpg://user:pass@localhost/db')
            **engine_kwargs: Additional arguments for create_async_engine
        """
        if connection_string is None:
            # Default to SQLite
            connection_string = "sqlite+aiosqlite:///gleitzeit_hub.db"
        
        self.connection_string = connection_string
        self.engine_kwargs = engine_kwargs
        self.engine = None
        self.async_session = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database connection and create tables"""
        if self._initialized:
            return
        
        try:
            # Ensure SQLite directory exists if using SQLite
            if self.connection_string.startswith("sqlite"):
                db_path = self.connection_string.split("///")[-1]
                if db_path != ":memory:":
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Create async engine
            # Use NullPool for SQLite to avoid connection issues
            if "sqlite" in self.connection_string:
                self.engine = create_async_engine(
                    self.connection_string,
                    poolclass=NullPool,
                    **self.engine_kwargs
                )
            else:
                self.engine = create_async_engine(
                    self.connection_string,
                    **self.engine_kwargs
                )
            
            # Create session factory
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            self._initialized = True
            logger.info(f"SQLAlchemy hub adapter initialized: {self.connection_string}")
            
        except Exception as e:
            logger.error(f"Failed to initialize SQLAlchemy adapter: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None
        self._initialized = False
        logger.info("SQLAlchemy hub adapter shut down")
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                # Check if instance exists
                result = await session.execute(
                    select(DBResourceInstance).where(
                        DBResourceInstance.instance_id == instance.id
                    )
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing instance
                    existing.hub_id = hub_id
                    existing.name = instance.name
                    existing.type = instance.type.value if isinstance(instance.type, ResourceType) else instance.type
                    existing.endpoint = instance.endpoint
                    existing.status = instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status
                    existing.instance_metadata = json.dumps(instance.metadata)
                    existing.tags = json.dumps(list(instance.tags))
                    existing.capabilities = json.dumps(list(instance.capabilities))
                    existing.health_checks_failed = instance.health_checks_failed
                    existing.last_health_check = instance.last_health_check
                    existing.updated_at = datetime.utcnow()
                else:
                    # Create new instance
                    db_instance = DBResourceInstance(
                    instance_id=instance.id,
                    hub_id=hub_id,
                    name=instance.name,
                    type=instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
                    endpoint=instance.endpoint,
                    status=instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
                    instance_metadata=json.dumps(instance.metadata),
                    tags=json.dumps(list(instance.tags)),
                    capabilities=json.dumps(list(instance.capabilities)),
                    health_checks_failed=instance.health_checks_failed,
                    last_health_check=instance.last_health_check,
                    created_at=instance.created_at,
                    updated_at=datetime.utcnow()
                )
                    session.add(db_instance)
                
                await session.commit()
                
            logger.debug(f"Saved instance {instance.id} to database")
            
        except Exception as e:
            logger.error(f"Failed to save instance {instance.id}: {e}")
            raise
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBResourceInstance).where(
                        DBResourceInstance.instance_id == instance_id
                    )
                )
                db_instance = result.scalar_one_or_none()
                
                if db_instance:
                    return {
                        'id': db_instance.instance_id,
                        'hub_id': db_instance.hub_id,
                        'name': db_instance.name,
                        'type': db_instance.type,
                        'endpoint': db_instance.endpoint,
                        'status': db_instance.status,
                        'metadata': json.loads(db_instance.instance_metadata) if db_instance.instance_metadata else {},
                        'tags': json.loads(db_instance.tags) if db_instance.tags else [],
                        'capabilities': json.loads(db_instance.capabilities) if db_instance.capabilities else [],
                        'health_checks_failed': db_instance.health_checks_failed,
                        'last_health_check': db_instance.last_health_check.isoformat() if db_instance.last_health_check else None,
                        'created_at': db_instance.created_at.isoformat(),
                        'updated_at': db_instance.updated_at.isoformat()
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to load instance {instance_id}: {e}")
            return None
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBResourceInstance).where(
                        DBResourceInstance.hub_id == hub_id
                    )
                )
                instances = []
                
                for db_instance in result.scalars():
                    instances.append({
                        'id': db_instance.instance_id,
                        'hub_id': db_instance.hub_id,
                        'name': db_instance.name,
                        'type': db_instance.type,
                        'endpoint': db_instance.endpoint,
                        'status': db_instance.status,
                        'metadata': json.loads(db_instance.instance_metadata) if db_instance.instance_metadata else {},
                        'tags': json.loads(db_instance.tags) if db_instance.tags else [],
                        'capabilities': json.loads(db_instance.capabilities) if db_instance.capabilities else [],
                        'health_checks_failed': db_instance.health_checks_failed,
                        'last_health_check': db_instance.last_health_check.isoformat() if db_instance.last_health_check else None,
                        'created_at': db_instance.created_at.isoformat(),
                        'updated_at': db_instance.updated_at.isoformat()
                    })
                
                return instances
                
        except Exception as e:
            logger.error(f"Failed to list instances for hub {hub_id}: {e}")
            return []
    
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                await session.execute(
                    delete(DBResourceInstance).where(
                        DBResourceInstance.instance_id == instance_id
                    )
                )
                await session.commit()
                
            logger.debug(f"Deleted instance {instance_id} from database")
            
        except Exception as e:
            logger.error(f"Failed to delete instance {instance_id}: {e}")
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                # Add new metrics
                db_metrics = DBResourceMetrics(
                    instance_id=instance_id,
                    timestamp=datetime.utcnow(),
                    cpu_percent=metrics.cpu_percent,
                    memory_percent=metrics.memory_percent,
                    memory_mb=metrics.memory_mb,
                    disk_io_mb=metrics.disk_io_mb,
                    network_io_mb=metrics.network_io_mb,
                    request_count=metrics.request_count,
                    error_count=metrics.error_count,
                    avg_response_time_ms=metrics.avg_response_time_ms,
                    p95_response_time_ms=metrics.p95_response_time_ms,
                    p99_response_time_ms=metrics.p99_response_time_ms,
                    active_connections=metrics.active_connections,
                    queued_requests=metrics.queued_requests,
                    custom_metrics=json.dumps(metrics.custom_metrics)
                )
                session.add(db_metrics)
                
                # Clean up old metrics (keep last 24 hours)
                cutoff = datetime.utcnow() - timedelta(hours=24)
                await session.execute(
                    delete(DBResourceMetrics).where(
                        and_(
                            DBResourceMetrics.instance_id == instance_id,
                            DBResourceMetrics.timestamp < cutoff
                        )
                    )
                )
                
                await session.commit()
                
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
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBResourceMetrics).where(
                        and_(
                            DBResourceMetrics.instance_id == instance_id,
                            DBResourceMetrics.timestamp >= start_time,
                            DBResourceMetrics.timestamp <= end_time
                        )
                    ).order_by(DBResourceMetrics.timestamp)
                )
                
                metrics_list = []
                for db_metrics in result.scalars():
                    metrics_list.append({
                        'timestamp': db_metrics.timestamp.isoformat(),
                        'cpu_percent': db_metrics.cpu_percent,
                        'memory_percent': db_metrics.memory_percent,
                        'memory_mb': db_metrics.memory_mb,
                        'request_count': db_metrics.request_count,
                        'error_count': db_metrics.error_count,
                        'avg_response_time_ms': db_metrics.avg_response_time_ms,
                        'p95_response_time_ms': db_metrics.p95_response_time_ms,
                        'p99_response_time_ms': db_metrics.p99_response_time_ms,
                        'active_connections': db_metrics.active_connections,
                        'queued_requests': db_metrics.queued_requests,
                        'custom': json.loads(db_metrics.custom_metrics) if db_metrics.custom_metrics else {}
                    })
                
                return metrics_list
                
        except Exception as e:
            logger.error(f"Failed to get metrics history for {instance_id}: {e}")
            return []
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for resource allocation"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                now = datetime.utcnow()
                expires_at = now + timedelta(seconds=timeout)
                
                # Clean up expired locks
                await session.execute(
                    delete(DBResourceLock).where(
                        DBResourceLock.expires_at < now
                    )
                )
                
                # Try to acquire lock
                db_lock = DBResourceLock(
                    resource_id=resource_id,
                    owner_id=owner_id,
                    acquired_at=now,
                    expires_at=expires_at
                )
                
                try:
                    session.add(db_lock)
                    await session.commit()
                    logger.debug(f"Acquired lock for {resource_id} by {owner_id}")
                    return True
                    
                except IntegrityError:
                    # Lock already exists
                    await session.rollback()
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to acquire lock for {resource_id}: {e}")
            return False
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                await session.execute(
                    delete(DBResourceLock).where(
                        and_(
                            DBResourceLock.resource_id == resource_id,
                            DBResourceLock.owner_id == owner_id
                        )
                    )
                )
                await session.commit()
                
            logger.debug(f"Released lock for {resource_id} by {owner_id}")
            
        except Exception as e:
            logger.error(f"Failed to release lock for {resource_id}: {e}")
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                new_expires = datetime.utcnow() + timedelta(seconds=timeout)
                
                result = await session.execute(
                    select(DBResourceLock).where(
                        and_(
                            DBResourceLock.resource_id == resource_id,
                            DBResourceLock.owner_id == owner_id
                        )
                    )
                )
                
                db_lock = result.scalar_one_or_none()
                if db_lock:
                    db_lock.expires_at = new_expires
                    await session.commit()
                    logger.debug(f"Extended lock for {resource_id} by {owner_id}")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Failed to extend lock for {resource_id}: {e}")
            return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        if not self.async_session:
            raise RuntimeError("SQLAlchemy adapter not initialized")
        
        try:
            async with self.async_session() as session:
                now = datetime.utcnow()
                
                # Clean up expired locks
                await session.execute(
                    delete(DBResourceLock).where(
                        DBResourceLock.expires_at < now
                    )
                )
                await session.commit()
                
                # Get current owner
                result = await session.execute(
                    select(DBResourceLock).where(
                        and_(
                            DBResourceLock.resource_id == resource_id,
                            DBResourceLock.expires_at >= now
                        )
                    )
                )
                
                db_lock = result.scalar_one_or_none()
                return db_lock.owner_id if db_lock else None
                
        except Exception as e:
            logger.error(f"Failed to get lock owner for {resource_id}: {e}")
            return None