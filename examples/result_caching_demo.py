#!/usr/bin/env python3
"""
Result Caching Demo

Shows how to store, retrieve, and process workflow results
for further data processing and analysis.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.storage.result_cache import ResultCache


async def demo_result_caching():
    """Demonstrate comprehensive result caching"""
    
    print("🗃️  Gleitzeit Result Caching Demo")
    print("=" * 50)
    
    # Initialize cluster and cache
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Mock for demo
        enable_redis=True
    )
    await cluster.start()
    
    cache = ResultCache(
        redis_client=cluster.redis_client,
        cache_dir=Path("./results_cache"),
        enable_file_backup=True
    )
    
    try:
        # 1. Create and run workflows with results
        print("\n1️⃣  Creating workflows with tagged results...")
        
        workflows = [
            ("data_analysis", "Analyze sales data", ["analysis", "sales"]),
            ("report_generation", "Generate quarterly report", ["report", "quarterly"]),
            ("data_cleaning", "Clean customer data", ["cleaning", "data"]),
            ("sentiment_analysis", "Analyze customer reviews", ["analysis", "sentiment"])
        ]
        
        workflow_results = {}
        
        for name, description, tags in workflows:
            print(f"   📋 Creating workflow: {name}")
            
            workflow = cluster.create_workflow(name, description)
            workflow.add_text_task("process", f"Process: {description}", "llama3")
            workflow.add_text_task("summarize", f"Summarize: {description}", "llama3")
            
            # Execute workflow
            result = await cluster.execute_workflow(workflow)
            
            # Store in cache with tags
            await cache.store_workflow_result(
                workflow_id=workflow.id,
                workflow_result={
                    "status": result.status.value,
                    "completed_tasks": result.completed_tasks,
                    "results": result.results,
                    "metadata": {"name": name, "description": description}
                },
                tags=tags
            )
            
            workflow_results[workflow.id] = result
            print(f"   ✅ Stored result for: {name}")
        
        # 2. Retrieve specific results
        print(f"\n2️⃣  Retrieving cached results...")
        
        for workflow_id in list(workflow_results.keys())[:2]:  # First 2
            cached_result = await cache.get_workflow_result(workflow_id)
            if cached_result:
                metadata = cached_result["result"]["metadata"]
                print(f"   📄 Retrieved: {metadata['name']}")
                print(f"      Status: {cached_result['result']['status']}")
                print(f"      Tasks: {cached_result['result']['completed_tasks']}")
                print(f"      Tags: {cached_result['tags']}")
        
        # 3. Query by tags
        print(f"\n3️⃣  Querying results by tags...")
        
        analysis_results = await cache.get_results_by_tags(["analysis"])
        print(f"   🔍 Found {len(analysis_results)} analysis workflows:")
        for result in analysis_results:
            name = result["result"]["metadata"]["name"]
            print(f"      - {name}")
        
        # 4. Get recent results
        print(f"\n4️⃣  Getting recent results...")
        
        recent_results = await cache.get_recent_results(hours=1)
        print(f"   ⏰ Found {len(recent_results)} results from last hour:")
        for result in recent_results:
            name = result["result"]["metadata"]["name"]
            stored_at = result["stored_at"]
            print(f"      - {name} (stored: {stored_at})")
        
        # 5. Extract specific task results
        print(f"\n5️⃣  Extracting individual task results...")
        
        if workflow_results:
            first_workflow_id = list(workflow_results.keys())[0]
            cached_result = await cache.get_workflow_result(first_workflow_id)
            
            if cached_result:
                task_results = cache.get_task_results(cached_result)
                print(f"   📋 Task results for first workflow:")
                for task_id, task_result in task_results.items():
                    print(f"      {task_id}: {task_result}")
        
        # 6. Export results for external processing
        print(f"\n6️⃣  Exporting results...")
        
        export_file = Path("./exported_results.json")
        success = await cache.export_results(export_file, format="json")
        
        if success:
            print(f"   💾 Results exported to: {export_file}")
            print(f"   📊 File size: {export_file.stat().st_size} bytes")
        
        # 7. Show data processing pipeline example
        print(f"\n7️⃣  Data processing pipeline example...")
        
        analysis_workflows = await cache.get_results_by_tags(["analysis"])
        
        # Process results for further analysis
        processed_data = []
        for result_data in analysis_workflows:
            workflow_result = result_data["result"]
            task_results = cache.get_task_results(result_data)
            
            # Extract meaningful data
            processed_item = {
                "workflow_name": workflow_result["metadata"]["name"],
                "completion_status": workflow_result["status"],
                "task_count": workflow_result["completed_tasks"],
                "processing_timestamp": result_data["stored_at"],
                "task_outputs": list(task_results.values())
            }
            processed_data.append(processed_item)
        
        print(f"   🔄 Processed {len(processed_data)} analysis workflows:")
        for item in processed_data:
            print(f"      - {item['workflow_name']}: {item['completion_status']}")
        
        # 8. Show cache statistics
        print(f"\n8️⃣  Cache statistics...")
        
        all_results = await cache.list_cached_results()
        tag_counts = {}
        status_counts = {}
        
        for result_data in all_results:
            # Count tags
            for tag in result_data.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            # Count statuses
            status = result_data["result"]["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print(f"   📊 Total cached results: {len(all_results)}")
        print(f"   🏷️  Tag distribution: {tag_counts}")
        print(f"   ✅ Status distribution: {status_counts}")
        
        return True
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await cluster.stop()


async def simple_result_example():
    """Simple example of storing and retrieving results"""
    
    print("\n🔧 Simple Result Storage Example")
    print("=" * 40)
    
    cluster = GleitzeitCluster(enable_redis=True)
    await cluster.start()
    
    try:
        # Create workflow
        workflow = cluster.create_workflow("simple_test", "Simple result test")
        task1 = workflow.add_text_task("analyze", "What is AI?", "llama3")
        task2 = workflow.add_text_task("summary", "Summarize AI", "llama3")
        
        # Execute
        result = await cluster.execute_workflow(workflow)
        
        # Store results for later use
        cache = ResultCache(redis_client=cluster.redis_client)
        await cache.store_workflow_result(
            workflow_id=workflow.id,
            workflow_result={
                "status": result.status.value,
                "results": result.results,
                "executed_at": datetime.utcnow().isoformat()
            },
            tags=["ai", "analysis"]
        )
        
        print(f"✅ Stored workflow result: {workflow.id}")
        
        # Retrieve later
        cached_result = await cache.get_workflow_result(workflow.id)
        if cached_result:
            print(f"📄 Retrieved result:")
            print(f"   Status: {cached_result['result']['status']}")
            print(f"   Results: {cached_result['result']['results']}")
            
            # Access individual task results
            task_results = cache.get_task_results(cached_result)
            for task_id, task_result in task_results.items():
                print(f"   Task {task_id}: {task_result}")
        
        return True
        
    finally:
        await cluster.stop()


async def main():
    """Run result caching demonstrations"""
    
    print("🚀 Gleitzeit Result Caching System")
    print("=" * 60)
    print()
    print("This demo shows how to:")
    print("✅ Store workflow results persistently")
    print("✅ Query results by tags and time")
    print("✅ Extract individual task outputs")
    print("✅ Export results for external processing")
    print("✅ Build data processing pipelines")
    print()
    
    # Run demos
    demos = [
        simple_result_example,
        demo_result_caching
    ]
    
    for demo in demos:
        try:
            success = await demo()
            if success:
                print(f"✅ {demo.__name__} completed successfully")
            else:
                print(f"❌ {demo.__name__} failed")
        except Exception as e:
            print(f"💥 {demo.__name__} crashed: {e}")
        print()
    
    print("=" * 60)
    print("✅ Result caching demo completed!")
    print()
    print("💡 Next steps:")
    print("1. Use ResultCache in your workflows")
    print("2. Tag results for easy organization") 
    print("3. Build data processing pipelines")
    print("4. Export results for external analysis")


if __name__ == "__main__":
    asyncio.run(main())