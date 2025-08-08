#!/usr/bin/env python3
"""
Development mode for Gleitzeit

Starts all components needed for local development in a single command.
"""

import asyncio
import signal
import sys
from typing import List, Optional

from .core.cluster import GleitzeitCluster
from .execution.executor_node import GleitzeitExecutorNode
from .scheduler.scheduler_node import GleitzeitScheduler, SchedulingPolicy
from .core.node import NodeCapabilities
from .core.task import TaskType


class GleitzeitDevEnvironment:
    """Manages all components for development"""
    
    def __init__(
        self,
        cluster_port: int = 8000,
        enable_redis: bool = False,
        enable_scheduler: bool = True,
        enable_executor: bool = True,
        executor_count: int = 1
    ):
        self.cluster_port = cluster_port
        self.enable_redis = enable_redis
        self.enable_scheduler = enable_scheduler
        self.enable_executor = enable_executor
        self.executor_count = executor_count
        
        self.cluster: Optional[GleitzeitCluster] = None
        self.scheduler: Optional[GleitzeitScheduler] = None
        self.executors: List[GleitzeitExecutorNode] = []
        self.running = False
    
    async def start(self):
        """Start all components"""
        print("🚀 Starting Gleitzeit Development Environment")
        print("=" * 50)
        
        # Start cluster
        print("📡 Starting cluster service...")
        self.cluster = GleitzeitCluster(
            redis_url="redis://localhost:6379" if self.enable_redis else None,
            enable_real_execution=False,
            enable_redis=self.enable_redis,
            enable_socketio=True,
            auto_start_socketio_server=True,
            socketio_host="localhost",
            socketio_port=self.cluster_port
        )
        await self.cluster.start()
        
        base_url = f"http://localhost:{self.cluster_port}"
        print(f"✅ Cluster running at {base_url}")
        
        # Short delay to ensure cluster is ready
        await asyncio.sleep(1)
        
        # Start scheduler
        if self.enable_scheduler:
            print("🗓️  Starting scheduler...")
            self.scheduler = GleitzeitScheduler(
                name="dev-scheduler",
                cluster_url=base_url,
                policy=SchedulingPolicy.LEAST_LOADED
            )
            scheduler_task = asyncio.create_task(self.scheduler.start())
            print("✅ Scheduler started")
        
        # Start executors
        if self.enable_executor:
            for i in range(self.executor_count):
                print(f"⚙️  Starting executor {i+1}/{self.executor_count}...")
                
                capabilities = NodeCapabilities(
                    supported_task_types=[
                        TaskType.FUNCTION,
                        TaskType.TEXT,
                        TaskType.VISION,
                    ],
                    available_models=["llama3", "codellama", "llava"],
                    max_concurrent_tasks=3,
                    has_gpu=False,
                    memory_limit_gb=8.0
                )
                
                executor = GleitzeitExecutorNode(
                    name=f"dev-executor-{i+1}",
                    cluster_url=base_url,
                    capabilities=capabilities,
                    heartbeat_interval=30,
                    max_concurrent_tasks=3
                )
                
                self.executors.append(executor)
                executor_task = asyncio.create_task(executor.start())
                print(f"✅ Executor {i+1} started")
        
        self.running = True
        
        # Print summary
        print()
        print("🎉 Development environment ready!")
        print("=" * 50)
        print(f"🌐 Dashboard: {base_url}")
        print(f"📊 Metrics: {base_url}/metrics")
        print(f"🔌 Socket.IO: {base_url}")
        print()
        print("📚 Quick start:")
        print(f"   gleitzeit run --function fibonacci --args n=10")
        print(f"   gleitzeit run --text 'Write a poem'")
        print(f"   gleitzeit functions list")
        print()
        print("Press Ctrl+C to stop all services")
        print("=" * 50)
    
    async def stop(self):
        """Stop all components gracefully"""
        print("\n🛑 Stopping development environment...")
        self.running = False
        
        # Stop executors
        for executor in self.executors:
            try:
                await executor.stop()
            except Exception as e:
                print(f"Error stopping executor: {e}")
        
        # Stop scheduler
        if self.scheduler:
            try:
                await self.scheduler.stop()
            except Exception as e:
                print(f"Error stopping scheduler: {e}")
        
        # Stop cluster
        if self.cluster:
            try:
                await self.cluster.stop()
            except Exception as e:
                print(f"Error stopping cluster: {e}")
        
        print("✅ All services stopped")
    
    async def run(self):
        """Run the development environment"""
        await self.start()
        
        # Keep running until interrupted
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


async def dev_command_handler(args):
    """Handle the dev command from CLI"""
    
    env = GleitzeitDevEnvironment(
        cluster_port=args.port,
        enable_redis=not args.no_redis,
        enable_scheduler=not args.no_scheduler,
        enable_executor=not args.no_executor,
        executor_count=args.executors
    )
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}")
        env.running = False
        # Create task to stop in the event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(env.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await env.run()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Development environment failed: {e}")
        raise