"""
SQLite persistence backend for Gleitzeit V4

High-performance local database storage with full ACID properties.
Ideal for single-node deployments or development environments.
"""

import asyncio
import aiosqlite
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution, TaskStatus, WorkflowStatus
from gleitzeit.core.errors import (
    ErrorCode, PersistenceError, PersistenceConnectionError,
    SystemError
)

logger = logging.getLogger(__name__)


class SQLiteBackend(PersistenceBackend):
    """SQLite-based persistence backend"""
    
    def __init__(self, db_path: str = "gleitzeit.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize SQLite database and create tables"""
        if self._initialized:
            return
        
        try:
            # Ensure parent directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Connect to database
            self.db = await aiosqlite.connect(self.db_path)
            self.db.row_factory = aiosqlite.Row
            
            # Create tables
            await self._create_tables()
            self._initialized = True
            
            logger.info(f"SQLite backend initialized: {self.db_path}")
            
        except Exception as e:
            raise PersistenceConnectionError(
                backend="SQLite",
                connection_string=self.db_path,
                cause=e
            )
    
    async def shutdown(self) -> None:
        """Close database connection"""
        if self.db:
            await self.db.close()
            self.db = None
        self._initialized = False
    
    async def _create_tables(self) -> None:
        """Create database tables"""
        
        # Tasks table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                method TEXT NOT NULL,
                params TEXT NOT NULL,  -- JSON
                priority TEXT NOT NULL,
                dependencies TEXT,     -- JSON array
                timeout INTEGER,
                retry_config TEXT,     -- JSON
                status TEXT NOT NULL,
                attempt_count INTEGER DEFAULT 0,
                workflow_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                assigned_provider TEXT,
                execution_node TEXT,
                error_message TEXT,
                tags TEXT,             -- JSON
                metadata TEXT          -- JSON
            )
        """)
        
        # Task results table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS task_results (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                result TEXT,           -- JSON
                error_message TEXT,
                execution_time REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        """)
        
        # Workflows table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                tasks TEXT NOT NULL,   -- JSON array of task objects
                metadata TEXT,         -- JSON
                created_at TEXT NOT NULL
            )
        """)
        
        # Workflow executions table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_executions (
                execution_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                progress TEXT,         -- JSON with progress info
                FOREIGN KEY (workflow_id) REFERENCES workflows (id)
            )
        """)
        
        # Queue states table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS queue_states (
                queue_name TEXT PRIMARY KEY,
                state TEXT NOT NULL,   -- JSON
                updated_at TEXT NOT NULL
            )
        """)
        
        # Create indexes for better performance
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks (workflow_id)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks (priority)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at)")
        
        await self.db.commit()
    
    # Task operations
    async def save_task(self, task: Task) -> None:
        """Save or update a task"""
        if not self._initialized or not self.db:
            raise SystemError(
                message="SQLite backend not properly initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )
        
        try:
            await self.db.execute("""
            INSERT OR REPLACE INTO tasks (
                id, name, protocol, method, params, priority, dependencies,
                timeout, retry_config, status, attempt_count, workflow_id,
                created_at, started_at, completed_at, assigned_provider,
                execution_node, error_message, tags, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.id,
            task.name,
            task.protocol,
            task.method,
            json.dumps(task.params),
            task.priority,
            json.dumps(task.dependencies) if task.dependencies else None,
            task.timeout,
            json.dumps(task.retry_config.dict()) if task.retry_config else None,
            task.status,
            task.attempt_count,
            task.workflow_id,
            task.created_at.isoformat() if task.created_at else None,
            task.started_at.isoformat() if task.started_at else None,
            task.completed_at.isoformat() if task.completed_at else None,
            task.assigned_provider,
            task.execution_node,
            task.error_message,
            json.dumps(task.tags) if task.tags else None,
            json.dumps(task.metadata) if task.metadata else None
        ))
            await self.db.commit()
            
        except Exception as e:
            raise PersistenceError(
                message=f"Failed to save task {task.id}: {e}",
                code=ErrorCode.PERSISTENCE_WRITE_FAILED,
                backend="SQLite",
                cause=e
            )
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return self._row_to_task(row)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        cursor = await self.db.execute(
            "DELETE FROM tasks WHERE id = ?", (task_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get all tasks with a specific status"""
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at", (status,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a workflow"""
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY created_at", (workflow_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]
    
    def _row_to_task(self, row) -> Task:
        """Convert database row to Task object"""
        from gleitzeit.core.models import RetryConfig  # Import here to avoid circular imports
        
        return Task(
            id=row['id'],
            name=row['name'],
            protocol=row['protocol'],
            method=row['method'],
            params=json.loads(row['params']) if row['params'] else {},
            priority=row['priority'],
            dependencies=json.loads(row['dependencies']) if row['dependencies'] else [],
            timeout=row['timeout'],
            retry_config=RetryConfig(**json.loads(row['retry_config'])) if row['retry_config'] else None,
            status=row['status'],
            attempt_count=row['attempt_count'],
            workflow_id=row['workflow_id'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.utcnow(),
            started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
            assigned_provider=row['assigned_provider'],
            execution_node=row['execution_node'],
            error_message=row['error_message'],
            tags=json.loads(row['tags']) if row['tags'] else {},
            metadata=json.loads(row['metadata']) if row['metadata'] else {}
        )
    
    # Task results
    async def save_task_result(self, task_result: TaskResult) -> None:
        """Save a task result"""
        await self.db.execute("""
            INSERT OR REPLACE INTO task_results (
                task_id, status, result, error_message, execution_time, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            task_result.task_id,
            task_result.status,
            json.dumps(task_result.result) if task_result.result is not None else None,
            task_result.error,
            task_result.duration_seconds,
            datetime.utcnow().isoformat()
        ))
        await self.db.commit()
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result by task ID"""
        cursor = await self.db.execute(
            "SELECT * FROM task_results WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return TaskResult(
            task_id=row['task_id'],
            status=row['status'],
            result=json.loads(row['result']) if row['result'] else None,
            error=row['error_message'],
            duration_seconds=row['execution_time'],
            metadata={}
        )
    
    # Workflow operations
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save or update a workflow"""
        # Convert tasks to dict and handle datetime serialization
        tasks_data = []
        for task in workflow.tasks:
            task_dict = task.dict()
            # Convert datetime objects to ISO format strings
            for field in ['created_at', 'started_at', 'completed_at']:
                if task_dict.get(field):
                    task_dict[field] = task_dict[field].isoformat()
            tasks_data.append(task_dict)
        
        await self.db.execute("""
            INSERT OR REPLACE INTO workflows (
                id, name, description, tasks, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            workflow.id,
            workflow.name,
            workflow.description,
            json.dumps(tasks_data),
            json.dumps(workflow.metadata) if workflow.metadata else None,
            workflow.created_at.isoformat() if workflow.created_at else datetime.utcnow().isoformat()
        ))
        await self.db.commit()
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID"""
        cursor = await self.db.execute(
            "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        tasks_data = json.loads(row['tasks'])
        tasks = []
        for task_data in tasks_data:
            # Convert ISO format strings back to datetime objects
            for field in ['created_at', 'started_at', 'completed_at']:
                if task_data.get(field):
                    task_data[field] = datetime.fromisoformat(task_data[field])
            tasks.append(Task(**task_data))
        
        return Workflow(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            tasks=tasks,
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.utcnow()
        )
    
    async def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save workflow execution state"""
        await self.db.execute("""
            INSERT OR REPLACE INTO workflow_executions (
                execution_id, workflow_id, status, started_at, completed_at,
                error_message, progress
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            execution.execution_id,
            execution.workflow_id,
            execution.status,
            execution.started_at.isoformat(),
            execution.completed_at.isoformat() if execution.completed_at else None,
            execution.error_message,
            json.dumps({
                "completed_tasks": execution.completed_tasks,
                "failed_tasks": execution.failed_tasks,
                "total_tasks": execution.total_tasks
            })
        ))
        await self.db.commit()
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get workflow execution by ID"""
        cursor = await self.db.execute(
            "SELECT * FROM workflow_executions WHERE execution_id = ?", (execution_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        progress = json.loads(row['progress']) if row['progress'] else {}
        
        return WorkflowExecution(
            execution_id=row['execution_id'],
            workflow_id=row['workflow_id'],
            status=row['status'],
            started_at=datetime.fromisoformat(row['started_at']),
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
            error_message=row['error_message'],
            completed_tasks=progress.get('completed_tasks', 0),
            failed_tasks=progress.get('failed_tasks', 0),
            total_tasks=progress.get('total_tasks', 0)
        )
    
    # Queue state operations
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        """Save queue state for recovery"""
        await self.db.execute("""
            INSERT OR REPLACE INTO queue_states (queue_name, state, updated_at)
            VALUES (?, ?, ?)
        """, (queue_name, json.dumps(state), datetime.utcnow().isoformat()))
        await self.db.commit()
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """Get saved queue state"""
        cursor = await self.db.execute(
            "SELECT state FROM queue_states WHERE queue_name = ?", (queue_name,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return json.loads(row['state'])
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        """Delete queue state"""
        cursor = await self.db.execute(
            "DELETE FROM queue_states WHERE queue_name = ?", (queue_name,)
        )
        await self.db.commit()
        return cursor.rowcount > 0
    
    # Bulk operations
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        """Save multiple tasks in a single transaction"""
        data = []
        for task in tasks:
            data.append((
                task.id, task.name, task.protocol, task.method,
                json.dumps(task.params), task.priority,
                json.dumps(task.dependencies) if task.dependencies else None,
                task.timeout,
                json.dumps(task.retry_config.dict()) if task.retry_config else None,
                task.status, task.attempt_count, task.workflow_id,
                task.created_at.isoformat() if task.created_at else None,
                task.started_at.isoformat() if task.started_at else None,
                task.completed_at.isoformat() if task.completed_at else None,
                task.assigned_provider, task.execution_node, task.error_message,
                json.dumps(task.tags) if task.tags else None,
                json.dumps(task.metadata) if task.metadata else None
            ))
        
        await self.db.executemany("""
            INSERT OR REPLACE INTO tasks (
                id, name, protocol, method, params, priority, dependencies,
                timeout, retry_config, status, attempt_count, workflow_id,
                created_at, started_at, completed_at, assigned_provider,
                execution_node, error_message, tags, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        await self.db.commit()
    
    async def get_all_queued_tasks(self) -> List[Task]:
        """Get all tasks that should be in queues on startup"""
        cursor = await self.db.execute("""
            SELECT * FROM tasks 
            WHERE status IN ('queued', 'retry_pending', 'executing')
            ORDER BY created_at
        """)
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]
    
    # Statistics
    async def get_task_count_by_status(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        cursor = await self.db.execute("""
            SELECT status, COUNT(*) as count 
            FROM tasks 
            GROUP BY status
        """)
        rows = await cursor.fetchall()
        return {row['status']: row['count'] for row in rows}
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        """Remove old completed tasks and results before cutoff date"""
        # Delete old task results first (foreign key constraint)
        await self.db.execute("""
            DELETE FROM task_results 
            WHERE task_id IN (
                SELECT id FROM tasks 
                WHERE status IN ('completed', 'failed') 
                AND completed_at < ?
            )
        """, (cutoff_date.isoformat(),))
        
        # Delete old tasks
        cursor = await self.db.execute("""
            DELETE FROM tasks 
            WHERE status IN ('completed', 'failed') 
            AND completed_at < ?
        """, (cutoff_date.isoformat(),))
        
        deleted_count = cursor.rowcount
        await self.db.commit()
        
        # Vacuum to reclaim space
        await self.db.execute("VACUUM")
        
        return deleted_count