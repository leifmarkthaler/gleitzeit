#!/usr/bin/env python3
"""
Test the newly implemented endpoints for API-Client alignment
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def test_all_endpoints():
    """Test all newly implemented endpoints"""

    async with GleitzeitClient() as client:
        print("\n" + "="*60)
        print("TESTING NEW ENDPOINTS")
        print("="*60)

        # Test 1: List workflows
        try:
            print("\n1. Testing list_workflows()...")
            workflows = await client.list_workflows(limit=5)
            print(f"   ✅ Success: Found {len(workflows)} workflows")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 2: Get system health (detailed)
        try:
            print("\n2. Testing get_system_health()...")
            health = await client.get_system_health()
            print(f"   ✅ Success: Status={health.status}, Workers={health.worker_count}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 3: Get current user
        try:
            print("\n3. Testing get_current_user()...")
            user = await client.get_current_user()
            print(f"   ✅ Success: User={user}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 4: Get rate limit status
        try:
            print("\n4. Testing get_rate_limit_status()...")
            rate_limit = await client.get_rate_limit_status()
            print(f"   ✅ Success: Limit={rate_limit.get('limit')}, Remaining={rate_limit.get('remaining')}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 5: Get workflow metrics
        try:
            print("\n5. Testing get_workflow_metrics()...")
            metrics = await client.get_workflow_metrics()
            print(f"   ✅ Success: Total workflows={metrics.get('total_workflows', 0)}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 6: Get task metrics
        try:
            print("\n6. Testing get_task_metrics()...")
            metrics = await client.get_task_metrics()
            print(f"   ✅ Success: Total tasks={metrics.get('total_tasks', 0)}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 7: Get Redis info
        try:
            print("\n7. Testing get_redis_info()...")
            redis_info = await client.get_redis_info()
            print(f"   ✅ Success: Redis version={redis_info.get('version')}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 8: Get queue depths
        try:
            print("\n8. Testing get_queue_depths()...")
            queues = await client.get_queue_depths()
            print(f"   ✅ Success: Found {len(queues)} queues")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 9: Get resource usage
        try:
            print("\n9. Testing get_resource_usage()...")
            resources = await client.get_resource_usage()
            print(f"   ✅ Success: CPU={resources.get('cpu', {}).get('percent')}%")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 10: Get configuration
        try:
            print("\n10. Testing get_configuration()...")
            config = await client.get_configuration()
            print(f"   ✅ Success: Redis mode={config.get('redis', {}).get('mode')}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 11: Get active sessions
        try:
            print("\n11. Testing get_active_sessions()...")
            sessions = await client.get_active_sessions()
            print(f"   ✅ Success: Found {len(sessions)} sessions")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 12: API version check
        try:
            print("\n12. Testing check_api_version()...")
            version = await client.check_api_version()
            print(f"   ✅ Success: API version={version}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

        # Test 13: Test workflow dependency endpoints (need a workflow first)
        try:
            print("\n13. Testing task dependency endpoints...")
            # First submit a simple workflow
            from gleitzeit.easy import t, w
            test_workflow = w(
                t('task1').with_code('result = 1'),
                t('task2').needs('task1').with_code('result = 2')
            ).name('Dependency Test')

            submission = await client.submit_workflow(test_workflow.to_dict()['workflow'])
            workflow_id = submission.workflow_id

            # Wait a moment for workflow to be processed
            await asyncio.sleep(1)

            # Test get dependencies
            deps = await client.get_task_dependencies('task2', workflow_id)
            print(f"   ✅ Task2 dependencies: {deps}")

            # Test get dependents
            deps = await client.get_task_dependents('task1', workflow_id)
            print(f"   ✅ Task1 dependents: {deps}")

        except Exception as e:
            print(f"   ❌ Failed: {e}")

        print("\n" + "="*60)
        print("TESTING COMPLETE")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(test_all_endpoints())