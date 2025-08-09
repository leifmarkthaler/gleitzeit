#!/usr/bin/env python3
"""
Decorator Example - Simple way to create Gleitzeit tasks

Shows how to use @gleitzeit_task decorator to easily register Python functions
as tasks that can be orchestrated alongside LLM tasks.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task, start_task_service


# ===========================================
# Define your tasks with simple decorators
# ===========================================

@gleitzeit_task(category="data")
def preprocess_text(text: str) -> dict:
    """Clean and prepare text for LLM processing"""
    cleaned = text.strip().lower()
    word_count = len(cleaned.split())
    return {
        "original": text,
        "cleaned": cleaned,
        "word_count": word_count
    }


@gleitzeit_task(category="analysis")
async def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment of text (mock implementation)"""
    # In real implementation, might call an API or model
    await asyncio.sleep(0.1)  # Simulate processing
    
    positive_words = ["good", "great", "excellent", "amazing", "wonderful"]
    negative_words = ["bad", "terrible", "awful", "horrible", "poor"]
    
    text_lower = text.lower()
    positive_score = sum(1 for word in positive_words if word in text_lower)
    negative_score = sum(1 for word in negative_words if word in text_lower)
    
    return {
        "text": text,
        "positive_score": positive_score,
        "negative_score": negative_score,
        "sentiment": "positive" if positive_score > negative_score else "negative" if negative_score > 0 else "neutral"
    }


@gleitzeit_task(category="formatting")
def format_results(preprocessing_result: dict, llm_result: str, sentiment: dict) -> str:
    """Format all results into a report"""
    report = f"""
    Analysis Report
    ===============
    
    Input Statistics:
    - Word Count: {preprocessing_result['word_count']}
    
    LLM Analysis:
    {llm_result}
    
    Sentiment Analysis:
    - Sentiment: {sentiment['sentiment']}
    - Positive Score: {sentiment['positive_score']}
    - Negative Score: {sentiment['negative_score']}
    """
    return report


# ===========================================
# Main workflow combining Python tasks with LLM tasks
# ===========================================

async def main():
    """
    Example workflow showing:
    1. Python task (preprocessing)
    2. LLM task (text generation)
    3. Python task (sentiment analysis)
    4. Python task (formatting)
    
    All orchestrated through Gleitzeit with clean separation of concerns.
    """
    
    # Sample input
    input_text = "This is a GREAT example of how Gleitzeit makes workflow orchestration simple!"
    
    print("🚀 Decorator-Based Task Example")
    print("=" * 50)
    print(f"Input: {input_text}")
    print()
    
    # Start the task service (registers all decorated functions)
    print("📌 Starting task service...")
    task_service = asyncio.create_task(start_task_service(
        service_name="My Python Tasks",
        auto_discover=False  # We've already defined our tasks
    ))
    
    # Give service time to start
    await asyncio.sleep(2)
    
    # Create Gleitzeit cluster
    print("🏗️ Creating workflow...")
    cluster = GleitzeitCluster(
        enable_redis=False,  # Simplified for demo
        enable_socketio=True,
        auto_start_socketio_server=True
    )
    
    await cluster.start()
    
    # Create workflow
    workflow = cluster.create_workflow("Text Analysis Pipeline")
    
    # Add Python preprocessing task
    preprocess = workflow.add_external_task(
        name="Preprocess Text",
        external_task_type="python_execution", 
        service_name="My Python Tasks",
        external_parameters={
            "function_name": "preprocess_text",
            "args": [input_text],
            "kwargs": {}
        }
    )
    
    # Add LLM task that uses preprocessing result
    llm_analysis = workflow.add_text_task(
        name="LLM Analysis",
        prompt=f"Analyze this text and provide insights: {{{{Preprocess Text.result.cleaned}}}}",
        model="llama3",
        dependencies=["Preprocess Text"]
    )
    
    # Add sentiment analysis task (async Python function)
    sentiment = workflow.add_external_task(
        name="Sentiment Analysis",
        external_task_type="python_execution",
        service_name="My Python Tasks", 
        external_parameters={
            "function_name": "analyze_sentiment",
            "args": ["{{Preprocess Text.result.original}}"],
            "kwargs": {}
        },
        dependencies=["Preprocess Text"]
    )
    
    # Add formatting task that combines all results
    report = workflow.add_external_task(
        name="Generate Report",
        external_task_type="python_execution",
        service_name="My Python Tasks",
        external_parameters={
            "function_name": "format_results",
            "args": [
                "{{Preprocess Text.result}}",
                "{{LLM Analysis.result}}",
                "{{Sentiment Analysis.result}}"
            ],
            "kwargs": {}
        },
        dependencies=["Preprocess Text", "LLM Analysis", "Sentiment Analysis"]
    )
    
    print(f"📋 Workflow has {len(workflow.tasks)} tasks:")
    for task in workflow.tasks.values():
        deps = f" (depends on: {', '.join(task.dependencies)})" if task.dependencies else ""
        print(f"   - {task.name}{deps}")
    print()
    
    # Submit workflow
    print("▶️ Executing workflow...")
    workflow_id = await cluster.submit_workflow(workflow)
    
    # Wait for completion
    result = await cluster.wait_for_workflow(workflow_id, timeout=60)
    
    if result.status.value == "completed":
        print("✅ Workflow completed successfully!")
        print("\n📊 Final Report:")
        print(result.results.get("Generate Report", "No report generated"))
    else:
        print(f"❌ Workflow failed: {result.status}")
        
    # Cleanup
    await cluster.stop()


if __name__ == "__main__":
    print("""
    This example demonstrates:
    
    1. 🎯 Simple decorator-based task definition
    2. 🔗 Seamless integration of Python and LLM tasks
    3. 📊 Clean orchestration through Socket.IO
    4. 🚀 Focus on LLM workflow orchestration
    
    The architecture is simplified:
    - LLM tasks execute on managed endpoints
    - Python tasks execute via Socket.IO services
    - Clean separation of concerns
    - No backwards compatibility complexity
    """)
    
    asyncio.run(main())