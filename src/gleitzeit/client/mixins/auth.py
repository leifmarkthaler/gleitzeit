"""
Authentication mixin for Gleitzeit client.
"""

from typing import Any, Dict, Optional, List


class AuthMixin:
    """Mixin providing authentication operations."""
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login user."""
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.login(username, password)
    
    async def logout(self) -> Dict[str, Any]:
        """Logout current user."""
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.logout()
    
    async def get_current_user(self) -> Dict[str, Any]:
        """Get current authenticated user."""
        if not self._adapter:
            raise RuntimeError("Client not initialized")
        return await self._adapter.get_current_user()