"""
Hub Connector - Client connection to ProviderHub

Allows clients to connect to a running ProviderHub instead of
creating providers locally, avoiding initialization blocking.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp

from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.core.errors import ProviderNotFoundError

logger = logging.getLogger(__name__)


class HubConnector:
    """
    Connects to a remote ProviderHub for task execution.
    
    This replaces local provider creation with remote hub calls,
    avoiding the blocking issues during initialization.
    """
    
    def __init__(
        self,
        hub_url: str = "http://localhost:8090",
        timeout: float = 30.0
    ):
        """
        Initialize hub connector.
        
        Args:
            hub_url: URL of the ProviderHub server
            timeout: Request timeout in seconds
        """
        self.hub_url = hub_url
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        
        logger.info(f"Created HubConnector for {hub_url}")
    
    async def connect(self) -> bool:
        """
        Connect to the provider hub.
        
        Returns:
            True if connection successful
        """
        if self._connected:
            return True
        
        try:
            # Create session
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
            
            # Test connection with health check
            async with self.session.get(f"{self.hub_url}/health") as resp:
                if resp.status == 200:
                    self._connected = True
                    logger.info(f"Connected to ProviderHub at {self.hub_url}")
                    return True
                else:
                    logger.error(f"ProviderHub returned status {resp.status}")
                    return False
                    
        except Exception as e:
            logger.debug(f"ProviderHub not available at {self.hub_url}: {e}")
            # This is expected - client will use local providers as fallback
            return False
    
    async def execute_request(
        self,
        protocol_id: str,
        request: JSONRPCRequest
    ) -> JSONRPCResponse:
        """
        Execute a request through the hub.
        
        Args:
            protocol_id: Protocol to use
            request: JSONRPC request
            
        Returns:
            JSONRPC response
        """
        if not self._connected:
            if not await self.connect():
                raise ProviderNotFoundError(f"Cannot connect to ProviderHub at {self.hub_url}")
        
        try:
            data = {
                "protocol": protocol_id,
                "request": request.dict()
            }
            
            async with self.session.post(f"{self.hub_url}/execute", json=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return JSONRPCResponse(**result)
                else:
                    error_text = await resp.text()
                    raise ProviderNotFoundError(f"Hub request failed: {error_text}")
                    
        except aiohttp.ClientError as e:
            logger.error(f"Hub request failed: {e}")
            raise ProviderNotFoundError(f"Hub request failed: {e}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get hub statistics"""
        if not self._connected:
            await self.connect()
        
        try:
            async with self.session.get(f"{self.hub_url}/stats") as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}
        except:
            return {}
    
    async def is_protocol_available(self, protocol: str) -> bool:
        """Check if protocol is available in hub"""
        stats = await self.get_stats()
        protocols = stats.get("protocols", [])
        return protocol in protocols
    
    async def disconnect(self):
        """Disconnect from hub"""
        if self.session and not self.session.closed:
            await self.session.close()
        self._connected = False
        logger.info(f"Disconnected from ProviderHub")