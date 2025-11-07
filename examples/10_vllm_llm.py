"""
Example: Using vLLM with Gleitzeit

This example demonstrates:
1. Text completion with vLLM
2. Chat completion with conversation history
3. Listing available models
4. Streaming responses

Prerequisites:
- vLLM server running (default: http://localhost:8000)
  Start with: vllm serve meta-llama/Llama-2-7b-hf
- Redis running
- Gleitzeit running

Usage:
    python examples/10_vllm_llm.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.client import GleitzeitClient


async def example_vllm_completion():
    """Example: Simple text completion with vLLM"""
    print("\n" + "="*60)
    print("Example 1: vLLM Text Completion")
    print("="*60)

    workflow = {
        'name': 'vllm-completion-example',
        'tasks': [
            {
                'id': 'generate_story',
                'type': 'vllm',
                'method': 'vllm/completions',
                'params': {
                    'model': 'meta-llama/Llama-2-7b-hf',  # Change to your model
                    'prompt': 'Once upon a time in a magical forest,',
                    'max_tokens': 100,
                    'temperature': 0.7,
                    'top_p': 0.9
                },
                'timeout': 60
            }
        ]
    }

    async with GleitzeitClient(auto_login=True) as client:
        # Submit workflow
        workflow_id = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id, timeout=120)
        print(f"✓ Workflow completed with status: {result['status']}")

        # Get task results
        tasks = await client.list_workflow_tasks(workflow_id)
        for task in tasks:
            if task['status'] == 'completed' and task['result']:
                print(f"\n📝 Generated Text:")
                print(f"   {task['result']['text']}")
                print(f"\n📊 Usage:")
                usage = task['result'].get('usage', {})
                print(f"   Prompt tokens: {usage.get('prompt_tokens', 'N/A')}")
                print(f"   Completion tokens: {usage.get('completion_tokens', 'N/A')}")
                print(f"   Total tokens: {usage.get('total_tokens', 'N/A')}")


async def example_vllm_chat():
    """Example: Chat completion with conversation history"""
    print("\n" + "="*60)
    print("Example 2: vLLM Chat Completion")
    print("="*60)

    workflow = {
        'name': 'vllm-chat-example',
        'tasks': [
            {
                'id': 'chat_conversation',
                'type': 'vllm',
                'method': 'vllm/chat',
                'params': {
                    'model': 'meta-llama/Llama-2-7b-hf',  # Change to your model
                    'messages': [
                        {
                            'role': 'system',
                            'content': 'You are a helpful AI assistant.'
                        },
                        {
                            'role': 'user',
                            'content': 'What are the three laws of robotics?'
                        }
                    ],
                    'max_tokens': 200,
                    'temperature': 0.7
                },
                'timeout': 60
            }
        ]
    }

    async with GleitzeitClient(auto_login=True) as client:
        # Submit workflow
        workflow_id = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id, timeout=120)
        print(f"✓ Workflow completed with status: {result['status']}")

        # Get task results
        tasks = await client.list_workflow_tasks(workflow_id)
        for task in tasks:
            if task['status'] == 'completed' and task['result']:
                message = task['result'].get('message', {})
                print(f"\n💬 Assistant Response:")
                print(f"   {message.get('content', 'No content')}")
                print(f"\n📊 Usage:")
                usage = task['result'].get('usage', {})
                print(f"   Total tokens: {usage.get('total_tokens', 'N/A')}")


async def example_vllm_streaming():
    """Example: Streaming text generation"""
    print("\n" + "="*60)
    print("Example 3: vLLM Streaming Completion")
    print("="*60)

    workflow = {
        'name': 'vllm-streaming-example',
        'tasks': [
            {
                'id': 'stream_story',
                'type': 'vllm',
                'method': 'vllm/completions',
                'params': {
                    'model': 'meta-llama/Llama-2-7b-hf',  # Change to your model
                    'prompt': 'Write a haiku about programming:',
                    'max_tokens': 50,
                    'temperature': 0.8,
                    'stream': True  # Enable streaming
                },
                'timeout': 60
            }
        ]
    }

    async with GleitzeitClient(auto_login=True) as client:
        # Submit workflow
        workflow_id = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id, timeout=120)
        print(f"✓ Workflow completed with status: {result['status']}")

        # Get task results
        tasks = await client.list_workflow_tasks(workflow_id)
        for task in tasks:
            if task['status'] == 'completed' and task['result']:
                print(f"\n📝 Streamed Text:")
                print(f"   {task['result']['text']}")
                print(f"\n📊 Streaming Info:")
                print(f"   Chunks received: {task['result'].get('chunks', 'N/A')}")


async def example_list_models():
    """Example: List available models"""
    print("\n" + "="*60)
    print("Example 4: List vLLM Models")
    print("="*60)

    workflow = {
        'name': 'vllm-list-models',
        'tasks': [
            {
                'id': 'list_models',
                'type': 'vllm',
                'method': 'vllm/models',
                'params': {},
                'timeout': 30
            }
        ]
    }

    async with GleitzeitClient(auto_login=True) as client:
        # Submit workflow
        workflow_id = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id, timeout=60)
        print(f"✓ Workflow completed with status: {result['status']}")

        # Get task results
        tasks = await client.list_workflow_tasks(workflow_id)
        for task in tasks:
            if task['status'] == 'completed' and task['result']:
                models = task['result']
                print(f"\n📋 Available Models: {len(models)}")
                for model in models:
                    print(f"   - {model.get('id', 'unknown')}")


async def example_multi_step_conversation():
    """Example: Multi-step workflow with vLLM"""
    print("\n" + "="*60)
    print("Example 5: Multi-Step Conversation")
    print("="*60)

    workflow = {
        'name': 'vllm-multi-step',
        'tasks': [
            {
                'id': 'ask_question',
                'type': 'vllm',
                'method': 'vllm/chat',
                'params': {
                    'model': 'meta-llama/Llama-2-7b-hf',
                    'messages': [
                        {'role': 'user', 'content': 'What is Python?'}
                    ],
                    'max_tokens': 100,
                    'temperature': 0.7
                },
                'timeout': 60
            },
            {
                'id': 'follow_up',
                'type': 'vllm',
                'method': 'vllm/chat',
                'params': {
                    'model': 'meta-llama/Llama-2-7b-hf',
                    'messages': [
                        {'role': 'user', 'content': 'What is Python?'},
                        # This would normally include the response from ask_question
                        # but for simplicity we'll ask a follow-up directly
                        {'role': 'user', 'content': 'Can you give me an example?'}
                    ],
                    'max_tokens': 150,
                    'temperature': 0.7
                },
                'depends_on': ['ask_question'],
                'timeout': 60
            }
        ]
    }

    async with GleitzeitClient(auto_login=True) as client:
        # Submit workflow
        workflow_id = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {workflow_id}")

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id, timeout=180)
        print(f"✓ Workflow completed with status: {result['status']}")

        # Get task results
        tasks = await client.list_workflow_tasks(workflow_id)
        for i, task in enumerate(tasks, 1):
            if task['status'] == 'completed' and task['result']:
                message = task['result'].get('message', {})
                print(f"\n💬 Response {i} ({task['id']}):")
                print(f"   {message.get('content', 'No content')}")


async def main():
    """Run all examples"""
    print("\n" + "="*60)
    print("vLLM + Gleitzeit Examples")
    print("="*60)
    print("\nMake sure:")
    print("1. vLLM server is running (vllm serve <model>)")
    print("2. Redis is running")
    print("3. Gleitzeit is running (gleitzeit serve)")
    print("="*60)

    try:
        # Run examples
        await example_vllm_completion()
        await example_vllm_chat()
        await example_vllm_streaming()
        await example_list_models()
        await example_multi_step_conversation()

        print("\n" + "="*60)
        print("✅ All examples completed successfully!")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
