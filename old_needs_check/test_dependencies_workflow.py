#!/usr/bin/env python3
"""
Test workflow with complex task dependencies using Ollama.
"""

import asyncio
import json
from datetime import datetime

from gleitzeit.core.models import Workflow, Task
from gleitzeit.handlers import handler_loader
from gleitzeit.handlers.ollama import OllamaHandler

async def run_dependency_workflow():
    """Run a workflow with multiple dependent tasks"""

    print("=" * 60)
    print("Testing Task Dependencies with Ollama")
    print("=" * 60)

    # Ensure handlers are loaded
    handler_loader._ensure_loaded()

    # Create handler
    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 120,
        'default_model': 'llama3.2'
    })

    # Create workflow with dependency chain:
    # task1 -> task2 -> task4
    #       -> task3 -> task5
    #                -> task6 (depends on both task4 and task5)

    workflow_id = f"dep-test-{datetime.now().timestamp()}"

    workflow = Workflow(
        id=workflow_id,
        name="Dependency Test Workflow",
        version="1.0.0",
        description="Test complex task dependencies",
        tasks=[
            Task(
                id="task1",
                workflow_id=workflow_id,
                name="Task 1: Generate Topic",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Name one interesting science topic in exactly 3 words.",
                    "options": {"temperature": 0.7, "num_predict": 10}
                }
            ),
            Task(
                id="task2",
                workflow_id=workflow_id,
                name="Task 2: Expand Topic (depends on task1)",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Write one sentence about quantum physics.",
                    "options": {"temperature": 0.7, "num_predict": 30}
                },
                dependencies=["task1"]
            ),
            Task(
                id="task3",
                workflow_id=workflow_id,
                name="Task 3: Create Question (depends on task1)",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Ask one simple question about quantum physics.",
                    "options": {"temperature": 0.7, "num_predict": 20}
                },
                dependencies=["task1"]
            ),
            Task(
                id="task4",
                workflow_id=workflow_id,
                name="Task 4: Deep Dive (depends on task2)",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Add one more technical detail about quantum physics.",
                    "options": {"temperature": 0.7, "num_predict": 30}
                },
                dependencies=["task2"]
            ),
            Task(
                id="task5",
                workflow_id=workflow_id,
                name="Task 5: Answer Question (depends on task3)",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Give a brief answer: What is quantum entanglement?",
                    "options": {"temperature": 0.7, "num_predict": 30}
                },
                dependencies=["task3"]
            ),
            Task(
                id="task6",
                workflow_id=workflow_id,
                name="Task 6: Summarize All (depends on task4 and task5)",
                protocol="ollama/v1",
                method="ollama/chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "system", "content": "You are a helpful summarizer."},
                        {"role": "user", "content": "Summarize quantum physics in one sentence."}
                    ],
                    "options": {"temperature": 0.5, "num_predict": 40}
                },
                dependencies=["task4", "task5"]
            )
        ]
    )

    print(f"\nWorkflow created with {len(workflow.tasks)} tasks")
    print("\nDependency structure:")
    print("  task1 (no deps)")
    print("    ├─> task2 (depends on task1)")
    print("    │     └─> task4 (depends on task2)")
    print("    └─> task3 (depends on task1)")
    print("          └─> task5 (depends on task3)")
    print("  task6 (depends on task4 AND task5)")
    print()

    # Execute tasks respecting dependencies
    results = {}
    completed_tasks = set()

    while len(completed_tasks) < len(workflow.tasks):
        for task in workflow.tasks:
            if task.id in completed_tasks:
                continue

            # Check if all dependencies are satisfied
            if task.dependencies:
                deps_satisfied = all(dep_id in completed_tasks for dep_id in task.dependencies)
                if not deps_satisfied:
                    waiting_for = [d for d in task.dependencies if d not in completed_tasks]
                    print(f"⏳ Task '{task.id}' waiting for: {waiting_for}")
                    continue

            # Execute task
            print(f"\n▶️  Executing: {task.name}")
            if task.dependencies:
                print(f"   Dependencies satisfied: {task.dependencies}")

            try:
                result = await handler.execute(task)
                results[task.id] = result

                if result.status == 'completed':
                    completed_tasks.add(task.id)
                    print(f"   ✓ Completed in {result.duration_seconds:.2f}s")

                    # Show output
                    if task.method == "ollama/generate":
                        response = result.result.get('response', 'No response')
                        print(f"   Output: {response[:100]}...")
                    elif task.method == "ollama/chat":
                        message = result.result.get('message', {})
                        content = message.get('content', 'No response')
                        print(f"   Output: {content[:100]}...")
                else:
                    print(f"   ✗ Failed: {result.error}")
                    completed_tasks.add(task.id)  # Mark as done even if failed

            except Exception as e:
                print(f"   ✗ Exception: {e}")
                completed_tasks.add(task.id)

    # Summary
    print("\n" + "=" * 60)
    print("Execution Summary")
    print("=" * 60)

    successful = sum(1 for r in results.values() if r.status == 'completed')
    failed = sum(1 for r in results.values() if r.status == 'failed')

    print(f"Total tasks: {len(workflow.tasks)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    if successful == len(workflow.tasks):
        print("\n✅ All tasks completed successfully with dependencies respected!")
    else:
        print(f"\n⚠️  {failed} task(s) failed")

    return results

if __name__ == "__main__":
    try:
        asyncio.run(run_dependency_workflow())
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()