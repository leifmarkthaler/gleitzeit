#!/usr/bin/env python3
"""
Investigate "Task not found" error
"""

import asyncio
import logging
import sys

# Set up logging to capture everything
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Redirect stderr to stdout to capture print statements
class StderrRedirect:
    def write(self, text):
        if "not found" in text.lower():
            print(f"STDERR CAPTURE: {text}", end='')
        sys.__stderr__.write(text)
    def flush(self):
        sys.__stderr__.flush()

sys.stderr = StderrRedirect()

async def main():
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.models import Task, TaskStatus, RetryConfig
    import uuid
    
    print("=== Investigating Task Not Found Error ===\n")
    
    # Create minimal system
    persistence = await PersistenceFactory.create()
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]
    )
    
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    
    # Create a task that will fail
    task = Task(
        id=f"task-{uuid.uuid4().hex[:8]}",
        workflow_id="test-workflow",
        name="test-task",
        protocol="llm/v1",
        method="generate",
        params={"model": "llama3.2", "prompt": "test"},
        retry_config=RetryConfig(max_attempts=1),  # Only try once
        status=TaskStatus.QUEUED
    )
    
    print(f"Created task: {task.id}")
    
    # Save task to persistence
    await persistence.save_task(task)
    print("Task saved to persistence")
    
    # Verify it exists
    retrieved = await persistence.get_task(task.id)
    if retrieved:
        print(f"✓ Task retrieved successfully: status={retrieved.status}")
    else:
        print(f"✗ Could not retrieve task!")
    
    # Now try to execute it through the execution engine
    print("\nAttempting task execution...")
    
    if system_manager.execution_engine:
        try:
            result = await system_manager.execution_engine.execute_task(task)
            print(f"Execution result: {result.status}")
            if result.error:
                print(f"Error: {result.error}")
        except Exception as e:
            print(f"Execution failed with: {e}")
    
    # Check if task still exists after execution
    print("\nChecking task after execution...")
    post_exec = await persistence.get_task(task.id)
    if post_exec:
        print(f"✓ Task still exists: status={post_exec.status}")
    else:
        print(f"✗ Task disappeared after execution!")
    
    await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())