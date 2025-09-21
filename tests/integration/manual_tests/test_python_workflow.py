#!/usr/bin/env python3
"""
Test Python workflow execution with parameter substitution between tasks.
"""

import asyncio
import aiohttp
import json
import sys

async def test_python_workflow():
    """Test Python workflow with dependencies and parameter substitution."""
    
    # Python workflow with dependent tasks
    workflow = {
        "workflow": {
            "name": "python-math-workflow",
            "tasks": [
                {
                    "id": "calculate",
                    "name": "Calculate Sum",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "parameters": {
                        "file_path": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/calculate_sum.py"
                    }
                },
                {
                    "id": "process",
                    "name": "Process Result",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "dependencies": ["calculate"],
                    "parameters": {
                        "file_path": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/process_result.py",
                        "context": {
                            "previous_result": "${calculate.result}"
                        }
                    }
                },
                {
                    "id": "finalize",
                    "name": "Final Report",
                    "protocol": "python/v1", 
                    "method": "python/execute",
                    "dependencies": ["process"],
                    "parameters": {
                        "file_path": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/final_report.py",
                        "context": {
                            "process_result": "${process.result}"
                        }
                    }
                }
            ]
        }
    }
    
    async with aiohttp.ClientSession() as session:
        # Submit workflow
        print("=" * 60)
        print("PYTHON WORKFLOW TEST - PARAMETER SUBSTITUTION")
        print("=" * 60)
        
        try:
            url = "http://localhost:8080/workflows/"
            print(f"\n1. Submitting Python workflow to {url}...")
            print(f"   Tasks: Calculate Sum -> Process Result -> Final Report")
            
            async with session.post(url, json=workflow) as response:
                if response.status == 200:
                    result = await response.json()
                    workflow_id = result.get('workflow_id')
                    print(f"✅ Workflow submitted: {workflow_id}")
                    
                    # Wait for execution
                    print("\n2. Waiting for Python task execution...")
                    await asyncio.sleep(5)  # Give tasks time to execute
                    
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
                    print("\n4. Getting workflow results...")
                    results_url = f"http://localhost:8080/workflows/{workflow_id}/results"
                    async with session.get(results_url) as results_resp:
                        if results_resp.status == 200:
                            results = await results_resp.json()
                            print(f"✅ Got results:")
                            
                            # Parse and display results
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
                                if result_data:
                                    # Show output
                                    if 'output' in result_data:
                                        output = result_data['output']
                                        if isinstance(output, dict):
                                            print(f"   Output: {json.dumps(output, indent=6)}")
                                        else:
                                            print(f"   Output: {output}")
                                    
                                    # Show stdout if present
                                    if 'stdout' in result_data:
                                        stdout = result_data['stdout']
                                        if stdout:
                                            print(f"   Stdout: {stdout[:200]}...")
                                    
                                    if 'error' in result_data and result_data['error']:
                                        print(f"   Error: {result_data['error']}")
                                else:
                                    print(f"   No result data")
                                    
                            print("\n" + "=" * 60)
                            print("TEST COMPLETE - Check if parameter substitution worked!")
                            print("=" * 60)
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
    success = asyncio.run(test_python_workflow())
    sys.exit(0 if success else 1)