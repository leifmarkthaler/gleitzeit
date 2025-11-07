#!/usr/bin/env python3
"""
Test Ollama handler integration with Gleitzeit's workflow execution system.
This test uses the actual workflow execution engine with dependency resolution.
"""

import asyncio
import json
import redis.asyncio as redis
from datetime import datetime

from gleitzeit.core.models import Workflow, Task
from gleitzeit.workers.runner import WorkflowRunner
from gleitzeit.workers.dependency_worker import DependencyWorker
from gleitzeit.workers.task_execution_worker import TaskExecutionWorker
from gleitzeit.handlers import handler_loader


async def create_ollama_workflow():
    """Create a workflow with Ollama tasks and dependencies"""

    workflow = Workflow(
        id=f"ollama-workflow-{datetime.now().timestamp()}",
        name="Ollama AI Workflow",
        version="1.0.0",
        description="AI workflow with dependencies",
        tasks=[
            Task(
                id="story-start",
                workflow_id=f"ollama-workflow-{datetime.now().timestamp()}",
                name="Generate Story Beginning",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Write the beginning of a short story about a robot discovering art. Maximum 3 sentences.",
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 60
                    }
                },
                dependencies=[]  # No dependencies
            ),
            Task(
                id="story-continue",
                workflow_id=f"ollama-workflow-{datetime.now().timestamp()}",
                name="Continue Story",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Continue the story: {{ tasks.story-start.result.response }}. Add 2-3 more sentences.",
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 60
                    }
                },
                dependencies=["story-start"]  # Depends on story-start
            ),
            Task(
                id="analyze",
                workflow_id=f"ollama-workflow-{datetime.now().timestamp()}",
                name="Analyze Story",
                protocol="ollama/v1",
                method="ollama/chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "system", "content": "You are a literary critic. Provide brief analysis."},
                        {"role": "user", "content": "What is the main theme of this story? Story: {{ tasks.story-start.result.response }} {{ tasks.story-continue.result.response }}"}
                    ],
                    "options": {
                        "temperature": 0.5,
                        "num_predict": 100
                    }
                },
                dependencies=["story-start", "story-continue"]  # Depends on both
            ),
            Task(
                id="summarize",
                workflow_id=f"ollama-workflow-{datetime.now().timestamp()}",
                name="Summarize in One Line",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Summarize this story in exactly one sentence: {{ tasks.story-start.result.response }} {{ tasks.story-continue.result.response }}",
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 30
                    }
                },
                dependencies=["story-continue"]  # Only needs the continued story
            )
        ]
    )

    # Set workflow ID for all tasks
    for task in workflow.tasks:
        task.workflow_id = workflow.id

    return workflow


async def run_with_gleitzeit_engine():
    """Run workflow using Gleitzeit's execution engine"""

    print("=" * 70)
    print("Testing Ollama Handler with Gleitzeit Workflow Engine")
    print("=" * 70)

    # Ensure handlers are loaded
    handler_loader._ensure_loaded()

    # Check if Ollama handler is registered
    registry = handler_loader.get_registry()
    if not registry.get_handler('ollama/v1'):
        print("❌ Ollama handler not registered!")
        return

    print("✅ Ollama handler is registered")

    # Connect to Redis
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    try:
        await redis_client.ping()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        print("Please ensure Redis is running: redis-server")
        return

    # Create workflow
    workflow = await create_ollama_workflow()
    print(f"\n📋 Created workflow: {workflow.name}")
    print(f"   ID: {workflow.id}")
    print(f"   Tasks: {len(workflow.tasks)}")

    # Display task dependencies
    print("\n📊 Task Dependencies:")
    for task in workflow.tasks:
        deps = f" (depends on: {', '.join(task.dependencies)})" if task.dependencies else " (no dependencies)"
        print(f"   - {task.id}{deps}")

    # Store workflow in Redis
    workflow_key = f"workflow:{workflow.id}"
    await redis_client.hset(
        workflow_key,
        mapping={
            "id": workflow.id,
            "name": workflow.name,
            "status": "pending",
            "definition": workflow.model_dump_json()
        }
    )

    # Initialize workers
    print("\n🔧 Initializing workers...")

    # Configuration for workers
    worker_config = {
        "redis_url": "redis://localhost:6379",
        "max_retries": 3,
        "retry_delay": 1
    }

    # Create runner to manage the workflow
    runner = WorkflowRunner(
        redis_client=redis_client,
        config=worker_config
    )

    print("✅ Workers initialized")

    # Execute workflow
    print(f"\n🚀 Executing workflow...")
    print("-" * 50)

    # Submit workflow for execution
    await runner.submit_workflow(workflow)

    # Monitor execution
    start_time = asyncio.get_event_loop().time()
    timeout = 120  # 2 minute timeout
    check_interval = 2  # Check every 2 seconds

    while True:
        # Get workflow status
        workflow_data = await redis_client.hgetall(workflow_key)
        status = workflow_data.get("status", "unknown")

        # Get task statuses
        task_statuses = {}
        for task in workflow.tasks:
            task_key = f"task:{task.id}"
            task_data = await redis_client.hgetall(task_key)
            if task_data:
                task_statuses[task.id] = {
                    "status": task_data.get("status", "pending"),
                    "error": task_data.get("error"),
                    "result": task_data.get("result")
                }

        # Display progress
        print(f"\r⏱️  Workflow status: {status} | ", end="")
        completed = sum(1 for t in task_statuses.values() if t["status"] == "completed")
        print(f"Tasks: {completed}/{len(workflow.tasks)} completed", end="")

        # Check if workflow is complete
        if status in ["completed", "failed"]:
            print()  # New line
            break

        # Check timeout
        if asyncio.get_event_loop().time() - start_time > timeout:
            print("\n⚠️  Workflow execution timeout!")
            break

        await asyncio.sleep(check_interval)

    # Display results
    print("\n" + "=" * 70)
    print("Workflow Execution Results")
    print("=" * 70)

    for task in workflow.tasks:
        task_key = f"task:{task.id}"
        task_data = await redis_client.hgetall(task_key)

        print(f"\n📝 Task: {task.name}")
        print(f"   ID: {task.id}")

        if task_data:
            status = task_data.get("status", "unknown")

            if status == "completed":
                print(f"   ✅ Status: {status}")

                # Parse and display result
                try:
                    result = json.loads(task_data.get("result", "{}"))

                    if task.method == "ollama/generate":
                        response = result.get("response", "No response")
                        print(f"   Generated: {response[:200]}...")
                    elif task.method == "ollama/chat":
                        message = result.get("message", {})
                        content = message.get("content", "No response")
                        print(f"   Response: {content[:200]}...")

                except json.JSONDecodeError:
                    print(f"   Result: {task_data.get('result', 'No result')}")

            elif status == "failed":
                print(f"   ❌ Status: {status}")
                print(f"   Error: {task_data.get('error', 'Unknown error')}")
            else:
                print(f"   ⏸️  Status: {status}")
        else:
            print(f"   ⚠️  No task data found")

    # Final summary
    print("\n" + "=" * 70)

    final_status = workflow_data.get("status", "unknown")
    if final_status == "completed":
        print("✅ Workflow completed successfully!")
    elif final_status == "failed":
        print("❌ Workflow failed!")
        error = workflow_data.get("error", "Unknown error")
        print(f"   Error: {error}")
    else:
        print(f"⚠️  Workflow ended with status: {final_status}")

    # Cleanup
    await redis_client.close()
    print("\n✅ Cleanup complete")


async def main():
    """Main entry point"""
    try:
        await run_with_gleitzeit_engine()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())