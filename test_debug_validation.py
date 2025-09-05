#!/usr/bin/env python3
"""
Debug validation issue
"""

import asyncio

async def main():
    from src.gleitzeit.system.system_manager import SystemManager
    from src.gleitzeit.system.models import SystemConfig
    from src.gleitzeit.persistence.factory import PersistenceFactory
    
    # Create system
    persistence = await PersistenceFactory.create()
    config = SystemConfig(
        environment="development",
        persistence_backend="redis",
        enable_auth=False,
        default_providers=["python", "ollama"]
    )
    
    system_manager = SystemManager(config=config, persistence=persistence)
    await system_manager.initialize()
    await system_manager.start_system()
    
    # Check what's in the execution engine
    print("Checking execution engine...")
    exec_engine = system_manager.execution_engine
    print(f"  Has pooling_adapter: {hasattr(exec_engine, 'pooling_adapter')}")
    
    if hasattr(exec_engine, 'pooling_adapter'):
        pooling_adapter = exec_engine.pooling_adapter
        print(f"  Pooling adapter: {pooling_adapter}")
        
        # Check validation
        is_available, error = await pooling_adapter.validate_provider_availability("llm/v1")
        print(f"  llm/v1 available: {is_available}")
        print(f"  Error: {error}")
    
    # Check workflow manager
    wf_mgr = system_manager.workflow_manager
    print(f"\nWorkflow manager: {wf_mgr}")
    print(f"  Has execution_engine: {hasattr(wf_mgr, 'execution_engine')}")
    
    if hasattr(wf_mgr, 'execution_engine'):
        print(f"  execution_engine == system's: {wf_mgr.execution_engine == exec_engine}")
        print(f"  exec_engine has pooling_adapter: {hasattr(wf_mgr.execution_engine, 'pooling_adapter')}")
    
    await system_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())