#!/usr/bin/env python3
"""
Log viewer for Gleitzeit

Stream and filter logs from workflows, tasks, and nodes.
Supports real-time following and search functionality.
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from .core.cluster import GleitzeitCluster


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogViewer:
    """Log streaming and filtering tool"""
    
    def __init__(self, cluster_url: str = "http://localhost:8000"):
        self.cluster_url = cluster_url
        self.console = Console()
        self.cluster: Optional[GleitzeitCluster] = None
        
    def format_log_entry(self, entry: Dict[str, Any], show_json: bool = False) -> str:
        """Format a log entry for display"""
        if show_json:
            return json.dumps(entry, indent=2)
        
        # Extract fields
        timestamp = entry.get('timestamp', '')
        level = entry.get('level', 'INFO')
        source = entry.get('source', 'system')
        message = entry.get('message', '')
        
        # Color based on level
        level_colors = {
            'DEBUG': 'dim',
            'INFO': 'blue',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold red'
        }
        color = level_colors.get(level, 'white')
        
        # Format timestamp
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]
            except:
                time_str = timestamp
        else:
            time_str = "--------"
        
        # Build formatted line
        return f"[dim]{time_str}[/] [{color}]{level:8}[/] [cyan]{source:15}[/] {message}"
    
    async def stream_logs(
        self,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        level: Optional[str] = None,
        follow: bool = False,
        tail: int = 50,
        search: Optional[str] = None,
        json_output: bool = False
    ):
        """Stream logs with filtering options"""
        
        # Initialize cluster connection
        self.cluster = GleitzeitCluster(
            socketio_url=self.cluster_url,
            enable_redis=False,
            enable_socketio=True,
            enable_real_execution=False,
            auto_start_services=False
        )
        
        try:
            await self.cluster.start()
            
            # Get initial logs
            logs = await self.get_logs(
                source_type=source_type,
                source_id=source_id,
                level=level,
                limit=tail
            )
            
            # Display initial logs
            displayed_ids = set()
            for log in logs:
                if search and search.lower() not in str(log).lower():
                    continue
                    
                log_id = log.get('id', str(log))
                if log_id not in displayed_ids:
                    self.console.print(self.format_log_entry(log, json_output))
                    displayed_ids.add(log_id)
            
            # Follow mode - continuously stream new logs
            if follow:
                self.console.print("\n[dim]--- Following logs (Ctrl+C to stop) ---[/]\n")
                
                while True:
                    await asyncio.sleep(1)
                    
                    # Get new logs
                    new_logs = await self.get_logs(
                        source_type=source_type,
                        source_id=source_id,
                        level=level,
                        limit=10
                    )
                    
                    for log in new_logs:
                        log_id = log.get('id', str(log))
                        if log_id not in displayed_ids:
                            if search and search.lower() not in str(log).lower():
                                continue
                            
                            self.console.print(self.format_log_entry(log, json_output))
                            displayed_ids.add(log_id)
                    
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Log streaming stopped[/]")
        finally:
            if self.cluster:
                await self.cluster.stop()
    
    async def get_logs(
        self,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch logs from cluster with filters"""
        
        # This would call the actual cluster API
        # For now, return mock data for demonstration
        logs = []
        
        # In real implementation, this would query:
        # - Redis for stored logs
        # - Socket.IO for real-time logs
        # - Filter by source_type (workflow, task, node, system)
        # - Filter by source_id (specific workflow/task/node ID)
        # - Filter by level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
        # Mock some example logs
        if not hasattr(self, '_log_counter'):
            self._log_counter = 0
        
        # Generate some mock log entries
        for i in range(min(5, limit)):
            self._log_counter += 1
            logs.append({
                'id': f'log_{self._log_counter}',
                'timestamp': datetime.now().isoformat(),
                'level': 'INFO',
                'source': source_type or 'system',
                'message': f'Log entry {self._log_counter} from {source_id or "cluster"}'
            })
        
        return logs


async def logs_command_handler(args):
    """Handle logs command"""
    viewer = LogViewer(
        cluster_url=getattr(args, 'cluster', "http://localhost:8000")
    )
    
    await viewer.stream_logs(
        source_type=getattr(args, 'type', None),
        source_id=getattr(args, 'id', None),
        level=getattr(args, 'level', None),
        follow=getattr(args, 'follow', False),
        tail=getattr(args, 'tail', 50),
        search=getattr(args, 'search', None),
        json_output=getattr(args, 'json', False)
    )


def main():
    """Standalone entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gleitzeit log viewer")
    parser.add_argument('--cluster', default="http://localhost:8000", help='Cluster URL')
    parser.add_argument('--type', choices=['workflow', 'task', 'node', 'system'],
                       help='Source type to filter')
    parser.add_argument('--id', help='Source ID to filter (workflow/task/node ID)')
    parser.add_argument('--level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Minimum log level')
    parser.add_argument('-f', '--follow', action='store_true',
                       help='Follow logs in real-time')
    parser.add_argument('-n', '--tail', type=int, default=50,
                       help='Number of lines to show initially')
    parser.add_argument('--search', help='Search string to filter logs')
    parser.add_argument('--json', action='store_true',
                       help='Output logs as JSON')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(logs_command_handler(args))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()