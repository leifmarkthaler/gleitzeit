"""
System operations mixin for Gleitzeit client.
"""

from typing import Any, Dict, List

from gleitzeit.core.errors import SystemError


class SystemMixin:
    """Mixin providing system operations."""
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get system status."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_system_status()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.health_check()
    
    async def get_providers(self) -> List[Dict[str, Any]]:
        """Get available providers."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_providers()
    
    async def get_protocols(self) -> List[Dict[str, Any]]:
        """Get available protocols."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.get_protocols()
    
    async def chat(self, message: str, model: str = "llama3.2:latest",
                  temperature: float = 0.7,
                  session_id: str = None) -> Dict[str, Any]:
        """Chat with LLM."""
        if not self._adapter:
            raise SystemError("Client not initialized")
        return await self._adapter.chat(message, model, temperature, session_id)