#!/usr/bin/env python3
"""
Test workflow execution with Ollama handler.
"""

import asyncio
import json
from datetime import datetime

# Import Gleitzeit components
from gleitzeit.core.models import Workflow, Task
from gleitzeit.handlers import handler_loader
from gleitzeit.handlers.ollama import OllamaHandler

async def run_simple_ollama_workflow():
    """Run a simple workflow with an Ollama task"""

    print("=" * 60)
    print("Testing Ollama Handler Integration")
    print("=" * 60)

    # Ensure handlers are loaded
    handler_loader._ensure_loaded()

    # Check if Ollama handler is registered
    registry = handler_loader.get_registry()
    ollama_handler_class = registry.get_handler('ollama/v1')

    if ollama_handler_class:
        print(f"✓ Ollama handler registered: {ollama_handler_class}")
    else:
        print("✗ Ollama handler not found in registry")
        return

    # Create a simple workflow with Ollama tasks
    workflow = Workflow(
        id=f"ollama-test-{datetime.now().timestamp()}",
        name="Test Ollama Workflow",
        version="1.0.0",
        description="Test workflow for Ollama integration",
        tasks=[
            Task(
                id="list-models",
                workflow_id=f"ollama-test-{datetime.now().timestamp()}",
                name="List Available Models",
                protocol="ollama/v1",
                method="ollama/list_models",
                params={}
            ),
            Task(
                id="generate-haiku",
                workflow_id=f"ollama-test-{datetime.now().timestamp()}",
                name="Generate Haiku",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Write a haiku about artificial intelligence",
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 50
                    }
                }
            ),
            Task(
                id="chat-qa",
                workflow_id=f"ollama-test-{datetime.now().timestamp()}",
                name="Q&A Chat",
                protocol="ollama/v1",
                method="ollama/chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
                        {"role": "user", "content": "What is the capital of Japan?"}
                    ],
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 30
                    }
                },
                dependencies=["generate-haiku"]  # Example dependency
            )
        ]
    )

    print(f"\nWorkflow created: {workflow.name}")
    print(f"Tasks: {len(workflow.tasks)}")

    # Create handler instance
    handler_config = {
        'base_url': 'http://localhost:11434',
        'timeout': 60,
        'default_model': 'llama3.2'
    }

    handler = OllamaHandler(handler_config)
    print(f"\nHandler initialized with config: {handler_config}")

    # Execute tasks
    results = {}

    for task in workflow.tasks:
        # Check dependencies
        if task.dependencies:
            print(f"\nTask '{task.name}' depends on: {task.dependencies}")
            for dep_id in task.dependencies:
                if dep_id not in results or results[dep_id].status != 'completed':
                    print(f"  Waiting for dependency: {dep_id}")

        print(f"\nExecuting task: {task.name}")
        print(f"  Method: {task.method}")
        print(f"  Params: {json.dumps(task.params, indent=2)}")

        try:
            result = await handler.execute(task)
            results[task.id] = result

            if result.status == 'completed':
                print(f"  ✓ Status: {result.status}")
                print(f"  Duration: {result.duration_seconds:.2f}s")

                # Display results based on task type
                if task.method == "ollama/list_models":
                    models = result.result
                    print(f"  Found {len(models)} models:")
                    for model in models[:3]:  # Show first 3
                        print(f"    - {model.get('name', 'unknown')}")

                elif task.method == "ollama/generate":
                    print(f"  Generated text:")
                    print(f"    {result.result.get('response', 'No response')}")

                elif task.method == "ollama/chat":
                    message = result.result.get('message', {})
                    print(f"  Assistant response:")
                    print(f"    {message.get('content', 'No response')}")

            else:
                print(f"  ✗ Status: {result.status}")
                print(f"  Error: {result.error}")

        except Exception as e:
            print(f"  ✗ Exception: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "=" * 60)
    print("Workflow Execution Summary")
    print("=" * 60)

    successful = sum(1 for r in results.values() if r.status == 'completed')
    failed = sum(1 for r in results.values() if r.status == 'failed')

    print(f"Total tasks: {len(workflow.tasks)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    if successful == len(workflow.tasks):
        print("\n✓ All tasks completed successfully!")
    else:
        print(f"\n⚠ {failed} task(s) failed")

    return results


async def run_advanced_workflow():
    """Run a more complex workflow with context passing"""

    print("\n" + "=" * 60)
    print("Advanced Ollama Workflow - Story Generation")
    print("=" * 60)

    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 120,
        'default_model': 'llama3.2'
    })

    # Create a story generation workflow
    tasks = [
        Task(
            id="story-beginning",
            workflow_id="story-workflow",
            name="Generate Story Beginning",
            protocol="ollama/v1",
            method="ollama/generate",
            params={
                "model": "llama3.2",
                "prompt": "Start a science fiction story about a robot learning to paint. Write only 2-3 sentences.",
                "options": {
                    "temperature": 0.9,
                    "num_predict": 50
                }
            }
        ),
        Task(
            id="story-middle",
            workflow_id="story-workflow",
            name="Continue Story",
            protocol="ollama/v1",
            method="ollama/generate",
            params={
                "model": "llama3.2",
                "prompt": "Continue this story with 2-3 more sentences about a challenge the robot faces.",
                "options": {
                    "temperature": 0.9,
                    "num_predict": 50
                }
            }
        ),
        Task(
            id="story-analysis",
            workflow_id="story-workflow",
            name="Analyze Story",
            protocol="ollama/v1",
            method="ollama/chat",
            params={
                "model": "llama3.2",
                "messages": [
                    {"role": "system", "content": "You are a literary critic. Analyze stories briefly."},
                    {"role": "user", "content": "What themes are present in this robot painter story?"}
                ],
                "options": {
                    "temperature": 0.5,
                    "num_predict": 100
                }
            }
        )
    ]

    story_parts = []

    for task in tasks:
        print(f"\n📝 {task.name}...")

        # Add context from previous parts if continuing story
        if task.id == "story-middle" and story_parts:
            task.params["prompt"] = f"Story so far: {story_parts[0]}\n\n{task.params['prompt']}"
        elif task.id == "story-analysis" and story_parts:
            full_story = " ".join(story_parts)
            task.params["messages"][1]["content"] = f"Analyze this story: {full_story}"

        result = await handler.execute(task)

        if result.status == 'completed':
            if task.method == "ollama/generate":
                response = result.result.get('response', '')
                story_parts.append(response)
                print(f"✓ Generated: {response}")
            elif task.method == "ollama/chat":
                response = result.result.get('message', {}).get('content', '')
                print(f"✓ Analysis: {response}")
        else:
            print(f"✗ Failed: {result.error}")

    if len(story_parts) >= 2:
        print("\n" + "=" * 60)
        print("Complete Story:")
        print("=" * 60)
        print(" ".join(story_parts))


async def main():
    """Main entry point"""

    # Run simple workflow
    results = await run_simple_ollama_workflow()

    # Run advanced workflow
    await run_advanced_workflow()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()