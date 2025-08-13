"""
Provider Manager for Gleitzeit V2

Manages provider registration, discovery, and task assignment.
Pure Socket.IO based communication.
"""

import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

from .models import Provider, Task, TaskType, ProviderCapabilities

logger = logging.getLogger(__name__)


class ProviderManager:
    """
    Manages providers in the Gleitzeit system
    
    Features:
    - Provider registration and discovery
    - Capability-based task routing
    - Health monitoring and heartbeat tracking
    - Load balancing across providers
    """
    
    def __init__(self):
        self.providers: Dict[str, Provider] = {}
        self.socket_to_provider: Dict[str, str] = {}  # socket_id -> provider_id
        
        # Health monitoring
        self.heartbeat_timeout = timedelta(minutes=2)
        
        logger.info("ProviderManager initialized")
    
    async def register_provider(self, socket_id: str, provider_data: Dict) -> str:
        """Register a new provider"""
        try:
            # Create provider from registration data
            provider = Provider(
                id=provider_data.get('id', f"provider_{socket_id}"),
                name=provider_data.get('name', 'Unknown Provider'),
                type=provider_data.get('type', 'external'),
                socket_id=socket_id,
                status='active'
            )
            
            # Parse capabilities
            if 'capabilities' in provider_data:
                provider.capabilities = ProviderCapabilities.from_dict(provider_data['capabilities'])
            
            # Store provider
            self.providers[provider.id] = provider
            self.socket_to_provider[socket_id] = provider.id
            
            logger.info(f"Provider registered: {provider.name} ({provider.id})")
            logger.info(f"  Type: {provider.type}")
            logger.info(f"  Task types: {[t.value for t in provider.capabilities.task_types]}")
            logger.info(f"  Models: {provider.capabilities.models}")
            
            return provider.id
            
        except Exception as e:
            logger.error(f"Failed to register provider: {e}")
            raise
    
    async def unregister_provider(self, socket_id: str) -> Optional[str]:
        """Unregister provider by socket ID"""
        provider_id = self.socket_to_provider.get(socket_id)
        if not provider_id:
            return None
        
        # Remove provider
        if provider_id in self.providers:
            provider = self.providers.pop(provider_id)
            logger.info(f"Provider unregistered: {provider.name} ({provider_id})")
        
        # Remove socket mapping
        self.socket_to_provider.pop(socket_id, None)
        
        return provider_id
    
    async def unregister_provider_by_id(self, provider_id: str) -> bool:
        """Unregister provider by ID"""
        if provider_id not in self.providers:
            return False
        
        provider = self.providers.pop(provider_id)
        
        # Remove socket mapping if exists
        if provider.socket_id in self.socket_to_provider:
            self.socket_to_provider.pop(provider.socket_id)
        
        logger.info(f"Provider unregistered by ID: {provider.name} ({provider_id})")
        return True
    
    async def update_heartbeat(self, provider_id: str):
        """Update provider heartbeat"""
        if provider_id in self.providers:
            self.providers[provider_id].last_heartbeat = datetime.utcnow()
    
    async def update_capabilities(self, provider_id: str, capabilities: Dict):
        """Update provider capabilities"""
        if provider_id in self.providers:
            self.providers[provider_id].capabilities = ProviderCapabilities.from_dict(capabilities)
            logger.info(f"Updated capabilities for provider: {provider_id}")
    
    def get_provider(self, provider_id: str) -> Optional[Provider]:
        """Get provider by ID"""
        return self.providers.get(provider_id)
    
    def get_provider_by_socket(self, socket_id: str) -> Optional[Provider]:
        """Get provider by socket ID"""
        provider_id = self.socket_to_provider.get(socket_id)
        return self.providers.get(provider_id) if provider_id else None
    
    def find_providers_for_task(self, task: Task) -> List[Provider]:
        """Find providers that can handle a task"""
        candidates = []
        
        for provider in self.providers.values():
            if provider.can_handle_task(task):
                candidates.append(provider)
        
        # Sort by availability (least loaded first)
        candidates.sort(key=lambda p: (p.current_tasks, -p.tasks_completed))
        
        return candidates
    
    def get_best_provider_for_task(self, task: Task) -> Optional[Provider]:
        """Get the best provider for a task"""
        candidates = self.find_providers_for_task(task)
        return candidates[0] if candidates else None
    
    def get_providers_by_type(self, provider_type: str) -> List[Provider]:
        """Get all providers of a specific type"""
        return [p for p in self.providers.values() if p.type == provider_type]
    
    def get_providers_by_task_type(self, task_type: TaskType) -> List[Provider]:
        """Get providers that can handle a specific task type"""
        return [
            p for p in self.providers.values()
            if task_type in p.capabilities.task_types and p.is_available()
        ]
    
    def get_active_providers(self) -> List[Provider]:
        """Get all active providers"""
        return [p for p in self.providers.values() if p.status == 'active']
    
    def get_available_providers(self) -> List[Provider]:
        """Get providers available for new tasks"""
        return [p for p in self.providers.values() if p.is_available()]
    
    async def mark_provider_busy(self, provider_id: str, task_id: str):
        """Mark provider as busy with a task"""
        if provider_id in self.providers:
            provider = self.providers[provider_id]
            provider.current_tasks += 1
            
            if provider.current_tasks >= provider.max_concurrent:
                provider.status = 'busy'
            
            logger.debug(f"Provider {provider_id} now has {provider.current_tasks} tasks")
    
    async def mark_provider_available(self, provider_id: str, task_id: str, success: bool = True):
        """Mark provider as available after task completion"""
        if provider_id in self.providers:
            provider = self.providers[provider_id]
            provider.current_tasks = max(0, provider.current_tasks - 1)
            
            if success:
                provider.tasks_completed += 1
            else:
                provider.tasks_failed += 1
            
            # Update status
            if provider.current_tasks < provider.max_concurrent:
                provider.status = 'active'
            
            logger.debug(f"Provider {provider_id} now has {provider.current_tasks} tasks")
    
    async def check_provider_health(self):
        """Check health of all providers"""
        now = datetime.utcnow()
        unhealthy_providers = []
        
        for provider_id, provider in self.providers.items():
            time_since_heartbeat = now - provider.last_heartbeat
            
            if time_since_heartbeat > self.heartbeat_timeout:
                logger.warning(f"Provider {provider_id} missed heartbeat ({time_since_heartbeat})")
                provider.status = 'error'
                unhealthy_providers.append(provider_id)
        
        return unhealthy_providers
    
    def get_provider_count(self) -> int:
        """Get total number of registered providers"""
        return len(self.providers)
    
    def get_stats(self) -> Dict:
        """Get provider manager statistics"""
        by_type = {}
        by_status = {}
        
        for provider in self.providers.values():
            # Count by type
            by_type[provider.type] = by_type.get(provider.type, 0) + 1
            
            # Count by status
            by_status[provider.status] = by_status.get(provider.status, 0) + 1
        
        total_tasks_completed = sum(p.tasks_completed for p in self.providers.values())
        total_tasks_failed = sum(p.tasks_failed for p in self.providers.values())
        current_load = sum(p.current_tasks for p in self.providers.values())
        
        return {
            'total_providers': len(self.providers),
            'by_type': by_type,
            'by_status': by_status,
            'total_tasks_completed': total_tasks_completed,
            'total_tasks_failed': total_tasks_failed,
            'current_load': current_load,
            'available_capacity': sum(
                p.max_concurrent - p.current_tasks 
                for p in self.providers.values() 
                if p.is_available()
            )
        }