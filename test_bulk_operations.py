#!/usr/bin/env python3
"""Test bulk operations functionality."""

import asyncio
import json
import yaml
import tempfile
import aiohttp
from pathlib import Path

API_URL = "http://localhost:8000"

# Sample workflows for testing
WORKFLOW_1 = {
    "name": "test-bulk-1",
    "tasks": [
        {
            "name": "task1",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "file": "test_tasks/bulk_task1.py"
            }
        }
    ]
}

WORKFLOW_2 = {
    "name": "test-bulk-2",
    "tasks": [
        {
            "name": "task2",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "file": "test_tasks/bulk_task2.py"
            }
        }
    ]
}

WORKFLOW_3 = {
    "name": "test-bulk-3",
    "tasks": [
        {
            "name": "task3",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "file": "test_tasks/bulk_task3.py"
            }
        }
    ]
}

async def test_batch_endpoint():
    """Test the /workflows/batch endpoint."""
    print("\n=== Testing /workflows/batch endpoint ===")
    
    async with aiohttp.ClientSession() as session:
        # Submit batch of workflows
        batch_data = [
            {"workflow": WORKFLOW_1},
            {"workflow": WORKFLOW_2},
            {"workflow": WORKFLOW_3}
        ]
        
        async with session.post(
            f"{API_URL}/workflows/batch",
            json=batch_data
        ) as resp:
            if resp.status == 200:
                results = await resp.json()
                print(f"Submitted {len(results)} workflows:")
                for i, result in enumerate(results):
                    if result.get("success"):
                        print(f"  Workflow {i+1}: ✓ {result['workflow_id']}")
                    else:
                        print(f"  Workflow {i+1}: ✗ {result.get('error', 'Unknown error')}")
                return results
            else:
                print(f"Failed: {resp.status} - {await resp.text()}")
                return None

async def test_upload_json_single():
    """Test /workflows/upload with single JSON workflow."""
    print("\n=== Testing /workflows/upload with single JSON ===")
    
    async with aiohttp.ClientSession() as session:
        # Create temp JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(WORKFLOW_1, f)
            temp_path = f.name
        
        try:
            with open(temp_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename='workflow.json', content_type='application/json')
                
                async with session.post(f"{API_URL}/workflows/upload", data=data) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        print(f"Upload results: {json.dumps(results, indent=2)}")
                        return results
                    else:
                        print(f"Failed: {resp.status} - {await resp.text()}")
                        return None
        finally:
            Path(temp_path).unlink()

async def test_upload_json_array():
    """Test /workflows/upload with JSON array of workflows."""
    print("\n=== Testing /workflows/upload with JSON array ===")
    
    async with aiohttp.ClientSession() as session:
        # Create temp JSON file with array
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([WORKFLOW_1, WORKFLOW_2, WORKFLOW_3], f)
            temp_path = f.name
        
        try:
            with open(temp_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename='workflows.json', content_type='application/json')
                
                async with session.post(f"{API_URL}/workflows/upload", data=data) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        print(f"Uploaded {len(results)} workflows:")
                        for i, result in enumerate(results):
                            if result.get("success"):
                                print(f"  Workflow {i+1}: ✓ {result['workflow_id']}")
                            else:
                                print(f"  Workflow {i+1}: ✗ {result.get('error', 'Unknown error')}")
                        return results
                    else:
                        print(f"Failed: {resp.status} - {await resp.text()}")
                        return None
        finally:
            Path(temp_path).unlink()

async def test_upload_yaml_multi():
    """Test /workflows/upload with multi-document YAML."""
    print("\n=== Testing /workflows/upload with multi-doc YAML ===")
    
    async with aiohttp.ClientSession() as session:
        # Create temp YAML file with multiple documents
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump_all([WORKFLOW_1, WORKFLOW_2, WORKFLOW_3], f)
            temp_path = f.name
        
        try:
            with open(temp_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename='workflows.yaml', content_type='text/yaml')
                
                async with session.post(f"{API_URL}/workflows/upload", data=data) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        print(f"Uploaded {len(results)} workflows:")
                        for i, result in enumerate(results):
                            if result.get("success"):
                                print(f"  Workflow {i+1}: ✓ {result['workflow_id']}")
                            else:
                                print(f"  Workflow {i+1}: ✗ {result.get('error', 'Unknown error')}")
                        return results
                    else:
                        print(f"Failed: {resp.status} - {await resp.text()}")
                        return None
        finally:
            Path(temp_path).unlink()

async def test_upload_yaml_array():
    """Test /workflows/upload with YAML containing array."""
    print("\n=== Testing /workflows/upload with YAML array ===")
    
    async with aiohttp.ClientSession() as session:
        # Create temp YAML file with array
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump([WORKFLOW_1, WORKFLOW_2, WORKFLOW_3], f)
            temp_path = f.name
        
        try:
            with open(temp_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename='workflows.yaml', content_type='text/yaml')
                
                async with session.post(f"{API_URL}/workflows/upload", data=data) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        print(f"Uploaded {len(results)} workflows:")
                        for i, result in enumerate(results):
                            if result.get("success"):
                                print(f"  Workflow {i+1}: ✓ {result['workflow_id']}")
                            else:
                                print(f"  Workflow {i+1}: ✗ {result.get('error', 'Unknown error')}")
                        return results
                    else:
                        print(f"Failed: {resp.status} - {await resp.text()}")
                        return None
        finally:
            Path(temp_path).unlink()

async def main():
    """Run all tests."""
    print("Testing Bulk Operations")
    print("=" * 50)
    
    # Test batch endpoint (with parallel processing)
    await test_batch_endpoint()
    
    # Test upload endpoint with various formats
    await test_upload_json_single()
    await test_upload_json_array()
    await test_upload_yaml_multi()
    await test_upload_yaml_array()
    
    print("\n" + "=" * 50)
    print("All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())