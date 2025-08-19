#!/usr/bin/env python3
"""
Test that all providers work with hub integration
"""

import asyncio
import sys
from pathlib import Path
import tempfile
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client
from gleitzeit.client import ClientMode


async def test_python_provider():
    """Test Python provider with workflow"""
    print("\n" + "="*50)
    print("Testing Python Provider...")
    print("-" * 50)
    
    workflow = {
        "name": "Python Test Workflow",
        "tasks": [
            {
                "id": "generate_numbers",
                "method": "python/execute",
                "parameters": {
                    "file": "examples/scripts/generate_numbers.py"
                }
            },
            {
                "id": "calculate_sum",
                "method": "python/execute",
                "dependencies": ["generate_numbers"],
                "parameters": {
                    "file": "examples/scripts/calculate_sum.py",
                    "context": {
                        "numbers": "${generate_numbers.result.numbers}"
                    }
                }
            }
        ]
    }
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # Save workflow to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name
        
        try:
            results = await client.run_workflow(workflow_file)
            workflow_results = results.get('results', {})
            
            if 'generate_numbers' in workflow_results:
                gen_result = workflow_results['generate_numbers'].get('result', {})
                output = gen_result.get('output', gen_result.get('result', 'N/A'))
                print(f"✓ Generate numbers: {output[:50]}...")
            
            if 'calculate_sum' in workflow_results:
                calc_result = workflow_results['calculate_sum'].get('result', {})
                output = calc_result.get('output', calc_result.get('result', 'N/A'))
                print(f"✓ Calculate sum: {output[:50]}...")
                
            return True
        except Exception as e:
            print(f"✗ Python workflow failed: {e}")
            return False


async def test_mcp_provider():
    """Test MCP provider with workflow"""
    print("\n" + "="*50)
    print("Testing MCP Provider...")
    print("-" * 50)
    
    workflow = {
        "name": "MCP Test Workflow",
        "tasks": [
            {
                "id": "add_numbers",
                "method": "mcp/tool.add",
                "parameters": {
                    "a": 10,
                    "b": 20
                }
            },
            {
                "id": "multiply_result",
                "method": "mcp/tool.multiply",
                "dependencies": ["add_numbers"],
                "parameters": {
                    "a": "${add_numbers.result}",
                    "b": 3
                }
            },
            {
                "id": "echo_result",
                "method": "mcp/tool.echo",
                "dependencies": ["multiply_result"],
                "parameters": {
                    "message": "Final result: ${multiply_result.result}"
                }
            }
        ]
    }
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # Save workflow to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name
        
        try:
            results = await client.run_workflow(workflow_file)
            workflow_results = results.get('results', {})
            
            if 'add_numbers' in workflow_results:
                add_result = workflow_results['add_numbers'].get('result', {})
                print(f"✓ Add: 10 + 20 = {add_result.get('result', 'N/A')}")
            
            if 'multiply_result' in workflow_results:
                mult_result = workflow_results['multiply_result'].get('result', {})
                print(f"✓ Multiply: 30 × 3 = {mult_result.get('result', 'N/A')}")
                
            if 'echo_result' in workflow_results:
                echo_result = workflow_results['echo_result'].get('result', {})
                print(f"✓ Echo: {echo_result.get('response', 'N/A')}")
                
            return True
        except Exception as e:
            print(f"✗ MCP workflow failed: {e}")
            return False


async def test_mixed_provider_workflow():
    """Test workflow mixing multiple providers"""
    print("\n" + "="*50)
    print("Testing Mixed Provider Workflow...")
    print("-" * 50)
    
    workflow = {
        "name": "Mixed Provider Test",
        "tasks": [
            {
                "id": "generate_prompt",
                "method": "python/execute",
                "parameters": {
                    "file": "examples/scripts/generate_prompt.py"
                }
            },
            {
                "id": "llm_response",
                "method": "llm/chat",
                "dependencies": ["generate_prompt"],
                "parameters": {
                    "model": "llama3.2:latest",
                    "messages": [
                        {"role": "user", "content": "${generate_prompt.result.prompt}"}
                    ]
                }
            },
            {
                "id": "count_words",
                "method": "python/execute",
                "dependencies": ["llm_response"],
                "parameters": {
                    "file": "examples/scripts/count_words.py",
                    "context": {
                        "text": "${llm_response.response}"
                    }
                }
            }
        ]
    }
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # Save workflow to file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name
        
        try:
            results = await client.run_workflow(workflow_file)
            workflow_results = results.get('results', {})
            
            has_results = False
            if 'generate_prompt' in workflow_results:
                print(f"✓ Python: Generated prompt")
                has_results = True
            
            if 'llm_response' in workflow_results:
                print(f"✓ Ollama: Generated response")
                has_results = True
                
            if 'count_words' in workflow_results:
                count_result = workflow_results['count_words'].get('result', {})
                print(f"✓ Python: Counted {count_result.get('word_count', 'N/A')} words")
                has_results = True
                
            return has_results
        except Exception as e:
            print(f"✗ Mixed workflow failed: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_template_provider():
    """Test template provider"""
    print("\n" + "="*50)
    print("Testing Template Provider...")
    print("-" * 50)
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # Template provider generates workflows, so we test via direct task submission
        try:
            task = await client.submit_task(
                name="Template Test",
                protocol="template/v1",
                method="template/research",
                params={
                    "topic": "workflow orchestration",
                    "depth": "shallow"
                }
            )
            
            # Wait for completion (template provider may need more time)
            await asyncio.sleep(5)
            
            result = await client.get_task_result(task.id)
            if result and result.status == "completed":
                print(f"✓ Template provider generated research workflow")
                return True
            else:
                print(f"✗ Template task status: {result.status if result else 'No result'}")
                return False
                
        except Exception as e:
            print(f"✗ Template provider failed: {e}")
            return False


async def main():
    """Run all provider tests"""
    
    print("Testing All Providers with Hub Integration")
    print("=" * 50)
    
    results = {}
    
    # Test each provider
    results['Python'] = await test_python_provider()
    results['MCP'] = await test_mcp_provider()
    results['Mixed'] = await test_mixed_provider_workflow()
    results['Template'] = await test_template_provider()
    
    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("-" * 50)
    
    all_passed = True
    for provider, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{provider:15} {status}")
        if not passed:
            all_passed = False
    
    print("="*50)
    if all_passed:
        print("✅ All providers work with hub integration!")
    else:
        print("❌ Some providers failed. Check details above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())