#!/usr/bin/env python
"""
Full integration test for WorkflowHandler.

Tests the complete workflow execution with all workers running.
"""

import asyncio
import json
import sys
import yaml
from pathlib import Path
from datetime import datetime
import logging
import uuid

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import redis.asyncio as redis
from gleitzeit.core.sharding import default_sharding
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.workflow_submission_worker import WorkflowSubmissionWorker
from gleitzeit.workers.workflow_monitor_worker import WorkflowMonitorWorker
from gleitzeit.core.redis_cluster import GleitzeitRedisCluster, RedisConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce noise from other loggers
logging.getLogger('gleitzeit.handlers').setLevel(logging.WARNING)
logging.getLogger('gleitzeit.core').setLevel(logging.WARNING)


class WorkflowIntegrationTest:
    """Integration test for workflow execution"""
    
    def __init__(self):
        self.redis_client = None
        self.workers = []
        self.test_workflow_id = f"test-parent-{uuid.uuid4().hex[:8]}"
        self.child_workflow_id = None
        
    async def setup(self):
        """Setup Redis connection and workers"""
        logger.info("Setting up integration test...")
        
        # Connect to Redis
        redis_config = RedisConfig(
            mode="single",
            single_node_host="localhost",
            single_node_port=6379
        )
        self.redis_client = GleitzeitRedisCluster(config=redis_config)
        await self.redis_client.initialize()
        
        try:
            await self.redis_client.ping()
            logger.info("✓ Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            logger.info("Make sure Redis is running: redis-server")
            raise
        
        # Create worker configs for shard 0
        base_config = {
            'worker_type': 'integration_test',
            'worker_id': 'test-worker',
            'consumer_group': 'test-group',
            'assigned_shards': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            'max_concurrent': 5,
            'batch_size': 5
        }
        
        # Create workers
        logger.info("Creating workers...")
        
        # WorkflowLoaderWorkerV2
        loader_config = WorkerConfig(**{**base_config, 'worker_type': 'workflow_loader'})
        loader_worker = WorkflowLoaderWorkerV2(loader_config)
        loader_worker.redis = self.redis_client
        self.workers.append(loader_worker)
        
        # DependencyWorker
        dep_config = WorkerConfig(**{**base_config, 'worker_type': 'dependency'})
        dep_worker = DependencyWorker(dep_config)
        dep_worker.redis = self.redis_client
        self.workers.append(dep_worker)
        
        # TaskExecutionWorker
        exec_config = WorkerConfig(**{**base_config, 'worker_type': 'task_execution'})
        exec_worker = TaskExecutionWorker(exec_config)
        exec_worker.redis = self.redis_client
        self.workers.append(exec_worker)
        
        # WorkflowSubmissionWorker
        sub_config = WorkerConfig(**{**base_config, 'worker_type': 'workflow_submission'})
        sub_worker = WorkflowSubmissionWorker(sub_config)
        sub_worker.redis = self.redis_client
        self.workers.append(sub_worker)
        
        # WorkflowMonitorWorker
        mon_config = WorkerConfig(**{**base_config, 'worker_type': 'workflow_monitor'})
        mon_worker = WorkflowMonitorWorker(mon_config)
        mon_worker.redis = self.redis_client
        self.workers.append(mon_worker)
        
        # Initialize all workers
        for worker in self.workers:
            await worker.on_initialize()
        
        logger.info(f"✓ Created {len(self.workers)} workers")
        
    async def create_test_workflows(self):
        """Create parent and child workflow definitions"""
        logger.info("\nCreating test workflows...")
        
        # Parent workflow that calls child
        parent_workflow = {
            'name': 'test-parent-workflow',
            'version': '1.0',
            'tasks': [
                {
                    'id': 'prepare',
                    'type': 'python',
                    'code': 'result = {"prepared": True, "value": 42}'
                },
                {
                    'id': 'call_child',
                    'type': 'workflow',
                    'method': 'workflow/execute',
                    'params': {
                        'workflow_ref': 'child_workflow.yaml',
                        'inputs': {'value': '{{ inputs.prepare.value }}'},
                        'shard_preference': 'any'
                    },
                    'dependencies': ['prepare']
                },
                {
                    'id': 'process_result',
                    'type': 'python',
                    'code': '''
child_result = inputs.get("call_child", {})
parent_data = inputs.get("prepare", {})
result = {
    "final": True,
    "parent_value": parent_data.get("value"),
    "child_value": child_result.get("processed"),
    "status": "completed"
}
''',
                    'dependencies': ['call_child']
                }
            ]
        }
        
        return parent_workflow
        
    async def submit_workflow(self, workflow):
        """Submit workflow to loader"""
        logger.info(f"\nSubmitting workflow {self.test_workflow_id}...")
        
        # Submit to workflow loader stream
        loader_stream = default_sharding.get_stream_key(
            "workflow:load",
            workflow_id=self.test_workflow_id
        )
        
        await self.redis_client.xadd(
            loader_stream,
            {
                b'workflow_id': self.test_workflow_id.encode(),
                b'workflow': json.dumps(workflow).encode(),
                b'timestamp': datetime.utcnow().isoformat().encode()
            }
        )
        
        logger.info(f"✓ Workflow submitted to loader stream: {loader_stream}")
        
    async def process_messages(self, max_iterations=50):
        """Process messages with workers"""
        logger.info("\nProcessing workflow...")
        
        for iteration in range(max_iterations):
            processed_any = False
            
            # Process messages for each worker
            for worker in self.workers:
                streams = worker.get_base_streams()
                
                for base_stream in streams:
                    # Check all shards
                    for shard in range(16):
                        stream_key = default_sharding.get_stream_key(base_stream, shard=shard)
                        
                        # Read messages
                        messages = await self.redis_client.xread(
                            {stream_key: '0'},
                            count=1,
                            block=0
                        )
                        
                        if messages:
                            for stream, stream_messages in messages:
                                for msg_id, data in stream_messages:
                                    # Decode data
                                    decoded_data = {}
                                    for k, v in data.items():
                                        key = k.decode() if isinstance(k, bytes) else k
                                        val = v.decode() if isinstance(v, bytes) else v
                                        decoded_data[key] = val
                                    
                                    # Process message
                                    logger.debug(f"Worker {worker.__class__.__name__} processing from {stream.decode()}")
                                    
                                    try:
                                        success = await worker.process_message(
                                            stream.decode(),
                                            msg_id.decode(),
                                            decoded_data
                                        )
                                        
                                        if success:
                                            # ACK the message
                                            await self.redis_client.xack(
                                                stream,
                                                'test-group',
                                                msg_id
                                            )
                                            processed_any = True
                                            
                                    except Exception as e:
                                        logger.error(f"Error processing message: {e}")
            
            # Check if workflow is complete
            workflow_status = await self.check_workflow_status()
            if workflow_status == 'completed':
                logger.info("✓ Workflow completed successfully!")
                return True
            elif workflow_status == 'failed':
                logger.error("❌ Workflow failed")
                return False
                
            if not processed_any:
                # No messages processed, wait a bit
                await asyncio.sleep(0.1)
                
        logger.warning("Max iterations reached")
        return False
        
    async def check_workflow_status(self):
        """Check workflow status"""
        status_key = default_sharding.get_workflow_key('status', self.test_workflow_id)
        status = await self.redis_client.hget(status_key, 'status')
        
        if status:
            return status.decode() if isinstance(status, bytes) else status
        return None
        
    async def verify_results(self):
        """Verify workflow execution results"""
        logger.info("\nVerifying results...")
        
        # Get workflow data
        data_key = default_sharding.get_workflow_key('data', self.test_workflow_id)
        workflow_data = await self.redis_client.hgetall(data_key)
        
        if not workflow_data:
            logger.error("No workflow data found")
            return False
            
        # Check task results
        results = {}
        for key, value in workflow_data.items():
            key_str = key.decode() if isinstance(key, bytes) else key
            if key_str.startswith('task:') and key_str.endswith(':result'):
                task_id = key_str.split(':')[1]
                result = json.loads(value.decode() if isinstance(value, bytes) else value)
                results[task_id] = result
                logger.info(f"  Task {task_id}: {result}")
                
        # Verify expected results
        if 'prepare' in results:
            assert results['prepare'].get('value') == 42, "Prepare task failed"
            logger.info("✓ Prepare task completed correctly")
            
        if 'call_child' in results:
            child_result = results['call_child']
            assert child_result.get('processed') == 84, f"Child processing failed: {child_result}"
            logger.info("✓ Child workflow completed correctly")
            
        if 'process_result' in results:
            final = results['process_result']
            assert final.get('final') == True, "Final processing failed"
            assert final.get('parent_value') == 42, "Parent value incorrect"
            assert final.get('child_value') == 84, "Child value incorrect"
            logger.info("✓ Final result correct")
            
        return True
        
    async def cleanup(self):
        """Clean up test data"""
        logger.info("\nCleaning up...")

        if self.redis_client:
            # Clean up workflow data
            patterns = [
                f"*{self.test_workflow_id}*",
                "*test-parent*",
                "*test-child*"
            ]

            for pattern in patterns:
                cursor = 0
                while True:
                    try:
                        cursor, keys = await self.redis_client.scan(
                            cursor,
                            match=pattern,
                            count=100
                        )

                        if keys:
                            await self.redis_client.delete(*keys)

                        if cursor == 0:
                            break
                    except Exception as e:
                        logger.debug(f"Cleanup error: {e}")
                        break

            # Close Redis connection
            try:
                await self.redis_client.close()
            except Exception as e:
                logger.debug(f"Error closing Redis: {e}")

        logger.info("✓ Cleanup complete")
        
    async def run(self):
        """Run the integration test"""
        try:
            logger.info("="*60)
            logger.info("WORKFLOW HANDLER FULL INTEGRATION TEST")
            logger.info("="*60)
            
            # Setup
            await self.setup()
            
            # Create and submit workflow
            workflow = await self.create_test_workflows()
            await self.submit_workflow(workflow)
            
            # Process workflow
            success = await self.process_messages()
            
            if success:
                # Verify results
                verified = await self.verify_results()
                
                if verified:
                    logger.info("\n" + "="*60)
                    logger.info("✓ ALL INTEGRATION TESTS PASSED")
                    logger.info("="*60)
                else:
                    logger.error("❌ Result verification failed")
            else:
                logger.error("❌ Workflow execution failed")
                
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            
        finally:
            await self.cleanup()


if __name__ == "__main__":
    test = WorkflowIntegrationTest()
    asyncio.run(test.run())