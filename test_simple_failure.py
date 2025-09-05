#!/usr/bin/env python3
"""
Simple test to reproduce Task not found error
"""
import asyncio
import sys
import io

# Capture stderr
stderr_capture = io.StringIO()

class StderrTee:
    def __init__(self):
        self.terminal = sys.__stderr__
        self.capture = stderr_capture
        
    def write(self, message):
        self.terminal.write(message)
        self.capture.write(message)
        if "not found" in message.lower():
            import traceback
            self.terminal.write("\n=== STACK TRACE FOR 'not found' ===\n")
            traceback.print_stack(file=self.terminal)
            self.terminal.write("=====================================\n")
    
    def flush(self):
        self.terminal.flush()

sys.stderr = StderrTee()

async def main():
    from src.gleitzeit.providers.ollama_provider import OllamaProvider
    from src.gleitzeit.core.models import Task, RetryConfig
    from src.gleitzeit.core.errors import ProviderError
    
    # Create a task that will fail
    task = Task(
        id="task-test001",
        workflow_id="test",
        name="test",
        protocol="llm/v1",
        method="generate",
        params={"model": "llama3.2", "prompt": "test"},
        retry_config=RetryConfig(max_attempts=1)
    )
    
    # Try to execute via Ollama provider
    provider = OllamaProvider()
    await provider.initialize()
    
    try:
        # This should fail with RESOURCE_EXHAUSTED
        from src.gleitzeit.core.jsonrpc import JSONRPCRequest
        request = JSONRPCRequest(
            method="generate",
            params=task.params,
            id=task.id
        )
        result = await provider.handle_request(request)
        print(f"Result: {result}")
    except ProviderError as e:
        print(f"Task {task.id} failed: {e}")
        # Now check if "not found" appears
        print(f"Task {task.id} not found")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
    
    # Show what was captured on stderr
    stderr_content = stderr_capture.getvalue()
    if stderr_content:
        print("\n=== STDERR CONTENT ===")
        print(stderr_content)