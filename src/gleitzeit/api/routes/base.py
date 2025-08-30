"""
Base infrastructure for modular API routes.
"""

from typing import Dict, Any, Optional
from fastapi import HTTPException, Request
from gleitzeit.client import GleitzeitClient, ClientMode
import asyncio
import logging

logger = logging.getLogger(__name__)


class APIRouteBase:
    """Base class for API route modules that delegate to client methods."""
    
    def __init__(self, client: GleitzeitClient):
        """
        Initialize with a shared client instance.
        
        Args:
            client: Initialized GleitzeitClient instance
        """
        self.client = client
        self.logger = logger.getChild(self.__class__.__name__)
    
    async def handle_client_call(self, client_method_name: str, *args, **kwargs) -> Dict[str, Any]:
        """
        Generic handler for client method calls with proper error handling.
        
        Args:
            client_method_name: Name of the client method to call
            *args: Positional arguments for the client method
            **kwargs: Keyword arguments for the client method
            
        Returns:
            Result from client method call
            
        Raises:
            HTTPException: On client errors or method not found
        """
        try:
            # Get the client method
            if not hasattr(self.client, client_method_name):
                raise HTTPException(
                    status_code=501,
                    detail=f"Client method '{client_method_name}' not implemented"
                )
            
            method = getattr(self.client, client_method_name)
            
            # Call the method
            if asyncio.iscoroutinefunction(method):
                result = await method(*args, **kwargs)
            else:
                result = method(*args, **kwargs)
            
            self.logger.debug(f"Successfully called {client_method_name}")
            return result
            
        except RuntimeError as e:
            if "not initialized" in str(e):
                raise HTTPException(status_code=503, detail="Service temporarily unavailable")
            raise HTTPException(status_code=500, detail=str(e))
        
        except NotImplementedError as e:
            raise HTTPException(status_code=501, detail=str(e))
        
        except Exception as e:
            self.logger.error(f"Error in {client_method_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
    def require_auth(self, request: Request) -> Optional[str]:
        """
        Extract user ID from authenticated request.
        
        Args:
            request: FastAPI request object
            
        Returns:
            User ID if authenticated, None otherwise
            
        Raises:
            HTTPException: If authentication required but not provided
        """
        # This would integrate with your auth system
        # For now, return a placeholder
        return request.headers.get("X-User-ID")
    
    def require_admin(self, request: Request) -> str:
        """
        Require admin authentication.
        
        Args:
            request: FastAPI request object
            
        Returns:
            Admin user ID
            
        Raises:
            HTTPException: If not authenticated as admin
        """
        user_id = self.require_auth(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Check if user is admin (this would use your auth system)
        is_admin = request.headers.get("X-User-Role") == "admin"
        if not is_admin:
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        return user_id


# Shared client instance for all route modules
_shared_client: Optional[GleitzeitClient] = None


def get_shared_client() -> GleitzeitClient:
    """
    Get or create the shared client instance for API routes.
    
    Returns:
        Initialized GleitzeitClient instance
    """
    global _shared_client
    
    if _shared_client is None:
        # Create client in NATIVE mode for direct engine access
        _shared_client = GleitzeitClient(mode=ClientMode.NATIVE)
        # Note: Client should be initialized during API startup
    
    return _shared_client


async def initialize_shared_client():
    """Initialize the shared client instance."""
    client = get_shared_client()
    if not client.is_initialized():
        await client.initialize()
        logger.info("Shared API client initialized successfully")


async def shutdown_shared_client():
    """Shutdown the shared client instance."""
    global _shared_client
    
    if _shared_client and _shared_client.is_initialized():
        await _shared_client.shutdown()
        logger.info("Shared API client shutdown completed")
        _shared_client = None