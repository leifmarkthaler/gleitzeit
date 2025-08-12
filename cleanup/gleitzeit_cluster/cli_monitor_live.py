#!/usr/bin/env python3
"""
Live Real-Time Monitoring Client

Connects to Gleitzeit cluster via Socket.IO and displays real-time metrics
"""

import asyncio
import json
import signal
import sys
from datetime import datetime
from typing import Dict, Any

import socketio


class LiveMonitoringClient:
    """Real-time monitoring client using Socket.IO"""
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=10
        )
        
        self.running = False
        self.metrics_history = []
        
        # Setup event handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        # Connection events
        self.sio.on('connect', namespace='/cluster')(self.handle_connect)
        self.sio.on('disconnect', namespace='/cluster')(self.handle_disconnect)
        
        # Monitoring events
        self.sio.on('monitor:subscribed', namespace='/cluster')(self.handle_subscribed)
        self.sio.on('monitor:initial_metrics', namespace='/cluster')(self.handle_initial_metrics)
        self.sio.on('monitor:metrics_update', namespace='/cluster')(self.handle_metrics_update)
        
        # Task and workflow events
        self.sio.on('task:completed', namespace='/cluster')(self.handle_task_completed)
        self.sio.on('task:failed', namespace='/cluster')(self.handle_task_failed)
        self.sio.on('workflow:started', namespace='/cluster')(self.handle_workflow_started)
        self.sio.on('workflow:completed', namespace='/cluster')(self.handle_workflow_completed)
        
        # Node events
        self.sio.on('node:registered', namespace='/cluster')(self.handle_node_registered)
        self.sio.on('node:disconnected', namespace='/cluster')(self.handle_node_disconnected)
    
    async def start(self):
        """Start monitoring client"""
        print("🔍 Starting Gleitzeit Live Monitoring")
        print(f"   Connecting to: {self.server_url}")
        print("   Press Ctrl+C to stop")
        print("=" * 60)
        
        try:
            # Connect to server
            await self.sio.connect(self.server_url, namespaces=['/cluster'])
            self.running = True
            
            # Subscribe to all monitoring events
            await self.sio.emit('monitor:subscribe', {
                'types': ['all']  # Subscribe to all metric types
            }, namespace='/cluster')
            
            # Keep running until stopped
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            return False
        
        return True
    
    async def stop(self):
        """Stop monitoring client"""
        print("\\n🛑 Stopping monitoring...")
        self.running = False
        
        if self.sio.connected:
            await self.sio.emit('monitor:unsubscribe', {}, namespace='/cluster')
            await self.sio.disconnect()
        
        print("✅ Monitoring stopped")
    
    # ========================
    # Connection Handlers
    # ========================
    
    async def handle_connect(self):
        """Handle connection to server"""
        print("🔌 Connected to Gleitzeit cluster")
    
    async def handle_disconnect(self):
        """Handle disconnection from server"""
        print("❌ Disconnected from cluster")
        self.running = False
    
    async def handle_subscribed(self, data):
        """Handle monitoring subscription confirmation"""
        print(f"✅ {data['message']}")
        print(f"   Subscribed to: {', '.join(data['types'])}")
        print()
    
    # ========================
    # Metrics Handlers
    # ========================
    
    async def handle_initial_metrics(self, data):
        """Handle initial metrics data"""
        metrics = data['metrics']
        interval = data['update_interval_seconds']
        
        print(f"📊 Initial Metrics (updates every {interval}s)")
        print("-" * 40)
        
        self._display_metrics(metrics)
    
    async def handle_metrics_update(self, metrics):
        """Handle real-time metrics update"""
        self.metrics_history.append(metrics)
        
        # Keep only last 10 minutes of history
        if len(self.metrics_history) > 300:  # 10 min at 2s intervals
            self.metrics_history = self.metrics_history[-300:]
        
        # Clear screen and display updated metrics
        print("\\033[2J\\033[H")  # Clear screen and move cursor to top
        print("🔍 Gleitzeit Live Monitoring - Real-Time Metrics")
        print(f"   Last updated: {datetime.now().strftime('%H:%M:%S')}")
        print("   Press Ctrl+C to stop")
        print("=" * 60)
        
        self._display_metrics(metrics)
    
    def _display_metrics(self, metrics: Dict[str, Any]):
        """Display formatted metrics"""
        # Cluster overview
        cluster = metrics.get('cluster_metrics', {})
        print(f"🏢 Cluster Status:")
        print(f"   Connected Clients: {cluster.get('connected_clients', 0)}")
        print(f"   Executor Nodes:    {cluster.get('executor_nodes', 0)}")
        print(f"   External Services: {cluster.get('external_service_nodes', 0)}")
        print(f"   Active Workflows:  {cluster.get('active_workflows', 0)}")
        print(f"   Monitoring Users:  {cluster.get('monitoring_clients', 0)}")
        print()
        
        # Node metrics (executors and external services)
        nodes = metrics.get('node_metrics', [])
        if nodes:
            executor_nodes = [n for n in nodes if n.get('node_type') == 'executor']
            external_services = [n for n in nodes if n.get('node_type') == 'external_service']
            
            if executor_nodes:
                print(f"🖥️  Executor Nodes ({len(executor_nodes)} active):")
                for node in executor_nodes:
                    status_icon = "🟢" if node.get('status') == 'ready' else "🔴"
                    gpu_info = "🎮" if node.get('has_gpu') else "💻"
                    
                    print(f"   {status_icon} {gpu_info} {node.get('name', 'Unknown')[:20]:20} "
                          f"CPU: {node.get('cpu_usage', 0):5.1f}% "
                          f"MEM: {node.get('memory_usage', 0):5.1f}% "
                          f"Tasks: {node.get('active_tasks', 0)}/{node.get('max_tasks', 1)}")
                print()
            
            if external_services:
                print(f"🔗 External Services ({len(external_services)} active):")
                for service in external_services:
                    status_icon = "🟢" if service.get('status') == 'ready' else "🔴"
                    capabilities = service.get('capabilities', [])
                    cap_preview = ', '.join(capabilities[:2])
                    if len(capabilities) > 2:
                        cap_preview += f" +{len(capabilities)-2}"
                    
                    completed = service.get('tasks_completed', 0)
                    failed = service.get('tasks_failed', 0)
                    success_rate = (completed / max(completed + failed, 1)) * 100
                    
                    print(f"   {status_icon} 🌐 {service.get('name', 'Unknown')[:20]:20} "
                          f"Tasks: {service.get('active_tasks', 0)}/{service.get('max_tasks', 10):2} "
                          f"Success: {success_rate:5.1f}% "
                          f"({cap_preview})")
                print()
        
        # Queue status
        queues = metrics.get('queue_metrics', {})
        if queues:
            total_queued = queues.get('total_queued', 0)
            print(f"📋 Task Queues (Total: {total_queued}):")
            print(f"   Urgent: {queues.get('urgent_queue', 0):3d}  "
                  f"High: {queues.get('high_queue', 0):3d}  "
                  f"Normal: {queues.get('normal_queue', 0):3d}  "
                  f"Low: {queues.get('low_queue', 0):3d}")
            print()
        
        # Aggregate metrics
        agg = metrics.get('aggregate_metrics', {})
        if agg:
            print(f"📈 Cluster Performance:")
            print(f"   Avg Node CPU:        {agg.get('avg_node_cpu', 0):5.1f}%")
            print(f"   Avg Node Memory:     {agg.get('avg_node_memory', 0):5.1f}%")
            print(f"   Active Tasks:        {agg.get('total_active_tasks', 0)}")
            print(f"   Cluster Utilization: {agg.get('cluster_utilization', 0):5.1f}%")
            print()
        
        # System metrics (server)
        system = metrics.get('system_metrics', {})
        if system:
            print(f"🖥️  Server System:")
            print(f"   Server CPU:  {system.get('server_cpu', 0):5.1f}%")
            print(f"   Server MEM:  {system.get('server_memory', 0):5.1f}%")
            print(f"   Server Disk: {system.get('server_disk', 0):5.1f}%")
            print()
    
    # ========================
    # Event Handlers
    # ========================
    
    async def handle_task_completed(self, data):
        """Handle task completion event"""
        task_id = data.get('task_id', 'unknown')[:8]
        workflow_id = data.get('workflow_id', 'unknown')[:8]
        
        print(f"✅ Task completed: {task_id}... (workflow: {workflow_id}...)")
    
    async def handle_task_failed(self, data):
        """Handle task failure event"""
        task_id = data.get('task_id', 'unknown')[:8]
        workflow_id = data.get('workflow_id', 'unknown')[:8]
        error = data.get('error', 'Unknown error')[:50]
        
        print(f"❌ Task failed: {task_id}... (workflow: {workflow_id}...) - {error}")
    
    async def handle_workflow_started(self, data):
        """Handle workflow start event"""
        workflow_id = data.get('workflow_id', 'unknown')[:8]
        name = data.get('name', 'Unnamed')
        total_tasks = data.get('total_tasks', 0)
        
        print(f"🚀 Workflow started: {name} ({workflow_id}...) - {total_tasks} tasks")
    
    async def handle_workflow_completed(self, data):
        """Handle workflow completion event"""
        workflow_id = data.get('workflow_id', 'unknown')[:8]
        status = data.get('status', 'unknown')
        completed = data.get('completed_tasks', 0)
        failed = data.get('failed_tasks', 0)
        
        status_icon = "✅" if status == 'completed' else "❌"
        print(f"{status_icon} Workflow {status}: {workflow_id}... ({completed} completed, {failed} failed)")
    
    async def handle_node_registered(self, data):
        """Handle node registration event"""
        name = data.get('name', 'Unknown')
        node_id = data.get('node_id', 'unknown')[:8]
        capabilities = data.get('capabilities', {})
        task_types = len(capabilities.get('task_types', []))
        
        print(f"🆕 Node registered: {name} ({node_id}...) - {task_types} task types")
    
    async def handle_node_disconnected(self, data):
        """Handle node disconnection event"""
        name = data.get('name', 'Unknown')
        node_id = data.get('node_id', 'unknown')[:8]
        
        print(f"📤 Node disconnected: {name} ({node_id}...)")


def setup_signal_handlers(client: LiveMonitoringClient):
    """Setup signal handlers for graceful shutdown"""
    
    def signal_handler(signum, frame):
        print(f"\\n📡 Received signal {signum}, shutting down...")
        
        # Create shutdown task
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(client.stop())
        else:
            loop.run_until_complete(client.stop())
        
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit Live Monitoring Client")
    parser.add_argument("--server", default="http://localhost:8000", help="Gleitzeit server URL")
    
    args = parser.parse_args()
    
    # Create monitoring client
    client = LiveMonitoringClient(server_url=args.server)
    
    # Setup signal handlers
    setup_signal_handlers(client)
    
    try:
        success = await client.start()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Monitoring failed: {e}")
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())