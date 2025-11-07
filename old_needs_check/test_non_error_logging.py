"""
Test script to verify non-error logging functionality.

This script:
1. Submits a simple workflow
2. Waits for completion
3. Queries INFO/DEBUG/WARNING logs via the REST API
4. Prints results
"""

import asyncio
import aiohttp
import json
from datetime import datetime

API_BASE = "http://localhost:8000"


async def test_non_error_logging():
    """Test that non-error logs are being recorded and queryable"""

    print("=" * 80)
    print("Testing Non-Error Logging Implementation")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        # Step 1: Submit a simple workflow
        print("\n1. Submitting test workflow...")
        workflow = {
            "name": "non_error_logging_test",
            "description": "Test workflow for non-error logging",
            "tasks": [
                {
                    "name": "task1",
                    "type": "python",
                    "params": {
                        "code": "print('Hello from task 1'); result = {'status': 'success', 'value': 42}"
                    }
                },
                {
                    "name": "task2",
                    "type": "python",
                    "params": {
                        "code": "print('Hello from task 2'); result = {'status': 'success', 'value': 100}"
                    },
                    "dependencies": ["task1"]
                }
            ]
        }

        async with session.post(
            f"{API_BASE}/workflows",
            json={"workflow": workflow}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                workflow_id = data['workflow_id']
                print(f"   ✅ Workflow submitted: {workflow_id}")
            else:
                print(f"   ❌ Failed to submit workflow: {resp.status}")
                return

        # Step 2: Wait for workflow completion
        print(f"\n2. Waiting for workflow {workflow_id} to complete...")
        for i in range(30):
            await asyncio.sleep(1)
            async with session.get(
                f"{API_BASE}/workflows/{workflow_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get('status', 'unknown')
                    if status in ['completed', 'failed', 'completed_with_skips']:
                        print(f"   ✅ Workflow completed with status: {status}")
                        break
                    elif i % 5 == 0:
                        print(f"   ⏳ Status: {status} (waiting...)")
        else:
            print("   ⚠️  Workflow did not complete in 30 seconds")

        # Step 3: Query logs for this workflow
        print(f"\n3. Querying logs for workflow {workflow_id}...")

        # Query INFO logs
        print("\n   📝 INFO Logs:")
        async with session.get(
            f"{API_BASE}/logs/workflow/{workflow_id}",
            params={"level": "INFO"}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get('logs', [])
                print(f"      Found {len(logs)} INFO logs")
                for log in logs[:5]:  # Show first 5
                    ts = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%H:%M:%S.%f')[:-3]
                    comp = log.get('component', 'unknown')
                    op = log.get('operation', 'unknown')
                    msg = log.get('message', '')[:80]
                    print(f"      [{ts}] {comp}.{op}: {msg}")
            else:
                print(f"      ❌ Failed to query INFO logs: {resp.status}")

        # Query DEBUG logs
        print("\n   🔍 DEBUG Logs:")
        async with session.get(
            f"{API_BASE}/logs/workflow/{workflow_id}",
            params={"level": "DEBUG"}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get('logs', [])
                print(f"      Found {len(logs)} DEBUG logs (10% sampling)")
                for log in logs[:5]:  # Show first 5
                    ts = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%H:%M:%S.%f')[:-3]
                    comp = log.get('component', 'unknown')
                    op = log.get('operation', 'unknown')
                    msg = log.get('message', '')[:80]
                    print(f"      [{ts}] {comp}.{op}: {msg}")
            else:
                print(f"      ❌ Failed to query DEBUG logs: {resp.status}")

        # Query WARNING logs
        print("\n   ⚠️  WARNING Logs:")
        async with session.get(
            f"{API_BASE}/logs/workflow/{workflow_id}",
            params={"level": "WARNING"}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get('logs', [])
                print(f"      Found {len(logs)} WARNING logs")
                for log in logs[:5]:  # Show first 5
                    ts = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%H:%M:%S.%f')[:-3]
                    comp = log.get('component', 'unknown')
                    warn_type = log.get('warning_type', 'unknown')
                    msg = log.get('message', '')[:80]
                    print(f"      [{ts}] {comp}.{warn_type}: {msg}")
            else:
                print(f"      ❌ Failed to query WARNING logs: {resp.status}")

        # Step 4: Query log statistics
        print(f"\n4. Querying log statistics for workflow {workflow_id}...")
        async with session.get(
            f"{API_BASE}/logs/stats",
            params={"workflow_id": workflow_id}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                stats = data.get('stats', {})
                total = data.get('total', 0)
                print(f"   📊 Log Statistics:")
                print(f"      Total logs: {total}")
                print(f"      - DEBUG:   {stats.get('debug', 0)}")
                print(f"      - INFO:    {stats.get('info', 0)}")
                print(f"      - WARNING: {stats.get('warning', 0)}")
                print(f"      - ERROR:   {stats.get('error', 0)}")
            else:
                print(f"   ❌ Failed to query log stats: {resp.status}")

        # Step 5: Query component-specific logs
        print(f"\n5. Querying TaskExecutionWorker component logs...")
        async with session.get(
            f"{API_BASE}/logs/component/task_execution",
            params={"level": "INFO", "limit": 5}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get('logs', [])
                total = data.get('total', 0)
                print(f"   Found {total} TaskExecutionWorker INFO logs (showing first 5):")
                for log in logs:
                    ts = datetime.fromtimestamp(log['timestamp'] / 1000).strftime('%H:%M:%S.%f')[:-3]
                    op = log.get('operation', 'unknown')
                    msg = log.get('message', '')[:80]
                    print(f"      [{ts}] {op}: {msg}")
            else:
                print(f"   ❌ Failed to query component logs: {resp.status}")

    print("\n" + "=" * 80)
    print("Non-Error Logging Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_non_error_logging())
