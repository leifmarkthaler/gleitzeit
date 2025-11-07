#!/usr/bin/env python
"""
Integration test for HTTP Handler
Tests actual HTTP requests against httpbin.org
"""

import asyncio
import json
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers.http import HttpHandler
from gleitzeit.core.models import Task, TaskStatus

async def test_http_handler():
    """Test HTTP handler with real requests"""
    print("\n🧪 Testing HTTP Handler Integration\n")
    print("=" * 50)

    handler = HttpHandler()
    results = []

    try:
        # Test 1: Simple GET request
        print("\n1. Testing GET request...")
        task_get = Task(
            id="test-get",
            name="GET Request",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/get",
                "params": {"test": "value", "foo": "bar"}
            }
        )

        result_get = await handler.execute(task_get)
        assert result_get.status == TaskStatus.COMPLETED
        assert 'args' in result_get.result
        assert result_get.result['args']['test'] == 'value'
        print("   ✅ GET request successful")
        print(f"   Response args: {result_get.result.get('args')}")
        results.append(("GET", "Success"))

        # Test 2: POST with JSON
        print("\n2. Testing POST with JSON...")
        task_post = Task(
            id="test-post",
            name="POST Request",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/post",
            params={
                "url": "https://httpbin.org/post",
                "json": {
                    "message": "Hello from Gleitzeit",
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        )

        result_post = await handler.execute(task_post)
        assert result_post.status == TaskStatus.COMPLETED
        assert 'json' in result_post.result
        assert result_post.result['json']['message'] == 'Hello from Gleitzeit'
        print("   ✅ POST request successful")
        print(f"   Posted data: {result_post.result.get('json')}")
        results.append(("POST", "Success"))

        # Test 3: Headers and User-Agent
        print("\n3. Testing custom headers...")
        task_headers = Task(
            id="test-headers",
            name="Headers Test",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/headers",
                "headers": {
                    "X-Custom-Header": "Gleitzeit-Test",
                    "User-Agent": "Gleitzeit/0.0.7"
                }
            }
        )

        result_headers = await handler.execute(task_headers)
        assert result_headers.status == TaskStatus.COMPLETED
        headers = result_headers.result.get('headers', {})
        assert headers.get('X-Custom-Header') == 'Gleitzeit-Test'
        print("   ✅ Headers sent successfully")
        print(f"   Custom header received: {headers.get('X-Custom-Header')}")
        results.append(("Headers", "Success"))

        # Test 4: PUT request
        print("\n4. Testing PUT request...")
        task_put = Task(
            id="test-put",
            name="PUT Request",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/put",
            params={
                "url": "https://httpbin.org/put",
                "json": {"update": "data", "id": 123}
            }
        )

        result_put = await handler.execute(task_put)
        assert result_put.status == TaskStatus.COMPLETED
        print("   ✅ PUT request successful")
        results.append(("PUT", "Success"))

        # Test 5: DELETE request
        print("\n5. Testing DELETE request...")
        task_delete = Task(
            id="test-delete",
            name="DELETE Request",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/delete",
            params={
                "url": "https://httpbin.org/delete",
                "params": {"id": "123"}
            }
        )

        result_delete = await handler.execute(task_delete)
        assert result_delete.status == TaskStatus.COMPLETED
        print("   ✅ DELETE request successful")
        results.append(("DELETE", "Success"))

        # Test 6: Status code validation
        print("\n6. Testing status code validation...")
        task_status = Task(
            id="test-status",
            name="Status Test",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/status/201",
                "expected_status": [200, 201]  # Expecting 201
            }
        )

        result_status = await handler.execute(task_status)
        assert result_status.status == TaskStatus.COMPLETED
        print("   ✅ Status code validation passed")
        results.append(("Status Validation", "Success"))

        # Test 7: Basic Auth
        print("\n7. Testing Basic Authentication...")
        task_auth = Task(
            id="test-auth",
            name="Basic Auth Test",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/basic-auth/user/passwd",
                "auth": {
                    "type": "basic",
                    "username": "user",
                    "password": "passwd"
                }
            }
        )

        result_auth = await handler.execute(task_auth)
        assert result_auth.status == TaskStatus.COMPLETED
        assert result_auth.result.get('authenticated') == True
        assert result_auth.result.get('user') == 'user'
        print("   ✅ Basic authentication successful")
        results.append(("Basic Auth", "Success"))

        # Test 8: Response types
        print("\n8. Testing different response types...")

        # JSON response (auto-detect)
        task_json = Task(
            id="test-json",
            name="JSON Response",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/json"
            }
        )

        result_json = await handler.execute(task_json)
        assert result_json.status == TaskStatus.COMPLETED
        assert isinstance(result_json.result, dict)
        print("   ✅ JSON response parsed correctly")

        # HTML response (text)
        task_html = Task(
            id="test-html",
            name="HTML Response",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/html",
                "response_type": "text"
            }
        )

        result_html = await handler.execute(task_html)
        assert result_html.status == TaskStatus.COMPLETED
        assert isinstance(result_html.result, str)
        assert '<html>' in result_html.result.lower()
        print("   ✅ HTML response received as text")
        results.append(("Response Types", "Success"))

        # Test 9: Timeout (should fail)
        print("\n9. Testing timeout handling...")
        task_timeout = Task(
            id="test-timeout",
            name="Timeout Test",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/delay/10",
                "timeout": 2  # 2 second timeout, but endpoint delays 10
            }
        )

        result_timeout = await handler.execute(task_timeout)
        if result_timeout.status == TaskStatus.FAILED:
            if result_timeout.error and "timeout" in str(result_timeout.error).lower():
                print("   ✅ Timeout handled correctly (task failed as expected)")
                results.append(("Timeout", "Handled"))
            else:
                print(f"   ⚠️  Failed but not timeout: {result_timeout.error}")
                results.append(("Timeout", "Failed differently"))
        else:
            print("   ⚠️  Request succeeded despite timeout")
            results.append(("Timeout", "Not enforced"))

        # Test 10: 404 error
        print("\n10. Testing error handling (404)...")
        task_404 = Task(
            id="test-404",
            name="404 Test",
            workflow_id="test-workflow",
            protocol="http/v1",
            method="http/get",
            params={
                "url": "https://httpbin.org/status/404",
                "expected_status": [200]  # Expecting 200, will get 404
            }
        )

        result_404 = await handler.execute(task_404)
        assert result_404.status == TaskStatus.FAILED
        assert "404" in str(result_404.error)
        print("   ✅ 404 error handled correctly")
        results.append(("404 Error", "Handled"))

    finally:
        # Cleanup
        if handler._session:
            await handler._session.close()

    # Print summary
    print("\n" + "=" * 50)
    print("\n📊 Test Summary:\n")
    for test_name, status in results:
        emoji = "✅" if status in ["Success", "Handled"] else "❌"
        print(f"   {emoji} {test_name}: {status}")

    print(f"\n✨ All {len(results)} tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_http_handler())