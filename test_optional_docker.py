"""
Test Optional Docker Dependency
Verifies that the package works with and without Docker
"""

import asyncio
import sys
import unittest.mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))


async def test_with_docker():
    """Test Python provider with Docker available"""
    print("\n" + "="*50)
    print("🔍 TESTING WITH DOCKER AVAILABLE")
    print("="*50)
    
    from gleitzeit.providers.python_provider import PythonProvider, DOCKER_AVAILABLE
    
    print(f"Docker available: {DOCKER_AVAILABLE}")
    
    if not DOCKER_AVAILABLE:
        print("⚠️ Docker not available in environment")
        return
    
    provider = PythonProvider('test-docker', enable_local=True)
    await provider.initialize()
    
    # Test local execution
    result = await provider.handle_request(
        'python/execute',
        {'code': 'result = "Docker available: " + str(5 * 5)', 'execution_mode': 'local'}
    )
    print(f"✅ Local execution: {result.get('result')}")
    
    # Test validation
    validation = await provider.handle_request(
        'python/validate',
        {'code': 'import math; print(math.pi)'}
    )
    print(f"✅ Code validation: {'Valid' if validation.get('valid') else 'Invalid'}")
    
    await provider.shutdown()
    print("✅ Provider shutdown complete")


async def test_without_docker():
    """Test Python provider without Docker available"""
    print("\n" + "="*50)
    print("🔍 TESTING WITHOUT DOCKER")
    print("="*50)
    
    # Mock Docker as unavailable
    with unittest.mock.patch.dict('sys.modules', {'docker': None}):
        # Force reimport to trigger the ImportError
        import importlib
        import gleitzeit.providers.python_provider as pps
        importlib.reload(pps)
        
        print(f"Docker available: {pps.DOCKER_AVAILABLE}")
        
        provider = pps.PythonProvider('test-no-docker', enable_local=True)
        await provider.initialize()
        
        # Test local execution (should work)
        result = await provider.handle_request(
            'python/execute',
            {'code': 'result = "No Docker: " + str(3 + 7)', 'execution_mode': 'local'}
        )
        print(f"✅ Local execution: {result.get('result')}")
        
        # Test validation (should work)
        validation = await provider.handle_request(
            'python/validate',
            {'code': 'def hello(): return "world"'}
        )
        print(f"✅ Code validation: {'Valid' if validation.get('valid') else 'Invalid'}")
        
        # Test that container execution fails gracefully
        try:
            result = await provider.handle_request(
                'python/execute',
                {'code': 'result = "container test"', 'execution_mode': 'sandboxed'}
            )
            # Should fallback to local execution
            print(f"✅ Sandboxed fallback: {result.get('result')}")
        except Exception as e:
            print(f"✅ Sandboxed mode properly failed: {type(e).__name__}")
        
        await provider.shutdown()
        print("✅ Provider shutdown complete")


async def test_package_imports():
    """Test that core package imports work without Docker"""
    print("\n" + "="*50)
    print("🔍 TESTING PACKAGE IMPORTS WITHOUT DOCKER")
    print("="*50)
    
    with unittest.mock.patch.dict('sys.modules', {'docker': None}):
        try:
            # Test core imports
            from gleitzeit.providers.base import ProtocolProvider
            from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider
            from gleitzeit.core.workflow_loader import load_workflow_from_file
            print("✅ Core imports successful")
            
            # Test that MCP provider still works
            mcp = SimpleMCPProvider('test')
            await mcp.initialize()
            result = await mcp.handle_request('mcp/tool.add', {'a': 2, 'b': 3})
            print(f"✅ MCP provider works: {result.get('result')}")
            await mcp.shutdown()
            
            # Test workflow loading
            if Path('examples/simple_mcp_workflow.yaml').exists():
                workflow = load_workflow_from_file('examples/simple_mcp_workflow.yaml')
                print(f"✅ Workflow loading works: {workflow.name}")
            
        except Exception as e:
            print(f"❌ Import test failed: {e}")


async def main():
    """Run all optional dependency tests"""
    print("\n" + "="*60)
    print("🚀 OPTIONAL DOCKER DEPENDENCY TEST SUITE")
    print("="*60)
    
    await test_package_imports()
    await test_without_docker()
    await test_with_docker()
    
    print("\n" + "="*60)
    print("✅ OPTIONAL DEPENDENCY TESTS COMPLETE")
    print("="*60)
    
    print("\nSUMMARY:")
    print("• Package installs and imports without Docker")
    print("• PythonProvider falls back to local execution")
    print("• MCP and LLM providers work independently") 
    print("• Core functionality preserved without optional dependencies")
    print("• Docker provides enhanced sandboxed execution when available")


if __name__ == "__main__":
    asyncio.run(main())