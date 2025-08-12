#!/usr/bin/env python3
"""
Gleitzeit V4 Working System Demo

This demonstrates a complete working V4 system with:
- Protocol registration
- Provider implementation
- Task execution
- Workflow orchestration
- Parameter substitution
"""

import asyncio
import logging
import json
from typing import Dict, Any, List

from gleitzeit_v4.core import (
    Task, Workflow, Priority, 
    ExecutionEngine, ExecutionMode,
    WorkflowManager
)
from gleitzeit_v4.core.protocol import ProtocolSpec, MethodSpec
from gleitzeit_v4.providers.base import ProtocolProvider
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.queue import QueueManager, DependencyResolver

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SimpleCalculatorProvider(ProtocolProvider):
    """Simple calculator provider for demo"""
    
    def __init__(self):
        self.provider_id = "simple-calculator"
        self.protocol_id = "calculator/v1"
        self.name = "Simple Calculator Provider"
        
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle calculator requests"""
        logger.info(f"Calculator handling: {method} with params: {params}")
        
        if method == "add":
            a = params.get("a", 0)
            b = params.get("b", 0)
            result = a + b
            return {
                "operation": "addition",
                "a": a,
                "b": b,
                "result": result,
                "formula": f"{a} + {b} = {result}"
            }
        
        elif method == "multiply":
            a = params.get("a", 1)
            b = params.get("b", 1)
            result = a * b
            return {
                "operation": "multiplication", 
                "a": a,
                "b": b,
                "result": result,
                "formula": f"{a} * {b} = {result}"
            }
        
        elif method == "divide":
            a = params.get("a", 0)
            b = params.get("b", 1)
            if b == 0:
                raise ValueError("Division by zero is not allowed")
            result = a / b
            return {
                "operation": "division",
                "a": a, 
                "b": b,
                "result": result,
                "formula": f"{a} / {b} = {result}"
            }
        
        else:
            raise ValueError(f"Unsupported calculator method: {method}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check"""
        return {"status": "healthy", "provider_id": self.provider_id}
    
    async def initialize(self):
        """Initialize the provider"""
        logger.info(f"Initialized {self.name}")
    
    async def shutdown(self):
        """Shutdown the provider"""
        logger.info(f"Shutdown {self.name}")
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["add", "multiply", "divide"]


class TextProcessorProvider(ProtocolProvider):
    """Text processing provider for demo"""
    
    def __init__(self):
        self.provider_id = "text-processor"
        self.protocol_id = "text/v1"
        self.name = "Text Processor Provider"
        
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle text processing requests"""
        logger.info(f"Text processor handling: {method} with params: {params}")
        
        if method == "uppercase":
            text = params.get("text", "")
            return {
                "operation": "uppercase",
                "original": text,
                "result": text.upper(),
                "length": len(text)
            }
        
        elif method == "reverse":
            text = params.get("text", "")
            return {
                "operation": "reverse",
                "original": text,
                "result": text[::-1],
                "length": len(text)
            }
        
        elif method == "summarize":
            data = params.get("data", [])
            summary = {
                "count": len(data),
                "items": data if len(data) <= 3 else data[:3] + ["..."],
                "summary": f"Processed {len(data)} items"
            }
            return {
                "operation": "summarize",
                "original_count": len(data),
                "result": summary
            }
        
        else:
            raise ValueError(f"Unsupported text method: {method}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check"""
        return {"status": "healthy", "provider_id": self.provider_id}
    
    async def initialize(self):
        """Initialize the provider"""
        logger.info(f"Initialized {self.name}")
    
    async def shutdown(self):
        """Shutdown the provider"""
        logger.info(f"Shutdown {self.name}")
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["uppercase", "reverse", "summarize"]


