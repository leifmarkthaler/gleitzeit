"""
Unified SQLAlchemy Persistence Adapter

Production-ready SQL persistence using SQLAlchemy ORM with SQLite as default.
Handles both task/workflow persistence and hub resource persistence in a unified manner.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, 
    Boolean, Text, Index, ForeignKey, and_, or_, select, delete,
    func, text
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool, StaticPool

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType
from gleitzeit.core.errors import ErrorCode, PersistenceError, PersistenceConnectionError

logger = logging.getLogger(__name__)

Base = declarative_base()


# ============================================================================
# ORM Models
# ============================================================================

# Task/Workflow Models
class DBTask(Base):
    """Task ORM model"""
    __tablename__ = 'tasks'
    
    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    protocol = Column(String(100), nullable=False)
    method = Column(String(255), nullable=False)
    params = Column(Text, nullable=False)  # JSON
    priority = Column(String(20), nullable=False)
    dependencies = Column(Text)  # JSON array
    timeout = Column(Integer)
    retry_config = Column(Text)  # JSON
    status = Column(String(50), nullable=False, index=True)
    attempt_count = Column(Integer, default=0)
    workflow_id = Column(String(255), index=True)
    created_at = Column(DateTime, nullable=False, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    assigned_provider = Column(String(255), index=True)  # Links to resource instance
    execution_node = Column(String(255))
    error_message = Column(Text)
    tags = Column(Text)  # JSON
    task_metadata = Column('metadata', Text)  # JSON
    
    # Relationship
    result = relationship("DBTaskResult", back_populates="task", uselist=False, cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_task_status_priority', 'status', 'priority'),
        Index('idx_task_workflow', 'workflow_id', 'status'),
        Index('idx_task_provider', 'assigned_provider', 'status'),
    )


class DBTaskResult(Base):
    """Task result ORM model"""
    __tablename__ = 'task_results'
    
    task_id = Column(String(255), ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True)
    status = Column(String(50), nullable=False)
    result = Column(Text)  # JSON
    error_message = Column(Text)
    execution_time = Column(Float)
    created_at = Column(DateTime, nullable=False)
    
    # Relationship
    task = relationship("DBTask", back_populates="result")


class DBWorkflow(Base):
    """Workflow ORM model"""
    __tablename__ = 'workflows'
    
    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    tasks = Column(Text, nullable=False)  # JSON array of task objects
    workflow_metadata = Column('metadata', Text)  # JSON
    created_at = Column(DateTime, nullable=False)
    
    # Relationship
    executions = relationship("DBWorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class DBWorkflowExecution(Base):
    """Workflow execution ORM model"""
    __tablename__ = 'workflow_executions'
    
    execution_id = Column(String(255), primary_key=True)
    workflow_id = Column(String(255), ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(50), nullable=False)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    progress = Column(Text)  # JSON with progress info
    
    # Relationship
    workflow = relationship("DBWorkflow", back_populates="executions")


class DBQueueState(Base):
    """Queue state ORM model"""
    __tablename__ = 'queue_states'
    
    queue_name = Column(String(255), primary_key=True)
    state = Column(Text, nullable=False)  # JSON
    updated_at = Column(DateTime, nullable=False)


# Hub Resource Models
class DBResourceInstance(Base):
    """Resource instance ORM model"""
    __tablename__ = 'resource_instances'
    
    instance_id = Column(String(255), primary_key=True)
    hub_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    endpoint = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    instance_metadata = Column('metadata', Text)  # JSON
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


# ============================================================================
# Unified SQLAlchemy Adapter
# ============================================================================

class UnifiedSQLAlchemyAdapter(UnifiedPersistenceAdapter):
    """
    SQLAlchemy-based unified persistence adapter.
    Default engine is SQLite, but supports any SQLAlchemy-compatible database.
    """
    
    def __init__(
        self, 
        connection_string: str = None,
        db_path: str = None,
        **engine_kwargs
    ):
        """
        Initialize unified SQLAlchemy adapter.
        
        Args:
            connection_string: SQLAlchemy connection string 
                             (default: sqlite+aiosqlite:///gleitzeit.db)
            db_path: Legacy parameter for SQLite path (for backward compatibility)
            **engine_kwargs: Additional arguments for create_async_engine
        """
        # Handle legacy db_path parameter
        self.is_memory = False
        if db_path and not connection_string:
            if db_path == ":memory:":
                connection_string = "sqlite+aiosqlite:///:memory:"
                self.is_memory = True
            else:
                connection_string = f"sqlite+aiosqlite:///{db_path}"
        
        # Default to SQLite if no connection string provided
        if connection_string is None:
            connection_string = "sqlite+aiosqlite:///gleitzeit.db"
        
        self.connection_string = connection_string
        self.engine_kwargs = engine_kwargs
        self.engine = None
        self.async_session = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database connection and create all tables"""
        if self._initialized:
            return
        
        try:
            # Ensure SQLite directory exists if using SQLite
            if self.connection_string.startswith("sqlite"):
                db_path = self.connection_string.split("///")[-1]
                if db_path != ":memory:":
                    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Create async engine with appropriate pool
            if "sqlite" in self.connection_string:
                # SQLite doesn't support most pool settings, filter them out
                sqlite_kwargs = {k: v for k, v in self.engine_kwargs.items() 
                               if k not in ['pool_size', 'max_overflow', 'pool_timeout', 'pool_recycle']}
                
                # Use StaticPool for in-memory databases to keep connection alive
                if self.is_memory or ":memory:" in self.connection_string:
                    self.engine = create_async_engine(
                        self.connection_string,
                        poolclass=StaticPool,  # Keep connection alive for in-memory DB
                        connect_args={"check_same_thread": False},
                        **sqlite_kwargs
                    )
                else:
                    self.engine = create_async_engine(
                        self.connection_string,
                        poolclass=NullPool,  # Regular SQLite file database
                        **sqlite_kwargs
                    )
            else:
                self.engine = create_async_engine(
                    self.connection_string,
                    **self.engine_kwargs
                )
            
            # Create session factory with foreign key support for SQLite
            if 'sqlite' in self.connection_string:
                # For SQLite, we need to enable foreign keys for each connection
                from sqlalchemy import event
                from sqlalchemy.engine import Engine
                
                @event.listens_for(Engine, "connect")
                def set_sqlite_pragma(dbapi_conn, connection_record):
                    cursor = dbapi_conn.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
            
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Create all tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                
                # Enable foreign key constraints for SQLite
                if 'sqlite' in self.connection_string:
                    await conn.execute(text("PRAGMA foreign_keys = ON"))
            
            self._initialized = True
            logger.info(f"Unified SQLAlchemy adapter initialized: {self.connection_string}")
            
        except Exception as e:
            logger.error(f"Failed to initialize SQLAlchemy adapter: {e}")
            raise PersistenceConnectionError(
                backend="SQLAlchemy",
                connection_string=self.connection_string,
                cause=e
            )
    
    async def shutdown(self) -> None:
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None
        self._initialized = False
        logger.info("Unified SQLAlchemy adapter shut down")
    
    # ========================================================================
    # Task/Workflow Operations
    # ========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save or update a task"""
        if not self._initialized:
            raise PersistenceError(
                message="Adapter not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                backend="SQLAlchemy"
            )
        
        try:
            async with self.async_session() as session:
                # Check if task exists
                result = await session.execute(
                    select(DBTask).where(DBTask.id == task.id)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing task
                    existing.name = task.name
                    existing.protocol = task.protocol
                    existing.method = task.method
                    existing.params = json.dumps(task.params)
                    existing.priority = task.priority
                    existing.dependencies = json.dumps(task.dependencies) if task.dependencies else None
                    existing.timeout = task.timeout
                    existing.retry_config = json.dumps(task.retry_config.dict()) if task.retry_config else None
                    existing.status = task.status
                    existing.attempt_count = task.attempt_count
                    existing.workflow_id = task.workflow_id
                    existing.started_at = task.started_at
                    existing.completed_at = task.completed_at
                    existing.assigned_provider = task.assigned_provider
                    existing.execution_node = task.execution_node
                    existing.error_message = task.error_message
                    existing.tags = json.dumps(task.tags) if task.tags else None
                    existing.task_metadata = json.dumps(task.metadata) if task.metadata else None
                else:
                    # Create new task
                    db_task = DBTask(
                        id=task.id,
                        name=task.name,
                        protocol=task.protocol,
                        method=task.method,
                        params=json.dumps(task.params),
                        priority=task.priority,
                        dependencies=json.dumps(task.dependencies) if task.dependencies else None,
                        timeout=task.timeout,
                        retry_config=json.dumps(task.retry_config.dict()) if task.retry_config else None,
                        status=task.status,
                        attempt_count=task.attempt_count,
                        workflow_id=task.workflow_id,
                        created_at=task.created_at or datetime.utcnow(),
                        started_at=task.started_at,
                        completed_at=task.completed_at,
                        assigned_provider=task.assigned_provider,
                        execution_node=task.execution_node,
                        error_message=task.error_message,
                        tags=json.dumps(task.tags) if task.tags else None,
                        task_metadata=json.dumps(task.metadata) if task.metadata else None
                    )
                    session.add(db_task)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save task {task.id}: {e}")
            raise PersistenceError(
                message=f"Failed to save task {task.id}",
                code=ErrorCode.PERSISTENCE_WRITE_FAILED,
                backend="SQLAlchemy",
                cause=e
            )
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        if not self._initialized:
            return None
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTask).where(DBTask.id == task_id)
                )
                db_task = result.scalar_one_or_none()
                
                if db_task:
                    return self._db_to_task(db_task)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None
    
    def _db_to_task(self, db_task: DBTask) -> Task:
        """Convert database model to Task object"""
        from gleitzeit.core.models import RetryConfig
        
        return Task(
            id=db_task.id,
            name=db_task.name,
            protocol=db_task.protocol,
            method=db_task.method,
            params=json.loads(db_task.params) if db_task.params else {},
            priority=db_task.priority,
            dependencies=json.loads(db_task.dependencies) if db_task.dependencies else [],
            timeout=db_task.timeout,
            retry_config=RetryConfig(**json.loads(db_task.retry_config)) if db_task.retry_config else None,
            status=db_task.status,
            attempt_count=db_task.attempt_count,
            workflow_id=db_task.workflow_id,
            created_at=db_task.created_at,
            started_at=db_task.started_at,
            completed_at=db_task.completed_at,
            assigned_provider=db_task.assigned_provider,
            execution_node=db_task.execution_node,
            error_message=db_task.error_message,
            tags=json.loads(db_task.tags) if db_task.tags else {},
            metadata=json.loads(db_task.task_metadata) if db_task.task_metadata else {}
        )
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        if not self._initialized:
            return False
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    delete(DBTask).where(DBTask.id == task_id)
                )
                await session.commit()
                return result.rowcount > 0
                
        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        if not self._initialized:
            return []
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTask)
                    .where(DBTask.status == status)
                    .order_by(DBTask.created_at)
                )
                return [self._db_to_task(db_task) for db_task in result.scalars()]
                
        except Exception as e:
            logger.error(f"Failed to get tasks by status {status}: {e}")
            return []
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        if not self._initialized:
            return []
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTask)
                    .where(DBTask.workflow_id == workflow_id)
                    .order_by(DBTask.created_at)
                )
                return [self._db_to_task(db_task) for db_task in result.scalars()]
                
        except Exception as e:
            logger.error(f"Failed to get tasks for workflow {workflow_id}: {e}")
            return []
    
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        if not self._initialized:
            return
        
        try:
            async with self.async_session() as session:
                # Check if result exists
                result = await session.execute(
                    select(DBTaskResult).where(DBTaskResult.task_id == task_result.task_id)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing result
                    existing.status = task_result.status
                    existing.result = json.dumps(task_result.result) if task_result.result is not None else None
                    existing.error_message = task_result.error
                    existing.execution_time = task_result.duration_seconds
                else:
                    # Create new result
                    db_result = DBTaskResult(
                        task_id=task_result.task_id,
                        status=task_result.status,
                        result=json.dumps(task_result.result) if task_result.result is not None else None,
                        error_message=task_result.error,
                        execution_time=task_result.duration_seconds,
                        created_at=datetime.utcnow()
                    )
                    session.add(db_result)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save task result for {task_result.task_id}: {e}")
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        if not self._initialized:
            return None
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTaskResult).where(DBTaskResult.task_id == task_id)
                )
                db_result = result.scalar_one_or_none()
                
                if db_result:
                    return TaskResult(
                        task_id=db_result.task_id,
                        status=db_result.status,
                        result=json.loads(db_result.result) if db_result.result else None,
                        error=db_result.error_message,
                        duration_seconds=db_result.execution_time,
                        metadata={}
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to get task result for {task_id}: {e}")
            return None
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        if not self._initialized:
            return
        
        try:
            # Convert tasks to dict for JSON storage
            tasks_data = []
            for task in workflow.tasks:
                task_dict = task.dict()
                # Convert datetime objects to ISO format strings
                for field in ['created_at', 'started_at', 'completed_at']:
                    if task_dict.get(field):
                        task_dict[field] = task_dict[field].isoformat()
                tasks_data.append(task_dict)
            
            async with self.async_session() as session:
                # Check if workflow exists
                result = await session.execute(
                    select(DBWorkflow).where(DBWorkflow.id == workflow.id)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing workflow
                    existing.name = workflow.name
                    existing.description = workflow.description
                    existing.tasks = json.dumps(tasks_data)
                    existing.workflow_metadata = json.dumps(workflow.metadata) if workflow.metadata else None
                else:
                    # Create new workflow
                    db_workflow = DBWorkflow(
                        id=workflow.id,
                        name=workflow.name,
                        description=workflow.description,
                        tasks=json.dumps(tasks_data),
                        workflow_metadata=json.dumps(workflow.metadata) if workflow.metadata else None,
                        created_at=workflow.created_at or datetime.utcnow()
                    )
                    session.add(db_workflow)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save workflow {workflow.id}: {e}")
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        if not self._initialized:
            return None
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBWorkflow).where(DBWorkflow.id == workflow_id)
                )
                db_workflow = result.scalar_one_or_none()
                
                if db_workflow:
                    tasks_data = json.loads(db_workflow.tasks)
                    tasks = []
                    for task_data in tasks_data:
                        # Convert ISO format strings back to datetime objects
                        for field in ['created_at', 'started_at', 'completed_at']:
                            if task_data.get(field):
                                task_data[field] = datetime.fromisoformat(task_data[field])
                        tasks.append(Task(**task_data))
                    
                    return Workflow(
                        id=db_workflow.id,
                        name=db_workflow.name,
                        description=db_workflow.description,
                        tasks=tasks,
                        metadata=json.loads(db_workflow.workflow_metadata) if db_workflow.workflow_metadata else {},
                        created_at=db_workflow.created_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            return None
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save workflow execution state"""
        if not self._initialized:
            return
        
        try:
            async with self.async_session() as session:
                # Check if execution exists
                result = await session.execute(
                    select(DBWorkflowExecution).where(
                        DBWorkflowExecution.execution_id == execution.execution_id
                    )
                )
                existing = result.scalar_one_or_none()
                
                progress_data = json.dumps({
                    "completed_tasks": execution.completed_tasks,
                    "failed_tasks": execution.failed_tasks,
                    "total_tasks": execution.total_tasks
                })
                
                if existing:
                    # Update existing execution
                    existing.status = execution.status
                    existing.completed_at = execution.completed_at
                    existing.error_message = execution.error_message
                    existing.progress = progress_data
                else:
                    # Create new execution
                    db_execution = DBWorkflowExecution(
                        execution_id=execution.execution_id,
                        workflow_id=execution.workflow_id,
                        status=execution.status,
                        started_at=execution.started_at,
                        completed_at=execution.completed_at,
                        error_message=execution.error_message,
                        progress=progress_data
                    )
                    session.add(db_execution)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save workflow execution {execution.execution_id}: {e}")
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution by ID"""
        if not self._initialized:
            return None
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBWorkflowExecution).where(
                        DBWorkflowExecution.execution_id == execution_id
                    )
                )
                db_execution = result.scalar_one_or_none()
                
                if db_execution:
                    progress = json.loads(db_execution.progress) if db_execution.progress else {}
                    
                    return WorkflowExecution(
                        execution_id=db_execution.execution_id,
                        workflow_id=db_execution.workflow_id,
                        status=db_execution.status,
                        started_at=db_execution.started_at,
                        completed_at=db_execution.completed_at,
                        error_message=db_execution.error_message,
                        completed_tasks=progress.get('completed_tasks', 0),
                        failed_tasks=progress.get('failed_tasks', 0),
                        total_tasks=progress.get('total_tasks', 0)
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to get workflow execution {execution_id}: {e}")
            return None
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        if not self._initialized:
            return
        
        try:
            async with self.async_session() as session:
                # Check if queue state exists
                result = await session.execute(
                    select(DBQueueState).where(DBQueueState.queue_name == queue_name)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing state
                    existing.state = json.dumps(state)
                    existing.updated_at = datetime.utcnow()
                else:
                    # Create new state
                    db_state = DBQueueState(
                        queue_name=queue_name,
                        state=json.dumps(state),
                        updated_at=datetime.utcnow()
                    )
                    session.add(db_state)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save queue state for {queue_name}: {e}")
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        if not self._initialized:
            return None
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBQueueState).where(DBQueueState.queue_name == queue_name)
                )
                db_state = result.scalar_one_or_none()
                
                if db_state:
                    return json.loads(db_state.state)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get queue state for {queue_name}: {e}")
            return None
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        if not self._initialized:
            return False
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    delete(DBQueueState).where(DBQueueState.queue_name == queue_name)
                )
                await session.commit()
                return result.rowcount > 0
                
        except Exception as e:
            logger.error(f"Failed to delete queue state for {queue_name}: {e}")
            return False
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single transaction"""
        if not self._initialized:
            return
        
        try:
            async with self.async_session() as session:
                for task in tasks:
                    # Check if task exists
                    result = await session.execute(
                        select(DBTask).where(DBTask.id == task.id)
                    )
                    existing = result.scalar_one_or_none()
                    
                    if not existing:
                        # Create new task
                        db_task = DBTask(
                            id=task.id,
                            name=task.name,
                            protocol=task.protocol,
                            method=task.method,
                            params=json.dumps(task.params),
                            priority=task.priority,
                            dependencies=json.dumps(task.dependencies) if task.dependencies else None,
                            timeout=task.timeout,
                            retry_config=json.dumps(task.retry_config.dict()) if task.retry_config else None,
                            status=task.status,
                            attempt_count=task.attempt_count,
                            workflow_id=task.workflow_id,
                            created_at=task.created_at or datetime.utcnow(),
                            started_at=task.started_at,
                            completed_at=task.completed_at,
                            assigned_provider=task.assigned_provider,
                            execution_node=task.execution_node,
                            error_message=task.error_message,
                            tags=json.dumps(task.tags) if task.tags else None,
                            task_metadata=json.dumps(task.metadata) if task.metadata else None
                        )
                        session.add(db_task)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to save tasks batch: {e}")
    
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        if not self._initialized:
            return []
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTask).where(
                        DBTask.status.in_(['queued', 'retry_pending', 'executing'])
                    ).order_by(DBTask.created_at)
                )
                return [self._db_to_task(db_task) for db_task in result.scalars()]
                
        except Exception as e:
            logger.error(f"Failed to get queued tasks: {e}")
            return []
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        if not self._initialized:
            return {}
        
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DBTask.status, func.count(DBTask.id))
                    .group_by(DBTask.status)
                )
                return {status: count for status, count in result}
                
        except Exception as e:
            logger.error(f"Failed to get task count by status: {e}")
            return {}
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        if not self._initialized:
            return 0
        
        try:
            async with self.async_session() as session:
                # Delete old tasks (results will cascade delete)
                result = await session.execute(
                    delete(DBTask).where(
                        and_(
                            DBTask.status.in_(['completed', 'failed']),
                            DBTask.completed_at < cutoff_date
                        )
                    )
                )
                deleted_count = result.rowcount
                await session.commit()
                
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return 0
    
    # ========================================================================
    # Hub Resource Operations
    # ========================================================================
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        if not self._initialized:
            return
        
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
                logger.debug(f"Saved instance {instance.id}")
                
        except Exception as e:
            logger.error(f"Failed to save instance {instance.id}: {e}")
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not self._initialized:
            return None
        
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
        if not self._initialized:
            return []
        
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
        if not self._initialized:
            return
        
        try:
            async with self.async_session() as session:
                await session.execute(
                    delete(DBResourceInstance).where(
                        DBResourceInstance.instance_id == instance_id
                    )
                )
                await session.commit()
                logger.debug(f"Deleted instance {instance_id}")
                
        except Exception as e:
            logger.error(f"Failed to delete instance {instance_id}: {e}")
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot"""
        if not self._initialized:
            return
        
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
        if not self._initialized:
            return []
        
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
        if not self._initialized:
            return False
        
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
        if not self._initialized:
            return
        
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
        if not self._initialized:
            return False
        
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
        if not self._initialized:
            return None
        
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


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# For backward compatibility with existing code
SQLiteBackend = UnifiedSQLAlchemyAdapter
SQLAlchemyHubAdapter = UnifiedSQLAlchemyAdapter