#!/usr/bin/env python3
"""
Trace the actual execution path to verify handler vs provider usage.

This test adds logging/tracing to verify which code path is actually taken.
"""

import asyncio
import sys
import inspect
from unittest.mock import patch, MagicMock

from gleitzeit.workers.task_execution_worker_v4 import TaskExecutionWorkerV4
from gleitzeit.workers.task_execution_worker_v2 import TaskExecutionWorkerV2
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.models import Task
from gleitzeit.handlers import handler_loader

# Load handlers
_ = handler_loader.get_all_capabilities()


class ExecutionTracer:
    """Trace execution calls to see what's actually being used"""
    def __init__(self):
        self.calls = []
    
    def trace(self, msg, obj=None):
        frame = inspect.currentframe().f_back
        module = frame.f_globals.get('__name__', 'unknown')
        func = frame.f_code.co_name
        line = frame.f_lineno
        
        self.calls.append({
            'msg': msg,
            'module': module,
            'func': func,
            'line': line,
            'obj': obj.__class__.__name__ if obj else None
        })


tracer = ExecutionTracer()


async def test_v4_uses_handlers():
    """Verify that V4 uses handlers, not providers"""
    print("\n=== Testing V4 Execution Path ===")
    
    # Create V4 worker
    config = WorkerConfig(
        worker_type="task_execution",
        worker_id="test-v4",
        consumer_group="test"
    )
    config.__dict__['enabled_task_types'] = ['python']
    
    worker = TaskExecutionWorkerV4(config)
    
    # Check what's initialized
    print("\n1. Checking V4 initialization...")
    print(f"   Handlers loaded: {list(worker.handlers.keys())}")
    print(f"   Has provider_adapter: {hasattr(worker, 'provider_adapter')}")
    print(f"   Has provider_registry: {hasattr(worker, 'provider_registry')}")
    
    assert 'python/v1' in worker.handlers, "PythonHandler not loaded"
    assert not hasattr(worker, 'provider_adapter'), "V4 should NOT have provider_adapter"
    assert not hasattr(worker, 'provider_registry'), "V4 should NOT have provider_registry"
    
    print("   ✓ V4 has handlers, NO providers")
    
    # Trace execution path
    print("\n2. Tracing execution path...")
    
    # Mock Redis with async mocks
    from unittest.mock import AsyncMock
    worker.redis = AsyncMock()
    worker.redis.hset = AsyncMock()
    worker.redis.xadd = AsyncMock()
    
    # Create a task
    task_data = {
        'id': 'test-task',
        'name': 'Test',
        'workflow_id': 'wf-123',
        'protocol': 'python/v1',
        'method': 'python/eval',
        'params': {'expression': '2 + 2'}
    }
    
    message = {
        'workflow_id': 'wf-123',
        'task_id': 'test-task',
        'task': task_data
    }
    
    # Patch the handler's execute to trace it
    original_execute = worker.handlers['python/v1'].execute
    
    async def traced_execute(task):
        tracer.trace("Handler.execute called", worker.handlers['python/v1'])
        return await original_execute(task)
    
    worker.handlers['python/v1'].execute = traced_execute
    
    # Process the message
    await worker.process_message('task:ready', 'msg-1', message)
    
    # Check trace
    print("\n3. Execution trace:")
    for call in tracer.calls:
        print(f"   - {call['msg']} (in {call['module']}.{call['func']}:{call['line']})")
        if call['obj']:
            print(f"     Object: {call['obj']}")
    
    # Verify handler was called
    handler_called = any('Handler.execute' in c['msg'] for c in tracer.calls)
    assert handler_called, "Handler.execute was not called!"
    
    print("\n   ✓ Execution went through handler, not provider")
    
    return True


