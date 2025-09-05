"""
Leader Election for Distributed SystemManager.

Implements leader election using Redis locks to ensure only one
SystemManager instance acts as the primary coordinator.
"""

import asyncio
import logging
import uuid
from typing import Optional, Callable, Any
from datetime import datetime, timedelta

from ..persistence.base import PersistenceBackend

logger = logging.getLogger(__name__)


class LeaderElection:
    """
    Leader election mechanism for distributed SystemManager instances.
    
    Uses Redis atomic operations to ensure only one leader at a time.
    Supports automatic failover and leader callbacks.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        instance_id: Optional[str] = None,
        lease_duration: int = 30,
        renewal_interval: int = 10,
        election_check_interval: float = 1.0
    ):
        """
        Initialize leader election.
        
        Args:
            persistence: Backend for leader state
            instance_id: Unique instance identifier (auto-generated if not provided)
            lease_duration: How long leadership lasts without renewal (seconds)
            renewal_interval: How often to renew leadership (seconds)
            election_check_interval: How often to check for leadership opportunity (seconds)
        """
        self.persistence = persistence
        self.instance_id = instance_id or f"system_{uuid.uuid4().hex[:12]}"
        self.lease_duration = lease_duration
        self.renewal_interval = renewal_interval
        self.election_check_interval = election_check_interval  # Fast checks for initial election
        
        self._leader_key = "system:leader:current"
        self._leader_lock_key = "system:leader:lock"
        self._candidates_key = "system:leader:candidates"
        
        self._is_leader = False
        self._running = False
        self._renewal_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._on_elected: Optional[Callable] = None
        self._on_demoted: Optional[Callable] = None
        
    def set_callbacks(
        self,
        on_elected: Optional[Callable] = None,
        on_demoted: Optional[Callable] = None
    ):
        """
        Set callbacks for leadership changes.
        
        Args:
            on_elected: Called when this instance becomes leader
            on_demoted: Called when this instance loses leadership
        """
        self._on_elected = on_elected
        self._on_demoted = on_demoted
    
    async def start(self) -> None:
        """Start participating in leader election."""
        if self._running:
            return
        
        self._running = True
        logger.info(f"Starting leader election for instance {self.instance_id}")
        
        # Register as candidate
        await self._register_candidate()
        
        # Try to become leader
        await self._attempt_leadership()
        
        # Start election loop
        asyncio.create_task(self._election_loop())
    
    async def stop(self) -> None:
        """Stop participating in leader election."""
        self._running = False
        
        # Cancel renewal task
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        
        # Step down if leader
        if self._is_leader:
            await self._step_down()
        
        # Remove from candidates
        await self._unregister_candidate()
        
        logger.info(f"Stopped leader election for instance {self.instance_id}")
    
    def is_leader(self) -> bool:
        """Check if this instance is the current leader."""
        return self._is_leader
    
    async def get_leader(self) -> Optional[str]:
        """Get the current leader instance ID."""
        data = await self.persistence.get(self._leader_key)
        if data:
            import json
            # Handle different data formats
            if isinstance(data, dict):
                leader_info = data
            elif isinstance(data, bytes):
                leader_info = json.loads(data.decode())
            else:
                leader_info = json.loads(data)
            # Check if lease is still valid
            expires_at = datetime.fromisoformat(leader_info["expires_at"])
            if datetime.utcnow() < expires_at:
                return leader_info["instance_id"]
        return None
    
    async def _attempt_leadership(self) -> bool:
        """
        Attempt to become the leader.
        
        Returns:
            True if became leader, False otherwise
        """
        import json
        
        lock_value = f"{self.instance_id}:{uuid.uuid4().hex}"
        expires_at = datetime.utcnow() + timedelta(seconds=self.lease_duration)
        
        leader_info = {
            "instance_id": self.instance_id,
            "lock_value": lock_value,
            "elected_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat()
        }
        
        # Check if persistence supports atomic operations
        supports_atomic = hasattr(self.persistence, 'supports_atomic_operations') and \
                         self.persistence.supports_atomic_operations()
        
        if not supports_atomic:
            # For non-atomic backends (like in-memory), use a simple approach
            # This is only suitable for single-instance development mode
            logger.warning(
                "Persistence backend does not support atomic operations. "
                "Leader election will not work correctly with multiple instances. "
                "Use Redis or another distributed backend for production."
            )
            # In development, just become leader
            await self.persistence.set(self._leader_key, json.dumps(leader_info))
            await self._become_leader()
            return True
        
        # For atomic backends, use proper distributed locking
        # Try to acquire lock atomically
        acquired = False
        
        # Check current lock
        current_lock = await self.persistence.get(self._leader_lock_key)
        current_leader = await self.persistence.get(self._leader_key)
        
        if current_lock is None:
            # No lock exists, try to acquire atomically
            if hasattr(self.persistence, 'set_nx'):
                # Use atomic SET NX operation
                acquired = await self.persistence.set_nx(
                    self._leader_lock_key,
                    lock_value,
                    ex=self.lease_duration
                )
            else:
                # Fallback for adapters without SET NX (still has race condition)
                await self.persistence.set(
                    self._leader_lock_key,
                    lock_value,
                    ex=self.lease_duration
                )
                # Check if we got it (race condition possible without true SET NX)
                check_lock = await self.persistence.get(self._leader_lock_key)
                if check_lock == lock_value:
                    acquired = True
        elif isinstance(current_lock, str) and current_lock.startswith(self.instance_id):
            # We already have the lock, renew it
            await self.persistence.set(
                self._leader_lock_key,
                lock_value,
                ex=self.lease_duration
            )
            acquired = True
        elif current_leader:
            # Check if current leader's lease has expired
            try:
                # Handle different data formats
                if isinstance(current_leader, dict):
                    leader_data = current_leader
                elif isinstance(current_leader, bytes):
                    leader_data = json.loads(current_leader.decode())
                else:
                    leader_data = json.loads(current_leader)
                    
                expires = datetime.fromisoformat(leader_data["expires_at"])
                if datetime.utcnow() > expires:
                    # Leader lease expired, try to take over
                    # First delete the expired lock
                    await self.persistence.delete(self._leader_lock_key)
                    # Now try to acquire atomically
                    if hasattr(self.persistence, 'set_nx'):
                        acquired = await self.persistence.set_nx(
                            self._leader_lock_key,
                            lock_value,
                            ex=self.lease_duration
                        )
                    else:
                        # Fallback (has race condition)
                        await self.persistence.set(
                            self._leader_lock_key,
                            lock_value,
                            ex=self.lease_duration
                        )
                        check_lock = await self.persistence.get(self._leader_lock_key)
                        if check_lock == lock_value:
                            acquired = True
            except:
                pass
        
        if acquired:
            # We got the lock, now set leader info
            await self.persistence.set(self._leader_key, json.dumps(leader_info))
            await self._become_leader()
            return True
        
        return False
    
    async def _become_leader(self) -> None:
        """Handle becoming the leader."""
        if self._is_leader:
            return
        
        self._is_leader = True
        logger.info(f"Instance {self.instance_id} became leader")
        
        # Start renewal task
        self._renewal_task = asyncio.create_task(self._renewal_loop())
        
        # Call callback
        if self._on_elected:
            try:
                result = self._on_elected()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in on_elected callback: {e}")
    
    async def _step_down(self) -> None:
        """Handle stepping down as leader."""
        if not self._is_leader:
            return
        
        self._is_leader = False
        logger.info(f"Instance {self.instance_id} stepped down as leader")
        
        # Cancel renewal
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        
        # Release lock
        await self.persistence.delete(self._leader_lock_key)
        await self.persistence.delete(self._leader_key)
        
        # Call callback
        if self._on_demoted:
            try:
                result = self._on_demoted()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in on_demoted callback: {e}")
    
    async def _renewal_loop(self) -> None:
        """Continuously renew leadership while leader."""
        while self._running and self._is_leader:
            try:
                await asyncio.sleep(self.renewal_interval)
                
                # Renew leadership
                if not await self._attempt_leadership():
                    # Lost leadership
                    await self._step_down()
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in renewal loop: {e}")
                await self._step_down()
                break
    
    async def _election_loop(self) -> None:
        """Main election loop for non-leaders."""
        while self._running:
            try:
                if not self._is_leader:
                    # Check if leader exists
                    current_leader = await self.get_leader()
                    if not current_leader:
                        # No leader, try to become one
                        await self._attempt_leadership()
                    
                # Use fast election check interval for quick initial election
                await asyncio.sleep(self.election_check_interval)
                
            except Exception as e:
                logger.error(f"Error in election loop: {e}")
                await asyncio.sleep(self.election_check_interval)
    
    async def _register_candidate(self) -> None:
        """Register this instance as a candidate."""
        import json
        
        # Get current candidates
        data = await self.persistence.get(self._candidates_key)
        if data:
            # Handle different data formats from different backends
            if isinstance(data, dict):
                candidates = data
            elif isinstance(data, bytes):
                candidates = json.loads(data.decode())
            else:
                candidates = json.loads(data)
        else:
            candidates = {}
        
        # Add or update this instance
        candidates[self.instance_id] = {
            "registered_at": datetime.utcnow().isoformat(),
            "last_seen": datetime.utcnow().isoformat()
        }
        
        await self.persistence.set(self._candidates_key, json.dumps(candidates))
    
    async def _unregister_candidate(self) -> None:
        """Remove this instance from candidates."""
        import json
        
        # Get current candidates
        data = await self.persistence.get(self._candidates_key)
        if not data:
            return
        
        # Handle different data formats from different backends
        if isinstance(data, dict):
            candidates = data
        elif isinstance(data, bytes):
            candidates = json.loads(data.decode())
        else:
            candidates = json.loads(data)
        
        # Remove this instance
        if self.instance_id in candidates:
            del candidates[self.instance_id]
            await self.persistence.set(self._candidates_key, json.dumps(candidates))
    
    async def get_candidates(self) -> dict:
        """
        Get all registered candidates.
        
        Returns:
            Dictionary of instance_id -> candidate info
        """
        import json
        data = await self.persistence.get(self._candidates_key)
        if data:
            # Handle different data formats from different backends
            if isinstance(data, dict):
                return data
            elif isinstance(data, bytes):
                return json.loads(data.decode())
            else:
                return json.loads(data)
        return {}
    
    async def force_election(self) -> None:
        """Force a new election by clearing current leader."""
        if hasattr(self.persistence, 'redis'):
            await self.persistence.redis.delete(self._leader_lock_key)
        await self.persistence.delete(self._leader_key)
        
        # Try to become leader
        await self._attempt_leadership()