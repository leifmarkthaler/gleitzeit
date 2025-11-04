#!/usr/bin/env python3
"""
Ollama LLM Example
==================
This example demonstrates using Gleitzeit with Ollama for LLM tasks.

Prerequisites:
- Ollama installed and running (https://ollama.ai)
- llama3.2:latest model pulled: ollama pull llama3.2:latest
- Gleitzeit server running: gleitzeit serve --dev-mode
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """Run Ollama LLM example"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Simple Ollama workflow
        workflow = {
            'name': 'ollama-haiku',
            'tasks': [
                {
                    'id': 'generate-haiku',
                    'type': 'ollama',
                    'params': {
                        'model': 'llama3.2:latest',
                        'prompt': 'Write a haiku about distributed systems',
                        'options': {
                            'temperature': 0.7,
                            'max_tokens': 100
                        }
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted Ollama workflow: {response.workflow_id}")

        # Wait for completion
        print("\n⏳ Generating haiku with Ollama...")
        status = await client.wait_for_workflow(response.workflow_id, timeout=60)

        print(f"\n✓ Ollama workflow completed: {status.status}")

        # Get the generated haiku
        tasks = await client.get_workflow_tasks(response.workflow_id)
        if tasks:
            task = tasks[0]
            result = task.get('result', {})
            haiku = result.get('response', 'No response')

            print(f"\n📝 Generated Haiku:")
            print(f"\n{haiku}\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Ollama LLM Example")
    print("=" * 60)
    print()

    asyncio.run(main())
