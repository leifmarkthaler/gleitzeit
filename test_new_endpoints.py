#!/usr/bin/env python3
"""Test the newly implemented API endpoints"""
import asyncio
import aiohttp
import json

API_BASE = "http://localhost:8000"

async def test_new_endpoints():
    """Test various newly implemented API endpoints"""
    async with aiohttp.ClientSession() as session:
        
        print("Testing Newly Implemented API Endpoints")
        print("=" * 50)
        
        # 1. Test Provider Management
        print("\n1. Provider Management:")
        
        # List providers
        async with session.get(f"{API_BASE}/providers") as resp:
            if resp.status == 200:
                providers = await resp.json()
                print(f"   ✓ Found {len(providers)} providers")
                
                # Test provider details for first provider
                if providers:
                    first_provider_id = list(providers.keys())[0]
                    async with session.get(f"{API_BASE}/providers/{first_provider_id}") as detail_resp:
                        if detail_resp.status == 200:
                            details = await detail_resp.json()
                            print(f"   ✓ Provider '{first_provider_id}': {details.get('name')}")
                            print(f"     Protocol: {details.get('protocol')}")
                            print(f"     Status: {details.get('status')}")
                        else:
                            print(f"   ✗ Failed to get provider details: {detail_resp.status}")
                    
                    # Test health check
                    async with session.post(f"{API_BASE}/providers/{first_provider_id}/health") as health_resp:
                        if health_resp.status == 200:
                            health = await health_resp.json()
                            print(f"   ✓ Health check: {health.get('status')}")
                        else:
                            print(f"   ✗ Health check failed: {health_resp.status}")
            else:
                print(f"   ✗ Failed to list providers: {resp.status}")
        
        # 2. Test Resource Management
        print("\n2. Resource Management:")
        
        async with session.get(f"{API_BASE}/resources/limits") as resp:
            if resp.status == 200:
                limits = await resp.json()
                print(f"   ✓ Resource limits:")
                print(f"     Max concurrent tasks: {limits.get('max_concurrent_tasks')}")
                print(f"     Max memory MB: {limits.get('max_memory_mb')}")
                print(f"     Max queue size: {limits.get('max_queue_size')}")
            else:
                print(f"   ✗ Failed to get resource limits: {resp.status}")
        
        async with session.get(f"{API_BASE}/resources/usage") as resp:
            if resp.status == 200:
                usage = await resp.json()
                print(f"   ✓ Resource usage:")
                print(f"     Active tasks: {usage.get('active_tasks')}")
                print(f"     Queued tasks: {usage.get('queued_tasks')}")
                print(f"     Memory usage MB: {usage.get('memory_usage_mb')}")
            else:
                print(f"   ✗ Failed to get resource usage: {resp.status}")
        
        # 3. Test Bulk Operations
        print("\n3. Bulk Operations:")
        
        # First, submit a few test tasks
        task_ids = []
        for i in range(3):
            task_data = {
                "id": f"bulk-test-{i}",
                "name": f"Bulk Test Task {i}",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": f"print('Task {i}')"
                }
            }
            async with session.post(f"{API_BASE}/tasks", json=task_data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    task_ids.append(result.get('task_id'))
        
        if task_ids:
            print(f"   ✓ Created {len(task_ids)} test tasks")
            
            # Wait for execution
            await asyncio.sleep(2)
            
            # Test bulk status
            params = "&".join([f"task_ids={tid}" for tid in task_ids])
            async with session.get(f"{API_BASE}/tasks/bulk/status?{params}") as resp:
                if resp.status == 200:
                    statuses = await resp.json()
                    print(f"   ✓ Bulk status check: {len(statuses)} tasks")
                    for tid, info in statuses.items():
                        print(f"     {tid[:8]}...: {info.get('status')}")
                else:
                    print(f"   ✗ Bulk status failed: {resp.status}")
        
        # 4. Test Workflow Export/Clone
        print("\n4. Workflow Export/Clone:")
        
        # Create a test workflow
        workflow_data = {
            "id": "test-export-workflow",
            "name": "Export Test Workflow",
            "description": "Test workflow for export",
            "tasks": [
                {
                    "id": "export-task-1",
                    "name": "Export Task 1",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "print('Task 1')"}
                },
                {
                    "id": "export-task-2",
                    "name": "Export Task 2",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"code": "print('Task 2')"},
                    "dependencies": ["export-task-1"]
                }
            ]
        }
        
        async with session.post(f"{API_BASE}/workflows", json=workflow_data) as resp:
            if resp.status == 200:
                wf_result = await resp.json()
                workflow_id = wf_result.get('workflow_id')
                print(f"   ✓ Created test workflow: {workflow_id}")
                
                # Test export
                async with session.get(f"{API_BASE}/workflows/{workflow_id}/export?format=json") as exp_resp:
                    if exp_resp.status == 200:
                        exported = await exp_resp.json()
                        print(f"   ✓ Exported workflow with {len(exported.get('tasks', []))} tasks")
                    else:
                        print(f"   ✗ Export failed: {exp_resp.status}")
                
                # Test clone
                async with session.post(f"{API_BASE}/workflows/{workflow_id}/clone") as clone_resp:
                    if clone_resp.status == 200:
                        cloned = await clone_resp.json()
                        print(f"   ✓ Cloned workflow: {cloned.get('new_workflow_id')}")
                        print(f"     Tasks cloned: {cloned.get('tasks_cloned')}")
                    else:
                        print(f"   ✗ Clone failed: {clone_resp.status}")
                
                # Test dependency graph
                async with session.get(f"{API_BASE}/workflows/{workflow_id}/dependencies") as dep_resp:
                    if dep_resp.status == 200:
                        deps = await dep_resp.json()
                        print(f"   ✓ Dependency graph: {len(deps.get('nodes', []))} nodes, {len(deps.get('edges', []))} edges")
                    else:
                        print(f"   ✗ Dependencies failed: {dep_resp.status}")
                
                # Test critical path
                async with session.get(f"{API_BASE}/workflows/{workflow_id}/critical-path") as cp_resp:
                    if cp_resp.status == 200:
                        cp = await cp_resp.json()
                        print(f"   ✓ Critical path: {len(cp.get('critical_path', []))} critical tasks")
                    else:
                        print(f"   ✗ Critical path failed: {cp_resp.status}")
            else:
                print(f"   ✗ Failed to create workflow: {resp.status}")
        
        print("\n" + "=" * 50)
        print("New Endpoint Testing Complete!")

if __name__ == "__main__":
    asyncio.run(test_new_endpoints())