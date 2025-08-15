"""
Echo Protocol Provider for Gleitzeit V4

Simple provider for testing and demonstration that echoes back input.
Implements the echo/v1 protocol with basic JSON-RPC methods.
"""

import logging
from typing import Dict, List, Any
from datetime import datetime

from gleitzeit.providers.base import ProtocolProvider

logger = logging.getLogger(__name__)


class EchoProvider(ProtocolProvider):
    """
    Simple echo provider for testing
    
    Supported methods:
    - echo: Returns the input parameters
    - ping: Returns "pong" 
    - timestamp: Returns current timestamp
    - delay: Simulates delay and returns parameters
    """
    
    def __init__(self, provider_id: str = "echo-provider-1"):
        super().__init__(
            provider_id=provider_id,
            protocol_id="echo/v1",
            name="Echo Provider",
            description="Simple echo provider for testing and demonstration"
        )
    
    async def initialize(self) -> None:
        """Initialize the echo provider"""
        logger.info(f"Echo provider {self.provider_id} initialized")
    
    async def shutdown(self) -> None:
        """Shutdown the echo provider"""
        logger.info(f"Echo provider {self.provider_id} shutdown")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC method calls"""
        if method == "echo":
            # Simple echo - return the parameters
            return {
                "echoed": params,
                "provider_id": self.provider_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        elif method == "ping":
            # Health check ping or message echo
            message = params.get("message", "pong")
            return {
                "response": message,
                "provider_id": self.provider_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        elif method == "timestamp":
            # Return current timestamp
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "unix_timestamp": datetime.utcnow().timestamp(),
                "provider_id": self.provider_id
            }
        
        elif method == "delay":
            # Simulate processing delay
            import asyncio
            
            delay_seconds = params.get("seconds", 1.0)
            if delay_seconds > 10:  # Safety limit
                raise ValueError("Delay cannot exceed 10 seconds")
            
            await asyncio.sleep(delay_seconds)
            
            return {
                "delayed_for_seconds": delay_seconds,
                "parameters": params,
                "provider_id": self.provider_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        elif method == "error":
            # Generate an error for testing error handling
            error_type = params.get("type", "generic")
            
            if error_type == "value":
                raise ValueError(params.get("message", "Test ValueError"))
            elif error_type == "runtime":
                raise RuntimeError(params.get("message", "Test RuntimeError"))
            else:
                raise Exception(params.get("message", "Test Exception"))
        
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        return {
            "status": "healthy",
            "details": "Echo provider is operational",
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["echo/echo", "echo/ping", "echo/timestamp", "echo/delay", "echo/error"]