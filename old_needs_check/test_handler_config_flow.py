#!/usr/bin/env python
"""
Test script to validate handler configuration flow from gleitzeit.yaml to workers
"""

import asyncio
import redis.asyncio as aioredis
import json
import yaml
from pathlib import Path


async def check_handler_configs():
    """Check if handler configs are being passed correctly"""

    print("=" * 60)
    print("Handler Configuration Flow Test")
    print("=" * 60)

    # 1. Check gleitzeit.yaml for handler configs
    print("\n1. Checking gleitzeit.yaml for handler configurations...")
    config_file = Path("gleitzeit.yaml")

    if config_file.exists():
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f) or {}

        # Check for handlers section
        if 'handlers' in config:
            print("✓ Found 'handlers' section in gleitzeit.yaml")
            for handler_name, handler_config in config['handlers'].items():
                if handler_name != 'global':
                    print(f"  - {handler_name}: {handler_config.get('config', {})}")
        else:
            print("✗ No 'handlers' section found in gleitzeit.yaml")
            print("  Add a handlers section to configure handler behavior")

        # Check for worker handler_configs
        if 'workers' in config:
            for worker in config['workers']:
                if 'handler_configs' in worker:
                    print(f"\n  Worker {worker['worker_type']} has handler_configs:")
                    for protocol, cfg in worker['handler_configs'].items():
                        print(f"    - {protocol}: {list(cfg.keys())}")
    else:
        print("✗ gleitzeit.yaml not found")

    # 2. Check Redis for worker config keys
    print("\n2. Checking Redis for worker configuration keys...")

    try:
        redis = await aioredis.from_url('redis://localhost:6379', decode_responses=False)

        # Look for worker config keys
        keys = await redis.keys(b'worker:config:*')

        if keys:
            print(f"✓ Found {len(keys)} worker config keys in Redis")

            for key in keys[:3]:  # Show first 3 as examples
                config_data = await redis.get(key)
                if config_data:
                    config_dict = json.loads(config_data)
                    worker_id = config_dict.get('worker_id')
                    handler_configs = config_dict.get('handler_configs', {})

                    print(f"\n  Worker: {worker_id}")
                    print(f"  Type: {config_dict.get('worker_type')}")
                    print(f"  Handler configs present: {len(handler_configs)} protocols")

                    if handler_configs:
                        for protocol in list(handler_configs.keys())[:3]:
                            print(f"    - {protocol}: {list(handler_configs[protocol].keys())[:5]}")
        else:
            print("✗ No worker config keys found in Redis")
            print("  Workers may not be running or configs not yet stored")

        await redis.aclose()

    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")

    # 3. Check running workers
    print("\n3. Checking for running workers...")

    try:
        import psutil
        worker_processes = []

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'gleitzeit.workers.runner' in ' '.join(cmdline):
                    worker_processes.append(proc)
            except:
                pass

        if worker_processes:
            print(f"✓ Found {len(worker_processes)} running worker processes")
            for proc in worker_processes[:3]:
                cmdline = proc.info.get('cmdline', [])
                # Check if using config-key
                if '--config-key' in cmdline:
                    idx = cmdline.index('--config-key')
                    if idx + 1 < len(cmdline):
                        config_key = cmdline[idx + 1]
                        print(f"  - PID {proc.info['pid']}: using config key {config_key}")
                else:
                    print(f"  - PID {proc.info['pid']}: using legacy CLI args (no handler configs)")
        else:
            print("✗ No worker processes found")
            print("  Start workers with: gleitzeit start")

    except ImportError:
        print("✗ psutil not installed, cannot check processes")


async def test_config_storage():
    """Test storing and retrieving a sample config"""

    print("\n" + "=" * 60)
    print("Testing Configuration Storage and Retrieval")
    print("=" * 60)

    redis = await aioredis.from_url('redis://localhost:6379', decode_responses=False)

    # Create a test configuration
    test_config = {
        'worker_type': 'test_worker',
        'worker_id': 'test-worker-1',
        'worker_class': 'gleitzeit.workers.task_execution_worker.TaskExecutionWorker',
        'handler_configs': {
            'python/v1': {
                'subprocess_pool_enabled': True,
                'subprocess_pool_min_size': 2,
                'subprocess_pool_max_size': 10,
                'default_timeout': 300
            },
            'ollama/v1': {
                'base_url': 'http://localhost:11434',
                'default_model': 'codellama',
                'timeout': 600
            }
        },
        'enabled_task_types': ['python', 'ollama']
    }

    # Store in Redis
    test_key = 'worker:config:test:validation'
    await redis.setex(
        test_key.encode(),
        60,  # 1 minute TTL
        json.dumps(test_config).encode()
    )

    print(f"✓ Stored test config at key: {test_key}")

    # Retrieve and verify
    retrieved_data = await redis.get(test_key.encode())
    if retrieved_data:
        retrieved_config = json.loads(retrieved_data)

        if retrieved_config.get('handler_configs'):
            print("✓ Handler configs successfully stored and retrieved:")
            for protocol, cfg in retrieved_config['handler_configs'].items():
                print(f"  - {protocol}: {list(cfg.keys())}")
        else:
            print("✗ Handler configs missing from retrieved data")
    else:
        print("✗ Failed to retrieve test config")

    # Clean up
    await redis.delete(test_key.encode())
    await redis.aclose()


async def main():
    """Run all tests"""
    await check_handler_configs()
    await test_config_storage()

    print("\n" + "=" * 60)
    print("Configuration Flow Test Complete")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Ensure handlers section is defined in gleitzeit.yaml")
    print("2. Start services with: gleitzeit start")
    print("3. Check worker logs for handler configuration messages")
    print("4. Verify handlers are using configured settings")


if __name__ == '__main__':
    asyncio.run(main())