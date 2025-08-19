"""
Base Protocol Provider for Gleitzeit V4

Abstract base class for all protocol providers that implement
JSON-RPC 2.0 compliant interfaces.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
import asyncio
import logging
from datetime import datetime

from gleitzeit.core.errors import (
    ErrorCode, GleitzeitError, ProviderError, ProviderNotFoundError,
    ProviderTimeoutError, SystemError, ConnectionTimeoutError,
    AuthenticationError, NetworkError, is_retryable_error
)

# Avoid circular imports
if TYPE_CHECKING:
    from gleitzeit.hub.resource_manager import ResourceManager
    from gleitzeit.hub.base import ResourceHub, ResourceInstance

logger = logging.getLogger(__name__)


class ProtocolProvider(ABC):
    """
    Abstract base class for protocol providers
    
    Protocol providers are lightweight adapters that implement specific
    protocol specifications and translate JSON-RPC calls to external services.
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: str = "1.0.0",
        resource_manager: Optional['ResourceManager'] = None,
        hub: Optional['ResourceHub'] = None
    ):
        self.provider_id = provider_id
        self.protocol_id = protocol_id
        self.name = name or self.__class__.__name__
        self.description = description or f"Provider for {protocol_id}"
        self.version = version
        
        # Resource management integration
        self.resource_manager = resource_manager
        self.hub = hub  # Direct hub connection for providers that need specific hub
        
        # State tracking
        self._initialized = False
        self._running = False
        self.created_at = datetime.utcnow()
        
        # Statistics
        self.request_count = 0
        self.error_count = 0
        
        logger.info(f"Initialized {self.__class__.__name__}: {provider_id}")
    
    @abstractmethod
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Handle a JSON-RPC method call
        
        Args:
            method: The JSON-RPC method name
            params: Method parameters as a dictionary
            
        Returns:
            Method result (must be JSON serializable)
            
        Raises:
            Exception: Any exception will be converted to JSON-RPC error
        """
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the provider (connect to services, load config, etc.)
        
        This method is called before the provider starts handling requests.
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """
        Shutdown the provider and cleanup resources
        
        This method is called when the provider is being stopped.
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Perform health check and return status
        
        Returns:
            True if healthy, False otherwise
        """
        pass
    
    def get_supported_methods(self) -> List[str]:
        """
        Get list of methods this provider supports
        
        Default implementation returns empty list.
        Override to specify supported methods.
        
        Returns:
            List of method names
        """
        return []
    
    async def start(self) -> None:
        """Start the provider"""
        if self._running:
            return
        
        try:
            await self.initialize()
            self._initialized = True
            self._running = True
            logger.info(f"Started provider: {self.provider_id}")
            
        except Exception as e:
            provider_error = ProviderError(
                message=f"Failed to initialize provider: {e}",
                code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.provider_id,
                cause=e
            )
            logger.error(f"Failed to start provider {self.provider_id}: {provider_error}")
            raise provider_error
    
    async def stop(self) -> None:
        """Stop the provider"""
        if not self._running:
            return
        
        try:
            await self.shutdown()
            self._running = False
            logger.info(f"Stopped provider: {self.provider_id}")
            
        except Exception as e:
            logger.error(f"Error stopping provider {self.provider_id}: {e}")
            # Don't raise errors during shutdown to avoid cascading failures
    
    def is_running(self) -> bool:
        """Check if provider is running"""
        return self._running
    
    def is_initialized(self) -> bool:
        """Check if provider is initialized"""
        return self._initialized
    
    async def allocate_resource(
        self,
        capabilities: Optional[Set[str]] = None,
        tags: Optional[Set[str]] = None,
        strategy: str = "least_loaded"
    ) -> Optional['ResourceInstance']:
        """
        Allocate a resource from the connected hub or resource manager.
        
        This method attempts to get an available resource instance that matches
        the specified requirements. It will try the following in order:
        1. Direct hub if connected
        2. Resource manager if available
        3. Return None if no resource management is configured
        
        Args:
            capabilities: Required capabilities (e.g., model names for Ollama)
            tags: Required tags for filtering
            strategy: Allocation strategy (least_loaded, round_robin, etc.)
            
        Returns:
            ResourceInstance if allocated, None otherwise
        """
        # Try direct hub first (most specific)
        if self.hub:
            try:
                instance = await self.hub.get_available_instance(
                    capabilities=capabilities,
                    tags=tags,
                    strategy=strategy
                )
                if instance:
                    logger.debug(f"Allocated resource {instance.id} from hub {self.hub.hub_id}")
                    return instance
            except Exception as e:
                logger.warning(f"Failed to allocate from hub: {e}")
        
        # Try resource manager (can allocate from any hub)
        if self.resource_manager:
            try:
                # Determine resource type based on provider
                from gleitzeit.hub.base import ResourceType
                
                # Map provider types to resource types
                resource_type_map = {
                    'ollama': ResourceType.OLLAMA,
                    'docker': ResourceType.DOCKER,
                    'python': ResourceType.DOCKER,  # Python uses Docker
                    'custom': ResourceType.CUSTOM
                }
                
                # Get resource type from provider_id or protocol_id
                resource_type = None
                for key, rtype in resource_type_map.items():
                    if key in self.provider_id.lower() or key in self.protocol_id.lower():
                        resource_type = rtype
                        break
                
                if not resource_type:
                    resource_type = ResourceType.CUSTOM
                
                instance = await self.resource_manager.allocate_resource(
                    resource_type=resource_type,
                    requirements={
                        'capabilities': capabilities,
                        'tags': tags,
                        'strategy': strategy
                    }
                )
                if instance:
                    logger.debug(f"Allocated resource {instance.id} from resource manager")
                    return instance
            except Exception as e:
                logger.warning(f"Failed to allocate from resource manager: {e}")
        
        logger.debug("No resource management configured, using default endpoint")
        return None
    
    async def _preprocess_params(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pre-process parameters to handle common patterns like file reading.
        
        This method handles:
        - Reading file content from file_path parameter
        - Reading image data from image_path parameter
        - Converting images array if needed
        
        Args:
            method: The method being called
            params: Original parameters
            
        Returns:
            Processed parameters with file contents included
        """
        import copy
        import glob
        from pathlib import Path
        
        # Create a copy to avoid modifying original params
        processed = copy.deepcopy(params)
        
        # Handle directory + file_pattern for batch processing
        if 'directory' in processed and 'file_pattern' in processed:
            directory = processed.pop('directory')
            file_pattern = processed.pop('file_pattern')
            
            # Discover files matching the pattern
            pattern_path = Path(directory) / file_pattern
            matching_files = glob.glob(str(pattern_path))
            
            if matching_files:
                # Add discovered files to the files list
                if 'files' not in processed:
                    processed['files'] = []
                processed['files'].extend(matching_files)
                logger.debug(f"Discovered {len(matching_files)} files matching {pattern_path}")
            else:
                logger.warning(f"No files found matching pattern: {pattern_path}")
        
        # Handle file_path for text files
        if 'file_path' in processed:
            file_path = processed['file_path']
            if file_path and Path(file_path).exists():
                try:
                    # Check if it's an image file
                    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
                    if Path(file_path).suffix.lower() in image_extensions:
                        # For images, keep the file_path as is (provider will handle it)
                        # Or optionally read and convert to base64
                        if 'image_data' not in processed and 'images' not in processed:
                            import base64
                            with open(file_path, 'rb') as f:
                                image_data = base64.b64encode(f.read()).decode('utf-8')
                            processed['image_data'] = image_data
                    else:
                        # For text files, read content and append to prompt/messages
                        with open(file_path, 'r', encoding='utf-8') as f:
                            file_content = f.read()
                        
                        # Append to messages if present
                        if 'messages' in processed and processed['messages']:
                            last_msg = processed['messages'][-1]
                            if last_msg.get('role') == 'user':
                                original_content = last_msg.get('content', '')
                                last_msg['content'] = f"{original_content}\n\nFile content from {file_path}:\n{file_content}"
                        # Or append to prompt if present
                        elif 'prompt' in processed:
                            original_prompt = processed.get('prompt', '')
                            processed['prompt'] = f"{original_prompt}\n\nFile content from {file_path}:\n{file_content}"
                        
                        logger.debug(f"Read file content from {file_path} ({len(file_content)} chars)")
                        
                except Exception as e:
                    logger.warning(f"Could not read file {file_path}: {e}")
        
        # Handle image_path for vision tasks
        if 'image_path' in processed and not processed.get('image_data') and not processed.get('images'):
            image_path = processed.pop('image_path')  # Remove image_path after reading
            if image_path and Path(image_path).exists():
                try:
                    import base64
                    with open(image_path, 'rb') as f:
                        image_data = base64.b64encode(f.read()).decode('utf-8')
                    # Only add to images array (not image_data) to avoid validation issues
                    processed['images'] = [image_data]
                    logger.debug(f"Read image from {image_path} and converted to base64")
                except Exception as e:
                    logger.warning(f"Could not read image {image_path}: {e}")
                    # If reading fails, restore image_path
                    processed['image_path'] = image_path
        
        return processed
    
    def get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            "provider_id": self.provider_id,
            "protocol_id": self.protocol_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "running": self._running,
            "initialized": self._initialized,
            "created_at": self.created_at.isoformat(),
            "supported_methods": self.get_supported_methods(),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "success_rate": (
                (self.request_count - self.error_count) / self.request_count * 100
                if self.request_count > 0 else 100.0
            )
        }
    
    async def execute_with_stats(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Execute request with automatic statistics tracking
        
        This is the main entry point used by the registry.
        """
        self.request_count += 1
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Pre-process params to handle file reading
            processed_params = await self._preprocess_params(method, params)
            
            result = await self.handle_request(method, processed_params)
            
            # Log successful request
            duration = asyncio.get_event_loop().time() - start_time
            logger.debug(f"Provider {self.provider_id} executed {method} in {duration:.3f}s")
            
            return result
            
        except GleitzeitError as e:
            # Already a structured error, just track it
            self.error_count += 1
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Provider {self.provider_id} failed {method} after {duration:.3f}s: {e}")
            raise
            
        except Exception as e:
            self.error_count += 1
            
            # Wrap unexpected errors in ProviderError
            duration = asyncio.get_event_loop().time() - start_time
            provider_error = ProviderError(
                message=f"Provider execution failed for method '{method}': {e}",
                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                provider_id=self.provider_id,
                data={"method": method, "duration_seconds": duration},
                cause=e
            )
            logger.error(f"Provider {self.provider_id} failed {method} after {duration:.3f}s: {provider_error}")
            raise provider_error


class HTTPServiceProvider(ProtocolProvider):
    """
    Base class for providers that connect to HTTP-based services
    
    Provides common HTTP functionality like session management,
    authentication, and retry logic.
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        base_url: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        super().__init__(provider_id, protocol_id, name, description)
        
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        
        # HTTP session (initialized in start())
        self.session: Optional[Any] = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session"""
        import aiohttp
        
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=self.get_default_headers()
        )
        
        logger.info(f"HTTP provider {self.provider_id} initialized with base URL: {self.base_url}")
    
    async def shutdown(self) -> None:
        """Close HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    def get_default_headers(self) -> Dict[str, str]:
        """Get default HTTP headers"""
        return {
            "Content-Type": "application/json",
            "User-Agent": f"Gleitzeit-V4-Provider/{self.version}"
        }
    
    async def make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path (relative to base_url)
            data: Request data (JSON serializable)
            headers: Additional headers
            
        Returns:
            Response data as dictionary
        """
        if not self.session:
            raise SystemError(
                message="HTTP provider not properly initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED,
                data={"provider_id": self.provider_id}
            )
        
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = self.get_default_headers()
        if headers:
            request_headers.update(headers)
        
        for attempt in range(self.max_retries + 1):
            try:
                async with self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    headers=request_headers
                ) as response:
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        
                        # Map HTTP status codes to appropriate errors
                        if response.status == 401:
                            raise AuthenticationError(
                                endpoint=url,
                                auth_method="HTTP",
                                data={"http_status": response.status, "error_text": error_text}
                            )
                        elif response.status == 403:
                            raise ProviderError(
                                message=f"Authorization failed: {error_text}",
                                code=ErrorCode.AUTHORIZATION_FAILED,
                                provider_id=self.provider_id,
                                data={"http_status": response.status, "url": url}
                            )
                        elif response.status == 404:
                            raise ProviderError(
                                message=f"HTTP endpoint not found: {url}",
                                code=ErrorCode.METHOD_NOT_FOUND,
                                provider_id=self.provider_id,
                                data={"http_status": response.status, "url": url}
                            )
                        elif response.status == 429:
                            raise ProviderError(
                                message=f"Rate limit exceeded: {error_text}",
                                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                                provider_id=self.provider_id,
                                data={"http_status": response.status, "retry_after": response.headers.get("Retry-After")}
                            )
                        elif response.status >= 500:
                            raise ProviderError(
                                message=f"HTTP server error: {error_text}",
                                code=ErrorCode.PROVIDER_UNHEALTHY,
                                provider_id=self.provider_id,
                                data={"http_status": response.status, "url": url}
                            )
                        else:
                            raise ProviderError(
                                message=f"HTTP client error: {error_text}",
                                code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                                provider_id=self.provider_id,
                                data={"http_status": response.status, "url": url}
                            )
                    
                    return await response.json()
                    
            except asyncio.TimeoutError as e:
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                raise ProviderTimeoutError(
                    provider_id=self.provider_id,
                    timeout=self.timeout,
                    cause=e
                )
                
            except GleitzeitError as e:
                # Already structured errors, handle retry logic
                if attempt < self.max_retries and is_retryable_error(e):
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
                
            except Exception as e:
                # Wrap unexpected errors
                network_error = NetworkError(
                    message=f"HTTP request failed: {e}",
                    code=ErrorCode.CONNECTION_REFUSED,
                    endpoint=url,
                    cause=e
                )
                
                if attempt < self.max_retries and is_retryable_error(network_error):
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise network_error
    
    async def health_check(self) -> bool:
        """Default health check via HTTP request"""
        try:
            if not self.session:
                return False
            
            # Try a simple request to check connectivity
            await self.make_request("GET", "/health")
            return True
            
        except Exception:
            return False


class WebSocketProvider(ProtocolProvider):
    """
    Base class for providers that use WebSocket connections
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        websocket_url: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ):
        super().__init__(provider_id, protocol_id, name, description)
        
        self.websocket_url = websocket_url
        self.websocket: Optional[Any] = None
        self._connection_lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize WebSocket connection"""
        await self._ensure_connected()
    
    async def shutdown(self) -> None:
        """Close WebSocket connection"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
    
    async def _ensure_connected(self) -> None:
        """Ensure WebSocket connection is established"""
        async with self._connection_lock:
            if self.websocket is None or self.websocket.closed:
                import websockets
                
                self.websocket = await websockets.connect(self.websocket_url)
                logger.info(f"WebSocket provider {self.provider_id} connected to {self.websocket_url}")
    
    async def send_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send message via WebSocket and wait for response
        
        Args:
            message: Message to send (JSON serializable)
            
        Returns:
            Response message as dictionary
        """
        await self._ensure_connected()
        
        import json
        await self.websocket.send(json.dumps(message))
        response = await self.websocket.recv()
        
        return json.loads(response)
    
    async def health_check(self) -> bool:
        """Health check via WebSocket ping"""
        try:
            if not self.websocket or self.websocket.closed:
                return False
            
            # Send ping
            await self.websocket.ping()
            return True
            
        except Exception:
            return False