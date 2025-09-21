#!/usr/bin/env python3
"""
Test getting a workflow directly.
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from gleitzeit.client import GleitzeitClient, ClientMode

async def test_get_workflow():
    """Test getting workflow directly."""
    
    workflow_id = "fe2fd458-bd09-4dd1-b956-860cc72af996"
    
    print(f"Testing workflow retrieval for {workflow_id}")
    print("=" * 60)
    
    # Test with API client
    client = GleitzeitClient(mode=ClientMode.API, base_url="http://localhost:8000")
    await client.initialize()
    
    print("\n1. Getting workflow via API client...")
    try:
        workflow = await client.get_workflow(workflow_id)
        if workflow:
            print(f"   ✓ Found: {workflow.name} (status: {workflow.status})")
            print(f"   Tasks: {len(workflow.tasks)}")
        else:
            print(f"   ✗ Not found")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test directly with persistence
    print("\n2. Getting workflow directly from persistence...")
    try:
        from gleitzeit.persistence.factory import PersistenceFactory
        persistence = await PersistenceFactory.create()
        
        data = await persistence.get_workflow(workflow_id)
        if data:
            print(f"   ✓ Found in Redis")
            print(f"   Status: {data.get('status')}")
        else:
            print(f"   ✗ Not found in Redis")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_get_workflow())