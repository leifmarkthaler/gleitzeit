#!/usr/bin/env python3
"""
Minimal Working Example of Gleitzeit Cluster

This demonstrates the basic API usage without requiring 
Redis or Socket.IO infrastructure.
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, ExecutorNode, NodeCapabilities, TaskType


async def main():
    """Minimal example demonstrating cluster usage"""
    
    print("🚀 Gleitzeit Cluster - Minimal Working Example")
    print("=" * 50)
    
    # 1. Initialize cluster with automatic Socket.IO server startup
    cluster = GleitzeitCluster(
        redis_url="redis://localhost:6379",
        socketio_url="http://localhost:8000",
        enable_real_execution=True,  # Try real Ollama execution, fallback to mock if unavailable
        enable_socketio=True,  # Enable Socket.IO with auto-start
        auto_start_socketio_server=True  # Automatically start Socket.IO server
    )
    
    # Start cluster (in real implementation, connects to Redis/Socket.IO)
    await cluster.start()
    
    try:
        # 2. Register some executor nodes (optional for this example)
        gpu_node = ExecutorNode(
            name="gpu-worker-1",
            host="gpu-server-1",
            capabilities=NodeCapabilities(
                supported_task_types={TaskType.TEXT_PROMPT, TaskType.VISION_TASK},
                available_models=["llama3", "llava"],
                has_gpu=True,
                cpu_cores=8,
                memory_gb=32
            )
        )
        await cluster.register_node(gpu_node)
        
        cpu_node = ExecutorNode(
            name="cpu-worker-1", 
            host="cpu-server-1",
            capabilities=NodeCapabilities(
                supported_task_types={TaskType.TEXT_PROMPT, TaskType.PYTHON_FUNCTION},
                available_models=["llama3"],
                has_gpu=False,
                cpu_cores=4,
                memory_gb=16
            )
        )
        await cluster.register_node(cpu_node)
        
        print(f"📋 Registered {len(await cluster.list_nodes())} executor nodes")
        
        # 3. Create and execute a simple workflow
        print("\n🔄 Example 1: Simple Text Analysis")
        result = await cluster.analyze_text(
            prompt="Explain the benefits of distributed computing in 2-3 sentences",
            model="llama3"
        )
        print(f"📄 Result: {result}")
        
        # 4. Create a more complex workflow with dependencies
        print("\n🔄 Example 2: Complex Workflow with Dependencies")
        workflow = cluster.create_workflow(
            name="document_analysis_pipeline",
            description="Analyze document content and generate insights"
        )
        
        # Add tasks with dependencies
        summarize_task = workflow.add_text_task(
            name="summarize_document",
            prompt="Summarize this research paper about machine learning",
            model="llama3"
        )
        
        extract_keywords_task = workflow.add_text_task(
            name="extract_keywords",
            prompt="Extract key technical terms and concepts", 
            model="llama3",
            dependencies=[summarize_task.id]  # Depends on summary
        )
        
        generate_questions_task = workflow.add_text_task(
            name="generate_questions",
            prompt="Generate 3 research questions based on the summary",
            model="llama3", 
            dependencies=[summarize_task.id]  # Also depends on summary
        )
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Result:")
        print(f"   Status: {result.status.value}")
        print(f"   Total Tasks: {result.total_tasks}")
        print(f"   Completed: {result.completed_tasks}")
        print(f"   Failed: {result.failed_tasks}")
        
        # 5. Show available models
        print("\n🔄 Example 3: Available Models")
        models = await cluster.get_available_models()
        if "available" in models:
            print(f"📋 Available models: {', '.join(models['available'][:5])}{'...' if len(models['available']) > 5 else ''}")
            print(f"🎯 Recommended text models: {', '.join(models['recommended']['text'][:3])}")
        
        # Show cluster stats
        stats = await cluster.get_cluster_stats()
        print(f"📊 Cluster Stats:")
        print(f"   Real execution: {'✅ Enabled' if stats['real_execution_enabled'] else '❌ Disabled'}")
        print(f"   Redis: {'✅ Enabled' if stats.get('redis_enabled') else '❌ Disabled'}")
        if "executor_stats" in stats:
            exec_stats = stats["executor_stats"]
            print(f"   Ollama connection: {'✅ Connected' if exec_stats['is_started'] else '❌ Disconnected'}")
        
        # 6. Show cluster status
        print("\n📊 Final Cluster Status:")
        workflows = await cluster.list_workflows()
        for workflow_info in workflows:
            print(f"   Workflow: {workflow_info['workflow_id'][:8]} - {workflow_info['status']}")
        
        nodes = await cluster.list_nodes() 
        for node in nodes:
            print(f"   Node: {node['name']} - {node['status']}")
            
    finally:
        # Clean shutdown
        await cluster.stop()
    
    print("\n✅ Minimal example completed successfully!")
    print("\n💡 Next Steps:")
    print("   1. Set up Redis and Socket.IO servers")
    print("   2. Start actual executor nodes")
    print("   3. Connect to real Ollama endpoints")
    print("   4. Build a web dashboard for monitoring")


if __name__ == "__main__":
    asyncio.run(main())