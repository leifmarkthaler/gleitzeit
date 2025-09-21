#!/usr/bin/env python3
"""
Test LLM workflow execution with Ollama provider.
"""

import asyncio
import aiohttp
import json
import sys

async def test_llm_workflow():
    """Test LLM workflow execution with results."""
    
    # LLM workflow that uses Ollama
    workflow = {
        "workflow": {
            "name": "llm-analysis",
            "tasks": [
                {
                    "id": "summarize",
                    "name": "Summarize Text",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a helpful assistant that provides concise summaries."
                            },
                            {
                                "role": "user",
                                "content": "Summarize this in one sentence: The quick brown fox jumps over the lazy dog. This pangram contains all letters of the English alphabet."
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 100
                    }
                },
                {
                    "id": "analyze",
                    "name": "Analyze Summary",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "dependencies": ["summarize"],
                    "parameters": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a linguistic analyst."
                            },
                            {
                                "role": "user",
                                "content": "What makes this sentence special from a linguistic perspective? Analyze: '${summarize.result.response}'"
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 150
                    }
                }
            ]
        }
    }
    
    async with aiohttp.ClientSession() as session:
        # Submit workflow
        print("=" * 60)
        print("LLM WORKFLOW TEST")
        print("=" * 60)
        
        try:
            url = "http://localhost:8080/workflows/"
            print(f"\n1. Submitting LLM workflow to {url}...")
            print(f"   Using model: llama3.2:latest")
            
            async with session.post(url, json=workflow) as response:
                if response.status == 200:
                    result = await response.json()
                    workflow_id = result.get('workflow_id')
                    print(f"✅ Workflow submitted: {workflow_id}")
                    
                    # Wait for LLM execution (may take longer)
                    print("\n2. Waiting for LLM execution (this may take a moment)...")
                    await asyncio.sleep(10)  # Give LLMs more time
                    
                    # Get workflow status
                    print("\n3. Getting workflow status...")
                    status_url = f"http://localhost:8080/workflows/{workflow_id}"
                    async with session.get(status_url) as status_resp:
                        if status_resp.status == 200:
                            status_data = await status_resp.json()
                            print(f"✅ Workflow status: {status_data.get('status')}")
                            
                            # Show task statuses
                            tasks = status_data.get('tasks', [])
                            if tasks:
                                print("\nTask statuses:")
                                for task in tasks:
                                    print(f"  - {task.get('name')}: {task.get('status')}")
                        else:
                            print(f"❌ Failed to get status: {status_resp.status}")
                    
                    # Get results
                    print("\n4. Getting LLM workflow results...")
                    results_url = f"http://localhost:8080/workflows/{workflow_id}/results"
                    async with session.get(results_url) as results_resp:
                        if results_resp.status == 200:
                            results = await results_resp.json()
                            print(f"✅ Got results:")
                            
                            # Parse and display LLM responses
                            for item in results.get('items', []):
                                task_id = item.get('task_id')
                                result_data = item.get('result', {})
                                
                                # Find task name
                                task_name = "Unknown"
                                for task in tasks:
                                    if task.get('id') == task_id:
                                        task_name = task.get('name')
                                        break
                                
                                print(f"\n📝 {task_name}:")
                                if result_data.get('success'):
                                    # Try to parse LLM response
                                    output = result_data.get('output', '')
                                    if output:
                                        try:
                                            # LLM responses might be JSON
                                            response_json = json.loads(output)
                                            if 'response' in response_json:
                                                print(f"   Response: {response_json['response']}")
                                            else:
                                                print(f"   Output: {output[:200]}...")
                                        except:
                                            # Plain text response
                                            print(f"   Output: {output[:200]}...")
                                else:
                                    print(f"   Error: {result_data.get('error')}")
                        else:
                            text = await results_resp.text()
                            print(f"❌ Failed to get results: {results_resp.status}")
                            print(f"Response: {text}")
                    
                    return True
                    
                else:
                    error = await response.text()
                    print(f"❌ Failed to submit: {response.status}")
                    print(f"Error: {error}")
                    return False
                    
        except aiohttp.ClientConnectorError:
            print("❌ Could not connect to server at localhost:8080")
            print("Make sure the server is running: gleitzeit serve --port 8080")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    print("Note: This test requires Ollama to be running with llama3.2 model installed")
    print("Run: ollama pull llama3.2 if you haven't already\n")
    
    success = asyncio.run(test_llm_workflow())
    sys.exit(0 if success else 1)