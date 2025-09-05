# Orchestration Debugging Strategy

## Overview
This document outlines debugging strategies and tooling for the distributed orchestration architecture, addressing the challenges of debugging across multiple services, async events, and distributed state.

## Debuggability Assessment

### Current Architecture Score: 7/10

**Strengths:**
- Centralized state in Redis
- Event-driven audit trail
- Clear component boundaries
- Single responsibility services

**Challenges:**
- Distributed tracing complexity
- Async event ordering
- Leader election transparency
- Race condition reproduction

## Core Debugging Principles

### 1. Observability First
Every action must be observable through:
- Structured logging
- Event streams
- Metrics
- Distributed tracing

### 2. Correlation Throughout
Track execution across services with:
- Correlation IDs
- Request IDs
- Workflow execution IDs
- Span IDs

### 3. State Inspection
Make all state inspectable:
- Redis state dumps
- Event history
- Lock status
- Queue contents

## Implementation Strategy

### 1. Correlation ID System

```python
# src/gleitzeit/debug/correlation.py
from typing import Optional
from contextvars import ContextVar
import uuid

# Thread-local correlation ID storage
correlation_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

class CorrelationMiddleware:
    """Add correlation IDs to all operations"""
    
    @staticmethod
    def generate_correlation_id(prefix: str = "") -> str:
        """Generate new correlation ID"""
        return f"{prefix}{uuid.uuid4().hex[:12]}"
    
    @staticmethod
    def get_or_create(workflow_id: Optional[str] = None) -> str:
        """Get existing or create new correlation ID"""
        existing = correlation_context.get()
        if existing:
            return existing
            
        # Create new with workflow prefix if available
        prefix = f"{workflow_id}-" if workflow_id else ""
        new_id = CorrelationMiddleware.generate_correlation_id(prefix)
        correlation_context.set(new_id)
        return new_id

class CorrelatedEvent:
    """Base event with correlation tracking"""
    
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data
        self.correlation_id = CorrelationMiddleware.get_or_create()
        self.timestamp = datetime.utcnow()
        self.source_node = os.environ.get('NODE_ID', 'unknown')
    
    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "source_node": self.source_node,
            "data": self.data
        }
```

### 2. Debug Mode Implementation

```python
# src/gleitzeit/debug/debug_mode.py
class DebugModeManager:
    """Manage debug mode for easier troubleshooting"""
    
    def __init__(self):
        self.debug_enabled = os.environ.get('GLEITZEIT_DEBUG', '').lower() == 'true'
        self.sync_mode = os.environ.get('GLEITZEIT_SYNC_DEBUG', '').lower() == 'true'
        self.trace_events = os.environ.get('GLEITZEIT_TRACE_EVENTS', '').lower() == 'true'
    
    def should_execute_sync(self) -> bool:
        """Check if should execute synchronously for debugging"""
        return self.debug_enabled and self.sync_mode
    
    def should_trace_event(self, event_type: str) -> bool:
        """Check if should trace this event"""
        if not self.trace_events:
            return False
            
        # Check event filter
        event_filter = os.environ.get('GLEITZEIT_EVENT_FILTER', '')
        if event_filter:
            return event_type in event_filter.split(',')
        return True

class DebugOrchestrationAdapter:
    """Orchestration adapter with debug capabilities"""
    
    def __init__(self):
        self.debug_manager = DebugModeManager()
        self.event_log = []
        
    async def execute_workflow(self, workflow: Workflow) -> WorkflowExecution:
        """Execute workflow with debug support"""
        correlation_id = CorrelationMiddleware.get_or_create(workflow.id)
        
        if self.debug_manager.should_execute_sync():
            # Synchronous execution for easier debugging
            logger.info(f"[DEBUG] Executing workflow {workflow.id} synchronously")
            return await self._execute_sync(workflow, correlation_id)
        else:
            # Normal async distributed execution
            return await self._execute_async(workflow, correlation_id)
    
    async def _execute_sync(self, workflow: Workflow, correlation_id: str):
        """Execute workflow synchronously for debugging"""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            correlation_id=correlation_id,
            debug_mode=True
        )
        
        # Execute tasks in order
        for task in self._get_execution_order(workflow):
            logger.debug(f"[DEBUG] Executing task {task.id}")
            
            try:
                # Direct execution
                result = await self._execute_task_directly(task)
                execution.task_results[task.id] = result
                logger.debug(f"[DEBUG] Task {task.id} completed: {result}")
                
            except Exception as e:
                logger.error(f"[DEBUG] Task {task.id} failed: {e}")
                execution.task_results[task.id] = TaskResult(
                    status="failed",
                    error=str(e)
                )
                
                if not workflow.continue_on_error:
                    break
        
        return execution
```

