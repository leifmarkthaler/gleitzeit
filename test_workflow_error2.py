import asyncio
import traceback
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager as StreamSystemManager
from gleitzeit.persistence.factory import PersistenceFactory

async def test_direct():
    """Test workflow submission directly through system manager"""
    try:
        # Get persistence
        persistence = await PersistenceFactory.create()
        
        # Get system manager - but don't start it since server is running
        system_manager = await StreamSystemManager.get_or_create(
            persistence=persistence,
            create_if_missing=True,
            start_system=False  # Don't start, just connect
        )
        
        if not system_manager:
            print("No system manager found")
            return
            
        print(f"Got system manager: {system_manager}")
        print(f"Has workflow manager: {hasattr(system_manager, 'workflow_manager')}")
        print(f"Workflow manager: {system_manager.workflow_manager}")
        
        # Simple workflow
        workflow = {
            'name': 'test_simple',
            'tasks': [
                {
                    'id': 'task1', 
                    'protocol': 'python/v1',
                    'method': 'python/execute',
                    'params': {'code': 'print("hello")'}
                }
            ]
        }
        
        # Try to submit
        print("Submitting workflow...")
        session_id = "test-session"
        workflow_id = await system_manager.submit_workflow_authenticated(workflow, session_id)
        print(f"Success! Workflow ID: {workflow_id}")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

asyncio.run(test_direct())
