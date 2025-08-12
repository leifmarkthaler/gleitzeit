#!/usr/bin/env python3

"""
Debug V5 dependency resolution flow with detailed logging
"""

import asyncio
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gleitzeit_v5.test_ollama_workflow import WorkflowClient
from gleitzeit_v5.hub.central_hub import CentralHub
from gleitzeit_v5.base.config import ComponentConfig
from gleitzeit_v5.components import QueueManagerClient, DependencyResolverClient

# Configure detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class DebugDependencyResolver(DependencyResolverClient):
    """Dependency resolver with debug logging"""
    
    def setup_events(self):
        """Setup event handlers with debug logging"""
        
        @self.sio.on('dependency_check_request')
        async def handle_dependency_check(data):
            logger.error(f"🔍 DEPENDENCY_CHECK_REQUEST received: {data}")
            try:
                from gleitzeit_v5.components.dependency_resolver import DependencyRequest
                from datetime import datetime
                import uuid
                
                request = DependencyRequest(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    dependencies=data['dependencies'],
                    requested_at=datetime.utcnow(),
                    correlation_id=data.get('_correlation_id', str(uuid.uuid4()))
                )
                
                logger.error(f"🔍 Processing dependency request for task {request.task_id}, deps: {request.dependencies}")
                await self._process_dependency_request(request)
                logger.error(f"🔍 Finished processing dependency request for task {request.task_id}")
                
            except Exception as e:
                logger.error(f"❌ Error handling dependency_check_request: {e}")
                import traceback
                traceback.print_exc()
        
        @self.sio.on('task_completed')
        async def handle_task_completed(data):
            logger.error(f"🎉 TASK_COMPLETED received: task_id={data['task_id']}, workflow_id={data['workflow_id']}")
            try:
                from gleitzeit_v5.components.dependency_resolver import TaskResult
                from datetime import datetime
                
                result = TaskResult(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    result=data.get('result'),
                    completed_at=datetime.utcnow(),
                    success=True
                )
                
                logger.error(f"🎉 Storing task result for {result.task_id}")
                await self._store_task_result(result)
                
                logger.error(f"🎉 Checking dependent tasks for {result.task_id}")
                await self._check_dependent_tasks(result.task_id)
                logger.error(f"🎉 Finished checking dependent tasks for {result.task_id}")
                
            except Exception as e:
                logger.error(f"❌ Error handling task_completed: {e}")
                import traceback
                traceback.print_exc()
        
        # Call parent to set up other handlers
        super().setup_events()


class DebugQueueManager(QueueManagerClient):
    """Queue manager with debug logging"""
    
    def setup_events(self):
        """Setup event handlers with debug logging"""
        
        @self.sio.on('queue_task')
        async def handle_queue_task(data):
            logger.error(f"📝 QUEUE_TASK received: task_id={data['task_id']}, dependencies={data.get('dependencies', [])}")
            try:
                from gleitzeit_v5.components.queue_manager import QueuedTask, TaskPriority
                from datetime import datetime
                import uuid
                
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                task = QueuedTask(
                    task_id=data['task_id'],
                    workflow_id=data['workflow_id'],
                    task_type=data.get('task_type', 'generic'),
                    method=data['method'],
                    parameters=data.get('parameters', {}),
                    dependencies=data.get('dependencies', []),
                    priority=TaskPriority(data.get('priority', TaskPriority.NORMAL.value)),
                    created_at=datetime.utcnow()
                )
                
                logger.error(f"📝 Queueing task {task.task_id} with deps: {task.dependencies}")
                await self._queue_task(task, correlation_id)
                logger.error(f"📝 Finished queueing task {task.task_id}")
                
            except Exception as e:
                logger.error(f"❌ Error handling queue_task: {e}")
                import traceback
                traceback.print_exc()
        
        @self.sio.on('dependency_resolved')
        async def handle_dependency_resolved(data):
            logger.error(f"✅ DEPENDENCY_RESOLVED received: dependent_task={data['dependent_task_id']}, dependency={data['dependency_task_id']}")
            try:
                task_id = data['dependent_task_id']
                dependency_id = data['dependency_task_id']
                result = data['result']
                correlation_id = data.get('_correlation_id', str(uuid.uuid4()))
                
                logger.error(f"✅ Resolving dependency {dependency_id} for task {task_id}")
                await self._resolve_dependency(task_id, dependency_id, result, correlation_id)
                logger.error(f"✅ Finished resolving dependency for task {task_id}")
                
            except Exception as e:
                logger.error(f"❌ Error handling dependency_resolved: {e}")
                import traceback
                traceback.print_exc()
        
        # Call parent to set up other handlers
        super().setup_events()