### 3. Workflow State Inspector

```python
# src/gleitzeit/debug/inspector.py
class WorkflowInspector:
    """Inspect and visualize workflow state"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        
    async def get_workflow_snapshot(self, workflow_id: str) -> dict:
        """Get complete workflow snapshot"""
        snapshot = {
            "workflow_id": workflow_id,
            "timestamp": datetime.utcnow().isoformat(),
            "state": {},
            "tasks": {},
            "events": [],
            "locks": {},
            "retries": {}
        }
        
        # Get workflow state
        state_key = f"workflow:{workflow_id}:state"
        snapshot["state"] = await self.redis.hgetall(state_key)
        
        # Get task states
        task_pattern = f"task:{workflow_id}:*:state"
        task_keys = await self.redis.keys(task_pattern)
        for key in task_keys:
            task_id = key.split(":")[2]
            snapshot["tasks"][task_id] = await self.redis.hgetall(key)
        
        # Get recent events
        event_key = f"events:workflow:{workflow_id}"
        events = await self.redis.xrange(event_key, count=100)
        snapshot["events"] = [self._parse_event(e) for e in events]
        
        # Get lock status
        leader_key = f"workflow:{workflow_id}:leader"
        snapshot["locks"]["leader"] = await self.redis.get(leader_key)
        
        # Get retry schedule
        retry_tasks = await self.redis.zrangebyscore(
            "retry_schedule",
            "-inf",
            "+inf",
            withscores=True
        )
        snapshot["retries"] = {
            task: score 
            for task, score in retry_tasks 
            if task.startswith(workflow_id)
        }
        
        return snapshot
    
    def generate_mermaid_diagram(self, snapshot: dict) -> str:
        """Generate Mermaid diagram from snapshot"""
        lines = ["graph TD"]
        
        # Add task nodes
        for task_id, task_state in snapshot["tasks"].items():
            status = task_state.get("status", "unknown")
            style = {
                "pending": "fill:#f9f,stroke:#333,stroke-width:2px",
                "running": "fill:#ff9,stroke:#333,stroke-width:2px",
                "completed": "fill:#9f9,stroke:#333,stroke-width:2px",
                "failed": "fill:#f99,stroke:#333,stroke-width:2px"
            }.get(status, "")
            
            lines.append(f'    {task_id}["{task_id}<br/>{status}"]')
            if style:
                lines.append(f'    style {task_id} {style}')
        
        # Add dependencies
        state = snapshot.get("state", {})
        deps = json.loads(state.get("dependencies", "{}"))
        for task_id, dependencies in deps.items():
            for dep in dependencies:
                lines.append(f'    {dep} --> {task_id}')
        
        return "\n".join(lines)
    
    def generate_timeline(self, snapshot: dict) -> str:
        """Generate execution timeline"""
        events = snapshot.get("events", [])
        
        timeline = []
        timeline.append("Workflow Execution Timeline")
        timeline.append("=" * 50)
        
        for event in sorted(events, key=lambda e: e["timestamp"]):
            time = event["timestamp"]
            event_type = event["event_type"]
            task_id = event.get("task_id", "")
            
            timeline.append(f"{time} | {event_type:20} | {task_id}")
        
        return "\n".join(timeline)
```

### 4. Debug CLI Tool

