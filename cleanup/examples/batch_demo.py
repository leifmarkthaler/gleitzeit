#!/usr/bin/env python3
"""
Batch Processing Demo - Current API
Shows batch processing capabilities for handling multiple items
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow


async def basic_batch_processing():
    """Basic batch processing using async_batch_process function"""
    
    print("📦 Basic Batch Processing")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Process a list of items
        batch_task = Task(
            name="Process Items in Batch",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="async_batch_process",
                kwargs={
                    "items": ["document1.txt", "document2.txt", "document3.txt", "report.pdf"],
                    "delay": 0.3  # Simulate processing time per item
                }
            )
        )
        
        workflow = Workflow(
            name="Basic Batch Processing"
        )
        workflow.add_task(batch_task)
        
        print("🚀 Processing batch items...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Monitor progress
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(0.5)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Batch processing completed:")
            batch_result = results.get(batch_task.id, [])
            for i, item in enumerate(batch_result):
                print(f"   📄 Item {i+1}: {item}")
        else:
            print(f"❌ Batch processing failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def text_analysis_batch():
    """Batch text analysis workflow"""
    
    print("\n📝 Text Analysis Batch Workflow")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Sample texts to analyze
        texts = [
            "The quick brown fox jumps over the lazy dog",
            "Artificial intelligence is transforming our world rapidly",
            "Machine learning algorithms require large datasets to train effectively",
            "Climate change presents significant challenges for future generations"
        ]
        
        # Create individual text analysis tasks
        analysis_tasks = []
        for i, text in enumerate(texts):
            # Word count task
            word_count_task = Task(
                id=f"words_{i}",
                name=f"Count Words - Text {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="count_words",
                    kwargs={"text": text}
                )
            )
            
            # Keyword extraction task
            keywords_task = Task(
                id=f"keywords_{i}",
                name=f"Extract Keywords - Text {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="extract_keywords",
                    kwargs={
                        "text": text,
                        "max_keywords": 3
                    }
                )
            )
            
            analysis_tasks.extend([word_count_task, keywords_task])
        
        # Summary task that processes all results
        summary_task = Task(
            id="summary",
            name="Summarize Batch Results",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="""Analyze these text processing results and provide a summary:

Text 1 - Words: {{words_0.result}}, Keywords: {{keywords_0.result}}
Text 2 - Words: {{words_1.result}}, Keywords: {{keywords_1.result}}  
Text 3 - Words: {{words_2.result}}, Keywords: {{keywords_2.result}}
Text 4 - Words: {{words_3.result}}, Keywords: {{keywords_3.result}}

Provide insights about the text collection.""",
                model_name="llama3"
            ),
            dependencies=[f"words_{i}" for i in range(4)] + [f"keywords_{i}" for i in range(4)]
        )
        
        all_tasks = analysis_tasks + [summary_task]
        
        workflow = Workflow(
            name="Batch Text Analysis",
            description="Analyze multiple texts in parallel"
        )
        for task in all_tasks:
            workflow.add_task(task)
        
        print(f"🚀 Analyzing {len(texts)} texts in batch...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Monitor progress with task completion tracking
        completed = set()
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            
            # Show progress
            current_completed = set(status.get("completed_tasks", []))
            new_completed = current_completed - completed
            
            for task_id in new_completed:
                if task_id.startswith("words_"):
                    text_num = int(task_id.split("_")[1]) + 1
                    print(f"   ✅ Word count completed for text {text_num}")
                elif task_id.startswith("keywords_"):
                    text_num = int(task_id.split("_")[1]) + 1
                    print(f"   ✅ Keywords extracted for text {text_num}")
            
            completed = current_completed
            
            if status["status"] in ["completed", "failed"]:
                break
            
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("\n📊 Batch Analysis Results:")
            
            for i in range(len(texts)):
                word_count = results.get(f"words_{i}", 0)
                keywords = results.get(f"keywords_{i}", [])
                print(f"   📄 Text {i+1}: {word_count} words, keywords: {keywords}")
            
            summary = results.get("summary", "No summary available")
            print(f"\n   📋 Summary: {summary}")
        else:
            print(f"❌ Batch analysis failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def data_processing_batch():
    """Batch data processing workflow"""
    
    print("\n📊 Data Processing Batch Workflow")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Sample datasets
        datasets = [
            [12, 25, 18, 31, 7, 44, 22],
            [88, 15, 92, 33, 67, 41, 55],
            [3, 19, 28, 8, 45, 16, 39],
            [77, 24, 61, 35, 12, 48, 29]
        ]
        
        # Create analysis tasks for each dataset
        analysis_tasks = []
        for i, dataset in enumerate(datasets):
            analyze_task = Task(
                id=f"analyze_{i}",
                name=f"Analyze Dataset {i+1}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name="analyze_numbers",
                    kwargs={"numbers": dataset}
                )
            )
            analysis_tasks.append(analyze_task)
        
        # Aggregate all results
        aggregate_task = Task(
            id="aggregate_all",
            name="Aggregate All Datasets",
            task_type=TaskType.FUNCTION,
            parameters=TaskParameters(
                function_name="aggregate",
                kwargs={
                    "data": [item for dataset in datasets for item in dataset],
                    "operation": "statistics"
                }
            )
        )
        
        workflow = Workflow(
            name="Batch Data Processing",
            description="Process multiple datasets in parallel"
        )
        for task in analysis_tasks + [aggregate_task]:
            workflow.add_task(task)
        
        print(f"🚀 Processing {len(datasets)} datasets...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Monitor progress
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(1)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Batch data processing completed:")
            
            for i in range(len(datasets)):
                analysis = results.get(f"analyze_{i}", {})
                if isinstance(analysis, dict):
                    avg = analysis.get("average", 0)
                    count = analysis.get("count", 0)
                    print(f"   📈 Dataset {i+1}: {count} items, avg={avg:.1f}")
            
            aggregate = results.get("aggregate_all", {})
            print(f"\n   📊 Combined statistics: {aggregate}")
        else:
            print(f"❌ Batch processing failed: {status.get('error')}")
    
    finally:
        await cluster.stop()


async def main():
    """Run all batch processing demos"""
    
    print("🔄 Gleitzeit Batch Processing Demonstration")
    print("=" * 60)
    
    # Run batch processing demos
    await basic_batch_processing()
    await text_analysis_batch()
    await data_processing_batch()
    
    print("\n✅ All batch processing demos completed!")
    print("\n💡 Key Batch Processing Features:")
    print("   ✅ Built-in async_batch_process function")
    print("   ✅ Parallel task execution within workflows")
    print("   ✅ Bulk text analysis and data processing")
    print("   ✅ Progress monitoring for batch operations")
    print("   ✅ Automatic result aggregation")
    print("\n🔍 Try with CLI: gleitzeit run --function async_batch_process --args items='[\"item1\",\"item2\"]' delay=0.5")


if __name__ == "__main__":
    asyncio.run(main())