async def test_dependency_debug():
    """Test dependency resolution with debug logging"""
    
    print("🔍 Debugging V5 Dependency Resolution...")
    print("=" * 60)
    
    # Create hub
    config = ComponentConfig()
    config.log_level = "DEBUG"
    
    hub = CentralHub(host="127.0.0.1", port=8001, config=config)
    hub_task = asyncio.create_task(hub.start())
    
    await asyncio.sleep(2)
    
    # Initialize cleanup variables
    components = []
    tasks = []
    workflow_client = None
    
    try:
        print("\n1️⃣ Starting debug components...")
        
        # Start debug components
        queue_manager = DebugQueueManager(component_id="debug-queue", config=config, hub_url="http://localhost:8001")
        tasks.append(asyncio.create_task(queue_manager.start()))
        components.append(queue_manager)
        
        dependency_resolver = DebugDependencyResolver(component_id="debug-depres", config=config, hub_url="http://localhost:8001")
        tasks.append(asyncio.create_task(dependency_resolver.start()))
        components.append(dependency_resolver)
        
        await asyncio.sleep(2)
        print("   ✅ Debug components started")
        
        print("\n2️⃣ Submitting dependent tasks...")
        workflow_client = WorkflowClient()
        await workflow_client.connect_to_hub("http://localhost:8001")
        
        workflow_id = "debug-workflow"
        
        # Task 1: No dependencies (should execute immediately)
        task1_id = "task-1"
        print(f"   📝 Submitting Task 1 ({task1_id}) - no dependencies")
        await workflow_client.submit_task(
            task_id=task1_id,
            workflow_id=workflow_id,
            method='debug/simple',
            parameters={'value': 42},
            dependencies=[]  # No dependencies
        )
        
        # Wait a moment
        await asyncio.sleep(1)
        
        # Task 2: Depends on Task 1
        task2_id = "task-2"
        print(f"   📝 Submitting Task 2 ({task2_id}) - depends on Task 1")
        await workflow_client.submit_task(
            task_id=task2_id,
            workflow_id=workflow_id,
            method='debug/dependent',
            parameters={'input': '${task-1.result}'},
            dependencies=[task1_id]  # Depends on task1
        )
        
        print("\n3️⃣ Simulating Task 1 completion...")
        await asyncio.sleep(2)
        
        # Manually emit task_completed for task 1 to see what happens
        await workflow_client.sio.emit('task_completed', {
            'task_id': task1_id,
            'workflow_id': workflow_id,
            'result': {'answer': 42},
            'execution_time_ms': 100.0
        })
        print(f"   ✅ Emitted task_completed for {task1_id}")
        
        print("\n4️⃣ Waiting to see dependency resolution...")
        await asyncio.sleep(5)
        
        print("\n5️⃣ Checking component states...")
        print(f"   Queue manager pending tasks: {len(queue_manager.pending_tasks)}")
        print(f"   Queue manager dependency waiting: {len(queue_manager.dependency_waiting)}")
        print(f"   Dependency resolver pending requests: {len(dependency_resolver.pending_requests)}")
        print(f"   Dependency resolver task results: {len(dependency_resolver.task_results)}")
        
        # Check if task 2 is in pending tasks or dependency waiting
        if task2_id in queue_manager.pending_tasks:
            task2 = queue_manager.pending_tasks[task2_id]
            print(f"   Task 2 status: pending, deps: {task2.dependencies}")
        
        if task2_id in queue_manager.dependency_waiting:
            waiting_deps = queue_manager.dependency_waiting[task2_id]
            print(f"   Task 2 waiting for dependencies: {waiting_deps}")
        
        if task1_id in dependency_resolver.task_results:
            result1 = dependency_resolver.task_results[task1_id]
            print(f"   Task 1 result stored: {result1.result}")
        
        return True
            
    except Exception as e:
        print(f"\n❌ Debug error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        if workflow_client:
            await workflow_client.disconnect()
        
        for component in components:
            await component.shutdown()
        
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        hub_task.cancel()
        try:
            await hub_task
        except asyncio.CancelledError:
            pass
        
        print("\n🧹 Cleanup completed")


if __name__ == "__main__":
    try:
        success = asyncio.run(test_dependency_debug())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        exit(1)