#!/usr/bin/env python3
"""
Gleitzeit Scheduler Node

Standalone scheduler service that connects to the cluster and handles
task assignment, workflow orchestration, and resource management.
"""

import asyncio
import logging
import signal
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from enum import Enum
from dataclasses import dataclass, field

import socketio

from ..core.task import Task, TaskType, TaskStatus
from ..core.workflow import Workflow, WorkflowStatus
from ..core.node import NodeCapabilities


logger = logging.getLogger(__name__)


class SchedulingPolicy(Enum):
    """Task scheduling policies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    FASTEST_RESPONSE = "fastest_response"
    PRIORITY_QUEUE = "priority_queue"
    RESOURCE_AWARE = "resource_aware"


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class QueuedTask:
    """Task in scheduler queue"""
    task_id: str
    workflow_id: str
    task_data: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    queued_at: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    max_retries: int = 3
    assigned_to: Optional[str] = None
    assigned_at: Optional[datetime] = None


@dataclass
class ExecutorInfo:
    """Information about connected executor"""
    sid: str
    node_id: str
    name: str
    capabilities: NodeCapabilities
    status: str = "ready"
    current_tasks: int = 0
    max_tasks: int = 3
    last_heartbeat: Optional[datetime] = None
    avg_task_time: float = 30.0  # seconds
    total_completed: int = 0
    total_failed: int = 0


class GleitzeitScheduler:
    """
    Standalone scheduler node that manages task assignment
    
    This service:
    1. Connects to cluster via Socket.IO
    2. Receives workflow submissions and task queues
    3. Manages executor availability and capabilities
    4. Assigns tasks using configurable scheduling policies
    5. Handles task failures, retries, and timeouts
    6. Provides scheduling analytics and metrics
    """
    
    def __init__(
        self,
        name: str = "scheduler-1",
        cluster_url: str = "http://localhost:8000",
        policy: SchedulingPolicy = SchedulingPolicy.LEAST_LOADED,
        max_queue_size: int = 1000,
        heartbeat_interval: int = 30,
        task_timeout: int = 300,
        retry_delay: int = 5
    ):
        self.name = name
        self.cluster_url = cluster_url
        self.policy = policy
        self.max_queue_size = max_queue_size
        self.heartbeat_interval = heartbeat_interval
        self.task_timeout = task_timeout
        self.retry_delay = retry_delay
        
        self.scheduler_id = f"scheduler_{uuid.uuid4().hex[:8]}"
        self.connected = False
        self.registered = False
        
        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=10,
            reconnection_delay=1,
            reconnection_delay_max=30
        )
        
        # Task queues (priority-based)
        self.task_queues: Dict[TaskPriority, List[QueuedTask]] = {
            priority: [] for priority in TaskPriority
        }
        self.assigned_tasks: Dict[str, QueuedTask] = {}
        
        # Executor tracking
        self.executors: Dict[str, ExecutorInfo] = {}  # sid -> ExecutorInfo
        
        # Statistics
        self.stats = {
            'tasks_queued': 0,
            'tasks_assigned': 0,
            'tasks_completed': 0,
            'tasks_failed': 0,
            'workflows_processed': 0,
            'avg_queue_time': 0.0,
            'started_at': datetime.utcnow()
        }
        
        self._setup_events()
    
    def _setup_events(self):
        """Setup Socket.IO event handlers"""
        # Connection events
        self.sio.on('connect', namespace='/cluster')(self.handle_connect)
        self.sio.on('disconnect', namespace='/cluster')(self.handle_disconnect)
        self.sio.on('connect_error')(self.handle_connect_error)
        
        # Authentication
        self.sio.on('authenticated', namespace='/cluster')(self.handle_authenticated)
        self.sio.on('authentication_failed', namespace='/cluster')(self.handle_auth_failed)
        
        # Workflow and task events
        self.sio.on('workflow:submit', namespace='/cluster')(self.handle_workflow_submit)
        self.sio.on('task:completed', namespace='/cluster')(self.handle_task_completed)
        self.sio.on('task:failed', namespace='/cluster')(self.handle_task_failed)
        
        # Executor events
        self.sio.on('executor:registered', namespace='/cluster')(self.handle_executor_registered)
        self.sio.on('executor:disconnected', namespace='/cluster')(self.handle_executor_disconnected)
        self.sio.on('executor:heartbeat', namespace='/cluster')(self.handle_executor_heartbeat)
        
        # Cluster events
        self.sio.on('cluster:shutdown', namespace='/cluster')(self.handle_cluster_shutdown)
    
    async def start(self):
        """Start the scheduler"""
        logger.info(f"🚀 Starting scheduler: {self.name}")
        print(f"🚀 Starting scheduler: {self.name}")
        print(f"   Policy: {self.policy.value}")
        print(f"   Max Queue: {self.max_queue_size}")
        print(f"   Cluster: {self.cluster_url}")
        print()
        
        try:
            # Connect to cluster
            await self.sio.connect(self.cluster_url, namespaces=['/cluster'])
            
            # Start background tasks
            await asyncio.gather(
                self._heartbeat_loop(),
                self._scheduling_loop(),
                self._cleanup_loop(),
                return_exceptions=True
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to start scheduler: {e}")
            raise
    
    async def stop(self):
        """Stop the scheduler"""
        logger.info(f"🛑 Stopping scheduler: {self.name}")
        print(f"🛑 Stopping scheduler: {self.name}")
        
        # Disconnect from cluster
        if self.connected:
            await self.sio.disconnect()
        
        print("✅ Scheduler stopped")
    
    # ========================
    # Connection Handlers
    # ========================
    
    async def handle_connect(self):
        """Handle connection to cluster"""
        logger.info(f"🔌 Connected to cluster: {self.cluster_url}")
        print(f"🔌 Connected to cluster: {self.cluster_url}")
        self.connected = True
        
        # Authenticate with cluster
        await self.sio.emit('authenticate', {
            'client_type': 'scheduler',
            'scheduler_id': self.scheduler_id,
            'name': self.name,
            'policy': self.policy.value,
            'token': 'demo_token'  # TODO: Use proper authentication
        }, namespace='/cluster')
    
    async def handle_disconnect(self):
        """Handle disconnection from cluster"""
        logger.warning(f"❌ Disconnected from cluster")
        print(f"❌ Disconnected from cluster")
        self.connected = False
        self.registered = False
    
    async def handle_connect_error(self, data):
        """Handle connection error"""
        logger.error(f"❌ Connection error: {data}")
        print(f"❌ Connection error: {data}")
    
    async def handle_authenticated(self, data):
        """Handle successful authentication"""
        if data.get('success'):
            logger.info("✅ Authenticated with cluster")
            print("✅ Authenticated with cluster")
            
            # Register scheduler with cluster
            await self.register_with_cluster()
        else:
            logger.error("❌ Authentication failed")
            print("❌ Authentication failed")
    
    async def handle_auth_failed(self, data):
        """Handle authentication failure"""
        logger.error(f"❌ Authentication failed: {data.get('error')}")
        print(f"❌ Authentication failed: {data.get('error')}")
    
    async def register_with_cluster(self):
        """Register scheduler with cluster"""
        logger.info("📋 Registering scheduler with cluster...")
        print("📋 Registering scheduler with cluster...")
        
        await self.sio.emit('scheduler:register', {
            'scheduler_id': self.scheduler_id,
            'name': self.name,
            'policy': self.policy.value,
            'max_queue_size': self.max_queue_size,
            'capabilities': {
                'supports_priorities': True,
                'supports_retries': True,
                'supports_timeouts': True,
                'scheduling_policies': [p.value for p in SchedulingPolicy]
            }
        }, namespace='/cluster')
        
        self.registered = True
        print("✅ Scheduler registered")
    
    # ========================
    # Workflow & Task Handlers
    # ========================
    
    async def handle_workflow_submit(self, data):
        """Handle workflow submission from cluster"""
        workflow_id = data.get('workflow_id')
        workflow_data = data.get('workflow')
        
        logger.info(f"📋 Received workflow: {workflow_id}")
        print(f"📋 Received workflow: {workflow_id} ({len(workflow_data.get('tasks', {}))} tasks)")
        
        # Queue tasks from workflow
        await self.queue_workflow_tasks(workflow_id, workflow_data)
        
        self.stats['workflows_processed'] += 1
    
    async def queue_workflow_tasks(self, workflow_id: str, workflow_data: Dict[str, Any]):
        """Queue tasks from a workflow"""
        tasks = workflow_data.get('tasks', {})
        
        for task_id, task_data in tasks.items():
            # Determine priority based on task properties
            priority = self.determine_task_priority(task_data)
            
            # Create queued task
            queued_task = QueuedTask(
                task_id=task_id,
                workflow_id=workflow_id,
                task_data=task_data,
                priority=priority
            )
            
            # Add to appropriate priority queue
            self.task_queues[priority].append(queued_task)
            self.stats['tasks_queued'] += 1
            
            logger.info(f"   ➕ Queued task: {task_id} (priority: {priority.name})")
    
    def determine_task_priority(self, task_data: Dict[str, Any]) -> TaskPriority:
        """Determine task priority based on task properties"""
        # Check for explicit priority
        if 'priority' in task_data:
            priority_str = task_data['priority'].upper()
            if priority_str in TaskPriority.__members__:
                return TaskPriority[priority_str]
        
        # Infer priority from task type
        task_type = task_data.get('type')
        if task_type == TaskType.OLLAMA_VISION.value:
            return TaskPriority.HIGH  # Vision tasks get higher priority
        elif task_type == TaskType.PYTHON_CODE.value:
            return TaskPriority.NORMAL
        
        return TaskPriority.NORMAL
    
    async def handle_task_completed(self, data):
        """Handle task completion from executor"""
        task_id = data.get('task_id')
        executor_sid = data.get('executor_sid')
        
        logger.info(f"✅ Task completed: {task_id}")
        
        if task_id in self.assigned_tasks:
            queued_task = self.assigned_tasks.pop(task_id)
            
            # Update executor info
            if executor_sid in self.executors:
                executor = self.executors[executor_sid]
                executor.current_tasks = max(0, executor.current_tasks - 1)
                executor.total_completed += 1
                
                # Update average task time
                if queued_task.assigned_at:
                    task_time = (datetime.utcnow() - queued_task.assigned_at).total_seconds()
                    executor.avg_task_time = (executor.avg_task_time + task_time) / 2
            
            self.stats['tasks_completed'] += 1
    
    async def handle_task_failed(self, data):
        """Handle task failure from executor"""
        task_id = data.get('task_id')
        executor_sid = data.get('executor_sid')
        error = data.get('error', 'Unknown error')
        
        logger.warning(f"❌ Task failed: {task_id} - {error}")
        
        if task_id in self.assigned_tasks:
            queued_task = self.assigned_tasks.pop(task_id)
            
            # Update executor info
            if executor_sid in self.executors:
                executor = self.executors[executor_sid]
                executor.current_tasks = max(0, executor.current_tasks - 1)
                executor.total_failed += 1
            
            # Handle retry
            queued_task.retry_count += 1
            if queued_task.retry_count <= queued_task.max_retries:
                logger.info(f"🔄 Retrying task: {task_id} (attempt {queued_task.retry_count})")
                
                # Reset assignment and re-queue with delay
                queued_task.assigned_to = None
                queued_task.assigned_at = None
                
                # Add back to queue after delay
                asyncio.create_task(self.delayed_requeue(queued_task))
            else:
                logger.error(f"💥 Task failed permanently: {task_id}")
                self.stats['tasks_failed'] += 1
    
    async def delayed_requeue(self, task: QueuedTask):
        """Re-queue a failed task after delay"""
        await asyncio.sleep(self.retry_delay)
        self.task_queues[task.priority].append(task)
    
    # ========================
    # Executor Management
    # ========================
    
    async def handle_executor_registered(self, data):
        """Handle executor registration"""
        sid = data.get('sid')
        node_id = data.get('node_id')
        name = data.get('name')
        capabilities_data = data.get('capabilities', {})
        
        # Convert capabilities data to NodeCapabilities
        capabilities = NodeCapabilities(
            supported_task_types=[TaskType(t) for t in capabilities_data.get('task_types', [])],
            available_models=capabilities_data.get('available_models', []),
            max_concurrent_tasks=capabilities_data.get('max_concurrent_tasks', 3),
            has_gpu=capabilities_data.get('has_gpu', False),
            memory_limit_gb=capabilities_data.get('memory_limit_gb', 4.0)
        )
        
        executor = ExecutorInfo(
            sid=sid,
            node_id=node_id,
            name=name,
            capabilities=capabilities,
            max_tasks=capabilities.max_concurrent_tasks,
            last_heartbeat=datetime.utcnow()
        )
        
        self.executors[sid] = executor
        
        logger.info(f"🤖 Executor registered: {name} ({node_id})")
        print(f"🤖 Executor registered: {name} ({len(capabilities.supported_task_types)} task types)")
    
    async def handle_executor_disconnected(self, data):
        """Handle executor disconnection"""
        sid = data.get('sid')
        
        if sid in self.executors:
            executor = self.executors.pop(sid)
            logger.info(f"👋 Executor disconnected: {executor.name}")
            print(f"👋 Executor disconnected: {executor.name}")
            
            # Re-queue any tasks assigned to this executor
            tasks_to_requeue = []
            for task_id, task in self.assigned_tasks.items():
                if task.assigned_to == sid:
                    tasks_to_requeue.append(task)
            
            for task in tasks_to_requeue:
                self.assigned_tasks.pop(task.task_id)
                task.assigned_to = None
                task.assigned_at = None
                self.task_queues[task.priority].append(task)
                logger.info(f"🔄 Re-queued task due to executor disconnect: {task.task_id}")
    
    async def handle_executor_heartbeat(self, data):
        """Handle executor heartbeat"""
        sid = data.get('sid')
        
        if sid in self.executors:
            executor = self.executors[sid]
            executor.last_heartbeat = datetime.utcnow()
            executor.status = data.get('status', 'ready')
            executor.current_tasks = data.get('current_tasks', 0)
    
    # ========================
    # Scheduling Logic
    # ========================
    
    async def _scheduling_loop(self):
        """Main scheduling loop"""
        while self.connected:
            try:
                await self.schedule_tasks()
                await asyncio.sleep(1)  # Schedule every second
            except Exception as e:
                logger.error(f"Scheduling loop error: {e}")
                await asyncio.sleep(5)
    
    async def schedule_tasks(self):
        """Schedule available tasks to executors"""
        if not self.registered or not self.executors:
            return
        
        # Process tasks by priority (high to low)
        for priority in sorted(TaskPriority, key=lambda p: p.value, reverse=True):
            queue = self.task_queues[priority]
            
            while queue and self.get_available_executors():
                task = queue.pop(0)
                
                # Find suitable executor
                executor_sid = await self.find_executor_for_task(task)
                if executor_sid:
                    await self.assign_task_to_executor(task, executor_sid)
    
    def get_available_executors(self) -> List[str]:
        """Get list of available executor SIDs"""
        available = []
        for sid, executor in self.executors.items():
            if (executor.status == 'ready' and 
                executor.current_tasks < executor.max_tasks and
                self.is_executor_healthy(executor)):
                available.append(sid)
        return available
    
    def is_executor_healthy(self, executor: ExecutorInfo) -> bool:
        """Check if executor is healthy"""
        if not executor.last_heartbeat:
            return False
        
        # Consider executor unhealthy if no heartbeat in 2 minutes
        return (datetime.utcnow() - executor.last_heartbeat).seconds < 120
    
    async def find_executor_for_task(self, task: QueuedTask) -> Optional[str]:
        """Find suitable executor for task based on scheduling policy"""
        available_executors = self.get_available_executors()
        
        if not available_executors:
            return None
        
        # Filter by task type capability
        task_type = task.task_data.get('type')
        if task_type:
            compatible_executors = []
            for sid in available_executors:
                executor = self.executors[sid]
                supported_types = [t.value for t in executor.capabilities.supported_task_types]
                if task_type in supported_types:
                    compatible_executors.append(sid)
            
            if compatible_executors:
                available_executors = compatible_executors
            else:
                return None
        
        # Apply scheduling policy
        if self.policy == SchedulingPolicy.ROUND_ROBIN:
            # Simple round-robin (just take first available)
            return available_executors[0]
            
        elif self.policy == SchedulingPolicy.LEAST_LOADED:
            # Choose executor with fewest current tasks
            best_executor = min(available_executors, 
                              key=lambda sid: self.executors[sid].current_tasks)
            return best_executor
            
        elif self.policy == SchedulingPolicy.FASTEST_RESPONSE:
            # Choose executor with best average task time
            best_executor = min(available_executors,
                              key=lambda sid: self.executors[sid].avg_task_time)
            return best_executor
            
        else:
            # Default to first available
            return available_executors[0]
    
    async def assign_task_to_executor(self, task: QueuedTask, executor_sid: str):
        """Assign task to specific executor"""
        executor = self.executors[executor_sid]
        
        # Update task assignment
        task.assigned_to = executor_sid
        task.assigned_at = datetime.utcnow()
        self.assigned_tasks[task.task_id] = task
        
        # Update executor load
        executor.current_tasks += 1
        
        # Send task assignment to executor
        await self.sio.emit('task:assign', {
            'task_id': task.task_id,
            'workflow_id': task.workflow_id,
            'task_data': task.task_data,
            'priority': task.priority.name,
            'retry_count': task.retry_count
        }, room=executor_sid, namespace='/cluster')
        
        self.stats['tasks_assigned'] += 1
        
        logger.info(f"📤 Assigned task {task.task_id} to {executor.name} "
                   f"({executor.current_tasks}/{executor.max_tasks} slots)")
    
    # ========================
    # Background Tasks
    # ========================
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to cluster"""
        while self.connected:
            if self.registered:
                await self.sio.emit('scheduler:heartbeat', {
                    'scheduler_id': self.scheduler_id,
                    'name': self.name,
                    'status': 'running',
                    'stats': self.get_stats(),
                    'timestamp': datetime.utcnow().isoformat()
                }, namespace='/cluster')
            
            await asyncio.sleep(self.heartbeat_interval)
    
    async def _cleanup_loop(self):
        """Clean up expired tasks and inactive executors"""
        while self.connected:
            try:
                await self.cleanup_expired_tasks()
                await self.cleanup_inactive_executors()
                await asyncio.sleep(60)  # Clean up every minute
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(60)
    
    async def cleanup_expired_tasks(self):
        """Clean up tasks that have exceeded timeout"""
        now = datetime.utcnow()
        expired_tasks = []
        
        for task_id, task in self.assigned_tasks.items():
            if task.assigned_at and (now - task.assigned_at).seconds > self.task_timeout:
                expired_tasks.append(task)
        
        for task in expired_tasks:
            logger.warning(f"⏰ Task timeout: {task.task_id}")
            self.assigned_tasks.pop(task.task_id)
            
            # Update executor info
            if task.assigned_to and task.assigned_to in self.executors:
                executor = self.executors[task.assigned_to]
                executor.current_tasks = max(0, executor.current_tasks - 1)
            
            # Re-queue if retries available
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.assigned_to = None
                task.assigned_at = None
                self.task_queues[task.priority].append(task)
                logger.info(f"🔄 Re-queued expired task: {task.task_id}")
    
    async def cleanup_inactive_executors(self):
        """Remove inactive executors"""
        now = datetime.utcnow()
        inactive_executors = []
        
        for sid, executor in self.executors.items():
            if (executor.last_heartbeat and 
                (now - executor.last_heartbeat).seconds > 300):  # 5 minutes
                inactive_executors.append(sid)
        
        for sid in inactive_executors:
            executor = self.executors.pop(sid)
            logger.warning(f"🗑️  Removed inactive executor: {executor.name}")
    
    # ========================
    # Stats and Monitoring
    # ========================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics"""
        total_queued = sum(len(queue) for queue in self.task_queues.values())
        
        return {
            **self.stats,
            'current_queued': total_queued,
            'current_assigned': len(self.assigned_tasks),
            'connected_executors': len(self.executors),
            'available_executors': len(self.get_available_executors()),
            'queue_breakdown': {
                priority.name: len(self.task_queues[priority])
                for priority in TaskPriority
            },
            'uptime_seconds': (datetime.utcnow() - self.stats['started_at']).total_seconds()
        }
    
    async def handle_cluster_shutdown(self, data):
        """Handle cluster shutdown notification"""
        logger.info("🛑 Cluster shutdown received")
        print("🛑 Cluster shutdown received")
        await self.stop()


async def main():
    """Main entry point for standalone scheduler"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit Scheduler Node")
    parser.add_argument("--name", default="scheduler-1", help="Scheduler name")
    parser.add_argument("--cluster", default="http://localhost:8000", help="Cluster URL")
    parser.add_argument("--policy", choices=[p.value for p in SchedulingPolicy], 
                       default=SchedulingPolicy.LEAST_LOADED.value, help="Scheduling policy")
    parser.add_argument("--queue-size", type=int, default=1000, help="Max queue size")
    parser.add_argument("--heartbeat", type=int, default=30, help="Heartbeat interval (seconds)")
    
    args = parser.parse_args()
    
    # Create scheduler
    scheduler = GleitzeitScheduler(
        name=args.name,
        cluster_url=args.cluster,
        policy=SchedulingPolicy(args.policy),
        max_queue_size=args.queue_size,
        heartbeat_interval=args.heartbeat
    )
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down...")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(scheduler.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Scheduler failed: {e}")
        logger.exception("Scheduler failed")
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(main())