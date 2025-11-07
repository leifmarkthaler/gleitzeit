#!/usr/bin/env python3
"""
End-to-end test of Ollama handler with Gleitzeit workflow execution.
This test simulates what would happen when workflows are submitted to Gleitzeit.
"""

import asyncio
import json
import redis.asyncio as redis
from datetime import datetime
import uuid

from gleitzeit.core.models import Workflow, Task, TaskStatus, WorkflowStatus
from gleitzeit.handlers import handler_loader
from gleitzeit.core.parameter_resolver import ParameterResolver


async def execute_workflow_with_dependencies():
    """Execute a workflow with Ollama tasks, handling dependencies properly"""

    print("=" * 70)
    print("End-to-End Test: Ollama Handler with Dependency Resolution")
    print("=" * 70)

    # Ensure handlers are loaded
    handler_loader._ensure_loaded()
    registry = handler_loader.get_registry()

    # Verify Ollama handler is registered
    ollama_handler_class = registry.get_handler('ollama/v1')
    if not ollama_handler_class:
        print("❌ Ollama handler not registered!")
        return False

    print("✅ Ollama handler registered")

    # Create Redis client
    redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    try:
        await redis_client.ping()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False

    # Create workflow with dependencies
    workflow_id = f"ollama-e2e-{uuid.uuid4()}"
    workflow = Workflow(
        id=workflow_id,
        name="Story Generation Pipeline",
        version="1.0.0",
        description="Multi-step story generation with analysis",
        tasks=[
            Task(
                id="intro",
                workflow_id=workflow_id,
                name="Generate Introduction",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Start a mystery story set in space. Write exactly 2 sentences.",
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 40
                    }
                },
                dependencies=[]
            ),
            Task(
                id="plot-twist",
                workflow_id=workflow_id,
                name="Add Plot Twist",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Add a surprising plot twist to: {{ tasks.intro.result.response }}. Write exactly 2 sentences.",
                    "options": {
                        "temperature": 0.9,
                        "num_predict": 40
                    }
                },
                dependencies=["intro"]
            ),
            Task(
                id="conclusion",
                workflow_id=workflow_id,
                name="Write Conclusion",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Conclude this story: {{ tasks.intro.result.response }} {{ tasks.plot-twist.result.response }}. Write exactly 2 sentences.",
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 40
                    }
                },
                dependencies=["intro", "plot-twist"]
            ),
            Task(
                id="title",
                workflow_id=workflow_id,
                name="Generate Title",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Create a short, catchy title (max 5 words) for: {{ tasks.intro.result.response }} {{ tasks.plot-twist.result.response }}",
                    "options": {
                        "temperature": 0.6,
                        "num_predict": 10
                    }
                },
                dependencies=["plot-twist"]
            )
        ]
    )

    print(f"\n📋 Created workflow: {workflow.name}")
    print(f"   Tasks: {len(workflow.tasks)}")

    # Display dependency graph
    print("\n📊 Dependency Graph:")
    for task in workflow.tasks:
        deps = f" → [{', '.join(task.dependencies)}]" if task.dependencies else ""
        print(f"   {task.id}{deps}")

    # Initialize components
    print("\n🔧 Initializing execution components...")

    # Create Ollama handler
    handler = ollama_handler_class({
        'base_url': 'http://localhost:11434',
        'timeout': 60,
        'default_model': 'llama3.2'
    })

    # Create parameter resolver
    resolver = ParameterResolver()

    # Store workflow state in Redis
    workflow_key = f"workflow:{workflow.id}"
    await redis_client.hset(
        workflow_key,
        mapping={
            "status": WorkflowStatus.EXECUTING.value,
            "definition": workflow.model_dump_json()
        }
    )

    # Execute tasks respecting dependencies
    print("\n🚀 Executing workflow with dependency resolution...")
    print("-" * 50)

    completed_tasks = {}
    task_results = {}
    max_iterations = 10
    iteration = 0

    while len(completed_tasks) < len(workflow.tasks) and iteration < max_iterations:
        iteration += 1
        made_progress = False

        for task in workflow.tasks:
            # Skip already completed tasks
            if task.id in completed_tasks:
                continue

            # Check if dependencies are satisfied
            deps_satisfied = all(dep_id in completed_tasks for dep_id in task.dependencies)

            if deps_satisfied:
                print(f"\n▶️  Executing: {task.name}")

                # Resolve parameters with results from completed tasks
                resolved_params = await resolver.resolve_parameters(
                    task.params,
                    {
                        "tasks": task_results,
                        "workflow": {"id": workflow.id, "name": workflow.name}
                    }
                )

                # Update task with resolved parameters
                task.params = resolved_params

                # Execute task
                try:
                    result = await handler.execute(task)

                    if result.status == TaskStatus.COMPLETED:
                        print(f"   ✅ Completed in {result.duration_seconds:.2f}s")

                        # Store result
                        completed_tasks[task.id] = True
                        task_results[task.id] = {
                            "result": result.result,
                            "status": "completed"
                        }

                        # Store in Redis
                        task_key = f"task:{task.id}"
                        await redis_client.hset(
                            task_key,
                            mapping={
                                "status": "completed",
                                "result": json.dumps(result.result)
                            }
                        )

                        # Display result preview
                        if task.method == "ollama/generate":
                            response = result.result.get('response', '')
                            print(f"   📝 Generated: {response[:100]}...")

                        made_progress = True

                    else:
                        print(f"   ❌ Failed: {result.error}")
                        task_results[task.id] = {
                            "error": result.error,
                            "status": "failed"
                        }

                        # Store failure in Redis
                        task_key = f"task:{task.id}"
                        await redis_client.hset(
                            task_key,
                            mapping={
                                "status": "failed",
                                "error": result.error
                            }
                        )

                except Exception as e:
                    print(f"   ❌ Exception: {e}")
                    task_results[task.id] = {
                        "error": str(e),
                        "status": "failed"
                    }

        if not made_progress:
            print("\n⚠️  No progress made - possible circular dependency or all remaining tasks failed")
            break

    # Display final results
    print("\n" + "=" * 70)
    print("Workflow Execution Complete")
    print("=" * 70)

    if len(completed_tasks) == len(workflow.tasks):
        print("\n✅ All tasks completed successfully!")

        # Compile the full story
        print("\n📖 Generated Story:")
        print("-" * 50)

        title = task_results.get("title", {}).get("result", {}).get("response", "Untitled")
        intro = task_results.get("intro", {}).get("result", {}).get("response", "")
        twist = task_results.get("plot-twist", {}).get("result", {}).get("response", "")
        conclusion = task_results.get("conclusion", {}).get("result", {}).get("response", "")

        print(f"\n**{title.strip()}**\n")
        print(f"{intro.strip()} {twist.strip()} {conclusion.strip()}")

    else:
        failed = len(workflow.tasks) - len(completed_tasks)
        print(f"\n⚠️  {failed} task(s) did not complete")

        for task in workflow.tasks:
            if task.id not in completed_tasks:
                print(f"   - {task.id}: Not executed (dependencies: {task.dependencies})")

    # Update workflow status
    final_status = WorkflowStatus.COMPLETED if len(completed_tasks) == len(workflow.tasks) else WorkflowStatus.FAILED
    await redis_client.hset(
        workflow_key,
        "status",
        final_status.value
    )

    # Cleanup
    await redis_client.close()

    return len(completed_tasks) == len(workflow.tasks)


async def main():
    """Main entry point"""
    try:
        success = await execute_workflow_with_dependencies()
        if success:
            print("\n🎉 End-to-end test passed!")
        else:
            print("\n❌ End-to-end test failed")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)


if __name__ == "__main__":
    import sys
    asyncio.run(main())