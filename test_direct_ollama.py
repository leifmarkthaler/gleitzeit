import asyncio
import sys
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit 0.0.7/src')

from gleitzeit.handlers.ollama import OllamaHandler
from gleitzeit.core.models import Task

async def test():
    handler = OllamaHandler({'base_url': 'http://localhost:11434'})
    task = Task(
        id='test',
        workflow_id='test',
        name='test',
        protocol='ollama/v1', 
        method='ollama/generate',
        params={
            'model': 'llama3.2:latest',
            'prompt': 'Write a haiku about computers',
            'options': {'temperature': 0.7, 'max_tokens': 100}
        }
    )
    result = await handler.execute(task)
    print(f"Success: {result.status}")
    print(f"Result: {result.result.get('response') if result.result else 'No result'}")

asyncio.run(test())
