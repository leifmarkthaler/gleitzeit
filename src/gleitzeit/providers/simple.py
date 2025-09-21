"""
Simple Provider Base Class

Simplified provider that handles all boilerplate automatically.
Users only need to implement the execute() method.

NOTE: All enterprise features (retry logic, enhanced logging, metrics)
are now built into the base ProtocolProvider class.
"""

from abc import abstractmethod
from typing import Dict, Any, Optional, List

from .base import ProtocolProvider
from gleitzeit.core.errors import MethodNotSupportedError


class SimpleProvider(ProtocolProvider):
    """
    Simplified provider base class that handles boilerplate automatically.
    
    Users only need to implement the execute() method. All other methods
    (initialize, shutdown, health_check) have sensible defaults.
    
    Features included automatically from ProtocolProvider:
    - Smart retry logic with exponential backoff
    - Enhanced structured logging
    - Basic metrics collection
    - Error classification and handling
    - Resource management integration
    
    Example:
        class WeatherProvider(SimpleProvider):
            async def execute(self, method: str, params: Dict[str, Any]):
                if method == "get_weather":
                    return {"temp": 20, "city": params.get("city", "London")}
    """
    
    def __init__(
        self,
        provider_id: Optional[str] = None,
        protocol_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: str = "1.0.0",
        **kwargs
    ):
        # Auto-generate IDs if not provided
        if not provider_id:
            provider_id = self.__class__.__name__.lower()
            if provider_id.endswith('provider'):
                provider_id = provider_id[:-8] or 'provider'  # Remove 'provider' suffix but keep something
        
        if not protocol_id:
            protocol_id = f"{provider_id}/v1"
        
        if not name:
            name = f"{provider_id.title()} Provider"
        
        if not description:
            description = f"Simplified provider for {protocol_id}"
        
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name=name,
            description=description,
            version=version,
            **kwargs
        )
        
    async def initialize(self) -> None:
        """
        Default initialization - override only if needed.
        
        The default implementation does nothing, making initialization optional.
        """
        pass
    
    async def shutdown(self) -> None:
        """
        Default shutdown - override only if needed.
        
        The default implementation does nothing, making cleanup optional.
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Default health check - override only if needed.
        
        The default implementation always returns True.
        Override to implement custom health checking logic.
        """
        return True
    
    
    @abstractmethod
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Simplified method that users implement.
        
        This is the only method users need to implement. All the complexity
        of provider lifecycle, error handling, retries, and logging is
        handled automatically by the base ProtocolProvider class.
        
        Args:
            method: The method name being called
            params: Method parameters as dictionary
            
        Returns:
            The result of the method execution (must be JSON serializable)
            
        Example:
            async def execute(self, method: str, params: Dict[str, Any]):
                if method == "get_weather":
                    city = params.get("city", "London")
                    return {"temperature": 20, "city": city}
                elif method == "get_forecast":
                    return {"forecast": "sunny", "days": 7}
                else:
                    raise ValueError(f"Unknown method: {method}")
        """
        pass
    
    
    def get_supported_methods(self) -> List[str]:
        """
        Default implementation returns empty list.
        Override to specify supported methods for better documentation.
        
        Example:
            def get_supported_methods(self):
                return ["get_weather", "get_forecast"]
        """
        return []