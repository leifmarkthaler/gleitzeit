"""
Service Auto-Start Manager for Gleitzeit Cluster

Automatically checks for and starts required services (Redis, executor nodes)
when they're not running.
"""

import asyncio
import subprocess
import time
import socket
import redis
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages automatic startup of required services"""
    
    def __init__(self):
        self.redis_process: Optional[subprocess.Popen] = None
        self.executor_processes: List[subprocess.Popen] = []
        
    def is_port_open(self, host: str, port: int, timeout: float = 1.0) -> bool:
        """Check if a port is open"""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.error, socket.timeout):
            return False
    
    def is_redis_running(self, redis_url: str = "redis://localhost:6379") -> bool:
        """Check if Redis is running and accessible"""
        try:
            # Parse Redis URL to get host and port
            if redis_url.startswith("redis://"):
                parts = redis_url.replace("redis://", "").split(":")
                host = parts[0] if parts[0] else "localhost"
                port = int(parts[1]) if len(parts) > 1 else 6379
            else:
                host, port = "localhost", 6379
            
            # Try to connect to Redis
            client = redis.Redis(host=host, port=port, socket_connect_timeout=1)
            client.ping()
            return True
        except Exception:
            return False
    
    def start_redis_server(self) -> bool:
        """Start Redis server if not running"""
        try:
            print("🔄 Starting Redis server...")
            
            # Try to start Redis as a daemon
            result = subprocess.run(
                ["redis-server", "--daemonize", "yes", "--port", "6379"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Wait a moment for Redis to start
                time.sleep(2)
                
                # Verify it's running
                if self.is_redis_running():
                    print("✅ Redis server started successfully")
                    return True
                else:
                    print("❌ Redis server failed to start properly")
                    return False
            else:
                print(f"❌ Failed to start Redis: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Redis startup timed out")
            return False
        except FileNotFoundError:
            print("❌ redis-server command not found. Please install Redis.")
            return False
        except Exception as e:
            print(f"❌ Error starting Redis: {e}")
            return False
    
    def start_executor_node(self, 
                           name: str = "auto-executor-1",
                           cluster_url: str = "http://localhost:8000",
                           max_tasks: int = 4) -> bool:
        """Start an executor node"""
        try:
            print(f"🔄 Starting executor node: {name}...")
            
            # Start executor in background
            process = subprocess.Popen([
                "gleitzeit", "executor",
                "--name", name,
                "--cluster", cluster_url,
                "--tasks", str(max_tasks),
                "--log-level", "WARNING"  # Reduce log noise
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Give it a moment to start
            time.sleep(3)
            
            # Check if process is still running
            if process.poll() is None:
                print(f"✅ Executor node {name} started successfully")
                self.executor_processes.append(process)
                return True
            else:
                stdout, stderr = process.communicate()
                print(f"❌ Executor node {name} failed to start:")
                if stderr:
                    print(f"   Error: {stderr.decode()}")
                return False
                
        except FileNotFoundError:
            print("❌ gleitzeit command not found")
            return False
        except Exception as e:
            print(f"❌ Error starting executor node: {e}")
            return False
    
    async def ensure_services_running(self, 
                                    redis_url: str = "redis://localhost:6379",
                                    socketio_url: str = "http://localhost:8000",
                                    auto_start_redis: bool = True,
                                    auto_start_executor: bool = True,
                                    min_executors: int = 1) -> Dict[str, bool]:
        """Ensure all required services are running"""
        results = {
            "redis": False,
            "executors": False,
            "services_started": []
        }
        
        # Check and start Redis if needed
        if auto_start_redis:
            if self.is_redis_running(redis_url):
                print("✅ Redis is already running")
                results["redis"] = True
            else:
                print("⚠️  Redis not found - attempting to start...")
                if self.start_redis_server():
                    results["redis"] = True
                    results["services_started"].append("redis")
                else:
                    print("❌ Could not start Redis server")
        else:
            results["redis"] = self.is_redis_running(redis_url)
        
        # Start executor nodes if needed
        if auto_start_executor and results["redis"]:  # Only start executors if Redis is available
            print(f"🔄 Ensuring {min_executors} executor node(s) are available...")
            
            # For simplicity, start the requested number of executors
            # In a production system, we'd check how many are already registered
            executors_started = 0
            for i in range(min_executors):
                executor_name = f"auto-executor-{i+1}"
                if self.start_executor_node(name=executor_name, cluster_url=socketio_url):
                    executors_started += 1
                    
            if executors_started > 0:
                results["executors"] = True
                results["services_started"].append(f"{executors_started}_executors")
                
                # Give executors time to register with the cluster
                print("⏳ Waiting for executor nodes to register...")
                await asyncio.sleep(5)
            else:
                print("❌ Could not start any executor nodes")
        
        return results
    
    def stop_managed_services(self):
        """Stop services that were started by this manager"""
        stopped = []
        
        # Stop executor processes
        for process in self.executor_processes:
            if process.poll() is None:  # Still running
                try:
                    process.terminate()
                    process.wait(timeout=5)
                    stopped.append("executor")
                except subprocess.TimeoutExpired:
                    process.kill()
                    stopped.append("executor (forced)")
                except Exception as e:
                    logger.error(f"Error stopping executor: {e}")
        
        self.executor_processes.clear()
        
        # Note: We don't stop Redis since other applications might be using it
        # and it was started as a daemon
        
        if stopped:
            print(f"🛑 Stopped managed services: {', '.join(stopped)}")
        
        return stopped