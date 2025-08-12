"""
Gleitzeit V3 Demo

Demonstrates the event-driven architecture with:
- Real-time event visualization
- Automatic health monitoring
- Event-driven parameter substitution
- Comprehensive audit trails
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, Any

from gleitzeit_v3.events.bus import EventBus, EventFilter
from gleitzeit_v3.events.store import InMemoryEventStore
from gleitzeit_v3.events.schemas import EventType, EventSeverity
from gleitzeit_v3.core.workflow_engine import EventDrivenWorkflowEngine
from gleitzeit_v3.core.models import Workflow, Task, TaskParameters
from gleitzeit_v3.providers.base import BaseProvider

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MockLLMProvider(BaseProvider):
    """Mock LLM provider for demonstration"""
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        super().__init__(
            provider_id="mock_llm_provider",
            provider_name="Mock LLM Provider",
            provider_type="llm",
            supported_functions=["generate", "chat"],
            server_url=server_url,
            max_concurrent_tasks=3
        )
    
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """Mock LLM task execution"""
        await asyncio.sleep(2)  # Simulate processing time
        
        function = parameters.get("function", "unknown")
        if function == "generate":
            prompt = parameters.get("prompt", "No prompt provided")
            return f"Mock LLM response to: {prompt[:100]}..."
        elif function == "chat":
            messages = parameters.get("messages", [])
            return f"Mock chat response based on {len(messages)} messages"
        else:
            raise ValueError(f"Unsupported function: {function}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Mock health check"""
        return {
            "healthy": True,
            "score": 0.95,
            "details": {
                "model_loaded": True,
                "gpu_memory": "2.1GB/8GB",
                "response_time": "1.2s"
            }
        }


class MockMCPProvider(BaseProvider):
    """Mock MCP provider for demonstration"""
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        super().__init__(
            provider_id="mock_mcp_provider",
            provider_name="Mock MCP Provider",
            provider_type="mcp",
            supported_functions=["list_files", "get_weather"],
            server_url=server_url,
            max_concurrent_tasks=5
        )
    
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """Mock MCP task execution"""
        await asyncio.sleep(1)  # Simulate processing time
        
        function_name = parameters.get("function", "unknown")
        if function_name == "list_files":
            return {
                "files": ["demo.txt", "example.py", "data.json"],
                "total": 3,
                "path": parameters.get("path", "/demo")
            }
        elif function_name == "get_weather":
            return {
                "temperature": 22,
                "condition": "sunny",
                "location": parameters.get("location", "demo city")
            }
        else:
            return f"Mock result from function: {function_name}"
    
    async def health_check(self) -> Dict[str, Any]:
        """Mock health check"""
        return {
            "healthy": True,
            "score": 0.98,
            "details": {
                "mcp_server_connected": True,
                "functions_available": 5,
                "last_ping": "12ms"
            }
        }


class EventMonitor:
    """Monitor and display events in real-time"""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.event_count = 0
        self.events_by_type = {}
    
    async def start_monitoring(self):
        """Start monitoring all events"""
        self.event_bus.subscribe(
            self._handle_event,
            EventFilter()  # Monitor all events
        )
        logger.info("🔍 Event monitoring started")
    
    async def _handle_event(self, event):
        """Handle and display events"""
        self.event_count += 1
        
        event_type = event.event_type.value
        if event_type not in self.events_by_type:
            self.events_by_type[event_type] = 0
        self.events_by_type[event_type] += 1
        
        # Display interesting events
        if event.severity in [EventSeverity.WARNING, EventSeverity.ERROR]:
            print(f"🚨 {event.event_type.value}: {event.payload}")
        elif event.event_type in [
            EventType.WORKFLOW_SUBMITTED,
            EventType.WORKFLOW_COMPLETED,
            EventType.TASK_READY,
            EventType.TASK_COMPLETED,
            EventType.PROVIDER_REGISTERED,
            EventType.ASSIGNMENT_APPROVED
        ]:
            print(f"📊 {event.event_type.value}: {self._format_payload(event.payload)}")
    
    def _format_payload(self, payload: Dict[str, Any]) -> str:
        """Format payload for display"""
        if "workflow_id" in payload:
            wid = payload["workflow_id"][:8]
            return f"workflow={wid}..."
        elif "task_id" in payload:
            tid = payload["task_id"][:8]
            return f"task={tid}..."
        elif "provider_id" in payload:
            pid = payload["provider_id"]
            return f"provider={pid}"
        else:
            return str(payload)[:50] + "..." if len(str(payload)) > 50 else str(payload)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        return {
            "total_events": self.event_count,
            "events_by_type": self.events_by_type,
            "top_events": sorted(
                self.events_by_type.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5]
        }


async def create_demo_workflow() -> Workflow:
    """Create a demo workflow with MCP -> LLM dependency"""
    
    # Create tasks
    mcp_task = Task(
        name="Get File List",
        parameters=TaskParameters(data={
            "function": "list_files",
            "path": "/demo/project"
        })
    )
    
    llm_task = Task(
        name="Analyze Files",
        parameters=TaskParameters(data={
            "function": "generate",
            "prompt": "Based on the following file list, analyze the project structure: ${task_" + mcp_task.id + "_result}",
            "max_tokens": 200
        }),
        dependencies=[mcp_task.id]
    )
    
    # Create workflow
    workflow = Workflow(
        name="Demo File Analysis Workflow",
        description="Demonstrates MCP -> LLM workflow with parameter substitution"
    )
    
    workflow.add_task(mcp_task)
    workflow.add_task(llm_task)
    
    return workflow


