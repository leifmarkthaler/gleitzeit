#!/usr/bin/env python3
"""
Functions Demo - Current API
Shows built-in function capabilities
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow
from gleitzeit_cluster.functions.registry import get_function_registry


async def explore_functions():
    """Explore available functions"""
    
    print("🔧 Function Registry Exploration")
    print("=" * 40)
    
    registry = get_function_registry()
    
    # Show stats
    stats = registry.get_stats()
    print(f"📊 Registry Stats:")
    print(f"   Total functions: {stats['total_functions']}")
    print(f"   Categories: {stats['total_categories']}")
    print(f"   Async functions: {stats['async_functions']}")
    
    # Show functions by category
    print(f"\n📚 Functions by Category:")
    for category, count in stats['categories'].items():
        functions = registry.list_functions(category=category)
        print(f"\n   📂 {category.upper()} ({count} functions):")
        
        for func_name in functions[:5]:  # Show first 5
            info = registry.get_function_info(func_name)
            if info:
                desc = info.get('description', 'No description')[:50]
                async_mark = " (async)" if info.get('is_async') else ""
                print(f"      • {func_name}{async_mark}: {desc}")
        
        if len(functions) > 5:
            print(f"      ... and {len(functions) - 5} more")


async def demo_core_functions():
    """Demonstrate core functions"""
    
    print("\n🔢 Core Functions Demo")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Math functions
        fib_task = Task(
            name="Fibonacci Sequence",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="fibonacci_sequence",
                kwargs={"n": 10}
            )
        )
        
        # Text functions
        word_count_task = Task(
            name="Count Words",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="count_words",
                kwargs={"text": "The quick brown fox jumps over the lazy dog"}
            )
        )
        
        # Data generation
        random_data_task = Task(
            name="Generate Random Data",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="random_data",
                kwargs={
                    "data_type": "numbers",
                    "count": 15,
                    "min": 10,
                    "max": 50
                }
            )
        )
        
        workflow = Workflow(
            name="Core Functions Demo",
            tasks=[fib_task, word_count_task, random_data_task]
        )
        
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"🚀 Testing core functions...")
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Core functions completed:")
            
            print(f"   📊 Fibonacci(10): {results.get(fib_task.id)}")
            print(f"   📝 Word count: {results.get(word_count_task.id)}")
            print(f"   🎲 Random data: {results.get(random_data_task.id)}")
        else:
            print(f"❌ Core functions failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def demo_data_functions():
    """Demonstrate data processing functions"""
    
    print("\n📊 Data Functions Demo")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Generate sample data first
        numbers = [15, 23, 8, 42, 4, 16, 23, 15, 35, 8, 19, 27, 31]
        
        # Analyze numbers
        analyze_task = Task(
            name="Analyze Numbers",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="analyze_numbers",
                kwargs={"numbers": numbers}
            )
        )
        
        # Aggregate data  
        aggregate_task = Task(
            name="Aggregate Data",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="aggregate",
                kwargs={
                    "data": numbers,
                    "operation": "statistics"
                }
            )
        )
        
        workflow = Workflow(
            name="Data Processing Demo",
            tasks=[analyze_task, aggregate_task]
        )
        
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"🚀 Processing data: {numbers}")
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Data processing completed:")
            
            analysis = results.get(analyze_task.id, {})
            if isinstance(analysis, dict):
                print(f"   📈 Analysis:")
                print(f"      Count: {analysis.get('count')}")
                print(f"      Average: {analysis.get('average', 0):.2f}")
                print(f"      Min/Max: {analysis.get('min')}/{analysis.get('max')}")
                print(f"      Unique: {analysis.get('unique_count')}")
            
            aggregation = results.get(aggregate_task.id, {})
            print(f"   📊 Aggregation: {aggregation}")
        else:
            print(f"❌ Data processing failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def demo_async_functions():
    """Demonstrate async functions"""
    
    print("\n⚡ Async Functions Demo")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        import time
        start_time = time.time()
        
        # Async timer function
        timer_task = Task(
            name="Async Timer",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_timer",
                kwargs={"seconds": 2}
            )
        )
        
        # Async batch processing
        batch_task = Task(
            name="Async Batch Process",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_batch_process",
                kwargs={
                    "items": ["task1", "task2", "task3", "task4"],
                    "delay": 0.5
                }
            )
        )
        
        workflow = Workflow(
            name="Async Functions Demo",
            tasks=[timer_task, batch_task]
        )
        
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"🚀 Testing async functions...")
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(0.5)
        
        elapsed = time.time() - start_time
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print(f"✅ Async functions completed in {elapsed:.1f}s:")
            
            print(f"   ⏰ Timer result: {results.get(timer_task.id)}")
            print(f"   📦 Batch result: {results.get(batch_task.id)}")
        else:
            print(f"❌ Async functions failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def main():
    """Run all function demos"""
    
    print("🛠️ Gleitzeit Functions Demonstration")
    print("=" * 60)
    
    # Explore available functions
    await explore_functions()
    
    # Demo different function types
    await demo_core_functions()
    await demo_data_functions()
    await demo_async_functions()
    
    print("\n✅ All function demos completed!")
    print("\n💡 Key Function Features:")
    print("   ✅ 30+ built-in secure functions")
    print("   ✅ Core utilities (math, text, data)")
    print("   ✅ Async function support")
    print("   ✅ Type validation and safety")
    print("   ✅ Categorized function registry")
    print("\n🔍 Explore more with: gleitzeit functions list")


if __name__ == "__main__":
    asyncio.run(main())