```python
# src/gleitzeit/debug/cli.py
import click
import asyncio
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout

console = Console()

@click.group()
def debug():
    """Gleitzeit debugging tools"""
    pass

@debug.command()
@click.argument('workflow_id')
@click.option('--live', is_flag=True, help='Live monitoring')
def workflow(workflow_id: str, live: bool):
    """Debug workflow execution"""
    inspector = WorkflowInspector(redis_client)
    
    if live:
        # Live monitoring
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                snapshot = asyncio.run(inspector.get_workflow_snapshot(workflow_id))
                layout = create_debug_layout(snapshot)
                live.update(layout)
                time.sleep(1)
    else:
        # One-time snapshot
        snapshot = asyncio.run(inspector.get_workflow_snapshot(workflow_id))
        display_snapshot(snapshot)

def create_debug_layout(snapshot: dict) -> Layout:
    """Create rich layout for debug display"""
    layout = Layout()
    
    # Header
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )
    
    # Header content
    header = f"Workflow: {snapshot['workflow_id']} | Status: {snapshot['state'].get('status', 'unknown')}"
    layout["header"].update(header)
    
    # Body split
    layout["body"].split_row(
        Layout(name="tasks"),
        Layout(name="events")
    )
    
    # Task table
    task_table = Table(title="Tasks")
    task_table.add_column("Task ID")
    task_table.add_column("Status")
    task_table.add_column("Attempts")
    
    for task_id, task_state in snapshot["tasks"].items():
        task_table.add_row(
            task_id,
            task_state.get("status", "unknown"),
            task_state.get("attempts", "0")
        )
    
    layout["tasks"].update(task_table)
    
    # Event list
    event_list = Table(title="Recent Events")
    event_list.add_column("Time")
    event_list.add_column("Event")
    event_list.add_column("Details")
    
    for event in snapshot["events"][-10:]:  # Last 10 events
        event_list.add_row(
            event["timestamp"],
            event["event_type"],
            event.get("task_id", "")
        )
    
    layout["events"].update(event_list)
    
    return layout

@debug.command()
@click.argument('task_id')
@click.option('--show-retries', is_flag=True)
def task(task_id: str, show_retries: bool):
    """Debug specific task"""
    console.print(f"[bold]Task Debug: {task_id}[/bold]")
    
    # Get task state
    state = asyncio.run(get_task_state(task_id))
    console.print(f"Status: {state.get('status', 'unknown')}")
    console.print(f"Attempts: {state.get('attempts', 0)}")
    
    if show_retries:
        retries = asyncio.run(get_task_retries(task_id))
        if retries:
            console.print("\n[bold]Retry History:[/bold]")
            for retry in retries:
                console.print(f"  - {retry['timestamp']}: {retry['error']}")

@debug.command()
@click.argument('workflow_id')
def visualize(workflow_id: str):
    """Generate workflow visualization"""
    inspector = WorkflowInspector(redis_client)
    snapshot = asyncio.run(inspector.get_workflow_snapshot(workflow_id))
    
    # Generate Mermaid diagram
    diagram = inspector.generate_mermaid_diagram(snapshot)
    
    # Save to file
    output_file = f"workflow_{workflow_id}_diagram.md"
    with open(output_file, 'w') as f:
        f.write("```mermaid\n")
        f.write(diagram)
        f.write("\n```")
    
    console.print(f"[green]Diagram saved to {output_file}[/green]")
    console.print("\n[bold]Preview:[/bold]")
    console.print(diagram)

@debug.command()
@click.option('--filter', help='Event type filter')
@click.option('--tail', is_flag=True, help='Follow events')
def events(filter: str, tail: bool):
    """Monitor system events"""
    console.print("[bold]Event Monitor[/bold]")
    
    if tail:
        # Real-time event monitoring
        asyncio.run(tail_events(filter))
    else:
        # Show recent events
        recent = asyncio.run(get_recent_events(filter))
        for event in recent:
            console.print(f"{event['timestamp']} | {event['type']} | {event['data']}")
