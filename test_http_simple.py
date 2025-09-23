#!/usr/bin/env python
"""
Simple test of HTTP handler functionality
"""

import asyncio
import json
from gleitzeit.handlers.http import HttpHandler
from gleitzeit.core.models import Task, TaskStatus

async def test_httpbin():
    """Test HTTP handler against httpbin.org"""

    handler = HttpHandler()

    # Test 1: Simple GET request
    print("Test 1: GET request")
    task = Task(
        id='test-1',
        workflow_id='test-workflow',
        name='get_test',
        type='http',
        protocol='http/v1',
        method='http/get',
        params={
            'url': 'https://httpbin.org/get',
            'params': {'test': 'value', 'foo': 'bar'}
        }
    )

    result = await handler.execute(task)
    print(f"  Status: {result.status}")
    print(f"  HTTP Status: {result.metadata.get('status_code')}")

    if result.status == TaskStatus.COMPLETED:
        data = result.result
        print(f"  Args received: {data.get('args')}")
        assert data['args'] == {'test': 'value', 'foo': 'bar'}, "GET params mismatch"
        print("  ✓ GET test passed")
    else:
        print(f"  ✗ GET test failed: {result.error}")

    # Test 2: POST with JSON
    print("\nTest 2: POST with JSON")
    task = Task(
        id='test-2',
        workflow_id='test-workflow',
        name='post_test',
        type='http',
        protocol='http/v1',
        method='http/post',
        params={
            'url': 'https://httpbin.org/post',
            'json': {
                'message': 'Hello from Gleitzeit',
                'test': True
            }
        }
    )

    result = await handler.execute(task)
    print(f"  Status: {result.status}")

    if result.status == TaskStatus.COMPLETED:
        data = result.result
        posted = json.loads(data.get('data', '{}'))
        print(f"  Posted data: {posted}")
        assert posted['message'] == 'Hello from Gleitzeit', "POST data mismatch"
        print("  ✓ POST test passed")
    else:
        print(f"  ✗ POST test failed: {result.error}")

    # Test 3: Custom headers
    print("\nTest 3: Custom headers")
    task = Task(
        id='test-3',
        workflow_id='test-workflow',
        name='headers_test',
        type='http',
        protocol='http/v1',
        method='http/get',
        params={
            'url': 'https://httpbin.org/headers',
            'headers': {
                'X-Custom-Header': 'Gleitzeit/0.0.7',
                'Accept': 'application/json'
            }
        }
    )

    result = await handler.execute(task)
    print(f"  Status: {result.status}")

    if result.status == TaskStatus.COMPLETED:
        data = result.result
        headers = data.get('headers', {})
        print(f"  Custom header received: {headers.get('X-Custom-Header')}")
        assert headers.get('X-Custom-Header') == 'Gleitzeit/0.0.7', "Header mismatch"
        print("  ✓ Headers test passed")
    else:
        print(f"  ✗ Headers test failed: {result.error}")

    # Test 4: Status code validation
    print("\nTest 4: Status code validation")
    task = Task(
        id='test-4',
        workflow_id='test-workflow',
        name='status_test',
        type='http',
        protocol='http/v1',
        method='http/get',
        params={
            'url': 'https://httpbin.org/status/404',
            'expected_status': [200]
        }
    )

    result = await handler.execute(task)
    print(f"  Status: {result.status}")

    if result.status == TaskStatus.FAILED:
        print(f"  Error: {result.error}")
        assert 'Unexpected status code: 404' in result.error, "Should fail on wrong status"
        print("  ✓ Status validation test passed (correctly failed)")
    else:
        print(f"  ✗ Status test should have failed")

    # Test 5: Rate limiting
    print("\nTest 5: Rate limiting (2 requests with rate limit)")
    import time

    start = time.time()
    tasks = []

    for i in range(2):
        task = Task(
            id=f'test-5-{i}',
            workflow_id='test-workflow',
            name=f'rate_test_{i}',
            type='http',
            protocol='http/v1',
            method='http/get',
            params={
                'url': 'https://httpbin.org/delay/0',
                'rate_limit': 2,  # 2 per second
                'rate_limit_key': 'httpbin'
            }
        )
        tasks.append(handler.execute(task))

    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start

    print(f"  Time for 2 requests: {elapsed:.2f}s")
    print(f"  Expected: ~0.5s with rate limit of 2/sec")

    all_success = all(r.status == TaskStatus.COMPLETED for r in results)
    if all_success and elapsed >= 0.4:
        print("  ✓ Rate limiting test passed")
    else:
        print(f"  ✗ Rate limiting test failed")

    # Cleanup
    await handler.cleanup()

    print("\n=== All tests completed ===")

if __name__ == "__main__":
    asyncio.run(test_httpbin())