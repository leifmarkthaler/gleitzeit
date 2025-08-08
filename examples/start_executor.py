#!/usr/bin/env python3
"""
Start Executor Node

Simple script to start executor nodes that connect to the cluster
and execute tasks assigned to them.

Usage:
    # Start single executor
    python examples/start_executor.py
    
    # Start with custom name
    python examples/start_executor.py --name gpu-worker-1
    
    # Start multiple executors (in separate terminals)
    python examples/start_executor.py --name worker-1
    python examples/start_executor.py --name worker-2 --tasks 5
    python examples/start_executor.py --name worker-3 --tasks 2
"""

import asyncio
import sys
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.execution.executor_node import GleitzeitExecutorNode
from gleitzeit_cluster.core.node import NodeCapabilities
from gleitzeit_cluster.core.task import TaskType


async def start_simple_executor():
    """Start a simple executor node"""
    
    print("🚀 Gleitzeit Executor Node")
    print("=" * 40)
    
    # Create executor node with default capabilities
    executor = GleitzeitExecutorNode(
        name="simple-executor",
        cluster_url="http://localhost:8000",
        max_concurrent_tasks=3
    )
    
    print("🖥️  Starting executor node...")
    print("   Connect to cluster and wait for tasks")
    print("   Press Ctrl+C to stop")
    print()
    
    try:
        await executor.start()
    except KeyboardInterrupt:
        print("\n🛑 Stopping executor...")
    finally:
        await executor.stop()


async def start_gpu_executor():
    """Start a GPU-enabled executor node"""
    
    print("🚀 Gleitzeit GPU Executor Node")  
    print("=" * 40)
    
    # Create GPU-capable executor
    gpu_capabilities = NodeCapabilities(
        supported_task_types={
            TaskType.TEXT_PROMPT,
            TaskType.VISION_TASK,
            TaskType.PYTHON_FUNCTION
        },
        available_models=["llama3", "llava", "codellama", "mistral"],
        max_concurrent_tasks=2,  # Lower for GPU tasks
        has_gpu=True,
        gpu_memory_gb=8.0,
        cpu_cores=8,
        memory_gb=16.0,
        tags={"gpu", "vision", "llm"}
    )
    
    executor = GleitzeitExecutorNode(
        name="gpu-executor-1",
        cluster_url="http://localhost:8000",
        capabilities=gpu_capabilities
    )
    
    print("🎮 GPU executor ready for vision and LLM tasks")
    print("   Press Ctrl+C to stop")
    print()
    
    try:
        await executor.start()
    except KeyboardInterrupt:
        print("\n🛑 Stopping GPU executor...")
    finally:
        await executor.stop()


async def start_cpu_executor():
    """Start a CPU-only executor node"""
    
    print("🚀 Gleitzeit CPU Executor Node")
    print("=" * 40)
    
    # Create CPU-only executor
    cpu_capabilities = NodeCapabilities(
        supported_task_types={
            TaskType.TEXT_PROMPT,
            TaskType.PYTHON_FUNCTION,
            TaskType.HTTP_REQUEST,
            TaskType.FILE_OPERATION
        },
        available_models=["llama3", "codellama"],
        max_concurrent_tasks=5,  # Higher for CPU tasks
        has_gpu=False,
        cpu_cores=4,
        memory_gb=8.0,
        tags={"cpu", "text", "code"}
    )
    
    executor = GleitzeitExecutorNode(
        name="cpu-executor-1",
        cluster_url="http://localhost:8000", 
        capabilities=cpu_capabilities
    )
    
    print("💻 CPU executor ready for text and code tasks")
    print("   Press Ctrl+C to stop")
    print()
    
    try:
        await executor.start()
    except KeyboardInterrupt:
        print("\n🛑 Stopping CPU executor...")
    finally:
        await executor.stop()


async def start_custom_executor():
    """Start executor with command line arguments"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit Executor Node")
    parser.add_argument("--name", default="executor-1", help="Node name")
    parser.add_argument("--cluster", default="http://localhost:8000", help="Cluster URL")  
    parser.add_argument("--tasks", type=int, default=3, help="Max concurrent tasks")
    parser.add_argument("--heartbeat", type=int, default=30, help="Heartbeat interval")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU capabilities")
    parser.add_argument("--models", nargs="+", default=["llama3"], help="Available models")
    
    args = parser.parse_args()
    
    # Build capabilities based on arguments
    task_types = {TaskType.TEXT_PROMPT, TaskType.PYTHON_FUNCTION}
    if args.gpu:
        task_types.add(TaskType.VISION_TASK)
    
    capabilities = NodeCapabilities(
        supported_task_types=task_types,
        available_models=args.models,
        max_concurrent_tasks=args.tasks,
        has_gpu=args.gpu
    )
    
    print(f"🚀 Gleitzeit Executor Node: {args.name}")
    print("=" * 40)
    print(f"   Cluster: {args.cluster}")
    print(f"   Max tasks: {args.tasks}")
    print(f"   GPU: {'✅ Enabled' if args.gpu else '❌ Disabled'}")
    print(f"   Models: {', '.join(args.models)}")
    print()
    
    executor = GleitzeitExecutorNode(
        name=args.name,
        cluster_url=args.cluster,
        capabilities=capabilities,
        heartbeat_interval=args.heartbeat,
        max_concurrent_tasks=args.tasks
    )
    
    try:
        await executor.start()
    except KeyboardInterrupt:
        print(f"\n🛑 Stopping {args.name}...")
    finally:
        await executor.stop()


async def main():
    """Main entry point - choose executor type"""
    
    if len(sys.argv) > 1:
        # Use command line arguments
        await start_custom_executor()
    else:
        # Interactive menu
        print("🚀 Gleitzeit Executor Node Launcher")
        print("=" * 50)
        print()
        print("Choose executor type:")
        print("1. Simple executor (default)")
        print("2. GPU executor (vision + LLM tasks)")
        print("3. CPU executor (text + code tasks)")
        print("4. Custom (with arguments)")
        print()
        
        choice = input("Enter choice (1-4) [1]: ").strip() or "1"
        print()
        
        if choice == "1":
            await start_simple_executor()
        elif choice == "2":
            await start_gpu_executor()
        elif choice == "3":
            await start_cpu_executor()
        elif choice == "4":
            print("Run with arguments:")
            print("python examples/start_executor.py --name my-executor --tasks 5 --gpu")
        else:
            print("❌ Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())