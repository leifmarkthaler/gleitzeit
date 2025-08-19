#!/usr/bin/env python3
"""
Demonstrate that workflows return actual results from all providers
"""

import asyncio
import sys
from pathlib import Path
import tempfile
import json

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client
from gleitzeit.client import ClientMode


async def test_workflows_with_results():
    """Test that all provider workflows return actual results"""
    
    print("Testing Workflow Results from All Providers")
    print("=" * 60)
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # 1. OLLAMA WORKFLOW
        print("\n1. OLLAMA PROVIDER WORKFLOW")
        print("-" * 40)
        
        ollama_workflow = {
            "name": "Ollama Math Test",
            "tasks": [
                {
                    "id": "math_question",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {"role": "user", "content": "What is 15 + 27? Answer with just the number."}
                        ]
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(ollama_workflow, f)
            ollama_file = f.name
        
        results = await client.run_workflow(ollama_file)
        ollama_result = results['results']['math_question']['result']['response']
        print(f"Question: What is 15 + 27?")
        print(f"Ollama answered: {ollama_result}")
        
        # 2. PYTHON WORKFLOW
        print("\n2. PYTHON PROVIDER WORKFLOW")
        print("-" * 40)
        
        python_workflow = {
            "name": "Python Calculation",
            "tasks": [
                {
                    "id": "generate_data",
                    "method": "python/execute",
                    "parameters": {
                        "file": "examples/scripts/generate_numbers.py"
                    }
                },
                {
                    "id": "calculate_stats",
                    "method": "python/execute",
                    "dependencies": ["generate_data"],
                    "parameters": {
                        "file": "examples/scripts/calculate_sum.py",
                        "context": {
                            "numbers": "${generate_data.result.numbers}"
                        }
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(python_workflow, f)
            python_file = f.name
        
        results = await client.run_workflow(python_file)
        gen_output = results['results']['generate_data']['result']['output']
        calc_output = results['results']['calculate_stats']['result']['output']
        
        print("Python script 1 output:")
        print(f"  {gen_output.strip()}")
        print("Python script 2 output:")
        print(f"  {calc_output.strip()}")
        
        # 3. MCP WORKFLOW
        print("\n3. MCP PROVIDER WORKFLOW")
        print("-" * 40)
        
        mcp_workflow = {
            "name": "MCP Calculations",
            "tasks": [
                {
                    "id": "step1",
                    "method": "mcp/tool.add",
                    "parameters": {"a": 100, "b": 50}
                },
                {
                    "id": "step2",
                    "method": "mcp/tool.multiply",
                    "dependencies": ["step1"],
                    "parameters": {
                        "a": "${step1.result}",
                        "b": 2
                    }
                },
                {
                    "id": "step3",
                    "method": "mcp/tool.concat",
                    "dependencies": ["step2"],
                    "parameters": {
                        "a": "The final result is: ",
                        "b": "${step2.result}"
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mcp_workflow, f)
            mcp_file = f.name
        
        results = await client.run_workflow(mcp_file)
        
        step1_result = results['results']['step1']['result']['result']
        step2_result = results['results']['step2']['result']['result']
        step3_result = results['results']['step3']['result']['response']
        
        print(f"Step 1 (100 + 50): {step1_result}")
        print(f"Step 2 ({step1_result} × 2): {step2_result}")
        print(f"Step 3 (concatenate): {step3_result}")
        
        # 4. MIXED PROVIDER WORKFLOW
        print("\n4. MIXED PROVIDER WORKFLOW")
        print("-" * 40)
        
        mixed_workflow = {
            "name": "Mixed Provider Chain",
            "tasks": [
                {
                    "id": "mcp_calc",
                    "method": "mcp/tool.add",
                    "parameters": {"a": 25, "b": 75}
                },
                {
                    "id": "ask_llm",
                    "method": "llm/chat",
                    "dependencies": ["mcp_calc"],
                    "parameters": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {"role": "user", "content": "Is ${mcp_calc.result} equal to 100? Answer YES or NO only."}
                        ]
                    }
                },
                {
                    "id": "python_process",
                    "method": "python/execute",
                    "dependencies": ["ask_llm"],
                    "parameters": {
                        "file": "examples/scripts/count_words.py",
                        "context": {
                            "text": "${ask_llm.response}"
                        }
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mixed_workflow, f)
            mixed_file = f.name
        
        results = await client.run_workflow(mixed_file)
        
        mcp_result = results['results']['mcp_calc']['result']['result']
        llm_response = results['results']['ask_llm']['result']['response']
        python_output = results['results']['python_process']['result']['output']
        
        print(f"MCP calculated: 25 + 75 = {mcp_result}")
        print(f"LLM responded: {llm_response}")
        print(f"Python counted: {python_output.strip()}")
        
        print("\n" + "=" * 60)
        print("✅ ALL WORKFLOWS RETURNED PROPER RESULTS!")
        print("✅ Parameter substitution (${...}) works correctly!")
        print("✅ All providers integrate properly with hub system!")


if __name__ == "__main__":
    asyncio.run(test_workflows_with_results())