async def test_v2_uses_providers():
    """For comparison, verify that V2 uses providers"""
    print("\n=== Testing V2 Execution Path (for comparison) ===")
    
    # Create V2 worker
    config = WorkerConfig(
        worker_type="task_execution",
        worker_id="test-v2",
        consumer_group="test"
    )
    
    worker = TaskExecutionWorkerV2(config)
    
    # Check what's initialized
    print("\n1. Checking V2 initialization...")
    print(f"   Has provider_registry: {hasattr(worker, 'provider_registry')}")
    print(f"   Has handlers: {hasattr(worker, 'handlers')}")
    
    assert hasattr(worker, 'provider_registry'), "V2 should have provider_registry"
    assert not hasattr(worker, 'handlers'), "V2 should NOT have handlers"
    
    print("   ✓ V2 has providers, NO handlers")
    
    return True


async def test_handler_imports():
    """Verify the import chain to ensure no provider dependencies"""
    print("\n=== Testing Import Dependencies ===")
    
    # Check PythonHandler imports
    import gleitzeit.handlers.python as python_module
    
    print("\n1. Checking PythonHandler imports...")
    
    # Get all imports in the module
    imports = []
    for name, obj in python_module.__dict__.items():
        if hasattr(obj, '__module__'):
            module = obj.__module__
            if module and 'provider' in module.lower():
                imports.append((name, module))
    
    if imports:
        print("   ⚠️  Found provider imports:")
        for name, module in imports:
            print(f"     - {name} from {module}")
    else:
        print("   ✓ No provider imports found")
    
    assert not imports, f"Handler should not import from providers: {imports}"
    
    # Check handler base imports
    import gleitzeit.handlers.base as base_module
    
    print("\n2. Checking BaseHandler imports...")
    base_imports = []
    for name, obj in base_module.__dict__.items():
        if hasattr(obj, '__module__'):
            module = obj.__module__
            if module and 'provider' in module.lower():
                base_imports.append((name, module))
    
    if base_imports:
        print("   ⚠️  Found provider imports:")
        for name, module in base_imports:
            print(f"     - {name} from {module}")
    else:
        print("   ✓ No provider imports found")
    
    assert not base_imports, f"BaseHandler should not import from providers: {base_imports}"
    
    return True


async def test_module_structure():
    """Check the actual module structure to verify separation"""
    print("\n=== Testing Module Structure ===")
    
    print("\n1. Handler modules:")
    import gleitzeit.handlers
    handler_path = gleitzeit.handlers.__file__
    print(f"   Location: {handler_path}")
    
    print("\n2. Provider modules:")
    try:
        import gleitzeit.providers
        provider_path = gleitzeit.providers.__file__
        print(f"   Location: {provider_path}")
    except ImportError:
        print("   No provider module found (good!)")
    
    # List handler files
    import os
    handler_dir = os.path.dirname(handler_path)
    handler_files = [f for f in os.listdir(handler_dir) if f.endswith('.py') and not f.startswith('_')]
    
    print("\n3. Handler implementations:")
    for f in handler_files:
        print(f"   - {f}")
    
    # Verify key handlers exist
    assert 'python.py' in handler_files, "python.py handler missing"
    assert 'timer.py' in handler_files, "timer.py handler missing"
    assert 'signal.py' in handler_files, "signal.py handler missing"
    assert 'base.py' in handler_files, "base.py missing"
    assert 'registry.py' in handler_files, "registry.py missing"
    
    print("\n   ✓ Handler module structure is correct")
    print("   ✓ Handlers are completely separate from providers")
    
    return True


async def main():
    """Run execution path verification"""
    print("\n" + "="*60)
    print("   EXECUTION PATH VERIFICATION")
    print("   Verifying: Handlers vs Providers")
    print("="*60)
    
    try:
        await test_v4_uses_handlers()
        await test_v2_uses_providers()
        await test_handler_imports()
        await test_module_structure()
        
        print("\n" + "="*60)
        print("     ✅ VERIFICATION COMPLETE")
        print("="*60 + "\n")
        
        print("\nConfirmed:")
        print("✓ TaskExecutionWorkerV4 uses HANDLERS")
        print("✓ TaskExecutionWorkerV2 uses PROVIDERS")
        print("✓ Handlers have NO provider dependencies")
        print("✓ Complete separation between architectures")
        print("\nThe new handler architecture is completely independent!")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
