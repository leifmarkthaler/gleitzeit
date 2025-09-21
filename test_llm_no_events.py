#!/usr/bin/env python3
"""
Test LLM workflow submission without events - simple synchronous approach.
"""

import requests
import json
import time

def test_llm_workflow():
    """Test submitting an LLM workflow via simple HTTP requests."""
    print("\n" + "="*60)
    print("SIMPLE LLM WORKFLOW TEST (No Events)")
    print("="*60)
    
    base_url = "http://localhost:8000"
    
    # Create LLM workflow
    print("\n1. Creating LLM workflow...")
    workflow_data = {
        "id": "llm_test_simple",
        "name": "Simple LLM Test",
        "description": "Test LLM workflow without events",
        "tasks": [
            {
                "id": "llm_task_hello",
                "name": "Say Hello",
                "method": "complete",
                "protocol": "llm",
                "config": {
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Say 'Hello World' in exactly 2 words"
                        }
                    ],
                    "max_tokens": 10,
                    "temperature": 0
                }
            }
        ]
    }
    
    print(f"   Task: {workflow_data['tasks'][0]['name']}")
    print(f"   Protocol: {workflow_data['tasks'][0]['protocol']}")
    
    # Submit workflow
    print("\n2. Submitting workflow...")
    try:
        response = requests.post(
            f"{base_url}/workflows/",
            json=workflow_data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            workflow_id = result.get("workflow_id")
            print(f"   ✓ Submitted: {workflow_id}")
            print(f"   Response: {json.dumps(result, indent=2)}")
            
            # Wait for execution
            print("\n3. Waiting for LLM execution...")
            time.sleep(5)
            
            # Get results
            print("\n4. Getting workflow results...")
            results_response = requests.get(
                f"{base_url}/workflows/{workflow_id}/results",
                timeout=10
            )
            
            if results_response.status_code == 200:
                results = results_response.json()
                print(f"   ✓ Got results:")
                print(json.dumps(results, indent=2))
                
                # Check if LLM actually ran
                for item in results.get("items", []):
                    if item.get("status") == "completed":
                        print("\n   ✅ LLM task completed successfully!")
                        result_data = item.get("result", {})
                        if isinstance(result_data, dict):
                            # Check for various result formats
                            if "choices" in result_data:
                                # OpenAI format
                                content = result_data["choices"][0]["message"]["content"]
                                print(f"   LLM Response: {content}")
                            elif "result" in result_data:
                                print(f"   Result: {result_data['result']}")
                            elif "error" in result_data:
                                print(f"   Error: {result_data['error']}")
                    elif item.get("status") == "failed":
                        print(f"\n   ❌ Task failed: {item.get('error')}")
            else:
                print(f"   Failed to get results: {results_response.status_code}")
                print(f"   {results_response.text}")
        else:
            print(f"   ✗ Failed to submit: {response.status_code}")
            print(f"   {response.text}")
    except requests.Timeout:
        print("   ✗ Request timed out!")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    test_llm_workflow()