async def setup_system():
    """Setup the complete V4 system"""
    logger.info("🔧 Setting up Gleitzeit V4 system...")
    
    # 1. Initialize core components
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    execution_engine = ExecutionEngine(registry, queue_manager, dependency_resolver, max_concurrent_tasks=3)
    workflow_manager = WorkflowManager(execution_engine, dependency_resolver)
    
    # 2. Register protocols
    calculator_protocol = ProtocolSpec(
        name="calculator",
        version="v1",
        description="Mathematical calculation protocol",
        methods={
            "add": MethodSpec(name="add", description="Add two numbers"),
            "multiply": MethodSpec(name="multiply", description="Multiply two numbers"),
            "divide": MethodSpec(name="divide", description="Divide two numbers")
        }
    )
    
    text_protocol = ProtocolSpec(
        name="text",
        version="v1", 
        description="Text processing protocol",
        methods={
            "uppercase": MethodSpec(name="uppercase", description="Convert text to uppercase"),
            "reverse": MethodSpec(name="reverse", description="Reverse text"),
            "summarize": MethodSpec(name="summarize", description="Summarize data")
        }
    )
    
    registry.register_protocol(calculator_protocol)
    registry.register_protocol(text_protocol)
    
    # 3. Register providers
    calc_provider = SimpleCalculatorProvider()
    text_provider = TextProcessorProvider()
    
    registry.register_provider(calc_provider.provider_id, calculator_protocol.protocol_id, calc_provider)
    registry.register_provider(text_provider.provider_id, text_protocol.protocol_id, text_provider)
    
    # Debug: Check what's registered
    calc_providers = registry.get_providers_for_protocol("calculator/v1", "add")
    logger.info(f"Debug: Found {len(calc_providers)} calculator providers for 'add' method")
    for p in calc_providers:
        logger.info(f"  Provider {p.provider_id}: methods={p.supported_methods}, healthy={p.is_healthy}")
    
    logger.info("✅ System setup complete!")
    
    return {
        "registry": registry,
        "queue_manager": queue_manager,
        "dependency_resolver": dependency_resolver,
        "execution_engine": execution_engine,
        "workflow_manager": workflow_manager
    }


async def demo_single_task(execution_engine):
    """Demo single task execution"""
    logger.info("\n🎯 === Demo: Single Task Execution ===")
    
    # Create a simple calculation task
    task = Task(
        name="Simple Addition",
        protocol="calculator/v1",
        method="add",
        params={"a": 15, "b": 27},
        priority=Priority.HIGH
    )
    
    logger.info(f"Submitting task: {task.name}")
    
    # Submit and execute
    await execution_engine.submit_task(task)
    result = await execution_engine._execute_single_task()
    
    if result:
        logger.info(f"✅ Task completed successfully!")
        logger.info(f"Result: {json.dumps(result.result, indent=2)}")
    else:
        logger.error("❌ Task failed")
    
    return result


