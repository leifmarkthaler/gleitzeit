#!/usr/bin/env python3
"""
Test running a single workflow via the Gleitzeit Python API.
"""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient


async def main():
    """Run a single simple workflow."""
    print("="*60)
    print("Testing Single Workflow via Python API")
    print("="*60)
    
    # Check if Ollama is available
    import aiohttp
    ollama_available = False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    ollama_available = True
                    print("✅ Ollama is available\n")
    except:
        print("⚠️  Ollama is not available\n")
        return False
    
    # Run the simple LLM workflow
    workflow_path = "examples/simple_llm_workflow.yaml"
    
    print(f"Loading workflow: {workflow_path}")
    
    async with GleitzeitClient(persistence="memory") as client:
        try:
            # Run the workflow
            print("Running workflow...")
            results = await client.run_workflow(workflow_path)
            
            print(f"\n✅ Workflow completed successfully!")
            print(f"Number of tasks executed: {len(results)}\n")
            
            # Show detailed results
            for task_id, result in results.items():
                print(f"Task: {task_id}")
                print("-" * 40)
                
                if hasattr(result, 'status'):
                    print(f"Status: {result.status}")
                    
                    if hasattr(result, 'error') and result.error:
                        print(f"Error: {result.error}")
                    elif hasattr(result, 'result') and result.result:
                        # Extract the actual response
                        if isinstance(result.result, dict):
                            if 'response' in result.result:
                                print(f"Response:\n{result.result['response']}")
                            elif 'content' in result.result:
                                print(f"Content:\n{result.result['content']}")
                            else:
                                print(f"Result: {result.result}")
                        else:
                            print(f"Result: {result.result}")
                else:
                    print(f"Result object: {result}")
                
                print()
            
            return True
            
        except Exception as e:
            print(f"\n❌ Workflow failed: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)