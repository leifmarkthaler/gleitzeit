#!/usr/bin/env python3
"""
Event stream for Gleitzeit

Real-time event stream from cluster showing task state changes,
workflow events, node events, and system events. JSON output for processing.
"""

import asyncio
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any, Set
from enum import Enum

from rich.console import Console
from rich.text import Text

from .core.cluster import GleitzeitCluster


class EventType(Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed" 
    TASK_FAILED = "task_failed"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_JOINED = "node_joined"
    NODE_LEFT = "node_left"
    NODE_HEARTBEAT = "node_heartbeat"
    SYSTEM_ERROR = "system_error"
    SYSTEM_WARNING = "system_warning"


class EventStream:
    """Real-time event streaming from cluster"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000"):
        self.cluster_url = cluster_url
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
        self.seen_events: Set[str] = set()
    
    async def stream_events(
        self,
        event_types: Optional[Set[str]] = None,
        json_output: bool = False,
        follow: bool = True
    ):
        """Stream events from the cluster"""
        
        # Initialize cluster connection
        if not self.cluster:
            self.cluster = GleitzeitCluster(
                socketio_url=self.cluster_url,
                enable_redis=False,
                enable_socketio=True,
                enable_real_execution=False,
                auto_start_services=False
            )
            await self.cluster.start()
        
        if not json_output:
            self.console.print("[cyan]Streaming events from cluster...[/]\n")
        
        try:
            while True:
                # Fetch recent events
                events = await self.fetch_events()
                
                # Filter and display new events
                for event in events:
                    event_id = event.get('id', str(event))
                    
                    # Skip if already seen
                    if event_id in self.seen_events:
                        continue
                    
                    # Filter by event type if specified
                    if event_types and event.get('type') not in event_types:
                        continue
                    
                    # Display event
                    self.display_event(event, json_output)
                    self.seen_events.add(event_id)
                
                if not follow:
                    break
                
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            if not json_output:
                self.console.print("\n[yellow]Event streaming stopped[/]")
        finally:
            if self.cluster:
                await self.cluster.stop()
    
    async def fetch_events(self) -> List[Dict[str, Any]]:
        """Fetch recent events from cluster"""
        
        # In a real implementation, this would:
        # 1. Subscribe to Socket.IO events
        # 2. Query Redis for stored events
        # 3. Get events from cluster API
        
        # Mock some events for demonstration
        events = []
        
        # Generate mock events
        import time
        current_time = time.time()
        
        # Task events
        events.append({
            'id': f'event_{int(current_time)}',
            'timestamp': datetime.now().isoformat(),
            'type': EventType.TASK_STARTED.value,
            'source': 'executor_node_1',
            'data': {
                'task_id': 'task_abc123',
                'task_name': 'Process Image',
                'workflow_id': 'wf_xyz789',
                'node_id': 'executor_1'
            }
        })
        
        # Workflow events
        if hasattr(self, '_workflow_started'):
            events.append({
                'id': f'event_{int(current_time) + 1}',
                'timestamp': datetime.now().isoformat(),
                'type': EventType.WORKFLOW_COMPLETED.value,
                'source': 'scheduler',
                'data': {
                    'workflow_id': 'wf_xyz789',
                    'workflow_name': 'Image Processing Pipeline',
                    'duration_seconds': 45.2,
                    'tasks_completed': 5,
                    'tasks_failed': 0
                }
            })
        else:
            self._workflow_started = True
            events.append({
                'id': f'event_{int(current_time) + 1}',
                'timestamp': datetime.now().isoformat(),
                'type': EventType.WORKFLOW_STARTED.value,
                'source': 'scheduler',
                'data': {
                    'workflow_id': 'wf_xyz789',
                    'workflow_name': 'Image Processing Pipeline',
                    'total_tasks': 5
                }
            })
        
        return events
    
    def display_event(self, event: Dict[str, Any], json_output: bool = False):
        """Display a single event"""
        
        if json_output:
            print(json.dumps(event))
            return
        
        # Format for human reading
        timestamp = event.get('timestamp', '')
        event_type = event.get('type', 'unknown')
        source = event.get('source', 'system')
        data = event.get('data', {})
        
        # Format timestamp
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]
            except:
                time_str = timestamp.split('T')[1][:12] if 'T' in timestamp else timestamp
        else:
            time_str = "--------"
        
        # Color based on event type
        event_colors = {
            'task_started': 'blue',
            'task_completed': 'green',
            'task_failed': 'red',
            'workflow_started': 'cyan',
            'workflow_completed': 'green',
            'workflow_failed': 'red',
            'node_joined': 'green',
            'node_left': 'yellow',
            'system_error': 'red',
            'system_warning': 'yellow'
        }
        color = event_colors.get(event_type, 'white')
        
        # Format message based on event type
        message = self.format_event_message(event_type, data)
        
        # Display
        self.console.print(f"[dim]{time_str}[/] [{color}]{event_type:20}[/] [dim]{source:15}[/] {message}")
    
    def format_event_message(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format event message based on type"""
        
        if event_type == EventType.TASK_STARTED.value:
            task_name = data.get('task_name', data.get('task_id', 'Unknown'))
            node = data.get('node_id', 'unknown')
            return f"Started task '{task_name}' on {node}"
        
        elif event_type == EventType.TASK_COMPLETED.value:
            task_name = data.get('task_name', data.get('task_id', 'Unknown'))
            duration = data.get('duration_seconds', 0)
            return f"Completed task '{task_name}' in {duration:.1f}s"
        
        elif event_type == EventType.TASK_FAILED.value:
            task_name = data.get('task_name', data.get('task_id', 'Unknown'))
            error = data.get('error', 'Unknown error')
            return f"Failed task '{task_name}': {error}"
        
        elif event_type == EventType.WORKFLOW_STARTED.value:
            wf_name = data.get('workflow_name', data.get('workflow_id', 'Unknown'))
            total_tasks = data.get('total_tasks', 0)
            return f"Started workflow '{wf_name}' with {total_tasks} tasks"
        
        elif event_type == EventType.WORKFLOW_COMPLETED.value:
            wf_name = data.get('workflow_name', data.get('workflow_id', 'Unknown'))
            duration = data.get('duration_seconds', 0)
            completed = data.get('tasks_completed', 0)
            failed = data.get('tasks_failed', 0)
            return f"Completed workflow '{wf_name}' in {duration:.1f}s ({completed} completed, {failed} failed)"
        
        elif event_type == EventType.WORKFLOW_FAILED.value:
            wf_name = data.get('workflow_name', data.get('workflow_id', 'Unknown'))
            error = data.get('error', 'Unknown error')
            return f"Failed workflow '{wf_name}': {error}"
        
        elif event_type == EventType.NODE_JOINED.value:
            node_id = data.get('node_id', 'unknown')
            node_type = data.get('node_type', 'executor')
            return f"Node {node_id} ({node_type}) joined cluster"
        
        elif event_type == EventType.NODE_LEFT.value:
            node_id = data.get('node_id', 'unknown')
            reason = data.get('reason', 'unknown')
            return f"Node {node_id} left cluster: {reason}"
        
        elif event_type == EventType.SYSTEM_ERROR.value:
            component = data.get('component', 'system')
            error = data.get('error', 'Unknown error')
            return f"Error in {component}: {error}"
        
        elif event_type == EventType.SYSTEM_WARNING.value:
            component = data.get('component', 'system')
            warning = data.get('warning', 'Unknown warning')
            return f"Warning in {component}: {warning}"
        
        else:
            return f"Event data: {data}"


async def events_command_handler(args):
    """Handle events command"""
    event_stream = EventStream(
        cluster_url=getattr(args, 'cluster', "http://localhost:8000")
    )
    
    # Parse event types filter
    event_types = None
    if hasattr(args, 'types') and args.types:
        event_types = set(args.types)
    
    await event_stream.stream_events(
        event_types=event_types,
        json_output=getattr(args, 'json', False),
        follow=getattr(args, 'follow', True)
    )


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit event stream")
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    parser.add_argument('--types', nargs='+', 
                       choices=[e.value for e in EventType],
                       help='Event types to filter')
    parser.add_argument('--json', action='store_true',
                       help='Output events as JSON')
    parser.add_argument('--no-follow', dest='follow', action='store_false',
                       help="Don't follow events continuously")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(events_command_handler(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()