async def demo_workflow(workflow_manager, execution_engine):
    """Demo workflow execution with parameter substitution"""
    logger.info("\n🔄 === Demo: Workflow with Parameter Substitution ===")
    
    # Create a workflow that processes data through multiple steps
    workflow_id = "math-and-text-workflow"
    
    tasks = [
        # Step 1: Calculate some numbers
        Task(
            id="calculate-base",
            name="Calculate Base Numbers",
            protocol="calculator/v1",
            method="multiply",
            params={"a": 6, "b": 7},
            workflow_id=workflow_id,
            priority=Priority.HIGH
        ),
        
        # Step 2: Calculate another operation
        Task(
            id="calculate-derived", 
            name="Divide Result",
            protocol="calculator/v1",
            method="divide",
            params={"a": "${calculate-base.result.result}", "b": 2},
            dependencies=["calculate-base"],
            workflow_id=workflow_id,
            priority=Priority.NORMAL
        ),
        
        # Step 3: Process the results as text
        Task(
            id="format-results",
            name="Format Final Results",
            protocol="text/v1",
            method="summarize",
            params={
                "data": [
                    "${calculate-base.result.formula}",
                    "${calculate-derived.result.formula}",
                    "Final computation complete"
                ]
            },
            dependencies=["calculate-base", "calculate-derived"],
            workflow_id=workflow_id,
            priority=Priority.NORMAL
        )
    ]
    
    workflow = Workflow(
        id=workflow_id,
        name="Mathematical Processing Workflow",
        description="Demonstrates parameter substitution between tasks",
        tasks=tasks
    )
    
    logger.info(f"Starting workflow: {workflow.name}")
    logger.info(f"Task count: {len(workflow.tasks)}")
    
    # Start execution engine in event-driven mode
    engine_task = asyncio.create_task(execution_engine.start(ExecutionMode.EVENT_DRIVEN))
    
    try:
        # Execute the workflow
        execution = await workflow_manager.execute_workflow(workflow)
        logger.info(f"Workflow execution started: {execution.execution_id}")
        
        # Wait for completion
        max_wait = 30
        waited = 0
        while execution.execution_id in workflow_manager.active_executions and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
            
            status = workflow_manager.get_execution_status(execution.execution_id)
            if status:
                progress = status['completed_tasks'] / status['total_tasks']
                logger.info(f"Workflow progress: {progress:.1%} ({status['completed_tasks']}/{status['total_tasks']} tasks)")
        
        # Check final results
        final_status = workflow_manager.get_execution_status(execution.execution_id)
        if final_status and final_status["status"] == "completed":
            logger.info("✅ Workflow completed successfully!")
            
            # Show results for each task
            for task in workflow.tasks:
                result = execution_engine.get_task_result(task.id)
                if result:
                    logger.info(f"Task '{task.name}' result:")
                    logger.info(json.dumps(result.result, indent=2))
        else:
            logger.error(f"❌ Workflow failed: {final_status}")
    
    finally:
        # Stop execution engine
        await execution_engine.stop()
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass


async def demo_system_stats(execution_engine, workflow_manager, queue_manager):
    """Demo system statistics"""
    logger.info("\n📊 === Demo: System Statistics ===")
    
    # Engine stats
    engine_stats = execution_engine.get_stats()
    logger.info("Execution Engine Stats:")
    logger.info(f"  Tasks processed: {engine_stats.tasks_processed}")
    logger.info(f"  Tasks succeeded: {engine_stats.tasks_succeeded}")
    logger.info(f"  Tasks failed: {engine_stats.tasks_failed}")
    logger.info(f"  Average duration: {engine_stats.average_task_duration:.3f}s")
    
    # Workflow stats
    wf_stats = workflow_manager.get_workflow_statistics()
    logger.info("Workflow Manager Stats:")
    logger.info(f"  Total templates: {wf_stats['total_templates']}")
    logger.info(f"  Completed executions: {wf_stats['completed_executions']}")
    logger.info(f"  Success rate: {wf_stats['success_rate']:.1f}%")
    
    # Queue stats
    queue_stats = await queue_manager.get_global_stats()
    logger.info("Queue Manager Stats:")
    logger.info(f"  Total enqueued: {queue_stats['total_enqueued']}")
    logger.info(f"  Total dequeued: {queue_stats['total_dequeued']}")
    logger.info(f"  Current size: {queue_stats['total_size']}")


async def main():
    """Run the complete V4 demo"""
    logger.info("🚀 Starting Gleitzeit V4 Complete System Demo")
    
    # Setup system
    components = await setup_system()
    execution_engine = components["execution_engine"]
    workflow_manager = components["workflow_manager"]
    queue_manager = components["queue_manager"]
    
    try:
        # Demo 1: Single task execution
        await demo_single_task(execution_engine)
        
        # Demo 2: Complex workflow
        await demo_workflow(workflow_manager, execution_engine)
        
        # Demo 3: System statistics
        await demo_system_stats(execution_engine, workflow_manager, queue_manager)
        
        logger.info("\n🎉 Demo completed successfully!")
        logger.info("\nGleitzeit V4 Features Demonstrated:")
        logger.info("✅ Protocol-based task execution")
        logger.info("✅ Provider registration and management")
        logger.info("✅ Priority-based task queuing")
        logger.info("✅ Complex workflow orchestration")
        logger.info("✅ Parameter substitution between tasks") 
        logger.info("✅ Dependency resolution and topological sorting")
        logger.info("✅ Comprehensive statistics and monitoring")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())