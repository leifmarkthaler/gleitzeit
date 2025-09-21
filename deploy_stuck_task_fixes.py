#!/usr/bin/env python
"""
Deploy stuck task fixes with monitoring.

This script:
1. Checks current stuck tasks
2. Restarts gleitzeit server with fixes
3. Monitors the system post-deployment
4. Verifies fixes are working
"""

import asyncio
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import TaskStatus


class DeploymentMonitor:
    def __init__(self):
        self.persistence = None
        self.server_process = None
        self.original_stuck_tasks = []
    
    async def initialize(self):
        """Initialize Redis connection."""
        self.persistence = UnifiedRedisAdapter(redis_url="redis://localhost:6379/0")
        await self.persistence.initialize()
    
    async def check_stuck_tasks(self):
        """Get current stuck tasks."""
        executing_tasks = await self.persistence.get_tasks_by_status(TaskStatus.EXECUTING.value)
        stuck_tasks = []
        
        for task in executing_tasks:
            if task.started_at:
                elapsed = datetime.utcnow() - task.started_at
                if elapsed.total_seconds() > 300:  # > 5 minutes
                    stuck_tasks.append({
                        'id': task.id,
                        'name': task.name,
                        'started_at': task.started_at,
                        'elapsed_seconds': elapsed.total_seconds()
                    })
        
        return stuck_tasks
    
    def kill_existing_servers(self):
        """Kill existing gleitzeit servers."""
        try:
            # Find gleitzeit serve processes
            result = subprocess.run(['pgrep', '-f', 'gleitzeit serve'], 
                                  capture_output=True, text=True)
            
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"Found {len(pids)} existing gleitzeit serve process(es)")
                
                for pid in pids:
                    print(f"Terminating process {pid}")
                    subprocess.run(['kill', '-TERM', pid], check=False)
                
                # Wait for graceful shutdown
                time.sleep(3)
                
                # Force kill if still running
                for pid in pids:
                    try:
                        subprocess.run(['kill', '-0', pid], check=True, 
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        print(f"Force killing process {pid}")
                        subprocess.run(['kill', '-KILL', pid], check=False)
                    except subprocess.CalledProcessError:
                        # Process already dead
                        pass
                        
                print("Existing servers stopped")
            else:
                print("No existing gleitzeit serve processes found")
                
        except Exception as e:
            print(f"Error stopping servers: {e}")
    
    def start_server(self):
        """Start new gleitzeit server with fixes."""
        print("Starting gleitzeit server with fixes...")
        
        self.server_process = subprocess.Popen([
            sys.executable, '-m', 'gleitzeit.cli.main', 'serve', '--port', '8000'
        ], cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait a bit for startup
        time.sleep(5)
        
        if self.server_process.poll() is None:
            print("✅ Server started successfully")
            return True
        else:
            print("❌ Server failed to start")
            stdout, stderr = self.server_process.communicate()
            print(f"STDOUT: {stdout.decode()}")
            print(f"STDERR: {stderr.decode()}")
            return False
    
    async def monitor_deployment(self, duration_minutes=10):
        """Monitor system after deployment."""
        print(f"\nMonitoring system for {duration_minutes} minutes...")
        
        start_time = datetime.utcnow()
        check_interval = 30  # Check every 30 seconds
        
        while (datetime.utcnow() - start_time).total_seconds() < duration_minutes * 60:
            try:
                # Check current stuck tasks
                stuck_tasks = await self.check_stuck_tasks()
                
                print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
                      f"Stuck tasks: {len(stuck_tasks)}")
                
                if stuck_tasks:
                    for task in stuck_tasks:
                        elapsed_min = task['elapsed_seconds'] / 60
                        print(f"  - {task['id']}: {elapsed_min:.1f} minutes")
                
                # Check if original stuck tasks are still there
                if self.original_stuck_tasks:
                    still_stuck = [
                        task for task in stuck_tasks 
                        if task['id'] in [t['id'] for t in self.original_stuck_tasks]
                    ]
                    
                    if still_stuck:
                        print(f"  ⚠️  {len(still_stuck)} original stuck tasks still present")
                    else:
                        print(f"  ✅ All original stuck tasks have been cleaned up!")
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                await asyncio.sleep(check_interval)
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.persistence:
            await self.persistence.shutdown()
        
        if self.server_process and self.server_process.poll() is None:
            print("Stopping server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server_process.kill()


async def main():
    """Main deployment function."""
    print("=== Gleitzeit Stuck Task Fixes Deployment ===\n")
    
    monitor = DeploymentMonitor()
    
    try:
        await monitor.initialize()
        
        # 1. Check current stuck tasks
        print("1. Checking current stuck tasks...")
        monitor.original_stuck_tasks = await monitor.check_stuck_tasks()
        
        if monitor.original_stuck_tasks:
            print(f"Found {len(monitor.original_stuck_tasks)} stuck tasks:")
            for task in monitor.original_stuck_tasks:
                elapsed_min = task['elapsed_seconds'] / 60
                print(f"  - {task['id']} ({task['name']}): {elapsed_min:.1f} minutes")
        else:
            print("No stuck tasks found")
        
        # 2. Deploy fixes
        print("\n2. Deploying fixes...")
        monitor.kill_existing_servers()
        
        if not monitor.start_server():
            print("❌ Deployment failed - server did not start")
            return
        
        print("✅ Deployment successful!")
        
        # 3. Monitor system
        print("\n3. Monitoring system behavior...")
        await monitor.monitor_deployment(duration_minutes=5)
        
        print("\n=== Deployment Complete ===")
        print("✅ Fixes deployed successfully")
        print("✅ System monitoring completed")
        
        if monitor.original_stuck_tasks:
            print(f"📊 Original stuck tasks: {len(monitor.original_stuck_tasks)}")
            print("🔄 Monitor logs above to see cleanup progress")
        
    except KeyboardInterrupt:
        print("\nDeployment interrupted by user")
    except Exception as e:
        print(f"Deployment error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await monitor.cleanup()


if __name__ == "__main__":
    asyncio.run(main())