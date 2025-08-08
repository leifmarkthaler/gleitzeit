#!/usr/bin/env python3
"""
Workflow Demo - Current API
Shows multi-step workflows with dependencies
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow


async def simple_workflow():
    """Demonstrate a simple multi-step workflow"""
    
    print("📋 Simple Multi-Step Workflow")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Step 1: Generate data
        generate_task = Task(
            id="task_1",
            name="Generate Random Data",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="random_data",
                kwargs={
                    "data_type": "numbers",
                    "count": 10,
                    "min": 1,
                    "max": 100
                }
            )
        )
        
        # Step 2: Analyze data (depends on step 1)
        analyze_task = Task(
            id="task_2", 
            name="Analyze Numbers",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="analyze_numbers",
                kwargs={"numbers": "{{task_1.result}}"}
            ),
            dependencies=["task_1"]
        )
        
        # Step 3: Generate report (depends on step 2)
        report_task = Task(
            id="task_3",
            name="Generate Report",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Create a brief statistical report based on this analysis: {{task_2.result}}",
                model_name="llama3"
            ),
            dependencies=["task_2"]
        )
        
        # Create workflow
        workflow = Workflow(
            name="Data Analysis Pipeline",
            description="Generate, analyze, and report on data",
            tasks=[generate_task, analyze_task, report_task]
        )
        
        print(f"🚀 Created workflow with {len(workflow.tasks)} tasks")
        print("   1. Generate random numbers")
        print("   2. Analyze the numbers")
        print("   3. Generate text report")
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"📨 Submitted workflow: {workflow_id}")
        
        # Monitor progress
        completed_tasks = set()
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            
            # Show progress
            current_completed = set(status.get("completed_tasks", []))
            new_completed = current_completed - completed_tasks
            
            for task_id in new_completed:
                task_name = next((t.name for t in workflow.tasks if t.id == task_id), task_id)
                print(f"✅ Completed: {task_name}")
            
            completed_tasks = current_completed
            
            # Check if done
            if status["status"] in ["completed", "failed"]:
                break
                
            await asyncio.sleep(1)
        
        # Show final results
        print(f"\n📊 Workflow Status: {status['status']}")
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("📋 Final Results:")
            
            for task in workflow.tasks:
                result = results.get(task.id)
                print(f"   • {task.name}: {result}")
        else:
            print(f"❌ Workflow failed: {status.get('error', 'Unknown error')}")
        
        return status
        
    finally:
        await cluster.stop()


async def parallel_workflow():
    """Demonstrate parallel task execution"""
    
    print("\n🔀 Parallel Workflow Example")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Parallel tasks (no dependencies)
        task1 = Task(
            id="parallel_1",
            name="Process Text 1",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="count_words",
                kwargs={"text": "The quick brown fox jumps over the lazy dog"}
            )
        )
        
        task2 = Task(
            id="parallel_2",
            name="Process Text 2", 
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="count_words",
                kwargs={"text": "Machine learning enables computers to learn without being explicitly programmed"}
            )
        )
        
        task3 = Task(
            id="parallel_3",
            name="Math Calculation",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="fibonacci_sequence",
                kwargs={"n": 6}
            )
        )
        
        # Combine results task (depends on all parallel tasks)
        combine_task = Task(
            id="combine",
            name="Combine Results",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Summarize these results: Text 1: {{parallel_1.result}}, Text 2: {{parallel_2.result}}, Fibonacci: {{parallel_3.result}}",
                model_name="llama3"
            ),
            dependencies=["parallel_1", "parallel_2", "parallel_3"]
        )
        
        # Create workflow
        workflow = Workflow(
            name="Parallel Processing Demo",
            description="Run tasks in parallel then combine results",
            tasks=[task1, task2, task3, combine_task]
        )
        
        print(f"🚀 Created parallel workflow with {len(workflow.tasks)} tasks")
        print("   • 3 tasks run in parallel")
        print("   • 1 task combines the results")
        
        # Submit and monitor
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"📨 Submitted workflow: {workflow_id}")
        
        # Monitor with timing
        import time
        start_time = time.time()
        
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(0.5)
        
        elapsed = time.time() - start_time
        print(f"⏱️ Completed in {elapsed:.1f} seconds")
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ All parallel tasks completed successfully")
            print(f"📄 Combined result: {results.get('combine', 'No result')}")
        else:
            print(f"❌ Workflow failed: {status.get('error', 'Unknown error')}")
        
        return status
        
    finally:
        await cluster.stop()


async def main():
    """Run all workflow demos"""
    
    print("🎯 Gleitzeit Workflow Demonstrations")
    print("=" * 60)
    
    # Run demos
    await simple_workflow()
    await parallel_workflow()
    
    print("\n✅ All workflow demos completed!")
    print("\n💡 Key Concepts Demonstrated:")
    print("   ✅ Task dependencies with {{task_id.result}} substitution")
    print("   ✅ Sequential workflow execution")
    print("   ✅ Parallel task processing")
    print("   ✅ Mixed task types (functions + LLM)")
    print("   ✅ Real-time workflow monitoring")


if __name__ == "__main__":
    asyncio.run(main())