```

### 5. Time-Travel Debugging

```python
# src/gleitzeit/debug/time_travel.py
class TimeTravelDebugger:
    """Debug by replaying workflow execution"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.snapshots = []
        
    async def enable_recording(self, workflow_id: str):
        """Enable state recording for workflow"""
        key = f"workflow:{workflow_id}:recording"
        await self.redis.set(key, "enabled", ex=3600)
        
    async def record_state_change(self, workflow_id: str, change_type: str, data: dict):
        """Record state change for replay"""
        if not await self._is_recording(workflow_id):
            return
            
        timestamp = datetime.utcnow().isoformat()
        record = {
            "timestamp": timestamp,
            "type": change_type,
            "data": data
        }
        
        # Store in Redis stream
        stream_key = f"workflow:{workflow_id}:history"
        await self.redis.xadd(stream_key, record)
        
    async def replay_workflow(self, workflow_id: str, stop_at: Optional[str] = None):
        """Replay workflow execution to specific point"""
        stream_key = f"workflow:{workflow_id}:history"
        
        # Get all history
        history = await self.redis.xrange(stream_key)
        
        # Initialize empty state
        state = WorkflowState(workflow_id=workflow_id)
        
        # Replay events
        for entry in history:
            timestamp = entry["timestamp"]
            change_type = entry["type"]
            data = entry["data"]
            
            # Apply state change
            state = self._apply_change(state, change_type, data)
            
            # Store snapshot
            self.snapshots.append({
                "timestamp": timestamp,
                "state": state.copy()
            })
            
            # Stop if reached target time
            if stop_at and timestamp >= stop_at:
                break
        
        return state
    
    def _apply_change(self, state: WorkflowState, change_type: str, data: dict):
        """Apply state change to workflow state"""
        if change_type == "task_started":
            state.task_states[data["task_id"]] = "running"
        elif change_type == "task_completed":
            state.task_states[data["task_id"]] = "completed"
            state.tasks_completed += 1
        elif change_type == "task_failed":
            state.task_states[data["task_id"]] = "failed"
            state.tasks_failed += 1
        
        return state
    
    def get_state_at_time(self, timestamp: str) -> Optional[WorkflowState]:
        """Get workflow state at specific time"""
        for snapshot in reversed(self.snapshots):
            if snapshot["timestamp"] <= timestamp:
                return snapshot["state"]
        return None
```

### 6. OpenTelemetry Integration

```python
# src/gleitzeit/debug/tracing.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

# Configure tracing
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("gleitzeit.orchestration")

# Add OTLP exporter for Jaeger/Tempo
otlp_exporter = OTLPSpanExporter(
    endpoint="localhost:4317",
    insecure=True
)
span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

class TracedWorkflowCoordinator:
    """Workflow coordinator with distributed tracing"""
    
    async def coordinate_workflow(self, workflow: Workflow):
        """Coordinate workflow with tracing"""
        with tracer.start_as_current_span(
            "workflow.coordinate",
            attributes={
                "workflow.id": workflow.id,
                "workflow.name": workflow.name,
                "workflow.tasks.count": len(workflow.tasks),
                "node.id": self.node_id
            }
        ) as span:
            try:
                # Add correlation ID to span
                correlation_id = CorrelationMiddleware.get_or_create(workflow.id)
                span.set_attribute("correlation.id", correlation_id)
                
                # Execute coordination
                result = await self._coordinate_execution(workflow)
                
                span.set_status(Status(StatusCode.OK))
                return result
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(
                    Status(StatusCode.ERROR, str(e))
                )
                raise
    
    async def _coordinate_execution(self, workflow: Workflow):
        """Execute with nested spans"""
        # Dependency resolution span
        with tracer.start_as_current_span("workflow.resolve_dependencies") as span:
            plan = await self._create_execution_plan(workflow)
            span.set_attribute("execution.batches", len(plan.batches))
        
        # Task distribution spans
        for batch in plan.batches:
            with tracer.start_as_current_span(
                "workflow.distribute_batch",
                attributes={"batch.number": batch.batch_number}
            ) as span:
                await self._distribute_task_batch(batch)
                span.set_attribute("batch.tasks", len(batch.tasks))
```

### 7. Performance Profiling

```python
# src/gleitzeit/debug/profiling.py
import cProfile
import pstats
from memory_profiler import profile

class WorkflowProfiler:
    """Profile workflow execution performance"""
    
    def __init__(self):
        self.profiles = {}
        
    def profile_workflow(self, workflow_id: str):
        """Decorator to profile workflow execution"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                # CPU profiling
                profiler = cProfile.Profile()
                profiler.enable()
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    profiler.disable()
                    
                    # Store profile
                    self.profiles[workflow_id] = profiler
                    
                    # Generate stats
                    stats = pstats.Stats(profiler)
                    stats.sort_stats('cumulative')
                    
                    # Save to file
                    stats.dump_stats(f"workflow_{workflow_id}.prof")
                    
            return wrapper
        return decorator
    
    @profile
    async def memory_profile_task(self, task: Task):
        """Profile memory usage for task execution"""
        # This will be decorated by memory_profiler
        return await self.execute_task(task)
```

## Redis Debugging Structure

```yaml
# Debug-specific keys
debug:workflows                    # List of workflows in debug mode
debug:breakpoints                  # Configured breakpoints

workflow:{id}:debug:enabled        # Debug mode flag
workflow:{id}:debug:sync           # Sync execution flag
workflow:{id}:debug:recording      # State recording enabled
workflow:{id}:debug:snapshots      # State snapshots

