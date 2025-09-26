"""
Port Management for Gleitzeit - Redis-based Multi-Machine Support

Manages distributed port allocation across multiple machines using Redis.
"""

import socket
import logging
import asyncio
import json
from typing import Dict, Optional, Tuple
from datetime import datetime

import redis.asyncio as aioredis

from .instance import get_current_instance

logger = logging.getLogger(__name__)


class PortManager:
    """Redis-based distributed port management for multi-machine deployments"""

    # Default base ports for services
    DEFAULT_PORTS = {
        "api": 8000,
        "ui": 8004,
        "metrics": 9090,
        "health": 8080,
        "grpc": 50051,
        "orchestrator": 8001,
        "worker": 8002
    }

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        """
        Initialize Port Manager with Redis backend

        Args:
            redis_client: Optional Redis client. If not provided, will create one.
        """
        self.instance = get_current_instance()
        if not self.instance:
            raise RuntimeError("Instance identity not initialized")

        self.redis = redis_client
        self.machine_id = getattr(self.instance, 'machine_id', socket.gethostname())
        self.port_ttl = 300  # 5 minutes default TTL
        self.refresh_interval = 120  # Refresh every 2 minutes
        self._refresh_tasks: Dict[str, asyncio.Task] = {}

    async def _ensure_redis(self):
        """Ensure Redis client is connected"""
        if self.redis is None:
            # Create Redis connection if not provided
            redis_url = "redis://localhost:6379"
            self.redis = await aioredis.from_url(redis_url, decode_responses=True)

    async def get_service_port(self, service_name: str) -> int:
        """
        Get port for a service with Redis-based allocation

        Args:
            service_name: Name of the service

        Returns:
            Port number for the service
        """
        await self._ensure_redis()

        # Check if already allocated for this instance
        instance_port_key = f"port:instance:{self.machine_id}:{self.instance.instance_id}:{service_name}"
        existing = await self.redis.get(instance_port_key)

        if existing:
            port = int(existing)
            logger.debug(f"Service {service_name} already has port {port}")
            return port

        # Calculate preferred port
        base_port = self.DEFAULT_PORTS.get(service_name, 8000)
        port = base_port + self.instance.port_offset

        # Try to allocate the port
        allocated_port = await self._allocate_port(service_name, port)

        # Start TTL refresh task for this port
        await self._start_refresh_task(service_name, allocated_port)

        return allocated_port

    async def _allocate_port(self, service_name: str, preferred_port: int) -> int:
        """
        Atomically allocate a port for a service

        Args:
            service_name: Name of the service
            preferred_port: Preferred port number

        Returns:
            Allocated port number
        """
        # Lua script for atomic port allocation
        allocation_script = """
        local machine_port_key = KEYS[1]
        local instance_port_key = KEYS[2]
        local port = ARGV[1]
        local instance_id = ARGV[2]
        local service = ARGV[3]
        local machine = ARGV[4]
        local ttl = ARGV[5]

        -- Check if port is already allocated on this machine
        local existing = redis.call('GET', machine_port_key)
        if existing then
            local data = cjson.decode(existing)
            -- Allow same instance to reclaim its port
            if data.instance_id ~= instance_id then
                return nil
            end
        end

        -- Allocate the port
        local allocation = cjson.encode({
            instance_id = instance_id,
            service = service,
            machine = machine,
            allocated_at = ARGV[6]
        })

        -- Set both keys atomically
        redis.call('SET', machine_port_key, allocation, 'EX', ttl)
        redis.call('SET', instance_port_key, port, 'EX', ttl)

        -- Add to machine's port set
        redis.call('SADD', 'machine:' .. machine .. ':ports', port)

        return port
        """

        # Try preferred port first
        port = preferred_port
        max_attempts = 100

        for attempt in range(max_attempts):
            machine_port_key = f"port:allocated:{self.machine_id}:{port}"
            instance_port_key = f"port:instance:{self.machine_id}:{self.instance.instance_id}:{service_name}"

            try:
                result = await self.redis.eval(
                    allocation_script,
                    2,  # Number of keys
                    machine_port_key,
                    instance_port_key,
                    str(port),
                    self.instance.instance_id,
                    service_name,
                    self.machine_id,
                    str(self.port_ttl),
                    datetime.utcnow().isoformat()
                )

                if result:
                    # Also check if port is actually available locally
                    if await self._check_local_port(port):
                        logger.info(f"Allocated port {port} for service {service_name} on machine {self.machine_id}")
                        return port
                    else:
                        # Port allocated in Redis but not available locally - release it
                        await self._release_port_allocation(machine_port_key, instance_port_key, port)

            except Exception as e:
                logger.warning(f"Error allocating port {port}: {e}")

            # Try next port
            port += 1

        raise RuntimeError(f"Could not allocate port for {service_name} after {max_attempts} attempts")

    async def _check_local_port(self, port: int, host: str = '0.0.0.0') -> bool:
        """
        Check if a port is available for binding locally

        Args:
            port: Port number to check
            host: Host address to check

        Returns:
            True if port is available, False otherwise
        """
        loop = asyncio.get_event_loop()

        def check_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind((host, port))
                    return True
                except socket.error:
                    return False

        return await loop.run_in_executor(None, check_port)

    async def _release_port_allocation(self, machine_port_key: str, instance_port_key: str, port: int):
        """Release a port allocation in Redis"""
        await self.redis.delete(machine_port_key)
        await self.redis.delete(instance_port_key)
        await self.redis.srem(f"machine:{self.machine_id}:ports", port)

    async def _start_refresh_task(self, service_name: str, port: int):
        """Start a background task to refresh port TTL"""
        task_key = f"{service_name}:{port}"

        # Cancel existing task if any
        if task_key in self._refresh_tasks:
            self._refresh_tasks[task_key].cancel()

        # Start new refresh task
        task = asyncio.create_task(self._refresh_ttl_loop(service_name, port))
        self._refresh_tasks[task_key] = task

    async def _refresh_ttl_loop(self, service_name: str, port: int):
        """Keep port allocation alive while service runs"""
        machine_port_key = f"port:allocated:{self.machine_id}:{port}"
        instance_port_key = f"port:instance:{self.machine_id}:{self.instance.instance_id}:{service_name}"

        while True:
            try:
                await asyncio.sleep(self.refresh_interval)

                # Refresh TTLs
                await self.redis.expire(machine_port_key, self.port_ttl)
                await self.redis.expire(instance_port_key, self.port_ttl)

                logger.debug(f"Refreshed TTL for port {port} (service: {service_name})")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error refreshing TTL for port {port}: {e}")
                break

    async def release_port(self, service_name: str):
        """
        Release a port allocation

        Args:
            service_name: Name of the service
        """
        await self._ensure_redis()

        # Get the port for this service
        instance_port_key = f"port:instance:{self.machine_id}:{self.instance.instance_id}:{service_name}"
        port_bytes = await self.redis.get(instance_port_key)

        if port_bytes:
            port = int(port_bytes)
            machine_port_key = f"port:allocated:{self.machine_id}:{port}"

            # Release the port
            await self._release_port_allocation(machine_port_key, instance_port_key, port)

            # Cancel refresh task
            task_key = f"{service_name}:{port}"
            if task_key in self._refresh_tasks:
                self._refresh_tasks[task_key].cancel()
                del self._refresh_tasks[task_key]

            logger.info(f"Released port {port} for service {service_name}")

    async def get_allocated_ports(self, machine_id: Optional[str] = None) -> Dict[str, int]:
        """
        Get all allocated ports

        Args:
            machine_id: Optional machine ID to filter by. Defaults to current machine.

        Returns:
            Dictionary of service names to ports
        """
        await self._ensure_redis()

        if machine_id is None:
            machine_id = self.machine_id

        allocated = {}

        # Scan for all port allocations on this machine
        pattern = f"port:allocated:{machine_id}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            for key in keys:
                # Parse port from key
                port = int(key.split(':')[-1])

                # Get allocation data
                data = await self.redis.get(key)
                if data:
                    allocation = json.loads(data)
                    service = allocation.get('service', 'unknown')
                    allocated[service] = port

            if cursor == 0:
                break

        return allocated

    async def check_port_conflicts(self) -> Dict[str, str]:
        """
        Check for port conflicts on this machine

        Returns:
            Dictionary of conflicting ports and their owners
        """
        await self._ensure_redis()

        conflicts = {}
        my_ports = await self.get_allocated_ports()

        # Get all port allocations on this machine
        all_ports = {}
        pattern = f"port:allocated:{self.machine_id}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            for key in keys:
                port = int(key.split(':')[-1])
                data = await self.redis.get(key)

                if data:
                    allocation = json.loads(data)
                    instance_id = allocation.get('instance_id')
                    service = allocation.get('service')

                    if instance_id != self.instance.instance_id:
                        # Check if this conflicts with our ports
                        for my_service, my_port in my_ports.items():
                            if my_port == port:
                                conflicts[f"{my_service}:{port}"] = f"{instance_id}/{service}"

            if cursor == 0:
                break

        return conflicts

    def is_port_available(self, port: int, host: str = '0.0.0.0') -> bool:
        """
        Synchronous check if a port is available (for compatibility)

        Args:
            port: Port number to check
            host: Host address to check

        Returns:
            True if port is available, False otherwise
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return True
            except socket.error:
                return False

    def find_available_port(self, base_port: int, max_attempts: int = 100) -> int:
        """
        Synchronous port finder (for compatibility)

        Args:
            base_port: Starting port to search from
            max_attempts: Maximum number of ports to try

        Returns:
            Available port number
        """
        for offset in range(max_attempts):
            port = base_port + offset
            if self.is_port_available(port):
                logger.info(f"Found available port {port} (base: {base_port})")
                return port

        raise RuntimeError(
            f"Could not find available port in range {base_port}-{base_port + max_attempts}"
        )

    async def cleanup(self):
        """Clean up resources"""
        # Cancel all refresh tasks
        for task in self._refresh_tasks.values():
            task.cancel()

        self._refresh_tasks.clear()

        # Close Redis connection if we created it
        if self.redis:
            await self.redis.close()