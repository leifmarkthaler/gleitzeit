#!/usr/bin/env python3
"""
Simple Working Example - Current API
Shows basic LLM text generation and function execution
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow


async def main():
    """Simple example using current API"""
    
    print("🚀 Gleitzeit Simple Example")
    print("=" * 40)
    
    # Start cluster
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True  # Try real execution
    )
    
    await cluster.start()
    
    try:
        print("✅ Cluster started")
        
        # Example 1: Text generation
        print("\n💬 Example 1: Text Generation")
        text_task = Task(
            name="Generate Story",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Write a short story about a robot learning to paint",
                model_name="llama3"
            )
        )
        
        workflow = Workflow(
            name="Simple Text Generation"
        )
        workflow.add_task(text_task)
        
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"📋 Submitted workflow: {workflow_id}")
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Text generation completed:")
            print(f"📝 Result: {results.get(text_task.id, 'No result')}")
        else:
            print(f"❌ Text generation failed: {status.get('error', 'Unknown error')}")
        
        # Example 2: Function execution
        print("\n🔧 Example 2: Function Execution")
        function_task = Task(
            name="Calculate Fibonacci",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="fibonacci_sequence",
                kwargs={"n": 8}
            )
        )
        
        workflow2 = Workflow(
            name="Simple Function Call",
            tasks=[function_task]
        )
        
        workflow_id2 = await cluster.submit_workflow(workflow2)
        print(f"📋 Submitted workflow: {workflow_id2}")
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id2)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Function execution completed:")
            print(f"🔢 Result: {results.get(function_task.id, 'No result')}")
        else:
            print(f"❌ Function execution failed: {status.get('error', 'Unknown error')}")
        
        # Example 3: Vision analysis (if image available)
        print("\n👁️ Example 3: Vision Analysis")
        print("(Skipped - requires image file and Ollama with llava model)")
        
        print("\n✅ Simple example completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await cluster.stop()
        print("🛑 Cluster stopped")


if __name__ == "__main__":
    asyncio.run(main())