workflow:{id}:history              # Redis stream of all events
workflow:{id}:timeline             # Execution timeline
workflow:{id}:errors               # Error log
workflow:{id}:metrics              # Performance metrics

task:{id}:debug:logs               # Task execution logs
task:{id}:debug:attempts           # All execution attempts
task:{id}:debug:profile            # Performance profile
```

## Debug Configuration

```yaml
# docker-compose.debug.yml
services:
  # Jaeger for distributed tracing
  jaeger:
    image: jaegertracing/all-in-one:1.51
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP gRPC
      - "4318:4318"    # OTLP HTTP
    environment:
      - COLLECTOR_OTLP_ENABLED=true

  # Redis with debugging enabled
  redis:
    image: redis:7-alpine
    command: redis-server --loglevel debug
    ports:
      - "6379:6379"
    volumes:
      - ./redis-debug.conf:/usr/local/etc/redis/redis.conf

  # Gleitzeit with debug mode
  gleitzeit:
    image: gleitzeit:debug
    environment:
      - GLEITZEIT_DEBUG=true
      - GLEITZEIT_TRACE_EVENTS=true
      - GLEITZEIT_SYNC_DEBUG=false
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
      - OTEL_SERVICE_NAME=gleitzeit-orchestration
      - LOG_LEVEL=DEBUG
    volumes:
      - ./debug-output:/debug
```

## Debug Workflows

### 1. Debugging Stuck Workflow
```bash
# Check workflow state
gleitzeit debug workflow wf-123

# Check for locks
redis-cli GET workflow:wf-123:leader

# Check task states
gleitzeit debug workflow wf-123 --show-tasks

# Check retry schedule
redis-cli ZRANGE retry_schedule 0 -1 WITHSCORES

# Live monitor
gleitzeit debug workflow wf-123 --live
```

### 2. Debugging Failed Task
```bash
# Get task details
gleitzeit debug task task-456

# Show retry attempts
gleitzeit debug task task-456 --show-retries

# Check task logs
redis-cli LRANGE task:task-456:debug:logs 0 -1

# Replay task execution
gleitzeit debug replay task-456
```

### 3. Performance Debugging
```bash
# Profile workflow
gleitzeit debug profile wf-123

# View metrics
gleitzeit debug metrics wf-123

# Generate flame graph
python -m py_flame workflow_wf-123.prof > flame.svg
```

### 4. Event Debugging
```bash
# Monitor all events
gleitzeit debug events --tail

# Filter specific events
gleitzeit debug events --filter "task:failed" --tail

# Replay events
gleitzeit debug replay-events wf-123 --stop-at "2024-01-01T12:00:00"
```

## Debugging Best Practices

1. **Always Use Correlation IDs**
   - Add to every event
   - Include in logs
   - Pass through all services

2. **Enable Debug Mode Selectively**
   - Per-workflow debugging
   - Temporary sync mode
   - Targeted event tracing

3. **Monitor Key Metrics**
   - Task completion rate
   - Retry frequency
   - Lock contention
   - Event latency

4. **Regular State Snapshots**
   - Capture state periodically
   - Store for time-travel
   - Clean up old snapshots

5. **Use Structured Logging**
   ```python
   logger.info("Task completed", extra={
       "workflow_id": workflow_id,
       "task_id": task_id,
       "correlation_id": correlation_id,
       "duration_ms": duration
   })
   ```

## Troubleshooting Guide

### Common Issues and Solutions

1. **Workflow Not Progressing**
   - Check leader election
   - Verify coordinator health
   - Look for stuck locks
   - Check event bus connectivity

2. **Tasks Not Executing**
   - Verify provider availability
   - Check task queue
   - Look for retry loops
   - Verify dependencies met

3. **High Retry Rate**
   - Check provider errors
   - Verify retry configuration
   - Look for transient failures
   - Check backoff settings

4. **Event Ordering Issues**
   - Check timestamps
   - Verify clock sync
   - Look for race conditions
   - Check event versioning

## Summary

With these debugging enhancements, the orchestration architecture becomes:

**Debuggability Score: 9/10**

Key improvements:
- Correlation IDs for request tracing
- Debug mode with sync execution
- Comprehensive state inspection
- Time-travel debugging
- Rich CLI tooling
- OpenTelemetry integration
- Performance profiling

The system is now highly debuggable while maintaining production performance.