#!/usr/bin/env python3
"""
Task-Level Recovery Demo for Gleitzeit

This demo shows how workflows can be resumed after interruption,
with task-level granularity and dependency resolution.
"""

import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path so we can import gleitzeit_cluster
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster, Workflow


async def demo_task_recovery():
    """Demonstrate task-level recovery capabilities"""
    
    print("🧪 Task-Level Recovery Demo")
    print("=" * 50)
    
    # Create cluster with persistence enabled
    cluster = GleitzeitCluster(
        enable_redis=True,
        enable_real_execution=True,
        enable_socketio=False,  # Simplified for demo
        auto_start_services=False  # Don't auto-start for demo
    )
    
    try:
        await cluster.start()
        
        # Demo 1: Create a multi-step workflow
        print("\n📋 Creating a multi-step data processing workflow...")
        
        workflow = cluster.create_workflow(
            name="Data Processing Pipeline",
            description="Multi-step workflow with dependencies for recovery demo"
        )
        
        # Task 1: Generate initial data (no dependencies)
        task1 = workflow.add_python_task(
            name="Generate Data",
            function_name="fibonacci",
            kwargs={"n": 8}
        )
        
        # Task 2: Process data (depends on Task 1)  
        task2 = workflow.add_python_task(
            name="Analyze Numbers",
            function_name="analyze_numbers",
            kwargs={"numbers": "{{Generate Data.result}}"},
            dependencies=["Generate Data"]
        )
        
        # Task 3: Generate summary (depends on Task 2)
        task3 = workflow.add_text_task(
            name="Create Report",
            prompt="Create a brief analysis report: {{Analyze Numbers.result}}",
            model="llama3",
            dependencies=["Analyze Numbers"]
        )
        
        # Task 4: Additional processing (depends on Task 1, independent of Task 2/3)
        task4 = workflow.add_python_task(
            name="Count Words",
            function_name="count_words", 
            kwargs={"text": "This is a test workflow with multiple tasks"},
            dependencies=[]  # Independent task
        )
        
        print(f"✅ Created workflow with {len(workflow.tasks)} tasks:")
        for task_id, task in workflow.tasks.items():
            deps = ', '.join(task.dependencies) if task.dependencies else 'none'
            print(f"   - {task.name} (depends on: {deps})")
        
        # Submit workflow to Redis for persistence
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"\n💾 Workflow submitted and persisted: {workflow_id[:12]}...")
        
        # Demo 2: Simulate partial execution by manually marking some tasks as completed
        print(f"\n🔄 Simulating partial execution...")
        
        if cluster.redis_client:
            # Simulate completing Task 1 and Task 4
            await cluster.redis_client.complete_task(
                task1.id, 
                result=[0, 1, 1, 2, 3, 5, 8, 13]
            )
            print(f"   ✅ Completed: Generate Data")
            
            await cluster.redis_client.complete_task(
                task4.id,
                result={"word_count": 9, "character_count": 53}
            )
            print(f"   ✅ Completed: Count Words")
            
            # Update workflow progress
            await cluster.redis_client.update_workflow_status(
                workflow_id,
                workflow.status,
                completed_tasks=2,
                failed_tasks=0
            )
            
            print(f"   📊 Workflow progress: 2/4 tasks completed")
            print(f"   ⚠️  Simulating system interruption...")
        
        # Demo 3: Show recovery information
        print(f"\n🔍 Checking recovery status...")
        
        if cluster.redis_client:
            resumable = await cluster.redis_client.get_resumable_workflows()
            
            if resumable:
                workflow_info = resumable[0]  # Our workflow
                incomplete = await cluster.redis_client.get_incomplete_tasks(workflow_id)
                
                print(f"📋 Resumable workflow found:")
                print(f"   Name: {workflow_info['name']}")
                print(f"   Progress: {workflow_info['completed_tasks']}/{workflow_info['total_tasks']}")
                print(f"   Incomplete tasks: {len(incomplete)}")
                
                print(f"\n🔍 Task-level recovery analysis:")
                for task in incomplete:
                    status_icon = "🟢" if task['can_resume'] else "🔴"
                    deps_info = f"depends on: {', '.join(task['dependencies'])}" if task['dependencies'] else "no dependencies"
                    print(f"   {status_icon} {task['name']} ({deps_info})")
        
        # Demo 4: Perform task-level recovery
        print(f"\n🚀 Performing task-level recovery...")
        
        try:
            recovery_result = await cluster.resume_workflow(workflow_id)
            
            print(f"✅ Recovery completed:")
            print(f"   Workflow: {recovery_result['workflow_name']}")
            print(f"   Restored tasks: {recovery_result['restored_tasks']}")
            print(f"   Blocked tasks: {recovery_result['blocked_tasks']}")
            print(f"   Ready for execution: {recovery_result['ready_for_execution']}")
            
            if recovery_result['restored_tasks'] > 0:
                print(f"\n💡 Tasks have been restored to the execution queue")
                print(f"   In a full cluster, executor nodes would now process these tasks")
                print(f"   Task 2 (Analyze Numbers) can run since Task 1 completed")
                print(f"   Task 3 (Create Report) will run after Task 2 completes")
                
        except Exception as e:
            print(f"❌ Recovery failed: {e}")
        
        # Demo 5: Show final state
        print(f"\n📊 Final workflow state:")
        if cluster.redis_client:
            final_status = await cluster.get_workflow_status(workflow_id)
            if final_status:
                print(f"   Status: {final_status.get('status')}")
                print(f"   Progress: {final_status.get('completed_tasks')}/{final_status.get('total_tasks')}")
                
                results = final_status.get('results', {})
                if results:
                    print(f"   Results available for {len(results)} tasks:")
                    for task_name, result in results.items():
                        print(f"     - {task_name}: {str(result)[:60]}...")
        
        print(f"\n✨ Task-level recovery demo completed!")
        print(f"💡 Key recovery features demonstrated:")
        print(f"   • Task-level persistence and restoration")
        print(f"   • Dependency resolution (only ready tasks restored)")
        print(f"   • Granular recovery status (blocked vs. ready tasks)")
        print(f"   • Workflow state preservation across interruptions")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await cluster.stop()


if __name__ == "__main__":
    asyncio.run(demo_task_recovery())