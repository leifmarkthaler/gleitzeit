"""
Base Protocol Provider for Gleitzeit V4

Abstract base class for all protocol providers that implement
JSON-RPC 2.0 compliant interfaces.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
import asyncio
import logging
import time
import uuid
from datetime import datetime
import statistics
import inspect
import warnings

from gleitzeit.core.errors import (
    ErrorCode, GleitzeitError, ProviderError, ProviderNotFoundError,
    ProviderTimeoutError, SystemError, ConnectionTimeoutError,
    AuthenticationError, NetworkError, is_retryable_error
)
from gleitzeit.core.logging_mixin import LoggingMixin

# Avoid circular imports
if TYPE_CHECKING:
    # ResourceManager removed - use stateless resource coordination
    from gleitzeit.hub.base import ResourceHub, ResourceInstance
    from gleitzeit.core.protocol import ProtocolSpec

logger = logging.getLogger(__name__)


class ProtocolProvider(ABC, LoggingMixin):
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
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        resource_manager: Optional['ResourceManager'] = None,
        hub: Optional['ResourceHub'] = None,
        validate_on_init: bool = True,
        strict_validation: bool = False,
        auto_generate_protocol: bool = False,
        register_protocol: bool = False,
        protocol_registry: Optional[Any] = None
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
        
        # Retry configuration
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        
        # Enhanced metrics
        self.request_count = 0
        self.error_count = 0
        self.latencies = []
        self.method_counts = {}
        self.last_request_time = None
        
        # Logger
        self.logger = logging.getLogger(f'gleitzeit.providers.{provider_id}')
        
        # Validation settings
        self.validate_on_init = validate_on_init
        self.strict_validation = strict_validation
        
        # Protocol generation settings
        self.auto_generate_protocol = auto_generate_protocol
        self.register_protocol = register_protocol
        self.protocol_registry = protocol_registry
        self._generated_protocol: Optional['ProtocolSpec'] = None
        
        # Perform automatic validation
        if validate_on_init:
            self._validate_provider()
        
        # Auto-generate protocol if requested
        if auto_generate_protocol:
            self._generated_protocol = self._generate_protocol()
            if register_protocol and self._generated_protocol and protocol_registry:
                self._register_generated_protocol()
        
        # Note: Initial setup logging will be done on first async operation
        logger.info(f"Initialized {self.__class__.__name__}: {provider_id}")
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Enhanced request handler with automatic retry, logging, and metrics.
        
        This method wraps the user's execute() method with:
        - Automatic retry logic using exponential backoff
        - Error classification (retryable vs non-retryable)
        - Request timing and metrics collection
        - Enhanced structured logging
        
        Args:
            method: The method name to execute
            params: Method parameters
            
        Returns:
            The result from the user's execute() method
            
        Raises:
            Exception: Re-raises the last exception if all retries fail
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # Add centralized logging via LoggingMixin
        await self.log_operation(
            "provider_handle_request",
            request_id=request_id,
            method=method,
            provider_id=self.provider_id,
            params_count=len(params)
        )
        
        # Enhanced logging - start (keep existing format for compatibility)
        self.logger.info(
            f"[{request_id}] Starting {method}",
            extra={
                'request_id': request_id,
                'method': method,
                'provider_id': self.provider_id,
                'params_count': len(params),
                'timestamp': datetime.utcnow().isoformat()
            }
        )
        
        # Update method counts
        self.method_counts[method] = self.method_counts.get(method, 0) + 1
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # Call user's execute method
                result = await self.execute(method, params)
                
                # Success metrics
                duration = time.time() - start_time
                self.latencies.append(duration)
                self.last_request_time = datetime.utcnow()
                
                # Add centralized success logging
                await self.log_success(
                    "provider_handle_request_success",
                    f"Provider method {method} completed successfully",
                    request_id=request_id,
                    method=method,
                    duration_ms=duration * 1000,
                    attempt=attempt + 1,
                    result_size=len(str(result)) if result else 0
                )
                
                # Enhanced logging - success (keep existing format for compatibility)
                self.logger.info(
                    f"[{request_id}] Success {method} in {duration:.3f}s",
                    extra={
                        'request_id': request_id,
                        'method': method,
                        'duration_ms': duration * 1000,
                        'attempt': attempt + 1,
                        'success': True,
                        'result_size': len(str(result)) if result else 0
                    }
                )
                
                return result
                
            except Exception as e:
                last_error = e
                duration = time.time() - start_time
                
                # Check if error is retryable
                is_retryable = is_retryable_error(e)
                is_final_attempt = (attempt == self.max_retries - 1)
                
                # Add centralized error logging
                if is_final_attempt:
                    await self.log_error(
                        "provider_handle_request_failed",
                        f"Provider method {method} failed after {attempt + 1} attempts: {str(e)}",
                        request_id=request_id,
                        method=method,
                        error_type=e.__class__.__name__,
                        error_message=str(e),
                        total_attempts=attempt + 1,
                        duration_ms=duration * 1000
                    )
                else:
                    await self.log_debug(
                        "provider_handle_request_retry",
                        f"Provider method {method} attempt {attempt + 1} failed, will retry: {str(e)}",
                        request_id=request_id,
                        method=method,
                        error_type=e.__class__.__name__,
                        attempt=attempt + 1,
                        retryable=is_retryable
                    )
                
                # Enhanced logging - error (keep existing format for compatibility)
                log_level = 'error' if is_final_attempt else 'warning'
                getattr(self.logger, log_level)(
                    f"[{request_id}] {'Final ' if is_final_attempt else ''}Attempt {attempt + 1} failed: {e}",
                    extra={
                        'request_id': request_id,
                        'method': method,
                        'duration_ms': duration * 1000,
                        'attempt': attempt + 1,
                        'success': False,
                        'error_type': e.__class__.__name__,
                        'error_message': str(e),
                        'retryable': is_retryable,
                        'final_attempt': is_final_attempt
                    }
                )
                
                # Don't retry if not retryable or final attempt
                if not is_retryable or is_final_attempt:
                    self.error_count += 1
                    raise
                
                # Calculate delay with exponential backoff
                delay = self.retry_delay * (self.retry_backoff ** attempt)
                
                self.logger.info(
                    f"[{request_id}] Retrying in {delay:.1f}s...",
                    extra={
                        'request_id': request_id,
                        'retry_delay': delay,
                        'next_attempt': attempt + 2
                    }
                )
                
                await asyncio.sleep(delay)
        
        # Should never reach here due to the logic above, but just in case
        self.error_count += 1
        raise last_error
    
    @abstractmethod
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Simplified method that users implement.
        
        This is the only method users need to implement. All the complexity
        of provider lifecycle, error handling, retries, and logging is
        handled automatically by the base class.
        
        Args:
            method: The method name being called
            params: Method parameters as dictionary
            
        Returns:
            The result of the method execution (must be JSON serializable)
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
    
    async def validate_availability(self) -> bool:
        """
        Validate that this provider is available and can handle requests.
        
        By default, this uses the health_check method, but providers can
        override this to provide more specific availability validation
        (e.g., checking if external services are running).
        
        Returns:
            True if provider is available, False otherwise
        """
        try:
            # First check if provider is initialized
            if not self._initialized:
                await self.initialize()
                self._initialized = True
            
            # Then perform health check
            return await self.health_check()
        except Exception as e:
            self.logger.debug(f"Provider {self.provider_id} availability check failed: {e}")
            return False
    
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
            await self.log_debug(
                "provider_already_running",
                "Provider already running, ignoring start request",
                provider_id=self.provider_id
            )
            return
        
        await self.log_operation(
            "provider_start",
            provider_id=self.provider_id,
            provider_type=self.__class__.__name__
        )
        
        try:
            await self.initialize()
            self._initialized = True
            self._running = True
            
            await self.log_success(
                "provider_started",
                "Provider started successfully",
                provider_id=self.provider_id
            )
            
            logger.info(f"Started provider: {self.provider_id}")
            
        except Exception as e:
            await self.log_error(
                "provider_start_failed",
                f"Failed to start provider: {str(e)}",
                provider_id=self.provider_id,
                error=str(e),
                error_type=type(e).__name__
            )
            
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
            await self.log_debug(
                "provider_not_running",
                "Provider not running, ignoring stop request",
                provider_id=self.provider_id
            )
            return
        
        await self.log_operation(
            "provider_stop",
            provider_id=self.provider_id
        )
        
        try:
            await self.shutdown()
            self._running = False
            
            await self.log_success(
                "provider_stopped",
                "Provider stopped successfully",
                provider_id=self.provider_id
            )
            
            logger.info(f"Stopped provider: {self.provider_id}")
            
        except Exception as e:
            await self.log_error(
                "provider_stop_failed",
                f"Error stopping provider: {str(e)}",
                provider_id=self.provider_id,
                error=str(e),
                error_type=type(e).__name__
            )
            
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
        """Get basic provider information"""
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
    
    def _validate_provider(self) -> None:
        """
        Automatic provider validation on initialization.
        
        Validates that the provider is correctly implemented and will work
        in the Gleitzeit system. Raises errors or warnings based on severity.
        """
        validation_errors = []
        validation_warnings = []
        
        # Check provider_id format
        if not self.provider_id or not isinstance(self.provider_id, str):
            validation_errors.append("provider_id must be a non-empty string")
        elif ' ' in self.provider_id:
            validation_errors.append("provider_id cannot contain spaces")
        elif not self.provider_id.replace('_', '').replace('-', '').replace('.', '').isalnum():
            validation_warnings.append("provider_id should only contain alphanumeric characters, underscores, hyphens, and dots")
        
        # Check protocol_id format
        if not self.protocol_id or not isinstance(self.protocol_id, str):
            validation_errors.append("protocol_id must be a non-empty string")
        elif '/' not in self.protocol_id and self.strict_validation:
            validation_warnings.append("protocol_id should follow format: namespace/version (e.g., 'llm/v1')")
        
        # Check required method implementations
        required_methods = self._get_required_methods()
        for method_name in required_methods:
            if not self._implements_method(method_name):
                validation_errors.append(f"Provider must implement {method_name}() method")
        
        # Check async methods
        async_methods = ['execute', 'initialize', 'shutdown', 'health_check', 'handle_request']
        for method_name in async_methods:
            if hasattr(self, method_name):
                method = getattr(self, method_name)
                if callable(method) and not inspect.iscoroutinefunction(method):
                    # Skip if it's from the base class (already async)
                    if method_name not in self.__class__.__dict__:
                        continue
                    validation_errors.append(f"{method_name}() must be async (use 'async def')")
        
        # Check for common mistakes
        if self.strict_validation:
            # Check if provider declares supported methods
            if hasattr(self, 'get_supported_methods'):
                methods = self.get_supported_methods()
                if not methods:
                    validation_warnings.append("Provider should declare supported methods via get_supported_methods()")
            
            # Check for proper error handling
            if hasattr(self, 'execute'):
                execute_source = inspect.getsource(self.execute) if self.execute.__name__ != 'execute' else ''
                if execute_source and 'try:' not in execute_source and 'except' not in execute_source:
                    validation_warnings.append("execute() should include error handling")
        
        # Handle validation results
        if validation_errors:
            from gleitzeit.core.errors import InvalidParameterError
            error_msg = f"Provider {self.__class__.__name__} validation failed:\n" + "\n".join(f"  - {e}" for e in validation_errors)
            raise InvalidParameterError("provider_validation", error_msg)
        
        if validation_warnings:
            for warning in validation_warnings:
                warnings.warn(f"Provider {self.__class__.__name__}: {warning}", UserWarning)
    
    def _get_required_methods(self) -> List[str]:
        """
        Get list of methods that must be implemented for this provider type.
        """
        # Check what type of provider this is
        class_name = self.__class__.__name__
        
        # For ultra-simple providers, check for decorated methods or execute override
        if 'Ultra' in class_name or hasattr(self.__class__, '_method_routes'):
            # Ultra providers need either decorated methods or execute override
            if not self._has_decorated_methods() and not self._overrides_method('execute'):
                return ['execute']  # Must have one or the other
            return []  # Has decorated methods, so no specific requirements
        
        # For SimpleProvider/HTTPProvider subclasses
        if 'Simple' in class_name or 'HTTP' in class_name:
            # These must override execute
            if not self._overrides_method('execute'):
                return ['execute']
            return []
        
        # For direct ProtocolProvider subclasses
        if self.__class__.__bases__[0].__name__ == 'ProtocolProvider':
            # Must implement all abstract methods
            return ['execute', 'initialize', 'shutdown', 'health_check']
        
        # Default: execute is minimum requirement
        return ['execute'] if not self._overrides_method('execute') else []
    
    def _implements_method(self, method_name: str) -> bool:
        """
        Check if this provider implements a specific method.
        """
        if not hasattr(self, method_name):
            return False
        
        method = getattr(self, method_name)
        if not callable(method):
            return False
        
        # Check if it's abstract
        if hasattr(method, '__isabstractmethod__') and method.__isabstractmethod__:
            return False
        
        # Check if it's overridden from base class
        if method_name in self.__class__.__dict__:
            return True
        
        # Check if parent has a non-abstract implementation
        for base in self.__class__.__mro__[1:]:
            if hasattr(base, method_name):
                base_method = getattr(base, method_name)
                if not (hasattr(base_method, '__isabstractmethod__') and base_method.__isabstractmethod__):
                    return True
        
        return False
    
    def _overrides_method(self, method_name: str) -> bool:
        """
        Check if this class overrides a specific method.
        """
        return method_name in self.__class__.__dict__
    
    def _generate_protocol(self) -> Optional['ProtocolSpec']:
        """
        Auto-generate protocol from provider implementation.
        
        Returns:
            ProtocolSpec if generation successful, None otherwise
        """
        try:
            from gleitzeit.core.protocol import ProtocolSpec, MethodSpec
            
            # Discover methods
            methods = self._discover_methods()
            
            if not methods:
                return None
            
            # Generate protocol spec
            protocol_id = self.protocol_id or f"{self.provider_id}/auto-v1"
            
            return ProtocolSpec(
                protocol_id=protocol_id,
                name=self.provider_id.replace("_", "-").replace(" ", "-"),
                version="v1",
                methods=methods
            )
        except Exception as e:
            logger.warning(f"Failed to auto-generate protocol for {self.provider_id}: {e}")
            return None
    
    def _discover_methods(self) -> Dict[str, Any]:
        """
        Discover provider methods through introspection.
        
        Returns:
            Dictionary of method_name -> MethodSpec
        """
        from gleitzeit.core.protocol import MethodSpec
        
        methods = {}
        
        # Check if this is an UltraSimpleProvider with decorated methods
        if hasattr(self, '_method_routes'):
            for method_name, handler in self._method_routes.items():
                methods[method_name] = self._create_method_spec_from_handler(
                    method_name, handler
                )
        
        # Check if provider reports supported methods
        elif hasattr(self, 'get_supported_methods'):
            try:
                supported = self.get_supported_methods()
                if supported:
                    for method_name in supported:
                        # Create basic spec without detailed introspection
                        methods[method_name] = MethodSpec(
                            name=method_name,
                            description=f"Method {method_name}"
                            # params_schema and returns_schema default to {} which is fine
                        )
            except:
                pass  # get_supported_methods might not be implemented yet
        
        # For MCP providers or providers with capabilities
        if hasattr(self, 'capabilities') and isinstance(self.capabilities, dict):
            for method_name, capability in self.capabilities.items():
                if isinstance(capability, dict):
                    # Convert MCP capability to MethodSpec
                    methods[method_name] = self._convert_mcp_capability_to_method_spec(
                        method_name, capability
                    )
        
        return methods
    
    def _convert_mcp_capability_to_method_spec(self, name: str, capability: Dict[str, Any]) -> Any:
        """
        Convert MCP-style capability to MethodSpec.
        
        Args:
            name: Method name
            capability: MCP capability dictionary with inputSchema/outputSchema
            
        Returns:
            MethodSpec instance
        """
        from gleitzeit.core.protocol import MethodSpec, ParameterSpec, ParameterType
        
        # Extract input schema
        input_schema = capability.get('inputSchema', {})
        params_schema = {}
        
        if input_schema and isinstance(input_schema, dict):
            # Check if it's an object type with properties
            if input_schema.get('type') == 'object' and 'properties' in input_schema:
                properties = input_schema.get('properties', {})
                required_fields = input_schema.get('required', [])
                additional_properties = input_schema.get('additionalProperties', True)
                
                for param_name, param_def in properties.items():
                    # Convert JSON schema to ParameterSpec
                    params_schema[param_name] = self._json_schema_to_parameter_spec(
                        param_def, 
                        param_name,
                        param_name in required_fields
                    )
        
        # Convert output schema
        output_schema = capability.get('outputSchema', {})
        returns_schema = None
        if output_schema and isinstance(output_schema, dict):
            returns_schema = self._json_schema_to_parameter_spec(
                output_schema,
                "return",
                True  # Return value is always "required"
            )
        
        return MethodSpec(
            name=name,
            description=capability.get('description', f"Method {name}"),
            params_schema=params_schema,
            returns_schema=returns_schema
        )
    
    def _json_schema_to_parameter_spec(self, schema: Dict[str, Any], name: str, required: bool) -> Any:
        """
        Convert a JSON schema to ParameterSpec, handling nested structures.
        
        Args:
            schema: JSON schema dictionary
            name: Parameter name for description
            required: Whether parameter is required
            
        Returns:
            ParameterSpec instance
        """
        from gleitzeit.core.protocol import ParameterSpec, ParameterType
        
        # Extract type
        json_type = schema.get('type', 'string')
        param_type = self._json_type_to_parameter_type(json_type)
        
        # Build ParameterSpec kwargs
        spec_kwargs = {
            'type': param_type,
            'description': schema.get('description', f"Parameter {name}"),
            'required': required,
            'default': schema.get('default', None) if not required else None
        }
        
        # Add constraints based on type
        if json_type in ['string', 'array']:
            if 'minLength' in schema:
                spec_kwargs['min_length'] = schema['minLength']
            if 'maxLength' in schema:
                spec_kwargs['max_length'] = schema['maxLength']
            if 'pattern' in schema:
                spec_kwargs['pattern'] = schema['pattern']
        
        if json_type in ['number', 'integer']:
            if 'minimum' in schema:
                spec_kwargs['minimum'] = schema['minimum']
            if 'maximum' in schema:
                spec_kwargs['maximum'] = schema['maximum']
        
        # Handle enum values
        if 'enum' in schema:
            spec_kwargs['enum'] = schema['enum']
        
        # Handle array items
        if json_type == 'array' and 'items' in schema:
            items_spec = self._json_schema_to_parameter_spec(
                schema['items'],
                f"{name}[item]",
                True  # Array items are required if array is provided
            )
            spec_kwargs['items'] = items_spec
        
        # Handle object properties
        if json_type == 'object' and 'properties' in schema:
            properties_specs = {}
            required_props = schema.get('required', [])
            
            for prop_name, prop_schema in schema['properties'].items():
                properties_specs[prop_name] = self._json_schema_to_parameter_spec(
                    prop_schema,
                    f"{name}.{prop_name}",
                    prop_name in required_props
                )
            
            spec_kwargs['properties'] = properties_specs
            spec_kwargs['additional_properties'] = schema.get('additionalProperties', True)
        
        return ParameterSpec(**spec_kwargs)
    
    def _json_type_to_parameter_type(self, json_type: str):
        """Convert JSON schema type to ParameterType"""
        from gleitzeit.core.protocol import ParameterType
        
        type_map = {
            'string': ParameterType.STRING,
            'number': ParameterType.NUMBER,
            'integer': ParameterType.INTEGER,
            'boolean': ParameterType.BOOLEAN,
            'array': ParameterType.ARRAY,
            'object': ParameterType.OBJECT,
            'null': ParameterType.NULL
        }
        return type_map.get(json_type, ParameterType.STRING)
    
    def _create_method_spec_from_handler(self, name: str, handler: callable) -> Any:
        """
        Create method spec from function signature and type hints.
        
        Args:
            name: Method name
            handler: Function handler
            
        Returns:
            MethodSpec instance
        """
        from gleitzeit.core.protocol import MethodSpec, ParameterSpec, ParameterType
        import typing
        from typing import get_origin, get_args
        
        # Get function signature
        try:
            sig = inspect.signature(handler)
        except:
            # Fallback for methods that can't be inspected
            return MethodSpec(
                name=name,
                description=handler.__doc__ or f"Method {name}"
                # Use default empty params_schema
            )
        
        # Build parameter specifications
        params_schema = {}
        accepts_kwargs = False
        
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # Check for **kwargs
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                accepts_kwargs = True
                continue
            
            # Skip *args for now (could be handled as array)
            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            
            # Determine parameter type from annotation
            param_type = self._annotation_to_parameter_type(param.annotation)
            
            # Check if parameter is optional
            is_optional = False
            default_value = None
            
            if param.default != inspect.Parameter.empty:
                is_optional = True
                default_value = param.default
            
            # Check for Optional[T] type hint
            if param.annotation != inspect.Parameter.empty:
                origin = get_origin(param.annotation)
                if origin is typing.Union:
                    args = get_args(param.annotation)
                    # Check if it's Optional (Union with None)
                    if type(None) in args:
                        is_optional = True
                        # Get the non-None type
                        non_none_types = [arg for arg in args if arg != type(None)]
                        if non_none_types:
                            param_type = self._annotation_to_parameter_type(non_none_types[0])
            
            # Create ParameterSpec
            param_spec = ParameterSpec(
                type=param_type,
                description=f"Parameter {param_name}",
                required=not is_optional,
                default=default_value
            )
            
            params_schema[param_name] = param_spec
        
        # Extract return type if available
        returns_schema = None
        if sig.return_annotation != inspect.Parameter.empty:
            # Handle None return type explicitly
            return_type = self._annotation_to_parameter_type(sig.return_annotation)
            returns_schema = ParameterSpec(
                type=return_type,
                description="Method return value"
            )
        
        # Create MethodSpec
        method_spec = MethodSpec(
            name=name,
            description=handler.__doc__ or f"Method {name}",
            params_schema=params_schema,
            returns_schema=returns_schema
        )
        
        # If method accepts **kwargs, note it in the description
        if accepts_kwargs and not method_spec.description.endswith("(accepts additional keyword arguments)"):
            method_spec.description += " (accepts additional keyword arguments)"
        
        return method_spec
    
    def _annotation_to_parameter_type(self, annotation):
        """Convert Python type annotation to ParameterType"""
        from gleitzeit.core.protocol import ParameterType
        from typing import get_origin, get_args
        import typing
        
        if annotation == inspect.Parameter.empty:
            return ParameterType.STRING  # Default
        
        # Handle None type
        if annotation is None or annotation == type(None):
            return ParameterType.NULL
        
        # Direct type mappings
        if annotation == str:
            return ParameterType.STRING
        elif annotation == int:
            return ParameterType.INTEGER
        elif annotation == float:
            return ParameterType.NUMBER
        elif annotation == bool:
            return ParameterType.BOOLEAN
        elif annotation == list:
            return ParameterType.ARRAY
        elif annotation == dict or annotation == Dict:
            return ParameterType.OBJECT
        
        # Handle generic types (List[T], Dict[K,V], etc.)
        origin = get_origin(annotation)
        if origin is not None:
            if origin == list or origin == typing.List:
                return ParameterType.ARRAY
            elif origin == dict or origin == typing.Dict:
                return ParameterType.OBJECT
            elif origin == set or origin == typing.Set:
                return ParameterType.ARRAY  # Sets are array-like
            elif origin == tuple or origin == typing.Tuple:
                return ParameterType.ARRAY  # Tuples are array-like
            elif origin == typing.Union:
                # For Union types, try to determine the primary type
                args = get_args(annotation)
                non_none_types = [arg for arg in args if arg != type(None)]
                if non_none_types:
                    # Use the first non-None type
                    return self._annotation_to_parameter_type(non_none_types[0])
            elif origin == typing.Optional:
                # Optional[T] is Union[T, None]
                args = get_args(annotation)
                if args:
                    return self._annotation_to_parameter_type(args[0])
        
        # Handle Any
        if annotation == typing.Any:
            return ParameterType.STRING  # Most flexible
        
        # Default for unknown types
        return ParameterType.STRING
    
    def _register_generated_protocol(self) -> None:
        """
        Register the auto-generated protocol with the registry.
        """
        if self._generated_protocol and self.protocol_registry:
            try:
                self.protocol_registry.register_protocol(self._generated_protocol)
                logger.info(f"Auto-registered protocol: {self._generated_protocol.protocol_id}")
            except Exception as e:
                logger.warning(f"Failed to register protocol for {self.provider_id}: {e}")
    
    def get_generated_protocol(self) -> Optional['ProtocolSpec']:
        """
        Get the auto-generated protocol if available.
        
        Returns:
            ProtocolSpec or None
        """
        return self._generated_protocol
    
    def _has_decorated_methods(self) -> bool:
        """
        Check if class has @method decorated methods (for ultra-simple providers).
        """
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if hasattr(method, '_method_names'):
                return True
        return False
    
    def validate(self) -> Dict[str, Any]:
        """
        Manually validate this provider and return a report.
        
        Returns:
            Dictionary with validation results and recommendations
        """
        report = {
            "provider_class": self.__class__.__name__,
            "provider_id": self.provider_id,
            "protocol_id": self.protocol_id,
            "valid": True,
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
        try:
            # Re-run validation to collect issues
            original_setting = self.strict_validation
            self.strict_validation = True
            self._validate_provider()
        except Exception as e:
            report["valid"] = False
            report["errors"].append(str(e))
        finally:
            self.strict_validation = original_setting
        
        # Add recommendations
        if not self.get_supported_methods():
            report["recommendations"].append(
                "Override get_supported_methods() to declare what methods this provider handles"
            )
        
        if hasattr(self, 'base_url') and 'http' in self.__class__.__name__.lower():
            report["recommendations"].append(
                "Consider using HTTPProvider or UltraHTTPProvider base class for HTTP-based providers"
            )
        
        return report
    
    def get_enhanced_metrics(self) -> Dict[str, Any]:
        """
        Get enhanced metrics including latency percentiles and method breakdown.
        
        Returns:
            Dictionary with comprehensive provider metrics
        """
        base_metrics = self.get_info()
        
        # Calculate latency statistics
        latency_stats = {}
        if self.latencies:
            latency_stats = {
                "mean_ms": statistics.mean(self.latencies) * 1000,
                "median_ms": statistics.median(self.latencies) * 1000,
                "min_ms": min(self.latencies) * 1000,
                "max_ms": max(self.latencies) * 1000,
            }
            
            # Calculate percentiles if we have enough data
            if len(self.latencies) >= 10:
                sorted_latencies = sorted(self.latencies)
                latency_stats.update({
                    "p95_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)] * 1000,
                    "p99_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)] * 1000,
                })
        
        # Enhanced metrics
        enhanced_metrics = {
            **base_metrics,
            "latency": latency_stats,
            "method_breakdown": dict(self.method_counts),
            "last_request": self.last_request_time.isoformat() if self.last_request_time else None,
            "total_latency_samples": len(self.latencies),
            "provider_type": self.__class__.__name__,
            "features": [
                "automatic_retry",
                "enhanced_logging", 
                "metrics_collection",
                "error_classification"
            ]
        }
        
        return enhanced_metrics
    
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