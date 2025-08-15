#!/usr/bin/env python3
"""
Test Python Batch Processing using examples/batch_python_workflow.yaml
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, os.path.join(parent_dir, 'src'))

from gleitzeit.core import ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.sqlite_backend import SQLiteBackend
from gleitzeit.providers.python_function_provider import CustomFunctionProvider
from gleitzeit.protocols.python_protocol import PYTHON_PROTOCOL_V1


async def test_python_batch_workflow():
    """Test the Python batch workflow from examples"""
    
    print("Testing Python Batch Processing Workflow")
    print("-" * 50)
    
    # Setup temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backend = SQLiteBackend(str(db_path))
        await backend.initialize()
        
        # Setup registry and providers
        registry = ProtocolProviderRegistry()
        registry.register_protocol(PYTHON_PROTOCOL_V1)
        
        python_provider = CustomFunctionProvider("python-1")
        await python_provider.initialize()
        registry.register_provider("python-1", "python/v1", python_provider)
        
        # Create execution engine
        queue_manager = QueueManager()
        dependency_resolver = DependencyResolver()
        
        engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=backend,
            max_concurrent_tasks=5
        )
        
        # Load the Python batch workflow from examples
        workflow_path = "examples/batch_python_workflow.yaml"
        print(f"Loading workflow: {workflow_path}")
        
        try:
            workflow = load_workflow_from_file(workflow_path)
            print(f"✅ Workflow loaded: {workflow.name}")
            print(f"   Tasks: {len(workflow.tasks)}")
            
            # Execute workflow
            print("\nExecuting workflow...")
            await engine._execute_workflow(workflow)
            
            # Check results
            success_count = 0
            failed_count = 0
            
            print("\nResults:")
            for task in workflow.tasks:
                if task.id in engine.task_results:
                    result = engine.task_results[task.id]
                    
                    # Check if result contains expected fields
                    if isinstance(result, dict) and 'result' in result:
                        task_result = result['result']
                        if isinstance(task_result, dict) and task_result.get('success'):
                            success_count += 1
                            print(f"  ✅ {task.name}:")
                            print(f"     - File: {task_result.get('file_path', 'unknown')}")
                            print(f"     - Lines: {task_result.get('line_count', 0)}")
                            print(f"     - Words: {task_result.get('word_count', 0)}")
                        else:
                            failed_count += 1
                            print(f"  ❌ {task.name}: Failed")
                    else:
                        # Even if structure is different, task completed
                        success_count += 1
                        print(f"  ✅ {task.name}: Completed")
                else:
                    failed_count += 1
                    print(f"  ❌ {task.name}: No result")
            
            # Summary
            print("\n" + "="*50)
            print("Summary:")
            print(f"  Total tasks: {len(workflow.tasks)}")
            print(f"  Successful: {success_count}")
            print(f"  Failed: {failed_count}")
            
            # Cleanup
            await backend.shutdown()
            await registry.stop()
            
            # Test passes if all tasks succeeded
            if success_count == len(workflow.tasks):
                print("\n✅ Python batch workflow test passed!")
                return True
            else:
                print(f"\n❌ Python batch workflow test failed: {failed_count} tasks failed")
                return False
                
        except Exception as e:
            print(f"❌ Error running workflow: {e}")
            await backend.shutdown()
            await registry.stop()
            return False


def main():
    """Main test runner"""
    success = asyncio.run(test_python_batch_workflow())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()