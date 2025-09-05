"""
Base infrastructure for modular API routes.

All routes use dependency injection - no singleton patterns.
"""

from typing import Dict, Any, Optional
from fastapi import HTTPException, Request
from gleitzeit.client import GleitzeitClient
import asyncio
import logging

logger = logging.getLogger(__name__)


class APIRouteBase:
    """Base class for API route modules that delegate to client methods."""
    
    def __init__(self):
        """Initialize route handler (stateless - no client stored)."""
        self.logger = logger.getChild(self.__class__.__name__)
    
    async def handle_client_call(
        self, 
        client_method_name: str, 
        *args, 
        client: GleitzeitClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generic handler for client method calls with proper error handling.
        
        Args:
            client_method_name: Name of the client method to call
            client: Client instance from dependency injection
            *args: Positional arguments for the client method
            **kwargs: Keyword arguments for the client method
            
        Returns:
            Result from client method call
            
        Raises:
            HTTPException: On client errors or method not found
        """
        if not client:
            raise HTTPException(
                status_code=503,
                detail="No client available - service not initialized"
            )
        
        try:
            # Get the client method
            if not hasattr(client, client_method_name):
                raise HTTPException(
                    status_code=501,
                    detail=f"Client method '{client_method_name}' not implemented"
                )
            
            method = getattr(client, client_method_name)
            
            # Call the method
            if asyncio.iscoroutinefunction(method):
                result = await method(*args, **kwargs)
            else:
                result = method(*args, **kwargs)
            
            # Wrap list results in a dict for API compatibility
            if isinstance(result, list):
                # For list_* methods, wrap in appropriate key
                if "list_workflows" in client_method_name:
                    result = {"workflows": result}
                elif "list_tasks" in client_method_name:
                    # Convert Task objects to dicts for proper serialization
                    tasks_as_dicts = []
                    for task in result:
                        if hasattr(task, 'dict'):
                            tasks_as_dicts.append(task.dict())
                        elif hasattr(task, 'model_dump'):
                            tasks_as_dicts.append(task.model_dump())
                        else:
                            tasks_as_dicts.append(task)
                    result = {"tasks": tasks_as_dicts}
                else:
                    result = {"items": result}
            
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