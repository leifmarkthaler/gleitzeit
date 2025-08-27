"""
API-based CLI commands for Gleitzeit.

Provides comprehensive CLI access to all API endpoints.
"""

import asyncio
import click
import httpx
import json
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import yaml
from tabulate import tabulate

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class APIClient:
    """HTTP client for Gleitzeit API"""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.base_url = f"http://{host}:{port}"
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def close(self):
        await self.client.aclose()
        
    async def get(self, path: str, params: Optional[Dict] = None) -> Dict:
        """GET request to API"""
        try:
            response = await self.client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
            raise click.ClickException(error_msg)
        except httpx.RequestError as e:
            raise click.ClickException(f"Connection error: {e}")
            
    async def post(self, path: str, json_data: Optional[Dict] = None) -> Dict:
        """POST request to API"""
        try:
            response = await self.client.post(f"{self.base_url}{path}", json=json_data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
            raise click.ClickException(error_msg)
        except httpx.RequestError as e:
            raise click.ClickException(f"Connection error: {e}")
            
    async def delete(self, path: str, params: Optional[Dict] = None) -> Dict:
        """DELETE request to API"""
        try:
            response = await self.client.delete(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
            raise click.ClickException(error_msg)
        except httpx.RequestError as e:
            raise click.ClickException(f"Connection error: {e}")
            
    async def put(self, path: str, json_data: Optional[Dict] = None) -> Dict:
        """PUT request to API"""
        try:
            response = await self.client.put(f"{self.base_url}{path}", json=json_data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
            raise click.ClickException(error_msg)
        except httpx.RequestError as e:
            raise click.ClickException(f"Connection error: {e}")


def format_timestamp(timestamp: str) -> str:
    """Format ISO timestamp for display"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return timestamp


def print_table(data: List[Dict], headers: List[str], max_width: int = 50):
    """Print data as formatted table"""
    rows = []
    for item in data:
        row = []
        for header in headers:
            value = item.get(header, '')
            if isinstance(value, str) and len(value) > max_width:
                value = value[:max_width-3] + '...'
            row.append(value)
        rows.append(row)
    
    if rows:
        click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
    else:
        click.echo("No data found")


# ============================================================================
# TASK COMMANDS
# ============================================================================

@click.group()
def task():
    """Task management commands"""
    pass


@task.command('list')
@click.option('--status', type=click.Choice(['PENDING', 'EXECUTING', 'COMPLETED', 'FAILED', 'CANCELLED']),
              help='Filter by task status')
@click.option('--workflow-id', help='Filter by workflow ID')
@click.option('--limit', default=50, help='Maximum tasks to return')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_list(status: Optional[str], workflow_id: Optional[str], limit: int, host: str, port: int):
    """List tasks"""
    async def _list():
        client = APIClient(host, port)
        try:
            params = {'limit': limit}
            if status:
                params['status'] = status
            if workflow_id:
                params['workflow_id'] = workflow_id
                
            result = await client.get('/tasks', params)
            
            if result.get('tasks'):
                headers = ['ID', 'Name', 'Status', 'Created', 'Provider']
                data = []
                for task in result['tasks']:
                    data.append({
                        'ID': task['id'][:8],
                        'Name': task.get('name', 'N/A'),
                        'Status': task['status'],
                        'Created': format_timestamp(task['created_at']),
                        'Provider': task.get('provider_id', 'N/A')
                    })
                print_table(data, headers)
            else:
                click.echo("No tasks found")
        finally:
            await client.close()
            
    asyncio.run(_list())


@task.command('get')
@click.argument('task_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_get(task_id: str, host: str, port: int):
    """Get task details"""
    async def _get():
        client = APIClient(host, port)
        try:
            result = await client.get(f'/tasks/{task_id}')
            
            click.echo(f"\n{Colors.BOLD}Task Details{Colors.RESET}")
            click.echo("=" * 50)
            click.echo(f"ID: {result['id']}")
            click.echo(f"Name: {result.get('name', 'N/A')}")
            click.echo(f"Status: {Colors.GREEN if result['status'] == 'COMPLETED' else Colors.YELLOW}{result['status']}{Colors.RESET}")
            click.echo(f"Created: {format_timestamp(result['created_at'])}")
            click.echo(f"Provider: {result.get('provider_id', 'N/A')}")
            
            if result.get('error'):
                click.echo(f"\n{Colors.RED}Error:{Colors.RESET}")
                click.echo(result['error'])
                
            if result.get('metadata'):
                click.echo(f"\n{Colors.CYAN}Metadata:{Colors.RESET}")
                click.echo(json.dumps(result['metadata'], indent=2))
        finally:
            await client.close()
            
    asyncio.run(_get())


@task.command('cancel')
@click.argument('task_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_cancel(task_id: str, host: str, port: int):
    """Cancel a task"""
    async def _cancel():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/tasks/{task_id}/cancel')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} {result.get('message', 'Task cancelled')}")
        finally:
            await client.close()
            
    asyncio.run(_cancel())


@task.command('retry')
@click.argument('task_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_retry(task_id: str, host: str, port: int):
    """Retry a failed task"""
    async def _retry():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/tasks/{task_id}/retry')
            new_task = result.get('task', {})
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Task retried")
            click.echo(f"New task ID: {new_task.get('id', 'N/A')}")
        finally:
            await client.close()
            
    asyncio.run(_retry())


@task.command('logs')
@click.argument('task_id')
@click.option('--tail', default=50, help='Number of lines to show')
@click.option('--level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']),
              help='Minimum log level')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_logs(task_id: str, tail: int, level: Optional[str], host: str, port: int):
    """Get task logs"""
    async def _logs():
        client = APIClient(host, port)
        try:
            params = {'tail': tail}
            if level:
                params['level'] = level
                
            result = await client.get(f'/tasks/{task_id}/logs', params)
            
            if result.get('logs'):
                for log in result['logs']:
                    timestamp = format_timestamp(log['timestamp'])
                    level_color = {
                        'ERROR': Colors.RED,
                        'WARNING': Colors.YELLOW,
                        'INFO': Colors.CYAN,
                        'DEBUG': Colors.BLUE
                    }.get(log['level'], '')
                    
                    click.echo(f"[{timestamp}] {level_color}{log['level']}{Colors.RESET}: {log['message']}")
            else:
                click.echo("No logs found")
        finally:
            await client.close()
            
    asyncio.run(_logs())


@task.command('result')
@click.argument('task_id')
@click.option('--output', '-o', type=click.Path(), help='Save result to file')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def task_result(task_id: str, output: Optional[str], host: str, port: int):
    """Get task result"""
    async def _result():
        client = APIClient(host, port)
        try:
            result = await client.get(f'/tasks/{task_id}/result')
            
            if output:
                with open(output, 'w') as f:
                    json.dump(result, f, indent=2)
                click.echo(f"{Colors.GREEN}✓{Colors.RESET} Result saved to {output}")
            else:
                click.echo(json.dumps(result, indent=2))
        finally:
            await client.close()
            
    asyncio.run(_result())


# ============================================================================
# WORKFLOW COMMANDS
# ============================================================================

@click.group()
def workflow():
    """Workflow management commands"""
    pass


@workflow.command('list')
@click.option('--status', type=click.Choice(['PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED']),
              help='Filter by workflow status')
@click.option('--limit', default=50, help='Maximum workflows to return')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_list(status: Optional[str], limit: int, host: str, port: int):
    """List workflows"""
    async def _list():
        client = APIClient(host, port)
        try:
            params = {'limit': limit}
            if status:
                params['status'] = status
                
            result = await client.get('/workflows', params)
            
            if result.get('workflows'):
                headers = ['ID', 'Name', 'Status', 'Tasks', 'Created']
                data = []
                for wf in result['workflows']:
                    data.append({
                        'ID': wf['id'][:8],
                        'Name': wf.get('name', 'N/A'),
                        'Status': wf['status'],
                        'Tasks': f"{wf.get('completed_tasks', 0)}/{wf.get('total_tasks', 0)}",
                        'Created': format_timestamp(wf['created_at'])
                    })
                print_table(data, headers)
            else:
                click.echo("No workflows found")
        finally:
            await client.close()
            
    asyncio.run(_list())


@workflow.command('get')
@click.argument('workflow_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_get(workflow_id: str, host: str, port: int):
    """Get workflow details"""
    async def _get():
        client = APIClient(host, port)
        try:
            result = await client.get(f'/workflows/{workflow_id}')
            
            click.echo(f"\n{Colors.BOLD}Workflow Details{Colors.RESET}")
            click.echo("=" * 50)
            click.echo(f"ID: {result['id']}")
            click.echo(f"Name: {result.get('name', 'N/A')}")
            click.echo(f"Status: {Colors.GREEN if result['status'] == 'COMPLETED' else Colors.YELLOW}{result['status']}{Colors.RESET}")
            click.echo(f"Created: {format_timestamp(result['created_at'])}")
            click.echo(f"Tasks: {result.get('completed_tasks', 0)}/{result.get('total_tasks', 0)}")
            
            if result.get('metadata'):
                click.echo(f"\n{Colors.CYAN}Metadata:{Colors.RESET}")
                click.echo(json.dumps(result['metadata'], indent=2))
        finally:
            await client.close()
            
    asyncio.run(_get())


@workflow.command('pause')
@click.argument('workflow_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_pause(workflow_id: str, host: str, port: int):
    """Pause a running workflow"""
    async def _pause():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/workflows/{workflow_id}/pause')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} {result.get('message', 'Workflow paused')}")
            if result.get('cancelled_tasks') is not None:
                click.echo(f"Cancelled {result['cancelled_tasks']} pending tasks")
        finally:
            await client.close()
            
    asyncio.run(_pause())


@workflow.command('resume')
@click.argument('workflow_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_resume(workflow_id: str, host: str, port: int):
    """Resume a paused workflow"""
    async def _resume():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/workflows/{workflow_id}/resume')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} {result.get('message', 'Workflow resumed')}")
            if result.get('requeued_tasks') is not None:
                click.echo(f"Requeued {result['requeued_tasks']} tasks")
        finally:
            await client.close()
            
    asyncio.run(_resume())


@workflow.command('retry')
@click.argument('workflow_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_retry(workflow_id: str, host: str, port: int):
    """Retry failed tasks in workflow"""
    async def _retry():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/workflows/{workflow_id}/retry')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} {result.get('message', 'Workflow retry initiated')}")
            if result.get('retried_tasks') is not None:
                click.echo(f"Retrying {result['retried_tasks']} failed tasks")
        finally:
            await client.close()
            
    asyncio.run(_retry())


@workflow.command('delete')
@click.argument('workflow_id')
@click.option('--force', is_flag=True, help='Force delete without confirmation')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_delete(workflow_id: str, force: bool, host: str, port: int):
    """Delete a workflow"""
    if not force:
        if not click.confirm(f"Delete workflow {workflow_id}?"):
            return
            
    async def _delete():
        client = APIClient(host, port)
        try:
            result = await client.delete(f'/workflows/{workflow_id}')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Workflow deleted")
        finally:
            await client.close()
            
    asyncio.run(_delete())


@workflow.command('export')
@click.argument('workflow_id')
@click.option('--output', '-o', type=click.Path(), help='Output file')
@click.option('--format', 'fmt', type=click.Choice(['json', 'yaml']), default='yaml',
              help='Export format')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def workflow_export(workflow_id: str, output: Optional[str], fmt: str, host: str, port: int):
    """Export workflow definition"""
    async def _export():
        client = APIClient(host, port)
        try:
            params = {'format': fmt}
            result = await client.get(f'/workflows/{workflow_id}/export', params)
            
            if output:
                with open(output, 'w') as f:
                    if fmt == 'yaml':
                        yaml.dump(result, f)
                    else:
                        json.dump(result, f, indent=2)
                click.echo(f"{Colors.GREEN}✓{Colors.RESET} Workflow exported to {output}")
            else:
                if fmt == 'yaml':
                    click.echo(yaml.dump(result))
                else:
                    click.echo(json.dumps(result, indent=2))
        finally:
            await client.close()
            
    asyncio.run(_export())


# ============================================================================
# QUEUE COMMANDS
# ============================================================================

@click.group()
def queue():
    """Queue management commands"""
    pass


@queue.command('list')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def queue_list(host: str, port: int):
    """List all queues"""
    async def _list():
        client = APIClient(host, port)
        try:
            result = await client.get('/queues')
            
            if result.get('queues'):
                headers = ['Name', 'Status', 'Size', 'Processing', 'Workers']
                data = []
                for q in result['queues']:
                    data.append({
                        'Name': q['name'],
                        'Status': q['status'],
                        'Size': q['size'],
                        'Processing': q.get('processing', 0),
                        'Workers': q.get('workers', 0)
                    })
                print_table(data, headers)
            else:
                click.echo("No queues found")
        finally:
            await client.close()
            
    asyncio.run(_list())


@queue.command('status')
@click.argument('queue_name')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def queue_status(queue_name: str, host: str, port: int):
    """Get queue status"""
    async def _status():
        client = APIClient(host, port)
        try:
            result = await client.get(f'/queues/{queue_name}')
            
            click.echo(f"\n{Colors.BOLD}Queue: {queue_name}{Colors.RESET}")
            click.echo("=" * 50)
            click.echo(f"Status: {Colors.GREEN if result['status'] == 'active' else Colors.YELLOW}{result['status']}{Colors.RESET}")
            click.echo(f"Size: {result['size']}")
            click.echo(f"Processing: {result.get('processing', 0)}")
            click.echo(f"Workers: {result.get('workers', 0)}")
            click.echo(f"Max Workers: {result.get('max_workers', 'N/A')}")
            
            if result.get('stats'):
                click.echo(f"\n{Colors.CYAN}Statistics:{Colors.RESET}")
                stats = result['stats']
                click.echo(f"  Processed: {stats.get('processed', 0)}")
                click.echo(f"  Failed: {stats.get('failed', 0)}")
                click.echo(f"  Average Time: {stats.get('avg_time', 0):.2f}s")
        finally:
            await client.close()
            
    asyncio.run(_status())


@queue.command('pause')
@click.argument('queue_name')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def queue_pause(queue_name: str, host: str, port: int):
    """Pause a queue"""
    async def _pause():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/queues/{queue_name}/pause')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Queue '{queue_name}' paused")
        finally:
            await client.close()
            
    asyncio.run(_pause())


@queue.command('resume')
@click.argument('queue_name')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def queue_resume(queue_name: str, host: str, port: int):
    """Resume a paused queue"""
    async def _resume():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/queues/{queue_name}/resume')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Queue '{queue_name}' resumed")
        finally:
            await client.close()
            
    asyncio.run(_resume())


@queue.command('clear')
@click.argument('queue_name')
@click.option('--force', is_flag=True, help='Force clear without confirmation')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def queue_clear(queue_name: str, force: bool, host: str, port: int):
    """Clear all tasks from queue"""
    if not force:
        if not click.confirm(f"Clear all tasks from queue '{queue_name}'?"):
            return
            
    async def _clear():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/queues/{queue_name}/clear')
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Queue '{queue_name}' cleared")
            if result.get('cleared_tasks') is not None:
                click.echo(f"Removed {result['cleared_tasks']} tasks")
        finally:
            await client.close()
            
    asyncio.run(_clear())


# ============================================================================
# LOG COMMANDS
# ============================================================================

@click.group()
def logs():
    """Log management commands"""
    pass


@logs.command('query')
@click.option('--level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']),
              help='Filter by log level')
@click.option('--source', type=click.Choice(['TASK', 'WORKFLOW', 'SYSTEM', 'API']),
              help='Filter by source')
@click.option('--task-id', help='Filter by task ID')
@click.option('--workflow-id', help='Filter by workflow ID')
@click.option('--since', help='Logs since timestamp (ISO format)')
@click.option('--limit', default=100, help='Maximum logs to return')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def logs_query(level: Optional[str], source: Optional[str], task_id: Optional[str],
               workflow_id: Optional[str], since: Optional[str], limit: int,
               host: str, port: int):
    """Query system logs"""
    async def _query():
        client = APIClient(host, port)
        try:
            params = {'limit': limit}
            if level:
                params['level'] = level
            if source:
                params['source'] = source
            if task_id:
                params['task_id'] = task_id
            if workflow_id:
                params['workflow_id'] = workflow_id
            if since:
                params['since'] = since
                
            result = await client.get('/logs', params)
            
            if result.get('logs'):
                for log in result['logs']:
                    timestamp = format_timestamp(log['timestamp'])
                    level_color = {
                        'ERROR': Colors.RED,
                        'WARNING': Colors.YELLOW,
                        'INFO': Colors.CYAN,
                        'DEBUG': Colors.BLUE
                    }.get(log['level'], '')
                    
                    prefix = f"[{timestamp}] {level_color}{log['level']}{Colors.RESET}"
                    if log.get('task_id'):
                        prefix += f" [{log['task_id'][:8]}]"
                    click.echo(f"{prefix}: {log['message']}")
            else:
                click.echo("No logs found")
        finally:
            await client.close()
            
    asyncio.run(_query())


@logs.command('search')
@click.argument('query')
@click.option('--task-id', help='Filter by task ID')
@click.option('--workflow-id', help='Filter by workflow ID')
@click.option('--limit', default=50, help='Maximum results')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def logs_search(query: str, task_id: Optional[str], workflow_id: Optional[str],
                limit: int, host: str, port: int):
    """Search logs by text"""
    async def _search():
        client = APIClient(host, port)
        try:
            params = {'query': query, 'limit': limit}
            if task_id:
                params['task_id'] = task_id
            if workflow_id:
                params['workflow_id'] = workflow_id
                
            result = await client.get('/logs/search', params)
            
            if result.get('logs'):
                click.echo(f"Found {len(result['logs'])} matching logs:\n")
                for log in result['logs']:
                    timestamp = format_timestamp(log['timestamp'])
                    level_color = {
                        'ERROR': Colors.RED,
                        'WARNING': Colors.YELLOW,
                        'INFO': Colors.CYAN,
                        'DEBUG': Colors.BLUE
                    }.get(log['level'], '')
                    
                    # Highlight matching text
                    message = log['message'].replace(query, f"{Colors.BOLD}{query}{Colors.RESET}")
                    click.echo(f"[{timestamp}] {level_color}{log['level']}{Colors.RESET}: {message}")
            else:
                click.echo("No matching logs found")
        finally:
            await client.close()
            
    asyncio.run(_search())


@logs.command('stats')
@click.option('--since', help='Statistics since timestamp')
@click.option('--until', help='Statistics until timestamp')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def logs_stats(since: Optional[str], until: Optional[str], host: str, port: int):
    """Get log statistics"""
    async def _stats():
        client = APIClient(host, port)
        try:
            params = {}
            if since:
                params['since'] = since
            if until:
                params['until'] = until
                
            result = await client.get('/logs/stats', params)
            
            click.echo(f"\n{Colors.BOLD}Log Statistics{Colors.RESET}")
            click.echo("=" * 50)
            click.echo(f"Total Logs: {result.get('total_logs', 0)}")
            click.echo(f"Storage Backend: {result.get('storage_backend', 'N/A')}")
            click.echo(f"Retention Days: {result.get('retention_days', 'N/A')}")
            
            if result.get('by_level'):
                click.echo(f"\n{Colors.CYAN}By Level:{Colors.RESET}")
                for level, count in result['by_level'].items():
                    click.echo(f"  {level}: {count}")
                    
            if result.get('by_source'):
                click.echo(f"\n{Colors.CYAN}By Source:{Colors.RESET}")
                for source, count in result['by_source'].items():
                    click.echo(f"  {source}: {count}")
                    
            if result.get('oldest_log'):
                click.echo(f"\nOldest: {format_timestamp(result['oldest_log'])}")
            if result.get('newest_log'):
                click.echo(f"Newest: {format_timestamp(result['newest_log'])}")
        finally:
            await client.close()
            
    asyncio.run(_stats())


@logs.command('cleanup')
@click.option('--days', default=30, help='Delete logs older than N days')
@click.option('--level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']),
              help='Only delete logs of this level or lower')
@click.option('--force', is_flag=True, help='Force cleanup without confirmation')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def logs_cleanup(days: int, level: Optional[str], force: bool, host: str, port: int):
    """Clean up old logs"""
    if not force:
        msg = f"Delete logs older than {days} days"
        if level:
            msg += f" (level {level} and lower)"
        if not click.confirm(f"{msg}?"):
            return
            
    async def _cleanup():
        client = APIClient(host, port)
        try:
            params = {'days': days}
            if level:
                params['level'] = level
                
            result = await client.delete('/logs/cleanup', params)
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} {result.get('message', 'Logs cleaned up')}")
        finally:
            await client.close()
            
    asyncio.run(_cleanup())


@logs.command('tail')
@click.argument('task_id')
@click.option('--lines', default=50, help='Number of lines to show')
@click.option('--follow', '-f', is_flag=True, help='Follow log output (not implemented)')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def logs_tail(task_id: str, lines: int, follow: bool, host: str, port: int):
    """Tail task logs"""
    if follow:
        click.echo("Warning: --follow not yet implemented, showing last logs only")
        
    async def _tail():
        client = APIClient(host, port)
        try:
            params = {'lines': lines}
            result = await client.get(f'/logs/tail/{task_id}', params)
            
            if isinstance(result, list):
                for log in result:
                    timestamp = format_timestamp(log['timestamp'])
                    level_color = {
                        'ERROR': Colors.RED,
                        'WARNING': Colors.YELLOW,
                        'INFO': Colors.CYAN,
                        'DEBUG': Colors.BLUE
                    }.get(log['level'], '')
                    
                    click.echo(f"[{timestamp}] {level_color}{log['level']}{Colors.RESET}: {log['message']}")
            else:
                click.echo("No logs found")
        finally:
            await client.close()
            
    asyncio.run(_tail())


# ============================================================================
# SYSTEM COMMANDS  
# ============================================================================

@click.group()
def system():
    """System management commands"""
    pass


@system.command('stats')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def system_stats(host: str, port: int):
    """Get system statistics"""
    async def _stats():
        client = APIClient(host, port)
        try:
            result = await client.get('/statistics/system')
            
            click.echo(f"\n{Colors.BOLD}System Statistics{Colors.RESET}")
            click.echo("=" * 50)
            
            if result.get('uptime_seconds'):
                hours = result['uptime_seconds'] / 3600
                click.echo(f"Uptime: {hours:.1f} hours")
                
            if result.get('tasks'):
                click.echo(f"\n{Colors.CYAN}Tasks:{Colors.RESET}")
                for key, value in result['tasks'].items():
                    click.echo(f"  {key}: {value}")
                    
            if result.get('workflows'):
                click.echo(f"\n{Colors.CYAN}Workflows:{Colors.RESET}")
                for key, value in result['workflows'].items():
                    click.echo(f"  {key}: {value}")
                    
            if result.get('queues'):
                click.echo(f"\n{Colors.CYAN}Queues:{Colors.RESET}")
                for key, value in result['queues'].items():
                    click.echo(f"  {key}: {value}")
                    
            if result.get('resources'):
                click.echo(f"\n{Colors.CYAN}Resources:{Colors.RESET}")
                click.echo(f"  CPU: {result['resources'].get('cpu_percent', 0):.1f}%")
                click.echo(f"  Memory: {result['resources'].get('memory_percent', 0):.1f}%")
        finally:
            await client.close()
            
    asyncio.run(_stats())


@system.command('cleanup')
@click.option('--days', default=30, help='Delete data older than N days')
@click.option('--force', is_flag=True, help='Force cleanup without confirmation')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def system_cleanup(days: int, force: bool, host: str, port: int):
    """Clean up old system data"""
    if not force:
        if not click.confirm(f"Delete all data older than {days} days?"):
            return
            
    async def _cleanup():
        client = APIClient(host, port)
        try:
            params = {'days': days}
            result = await client.delete('/cleanup', params)
            
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Cleanup completed")
            if result.get('tasks_deleted') is not None:
                click.echo(f"  Tasks deleted: {result['tasks_deleted']}")
            if result.get('workflows_deleted') is not None:
                click.echo(f"  Workflows deleted: {result['workflows_deleted']}")
            if result.get('logs_deleted') is not None:
                click.echo(f"  Logs deleted: {result['logs_deleted']}")
        finally:
            await client.close()
            
    asyncio.run(_cleanup())


@system.command('health')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def system_health(host: str, port: int):
    """Check system health"""
    async def _health():
        client = APIClient(host, port)
        try:
            result = await client.get('/health')
            
            if result.get('status') == 'healthy':
                click.echo(f"{Colors.GREEN}✓ System is healthy{Colors.RESET}")
            else:
                click.echo(f"{Colors.RED}✗ System is unhealthy{Colors.RESET}")
                
            if result.get('timestamp'):
                click.echo(f"Checked at: {format_timestamp(result['timestamp'])}")
        finally:
            await client.close()
            
    asyncio.run(_health())


# ============================================================================
# PROVIDER COMMANDS
# ============================================================================

@click.group()
def provider():
    """Provider management commands"""
    pass


@provider.command('list')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def provider_list(host: str, port: int):
    """List providers"""
    async def _list():
        client = APIClient(host, port)
        try:
            result = await client.get('/providers')
            
            if result.get('providers'):
                headers = ['ID', 'Name', 'Type', 'Status']
                data = []
                for prov in result['providers']:
                    data.append({
                        'ID': prov['id'],
                        'Name': prov.get('name', 'N/A'),
                        'Type': prov.get('type', 'N/A'),
                        'Status': prov.get('status', 'N/A')
                    })
                print_table(data, headers)
            else:
                click.echo("No providers found")
        finally:
            await client.close()
            
    asyncio.run(_list())


@provider.command('health')
@click.argument('provider_id')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def provider_health(provider_id: str, host: str, port: int):
    """Check provider health"""
    async def _health():
        client = APIClient(host, port)
        try:
            result = await client.post(f'/providers/{provider_id}/health')
            
            if result.get('healthy'):
                click.echo(f"{Colors.GREEN}✓ Provider '{provider_id}' is healthy{Colors.RESET}")
            else:
                click.echo(f"{Colors.RED}✗ Provider '{provider_id}' is unhealthy{Colors.RESET}")
                
            if result.get('details'):
                click.echo(f"\n{Colors.CYAN}Details:{Colors.RESET}")
                click.echo(json.dumps(result['details'], indent=2))
        finally:
            await client.close()
            
    asyncio.run(_health())


# ============================================================================
# EVENT ERROR COMMANDS
# ============================================================================

@click.group()
def errors():
    """Event error management commands"""
    pass


@errors.command('list')
@click.option('--event-type', help='Filter by event type')
@click.option('--handler', help='Filter by handler name')
@click.option('--limit', default=100, help='Maximum errors to return')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def errors_list(event_type: Optional[str], handler: Optional[str], limit: int,
                host: str, port: int):
    """List event errors"""
    async def _list():
        client = APIClient(host, port)
        try:
            params = {'limit': limit}
            if event_type:
                params['event_type'] = event_type
            if handler:
                params['handler_name'] = handler
                
            result = await client.get('/event-errors', params)
            
            if result:
                headers = ['ID', 'Handler', 'Event Type', 'Error', 'Timestamp']
                data = []
                for err in result:
                    data.append({
                        'ID': err['id'][:8],
                        'Handler': err.get('handler_name', 'N/A'),
                        'Event Type': err.get('event_type', 'N/A'),
                        'Error': err.get('error_message', 'N/A')[:40],
                        'Timestamp': format_timestamp(err['timestamp'])
                    })
                print_table(data, headers)
            else:
                click.echo("No event errors found")
        finally:
            await client.close()
            
    asyncio.run(_list())


@errors.command('stats')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def errors_stats(host: str, port: int):
    """Get event error statistics"""
    async def _stats():
        client = APIClient(host, port)
        try:
            result = await client.get('/event-errors/stats')
            
            click.echo(f"\n{Colors.BOLD}Event Error Statistics{Colors.RESET}")
            click.echo("=" * 50)
            click.echo(f"Total Errors: {result.get('total_errors', 0)}")
            
            if result.get('handlers_with_errors'):
                click.echo(f"\n{Colors.CYAN}By Handler:{Colors.RESET}")
                for handler, count in result['handlers_with_errors']:
                    click.echo(f"  {handler}: {count}")
                    
            if result.get('event_types_with_errors'):
                click.echo(f"\n{Colors.CYAN}By Event Type:{Colors.RESET}")
                for event_type, count in result['event_types_with_errors']:
                    click.echo(f"  {event_type}: {count}")
                    
            if result.get('oldest_error'):
                click.echo(f"\nOldest: {format_timestamp(result['oldest_error'])}")
            if result.get('newest_error'):
                click.echo(f"Newest: {format_timestamp(result['newest_error'])}")
        finally:
            await client.close()
            
    asyncio.run(_stats())


# ============================================================================
# AUTH COMMANDS (if auth is enabled)
# ============================================================================

@click.group()
def auth():
    """Authentication management commands"""
    pass


@auth.command('login')
@click.option('--email', prompt=True, help='User email')
@click.option('--password', prompt=True, hide_input=True, help='Password')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def auth_login(email: str, password: str, host: str, port: int):
    """Login to the system"""
    async def _login():
        client = APIClient(host, port)
        try:
            data = {'email': email, 'password': password}
            result = await client.post('/auth/login', data)
            
            if result.get('access_token'):
                # Save token to config file
                config_dir = Path.home() / '.gleitzeit'
                config_dir.mkdir(exist_ok=True)
                token_file = config_dir / '.token'
                
                with open(token_file, 'w') as f:
                    f.write(result['access_token'])
                    
                click.echo(f"{Colors.GREEN}✓{Colors.RESET} Login successful")
                click.echo(f"User: {result.get('user', {}).get('email')}")
                click.echo(f"Token saved to: {token_file}")
            else:
                click.echo(f"{Colors.RED}✗{Colors.RESET} Login failed")
        finally:
            await client.close()
            
    asyncio.run(_login())


@auth.command('logout')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def auth_logout(host: str, port: int):
    """Logout from the system"""
    async def _logout():
        client = APIClient(host, port)
        try:
            # Load token
            token_file = Path.home() / '.gleitzeit' / '.token'
            if not token_file.exists():
                click.echo("Not logged in")
                return
                
            with open(token_file, 'r') as f:
                token = f.read().strip()
                
            # Add token to client headers
            client.client.headers['Authorization'] = f'Bearer {token}'
            
            result = await client.post('/auth/logout')
            
            # Remove token file
            token_file.unlink()
            
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} Logged out successfully")
        finally:
            await client.close()
            
    asyncio.run(_logout())


@auth.command('register')
@click.option('--email', prompt=True, help='User email')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True,
              help='Password')
@click.option('--name', prompt=True, help='Full name')
@click.option('--role', default='user', help='User role')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def auth_register(email: str, password: str, name: str, role: str, host: str, port: int):
    """Register a new user"""
    async def _register():
        client = APIClient(host, port)
        try:
            data = {
                'email': email,
                'password': password,
                'name': name,
                'role_name': role
            }
            result = await client.post('/auth/register', data)
            
            click.echo(f"{Colors.GREEN}✓{Colors.RESET} User registered successfully")
            click.echo(f"User ID: {result.get('user_id')}")
            click.echo(f"Email: {email}")
            click.echo("You can now login with these credentials")
        finally:
            await client.close()
            
    asyncio.run(_register())


@auth.command('api-key')
@click.argument('action', type=click.Choice(['create', 'list', 'revoke']))
@click.option('--name', help='API key name (for create)')
@click.option('--key-id', help='API key ID (for revoke)')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def auth_api_key(action: str, name: Optional[str], key_id: Optional[str],
                 host: str, port: int):
    """Manage API keys"""
    async def _api_key():
        client = APIClient(host, port)
        try:
            # Load token
            token_file = Path.home() / '.gleitzeit' / '.token'
            if not token_file.exists():
                click.echo("Please login first")
                return
                
            with open(token_file, 'r') as f:
                token = f.read().strip()
                
            client.client.headers['Authorization'] = f'Bearer {token}'
            
            if action == 'create':
                if not name:
                    name = click.prompt('API key name')
                    
                data = {'name': name}
                result = await client.post('/auth/api-keys', data)
                
                click.echo(f"{Colors.GREEN}✓{Colors.RESET} API key created")
                click.echo(f"Name: {result.get('name')}")
                click.echo(f"Key: {Colors.BOLD}{result.get('key')}{Colors.RESET}")
                click.echo(f"\n{Colors.YELLOW}⚠️  Save this key securely - it won't be shown again{Colors.RESET}")
                
            elif action == 'list':
                result = await client.get('/auth/api-keys')
                
                if result:
                    headers = ['ID', 'Name', 'Created', 'Last Used']
                    data = []
                    for key in result:
                        data.append({
                            'ID': key['id'][:8],
                            'Name': key.get('name', 'N/A'),
                            'Created': format_timestamp(key['created_at']),
                            'Last Used': format_timestamp(key['last_used_at']) if key.get('last_used_at') else 'Never'
                        })
                    print_table(data, headers)
                else:
                    click.echo("No API keys found")
                    
            elif action == 'revoke':
                if not key_id:
                    key_id = click.prompt('API key ID to revoke')
                    
                if not click.confirm(f"Revoke API key {key_id}?"):
                    return
                    
                result = await client.delete(f'/auth/api-keys/{key_id}')
                click.echo(f"{Colors.GREEN}✓{Colors.RESET} API key revoked")
                
        finally:
            await client.close()
            
    asyncio.run(_api_key())


@auth.command('audit-logs')
@click.option('--user-id', help='Filter by user ID')
@click.option('--action', help='Filter by action type')
@click.option('--limit', default=50, help='Maximum logs to return')
@click.option('--host', default='localhost', help='API server host')
@click.option('--port', default=8000, help='API server port')
def auth_audit_logs(user_id: Optional[str], action: Optional[str], limit: int,
                   host: str, port: int):
    """View audit logs"""
    async def _audit():
        client = APIClient(host, port)
        try:
            # Load token
            token_file = Path.home() / '.gleitzeit' / '.token'
            if not token_file.exists():
                click.echo("Please login first")
                return
                
            with open(token_file, 'r') as f:
                token = f.read().strip()
                
            client.client.headers['Authorization'] = f'Bearer {token}'
            
            params = {'limit': limit}
            if user_id:
                params['user_id'] = user_id
            if action:
                params['action'] = action
                
            result = await client.get('/audit-logs', params)
            
            if result.get('audit_logs'):
                headers = ['Timestamp', 'User', 'Action', 'Resource', 'IP']
                data = []
                for log in result['audit_logs']:
                    data.append({
                        'Timestamp': format_timestamp(log['timestamp']),
                        'User': log.get('user_id', 'N/A')[:8] if log.get('user_id') else 'N/A',
                        'Action': log.get('action', 'N/A'),
                        'Resource': f"{log.get('resource_type', '')} {log.get('resource_id', '')[:8] if log.get('resource_id') else ''}".strip(),
                        'IP': log.get('ip_address', 'N/A')
                    })
                print_table(data, headers, max_width=30)
            else:
                click.echo("No audit logs found")
        finally:
            await client.close()
            
    asyncio.run(_audit())


# Export all command groups for integration
__all__ = ['task', 'workflow', 'queue', 'logs', 'system', 'provider', 'errors', 'auth']