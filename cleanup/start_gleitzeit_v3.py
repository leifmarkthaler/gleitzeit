#!/usr/bin/env python3
"""
Start Gleitzeit V3 System

This starts all the components needed for V3:
1. Central Socket.IO server
2. Providers (MCP, Ollama, etc.)
3. Workflow engine
4. CLI interface for adding tasks
"""

import asyncio
import argparse
import logging
import sys
import json
from typing import Optional
from pathlib import Path

from gleitzeit_v3.server.central_server import CentralServer
from gleitzeit_v3.core.workflow_engine_client import WorkflowEngineClient
from gleitzeit_v3.core.models import Workflow, Task, TaskParameters
from gleitzeit_v3.providers.ollama_provider import OllamaProvider
from test_gleitzeit_v3_mcp import RealMCPProvider

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GleitzeitV3System:
    """Main V3 system orchestrator"""
    
    def __init__(self):
        self.server = None
        self.server_task = None
        self.workflow_engine = None
        self.providers = []
        self.running = False
    
    async def start(self, enable_ollama=True, enable_mcp=True):
        """Start all V3 components"""
        print("🚀 Starting Gleitzeit V3...")
        
        # 1. Start central server
        print("📡 Starting central server...")
        self.server = CentralServer(host="localhost", port=8000)
        self.server_task = asyncio.create_task(self.server.start())
        await asyncio.sleep(2)
        
        # 2. Start providers
        if enable_mcp:
            print("🔧 Starting MCP provider...")
            mcp_provider = RealMCPProvider(server_url="http://localhost:8000")
            try:
                await mcp_provider.start()
                self.providers.append(mcp_provider)
                print(f"   ✅ MCP provider ready")
            except Exception as e:
                print(f"   ⚠️ MCP provider failed: {e}")
        
        if enable_ollama:
            print("🤖 Starting Ollama provider...")
            ollama_provider = OllamaProvider(server_url="http://localhost:8000")
            try:
                await ollama_provider.start()
                self.providers.append(ollama_provider)
                print(f"   ✅ Ollama provider ready ({len(ollama_provider.available_models)} models)")
            except Exception as e:
                print(f"   ⚠️ Ollama provider failed: {e}")
        
        # 3. Start workflow engine
        print("⚙️ Starting workflow engine...")
        self.workflow_engine = WorkflowEngineClient(
            engine_id="main_engine",
            server_url="http://localhost:8000"
        )
        await self.workflow_engine.start()
        
        self.running = True
        print("\n✅ Gleitzeit V3 is ready!")
        print("   Server: http://localhost:8000")
        print(f"   Providers: {len(self.providers)}")
        print("\n📝 You can now add tasks. Examples:")
        print('   python start_gleitzeit_v3.py add-task "List files in current directory"')
        print('   python start_gleitzeit_v3.py add-task "Write a poem about distributed systems"')
        print("\n")
    
    async def stop(self):
        """Stop all components"""
        print("\n🛑 Stopping Gleitzeit V3...")
        
        if self.workflow_engine:
            await self.workflow_engine.stop()
        
        for provider in self.providers:
            if hasattr(provider, '_running') and provider._running:
                await provider.stop()
        
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        
        self.running = False
        print("✅ Gleitzeit V3 stopped")
    
    async def add_task(self, task_description: str, function: str = None):
        """Add a task to the system"""
        if not self.running:
            print("❌ System not running. Start it first with 'start' command")
            return
        
        # Determine function type from description if not specified
        if not function:
            desc_lower = task_description.lower()
            if any(word in desc_lower for word in ['list', 'file', 'directory', 'folder', 'read']):
                function = "list_files"
                params = {
                    "function": "list_files",
                    "arguments": {"path": "."}
                }
            elif any(word in desc_lower for word in ['image', 'picture', 'photo', 'visual', 'see']):
                function = "vision"
                params = {
                    "function": "vision",
                    "prompt": task_description,
                    "model": "llava:latest",
                    "image_path": "/tmp/gleitzeit_test_diagram.png"  # Would need actual image
                }
            else:
                # Default to LLM generation
                function = "generate"
                params = {
                    "function": "generate",
                    "prompt": task_description,
                    "model": "llama3.2:latest",
                    "temperature": 0.7,
                    "max_tokens": 500
                }
        
        # Create task
        task = Task(
            name=task_description[:50],  # Truncate for name
            parameters=TaskParameters(data=params)
        )
        
        # Create workflow
        workflow = Workflow(
            name=f"Quick Task: {task_description[:30]}",
            description=task_description
        )
        workflow.add_task(task)
        
        # Submit workflow
        print(f"📋 Adding task: {task_description}")
        workflow_id = await self.workflow_engine.submit_workflow(workflow)
        print(f"✅ Task submitted (ID: {workflow_id[:8]}...)")
        
        # Monitor execution
        print("⏳ Executing...")
        max_wait = 30
        for i in range(max_wait):
            await asyncio.sleep(1)
            
            if workflow_id in self.workflow_engine.workflows:
                wf = self.workflow_engine.workflows[workflow_id]
                if wf.status.value in ["completed", "failed"]:
                    break
                
                if i % 5 == 0 and i > 0:
                    print(f"   Still working... ({i}s)")
        
        # Show result
        if workflow_id in self.workflow_engine.workflows:
            wf = self.workflow_engine.workflows[workflow_id]
            if wf.status.value == "completed":
                print(f"✅ Task completed!")
                if task.id in wf.task_results:
                    result = wf.task_results[task.id]
                    print("\n📊 Result:")
                    if isinstance(result, str):
                        lines = result.split('\n')
                        for line in lines[:10]:
                            print(f"   {line}")
                        if len(lines) > 10:
                            print(f"   ... ({len(lines) - 10} more lines)")
                    else:
                        print(f"   {str(result)[:500]}")
            else:
                print(f"❌ Task failed: {wf.status.value}")


async def run_system():
    """Run the V3 system continuously"""
    system = GleitzeitV3System()
    
    try:
        await system.start()
        
        print("System running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(60)
            
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        await system.stop()


async def run_task(task_description: str):
    """Run a single task"""
    system = GleitzeitV3System()
    
    try:
        await system.start()
        await system.add_task(task_description)
        
    finally:
        await system.stop()


def main():
    parser = argparse.ArgumentParser(description="Gleitzeit V3 System")
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start the V3 system')
    start_parser.add_argument('--no-ollama', action='store_true', help='Disable Ollama provider')
    start_parser.add_argument('--no-mcp', action='store_true', help='Disable MCP provider')
    
    # Add task command
    task_parser = subparsers.add_parser('add-task', help='Add a task')
    task_parser.add_argument('description', help='Task description')
    task_parser.add_argument('--function', choices=['generate', 'list_files', 'vision'], 
                             help='Function type')
    
    args = parser.parse_args()
    
    if not args.command:
        # Default: start the system
        asyncio.run(run_system())
    elif args.command == 'start':
        asyncio.run(run_system())
    elif args.command == 'add-task':
        asyncio.run(run_task(args.description))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()