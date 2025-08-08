#!/usr/bin/env python3
"""
Standalone Executor Node

This is the actual worker process that connects to the cluster
and executes tasks assigned to it via Socket.IO.
"""

import asyncio
import json
import logging
import psutil
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import socketio

from ..core.node import ExecutorNode, NodeCapabilities, NodeResources, NodeHealth, NodeStatus
from ..core.task import Task, TaskType, TaskStatus
from .task_executor import TaskExecutor


logger = logging.getLogger(__name__)


class GleitzeitExecutorNode:
    """
    Standalone executor node that connects to Gleitzeit cluster
    
    This process runs independently and:
    1. Connects to cluster via Socket.IO
    2. Registers with cluster capabilities
    3. Receives task assignments
    4. Executes tasks using TaskExecutor
    5. Reports results back to cluster
    6. Monitors system resources
    """
    
    def __init__(
        self,
        name: str,
        cluster_url: str = "http://localhost:8000",
        capabilities: Optional[NodeCapabilities] = None,
        heartbeat_interval: int = 30,
        max_concurrent_tasks: int = 3
    ):
        self.name = name
        self.cluster_url = cluster_url
        self.heartbeat_interval = heartbeat_interval
        self.node_id = str(uuid.uuid4())
        
        # Default capabilities if not provided
        if capabilities is None:
            capabilities = NodeCapabilities(
                supported_task_types={
                    TaskType.TEXT_PROMPT,
                    TaskType.VISION_TASK,
                    TaskType.PYTHON_FUNCTION,
                    TaskType.HTTP_REQUEST,
                    TaskType.FILE_OPERATION
                },
                available_models=["llama3", "llava", "codellama"],
                max_concurrent_tasks=max_concurrent_tasks,
                has_gpu=self._detect_gpu(),
                cpu_cores=psutil.cpu_count(),
                memory_gb=psutil.virtual_memory().total / (1024**3)
            )
        
        # Node representation
        self.node = ExecutorNode(
            id=self.node_id,
            name=name,
            capabilities=capabilities,
            status=NodeStatus.STARTING
        )
        
        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=10,
            reconnection_delay=1,
            reconnection_delay_max=30
        )
        
        # Task execution
        self.executor = TaskExecutor()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        
        # State
        self.running = False
        self.connected = False
        self.registered = False
        
        # Setup event handlers
        self._setup_handlers()
        
        # Resource monitoring
        self.last_resource_update = time.time()
    
    def _detect_gpu(self) -> bool:
        """Detect if GPU is available"""
        try:
            import GPUtil
            return len(GPUtil.getGPUs()) > 0
        except ImportError:
            # Try nvidia-ml-py
            try:
                import pynvml
                pynvml.nvmlInit()
                return pynvml.nvmlDeviceGetCount() > 0
            except Exception:
                return False
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        # Connection events
        self.sio.on('connect', namespace='/cluster')(self.handle_connect)
        self.sio.on('disconnect', namespace='/cluster')(self.handle_disconnect)
        self.sio.on('connect_error')(self.handle_connect_error)
        
        # Authentication
        self.sio.on('authenticated', namespace='/cluster')(self.handle_authenticated)
        self.sio.on('authentication_failed', namespace='/cluster')(self.handle_auth_failed)
        
        # Task assignment
        self.sio.on('task:assign', namespace='/cluster')(self.handle_task_assign)
        self.sio.on('task:cancel', namespace='/cluster')(self.handle_task_cancel)
        
        # Cluster events
        self.sio.on('cluster:shutdown', namespace='/cluster')(self.handle_cluster_shutdown)
    
    async def start(self):
        """Start the executor node"""
        logger.info(f"🚀 Starting executor node: {self.name}")
        print(f"🚀 Starting executor node: {self.name}")
        print(f"   Node ID: {self.node_id}")
        print(f"   Cluster: {self.cluster_url}")
        print(f"   Capabilities: {len(self.node.capabilities.supported_task_types)} task types")
        
        self.running = True
        
        try:
            # Start task executor
            await self.executor.start()
            
            # Connect to cluster
            await self.sio.connect(self.cluster_url, namespaces=['/cluster'])
            
            # Start background tasks
            await asyncio.gather(
                self._heartbeat_loop(),
                self._resource_monitor_loop(),
                return_exceptions=True
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to start executor node: {e}")
            raise
    
    async def stop(self):
        """Stop the executor node"""
        logger.info(f"🛑 Stopping executor node: {self.name}")
        print(f"🛑 Stopping executor node: {self.name}")
        
        self.running = False
        
        # Cancel active tasks
        for task_id, task_coroutine in self.active_tasks.items():
            if not task_coroutine.done():
                logger.info(f"⚠️  Cancelling active task: {task_id}")
                task_coroutine.cancel()
        
        # Wait for tasks to complete
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
        
        # Disconnect from cluster
        if self.connected:
            await self.sio.disconnect()
        
        # Stop executor
        await self.executor.stop()
        
        print("✅ Executor node stopped")
    
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
            'client_type': 'executor',
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
            
            # Register node with cluster
            await self.register_with_cluster()
        else:
            logger.error("❌ Authentication failed")
            print("❌ Authentication failed")
    
    async def handle_auth_failed(self, data):
        """Handle authentication failure"""
        logger.error(f"❌ Authentication failed: {data.get('error')}")
        print(f"❌ Authentication failed: {data.get('error')}")
    
    async def register_with_cluster(self):
        """Register this node with the cluster"""
        logger.info(f"📋 Registering with cluster...")
        print(f"📋 Registering with cluster...")
        
        # Update node status
        self.node.status = NodeStatus.HEALTHY
        
        # Send registration
        await self.sio.emit('node:register', {
            'node_id': self.node_id,
            'name': self.name,
            'capabilities': {
                'task_types': [t.value for t in self.node.capabilities.supported_task_types],
                'available_models': self.node.capabilities.available_models,
                'max_concurrent_tasks': self.node.capabilities.max_concurrent_tasks,
                'has_gpu': self.node.capabilities.has_gpu,
                'cpu_cores': self.node.capabilities.cpu_cores,
                'memory_gb': self.node.capabilities.memory_gb
            }
        }, namespace='/cluster')
        
        self.registered = True
        logger.info("✅ Successfully registered with cluster")
        print("✅ Successfully registered with cluster")
        print(f"   Ready to execute tasks!")
    
    # ========================
    # Task Handlers
    # ========================
    
    async def handle_task_assign(self, data):
        """Handle task assignment from cluster"""
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        task_type = data.get('task_type')
        
        logger.info(f"📋 Received task assignment: {task_id}")
        print(f"📋 Received task assignment: {task_id} (type: {task_type})")
        
        # Check if we can handle this task
        try:
            task_type_enum = TaskType(task_type)
        except ValueError:
            logger.error(f"❌ Unknown task type: {task_type}")
            await self.report_task_failed(task_id, workflow_id, f"Unknown task type: {task_type}")
            return
        
        if task_type_enum not in self.node.capabilities.supported_task_types:
            logger.warning(f"⚠️  Task type not supported: {task_type}")
            await self.report_task_failed(task_id, workflow_id, f"Task type not supported: {task_type}")
            return
        
        # Check capacity
        if len(self.active_tasks) >= self.node.capabilities.max_concurrent_tasks:
            logger.warning(f"⚠️  At capacity, rejecting task: {task_id}")
            await self.report_task_failed(task_id, workflow_id, "Node at capacity")
            return
        
        # Accept task
        await self.sio.emit('task:accepted', {
            'task_id': task_id,
            'workflow_id': workflow_id,
            'node_id': self.node_id
        }, namespace='/cluster')
        
        # Execute task asynchronously
        task_coroutine = asyncio.create_task(
            self.execute_task(task_id, workflow_id, data)
        )
        self.active_tasks[task_id] = task_coroutine
        
        # Update node resources
        self.node.assign_task(task_id)
    
    async def handle_task_cancel(self, data):
        """Handle task cancellation"""
        task_id = data.get('task_id')
        
        logger.info(f"❌ Task cancellation requested: {task_id}")
        print(f"❌ Task cancellation requested: {task_id}")
        
        if task_id in self.active_tasks:
            task_coroutine = self.active_tasks[task_id]
            if not task_coroutine.done():
                task_coroutine.cancel()
            del self.active_tasks[task_id]
            self.node.complete_task(task_id, success=False)
    
    async def execute_task(self, task_id: str, workflow_id: str, task_data: Dict[str, Any]):
        """Execute a task"""
        start_time = time.time()
        
        try:
            logger.info(f"⚡ Executing task: {task_id}")
            print(f"⚡ Executing task: {task_id}")
            
            # Create Task object
            task = Task(
                id=task_id,
                name=task_data.get('name', task_id),
                task_type=TaskType(task_data['task_type']),
                parameters=task_data.get('parameters', {}),
                timeout=task_data.get('timeout', 300)
            )
            
            # Report progress
            await self.report_task_progress(task_id, workflow_id, 0, "Starting task execution")
            
            # Execute task
            result = await self.executor.execute_task(task)
            
            # Report completion
            execution_time = time.time() - start_time
            logger.info(f"✅ Task completed: {task_id} (took {execution_time:.2f}s)")
            print(f"✅ Task completed: {task_id} (took {execution_time:.2f}s)")
            
            await self.report_task_completed(task_id, workflow_id, result)
            
        except asyncio.CancelledError:
            logger.info(f"❌ Task cancelled: {task_id}")
            print(f"❌ Task cancelled: {task_id}")
            await self.report_task_failed(task_id, workflow_id, "Task cancelled")
            
        except Exception as e:
            logger.error(f"❌ Task failed: {task_id} - {e}")
            print(f"❌ Task failed: {task_id} - {e}")
            await self.report_task_failed(task_id, workflow_id, str(e))
            
        finally:
            # Clean up
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
            self.node.complete_task(task_id, success=True)
    
    async def report_task_progress(self, task_id: str, workflow_id: str, progress: int, message: str):
        """Report task progress to cluster"""
        if self.connected:
            await self.sio.emit('task:progress', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'progress': progress,
                'message': message,
                'node_id': self.node_id,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    async def report_task_completed(self, task_id: str, workflow_id: str, result: Any):
        """Report task completion to cluster"""
        if self.connected:
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'result': result,
                'node_id': self.node_id,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    async def report_task_failed(self, task_id: str, workflow_id: str, error: str):
        """Report task failure to cluster"""
        if self.connected:
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'error': error,
                'node_id': self.node_id,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
    
    # ========================
    # Background Tasks
    # ========================
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to cluster"""
        while self.running:
            if self.connected and self.registered:
                await self.send_heartbeat()
            
            await asyncio.sleep(self.heartbeat_interval)
    
    async def send_heartbeat(self):
        """Send heartbeat with current status"""
        try:
            # Get current resources
            resources = self._get_current_resources()
            
            await self.sio.emit('node:heartbeat', {
                'node_id': self.node_id,
                'status': self.node.status.value,
                'active_tasks': len(self.active_tasks),
                'cpu_usage': resources.cpu_usage_percent,
                'memory_usage': resources.memory_usage_percent,
                'timestamp': datetime.utcnow().isoformat()
            }, namespace='/cluster')
            
        except Exception as e:
            logger.error(f"❌ Failed to send heartbeat: {e}")
    
    async def _resource_monitor_loop(self):
        """Monitor system resources"""
        while self.running:
            # Update resources every 5 seconds
            resources = self._get_current_resources()
            self.node.update_resources(resources)
            
            await asyncio.sleep(5)
    
    def _get_current_resources(self) -> NodeResources:
        """Get current system resource usage"""
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # GPU usage (if available)
        gpu_percent = None
        gpu_memory_percent = None
        
        if self.node.capabilities.has_gpu:
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]  # Use first GPU
                    gpu_percent = gpu.load * 100
                    gpu_memory_percent = gpu.memoryUtil * 100
            except Exception:
                pass
        
        return NodeResources(
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory_percent,
            gpu_usage_percent=gpu_percent,
            gpu_memory_usage_percent=gpu_memory_percent,
            active_tasks=len(self.active_tasks),
            queue_length=0  # No queue in this implementation
        )
    
    async def handle_cluster_shutdown(self, data):
        """Handle cluster shutdown notification"""
        logger.info("🛑 Cluster shutdown requested")
        print("🛑 Cluster shutdown requested")
        await self.stop()


# Signal handling for graceful shutdown
def setup_signal_handlers(executor_node: GleitzeitExecutorNode):
    """Setup signal handlers for graceful shutdown"""
    
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}, shutting down...")
        print(f"📡 Received signal {signum}, shutting down...")
        
        # Create shutdown task
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(executor_node.stop())
        else:
            loop.run_until_complete(executor_node.stop())
        
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point for standalone executor node"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit Executor Node")
    parser.add_argument("--name", default="executor-1", help="Node name")
    parser.add_argument("--cluster", default="http://localhost:8000", help="Cluster URL")
    parser.add_argument("--tasks", type=int, default=3, help="Max concurrent tasks")
    parser.add_argument("--heartbeat", type=int, default=30, help="Heartbeat interval (seconds)")
    
    args = parser.parse_args()
    
    # Create executor node
    executor_node = GleitzeitExecutorNode(
        name=args.name,
        cluster_url=args.cluster,
        max_concurrent_tasks=args.tasks,
        heartbeat_interval=args.heartbeat
    )
    
    # Setup signal handlers
    setup_signal_handlers(executor_node)
    
    try:
        await executor_node.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Executor node failed: {e}")
        logger.exception("Executor node failed")
    finally:
        await executor_node.stop()


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(main())