async def main():
    """Run the Gleitzeit V3 demo"""
    print("🚀 Starting Gleitzeit V3 Demo")
    print("=" * 50)
    
    try:
        # Create event store
        event_store = InMemoryEventStore(max_events=1000)
        
        # Create event bus (mock - no actual Socket.IO)
        event_bus = EventBus(
            component_id="demo_system",
            socketio_url="mock://demo",
            event_store=event_store,
            enable_persistence=True
        )
        
        # Mock the connection for demo
        event_bus.connected = True
        event_bus.registered = True
        
        # Create event monitor
        monitor = EventMonitor(event_bus)
        await monitor.start_monitoring()
        
        # Create workflow engine
        workflow_engine = EventDrivenWorkflowEngine(
            component_id="demo_workflow_engine",
            event_bus=event_bus
        )
        await workflow_engine.start()
        
        # Create providers
        llm_provider = MockLLMProvider(event_bus)
        mcp_provider = MockMCPProvider(event_bus)
        
        await llm_provider.start()
        await mcp_provider.start()
        
        print("\n📋 System Status:")
        print(f"  Workflow Engine: ✅ Running")
        print(f"  LLM Provider: ✅ Running")
        print(f"  MCP Provider: ✅ Running")
        print(f"  Event Monitor: ✅ Running")
        
        # Wait for providers to register
        await asyncio.sleep(2)
        
        # Create and submit demo workflow
        print("\n🔄 Creating demo workflow...")
        demo_workflow = await create_demo_workflow()
        
        print(f"  Workflow: {demo_workflow.name}")
        print(f"  Tasks: {len(demo_workflow.tasks)}")
        print(f"    1. {demo_workflow.tasks[0].name} ({demo_workflow.tasks[0].task_type.value})")
        print(f"    2. {demo_workflow.tasks[1].name} ({demo_workflow.tasks[1].task_type.value}) [depends on 1]")
        
        # Submit workflow
        print("\n📤 Submitting workflow...")
        workflow_id = await workflow_engine.submit_workflow(demo_workflow)
        
        # Monitor execution
        print("\n🔍 Monitoring execution...")
        print("Events will be displayed as they occur:")
        print("-" * 40)
        
        # Wait for completion
        max_wait = 30  # seconds
        wait_time = 0
        check_interval = 1
        
        while wait_time < max_wait:
            await asyncio.sleep(check_interval)
            wait_time += check_interval
            
            # Check if workflow is complete
            if workflow_id in workflow_engine.workflows:
                workflow = workflow_engine.workflows[workflow_id]
                if workflow.status.value in ["completed", "failed", "cancelled"]:
                    break
            
            # Show progress every 5 seconds
            if wait_time % 5 == 0:
                stats = workflow_engine.get_stats()
                print(f"⏱️  Status: {stats['running_tasks']} running, {stats['ready_tasks']} ready")
        
        print("-" * 40)
        
        # Show final results
        print("\n📊 Final Results:")
        if workflow_id in workflow_engine.workflows:
            final_workflow = workflow_engine.workflows[workflow_id]
            print(f"  Workflow Status: {final_workflow.status.value}")
            print(f"  Completed Tasks: {len(final_workflow.completed_tasks)}")
            print(f"  Failed Tasks: {len(final_workflow.failed_tasks)}")
            
            if final_workflow.task_results:
                print("\n  Task Results:")
                for task_id, result in final_workflow.task_results.items():
                    task_name = next(
                        (t.name for t in final_workflow.tasks if t.id == task_id),
                        f"Task {task_id[:8]}"
                    )
                    print(f"    {task_name}: {str(result)[:100]}...")
        
        # Show system metrics
        print("\n📈 System Metrics:")
        engine_stats = workflow_engine.get_stats()
        monitor_stats = monitor.get_stats()
        llm_metrics = llm_provider.get_metrics()
        mcp_metrics = mcp_provider.get_metrics()
        
        print(f"  Workflows: {engine_stats['total_workflows']} total")
        print(f"  Tasks: {engine_stats['total_tasks']} total")
        print(f"  Events: {monitor_stats['total_events']} total")
        print(f"  LLM Tasks: {llm_metrics['tasks_completed']} completed, {llm_metrics['tasks_failed']} failed")
        print(f"  MCP Tasks: {mcp_metrics['tasks_completed']} completed, {mcp_metrics['tasks_failed']} failed")
        
        print("\n🎯 Top Event Types:")
        for event_type, count in monitor_stats['top_events']:
            print(f"    {event_type}: {count}")
        
        # Show event history for debugging
        print("\n📝 Event Store Summary:")
        all_events = await event_store.get_events(
            start_time=datetime.utcnow().replace(hour=0, minute=0, second=0),
            limit=50
        )
        print(f"  Stored Events: {len(all_events)}")
        
        if workflow_id:
            workflow_events = await event_store.get_workflow_events(workflow_id)
            print(f"  Workflow Events: {len(workflow_events)}")
        
        # Stop providers
        print("\n🛑 Stopping providers...")
        await llm_provider.stop()
        await mcp_provider.stop()
        await workflow_engine.stop()
        
        print("\n✅ Demo completed successfully!")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        print(f"\n❌ Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())