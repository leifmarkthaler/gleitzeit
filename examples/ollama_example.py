#!/usr/bin/env python3
"""
Example demonstrating the Ollama handler for Gleitzeit.

This example shows how to:
1. Configure an Ollama handler
2. Execute text generation tasks
3. Use chat completion
4. Generate embeddings
5. List available models

Prerequisites:
- Ollama running locally (default: http://localhost:11434)
- At least one model installed (e.g., ollama pull llama3.2:latest)
"""

import asyncio
import json
from gleitzeit.handlers.ollama import OllamaHandler
from gleitzeit.core.models import Task


async def main():
    """Run Ollama handler examples"""

    # Configure the handler
    config = {
        'base_url': 'http://localhost:11434',
        'timeout': 60,
        'default_model': 'llama3.2:latest'
    }

    handler = OllamaHandler(config)

    print("Ollama Handler Examples")
    print("=" * 50)

    # Example 1: List available models
    print("\n1. Listing available models:")
    list_task = Task(
        id='example-list-1',
        workflow_id='example-workflow',
        name='list-models',
        protocol='ollama/v1',
        method='ollama/list_models',
        params={}
    )

    result = await handler.execute(list_task)
    if result.status == 'completed':
        print(f"Available models: {json.dumps(result.result, indent=2)}")
    else:
        print(f"Error: {result.error}")

    # Example 2: Text generation
    print("\n2. Text generation:")
    gen_task = Task(
        id='example-gen-1',
        workflow_id='example-workflow',
        name='generate-text',
        protocol='ollama/v1',
        method='ollama/generate',
        params={
            'model': 'llama3.2:latest',
            'prompt': 'Write a haiku about programming',
            'options': {
                'temperature': 0.7,
                'num_predict': 50
            }
        }
    )

    result = await handler.execute(gen_task)
    if result.status == 'completed':
        print(f"Generated text: {result.result['response']}")
        print(f"Generation time: {result.result.get('eval_duration', 0) / 1e9:.2f}s")
    else:
        print(f"Error: {result.error}")

    # Example 3: Chat completion
    print("\n3. Chat completion:")
    chat_task = Task(
        id='example-chat-1',
        workflow_id='example-workflow',
        name='chat-completion',
        protocol='ollama/v1',
        method='ollama/chat',
        params={
            'model': 'llama3.2:latest',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': 'What is the capital of France?'},
                {'role': 'assistant', 'content': 'The capital of France is Paris.'},
                {'role': 'user', 'content': 'What is its population?'}
            ],
            'options': {
                'temperature': 0.5
            }
        }
    )

    result = await handler.execute(chat_task)
    if result.status == 'completed':
        message = result.result['message']
        print(f"Assistant: {message['content']}")
    else:
        print(f"Error: {result.error}")

    # Example 4: Generate embeddings (if model supports it)
    print("\n4. Generate embeddings:")
    embed_task = Task(
        id='example-embed-1',
        workflow_id='example-workflow',
        name='generate-embeddings',
        protocol='ollama/v1',
        method='ollama/embeddings',
        params={
            'model': 'llama3.2:latest',  # Note: Not all models support embeddings
            'prompt': 'Machine learning is fascinating'
        }
    )

    result = await handler.execute(embed_task)
    if result.status == 'completed':
        embedding = result.result['embedding']
        print(f"Embedding dimensions: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")
    else:
        print(f"Error: {result.error}")
        print("Note: The model might not support embeddings")

    # Example 5: Streaming generation
    print("\n5. Streaming text generation:")
    stream_task = Task(
        id='example-stream-1',
        workflow_id='example-workflow',
        name='stream-text',
        protocol='ollama/v1',
        method='ollama/generate',
        params={
            'model': 'llama3.2:latest',
            'prompt': 'Tell me a very short story about a robot',
            'stream': True,
            'options': {
                'temperature': 0.8,
                'num_predict': 100
            }
        }
    )

    result = await handler.execute(stream_task)
    if result.status == 'completed':
        print(f"Story: {result.result['response']}")
        print(f"Total duration: {result.result.get('total_duration', 0) / 1e9:.2f}s")
    else:
        print(f"Error: {result.error}")

    print("\n" + "=" * 50)
    print("Examples completed!")


if __name__ == "__main__":
    # Run the examples
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExamples interrupted by user")
    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()