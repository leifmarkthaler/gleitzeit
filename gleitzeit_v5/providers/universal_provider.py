"""
Universal Provider for Gleitzeit

A SocketIO component that can execute any protocol method using executor-based architecture.
Integrates YAML configurations with executor implementations for maximum flexibility.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional

from ..base.component import SocketIOComponent
from ..core.yaml_loader import ProviderConfig, get_yaml_loader
from ..core.protocol import get_protocol_registry
from ..core.executor_base import (
    get_executor_registry, 
    ExecutionContext, 
    ExecutionResult,
    MethodExecutor
)
from ..core.errors import ProviderError, ErrorCode

logger = logging.getLogger(__name__)


class UniversalProvider(SocketIOComponent):
    """
    Universal provider that executes protocol methods using configurable executors
    
    This component:
    1. Loads provider configuration from YAML (including executor specification)
    2. Uses the executor registry to find the appropriate executor for methods
    3. Validates requests against protocol specifications
    4. Delegates execution to the configured executor
    5. Integrates with the SocketIO event system
    """
    
    def __init__(self, provider_name: str):
        super().__init__(
            component_type="provider",
            component_id=f"universal-provider-{provider_name}"
        )
        self.provider_name = provider_name
        self.provider_config: Optional[ProviderConfig] = None
        self.protocol_spec = None
        self.executor: Optional[MethodExecutor] = None
    
    async def on_ready(self):
        """Initialize after connecting to hub"""
        logger.info(f"Universal Provider {self.provider_name} is ready")
        
        # Load provider configuration
        await self._load_provider_config()
        
        # Get and initialize executor
        await self._initialize_executor()
        
        # Register event handlers
        await self._register_handlers()
        
        # Register provider with hub
        await self._register_provider()
        
        logger.info(f"Provider {self.provider_name} fully initialized with executor {self.provider_config.executor}")
    
    async def _load_provider_config(self):
        """Load provider configuration from YAML"""
        yaml_loader = get_yaml_loader()
        loaded_providers = yaml_loader.get_loaded_providers()
        
        if self.provider_name not in loaded_providers:
            raise ProviderError(
                f"Provider {self.provider_name} not found in YAML configurations",
                ErrorCode.PROVIDER_NOT_FOUND,
                provider_id=self.provider_name
            )
        
        self.provider_config = loaded_providers[self.provider_name]
        
        # Get protocol specification
        protocol_registry = get_protocol_registry()
        protocol_id = f"{self.provider_config.protocol}/{self.provider_config.version}"
        self.protocol_spec = protocol_registry.get(protocol_id)
        
        if not self.protocol_spec:
            raise ProviderError(
                f"Protocol {protocol_id} not found",
                ErrorCode.PROTOCOL_NOT_FOUND,
                provider_id=self.provider_name
            )
        
        logger.info(f"Loaded config for {self.provider_name}: protocol={protocol_id}")
    
    async def _initialize_executor(self):
        """Get and initialize the executor for this provider"""
        executor_registry = get_executor_registry()
        
        # Get executor specified in YAML config
        executor_id = self.provider_config.executor
        if not executor_id:
            raise ProviderError(
                f"No executor specified for provider {self.provider_name}",
                ErrorCode.CONFIGURATION_ERROR,
                provider_id=self.provider_name
            )
        
        # Find executor in registry
        executors = executor_registry.list_executors()
        if executor_id not in executors:
            raise ProviderError(
                f"Executor {executor_id} not found in registry",
                ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.provider_name
            )
        
        self.executor = executors[executor_id]
        
        # Verify executor supports the connection type
        connection_type = self.provider_config.connection.get('type')
        if connection_type not in self.executor.required_connection_types:
            raise ProviderError(
                f"Executor {executor_id} does not support connection type {connection_type}",
                ErrorCode.CONFIGURATION_ERROR,
                provider_id=self.provider_name
            )
        
        # Initialize the executor
        await self.executor.initialize(self.provider_config)
        
        logger.info(f"Initialized executor {executor_id} for provider {self.provider_name}")
    
    async def _register_handlers(self):
        """Register SocketIO event handlers"""
        
        @self.sio.event
        async def execute_task(data):
            """Handle task execution requests"""
            try:
                result = await self._execute_task_request(data)
                
                # Emit result back to hub
                await self.emit_with_correlation(
                    'task_execution_result',
                    result,
                    correlation_id=data.get('correlation_id')
                )
                
            except Exception as e:
                logger.error(f"Task execution failed: {e}")
                await self.emit_with_correlation(
                    'task_execution_error',
                    {
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'provider_id': self.provider_name,
                        'task_id': data.get('id')
                    },
                    correlation_id=data.get('correlation_id')
                )
        
        @self.sio.event
        async def provider_health_check(data):
            """Handle health check requests"""
            try:
                health_status = await self._check_health()
                
                await self.emit_with_correlation(
                    'provider_health_status',
                    {
                        'provider_id': self.provider_name,
                        'healthy': health_status['healthy'],
                        'status': health_status
                    },
                    correlation_id=data.get('correlation_id')
                )
                
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                await self.emit_with_correlation(
                    'provider_health_status',
                    {
                        'provider_id': self.provider_name,
                        'healthy': False,
                        'error': str(e)
                    },
                    correlation_id=data.get('correlation_id')
                )
        
        logger.info(f"Event handlers registered for {self.provider_name}")
    
    async def _register_provider(self):
        """Register this provider with the central hub"""
        registration_data = {
            'provider_id': self.provider_name,
            'protocol': f"{self.provider_config.protocol}/{self.provider_config.version}",
            'capabilities': self.provider_config.capabilities,
            'supported_methods': self.executor.supported_methods if self.executor else [],
            'connection_type': self.provider_config.connection.get('type'),
            'executor': self.provider_config.executor,
            'metadata': self.provider_config.metadata or {}
        }
        
        await self.emit_with_correlation('provider_registration', registration_data)
        logger.info(f"Registered provider {self.provider_name} with hub")
    
    async def _execute_task_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task request using the configured executor"""
        start_time = time.time()
        
        method = request_data.get('method')
        params = request_data.get('params', {})
        task_id = request_data.get('id')
        correlation_id = request_data.get('correlation_id')
        
        # Validate method exists in protocol
        if not self.protocol_spec or method not in self.protocol_spec.methods:
            raise ProviderError(
                f"Method {method} not supported by protocol {self.protocol_spec.protocol_id if self.protocol_spec else 'unknown'}",
                ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.provider_name
            )
        
        # Validate parameters against protocol
        method_spec = self.protocol_spec.methods[method]
        method_spec.validate_params(params)
        
        # Verify executor supports this method
        if method not in self.executor.supported_methods:
            raise ProviderError(
                f"Executor {self.provider_config.executor} does not support method {method}",
                ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.provider_name
            )
        
        # Create execution context
        context = ExecutionContext(
            provider_config=self.provider_config,
            task_id=task_id,
            correlation_id=correlation_id,
            timeout=request_data.get('timeout'),
            metadata=request_data.get('metadata', {})
        )
        
        # Execute using the configured executor
        logger.info(f"Executing {method} for task {task_id} using executor {self.provider_config.executor}")
        execution_result = await self.executor.execute(method, params, context)
        
        execution_time = time.time() - start_time
        
        # Build response
        response = {
            'success': execution_result.success,
            'task_id': task_id,
            'method': method,
            'provider': self.provider_name,
            'executor': self.provider_config.executor,
            'execution_time': execution_time
        }
        
        if execution_result.success:
            # Merge result data into response
            response.update(execution_result.data)
            response['result'] = execution_result.data
        else:
            response['error'] = execution_result.error
            response['error_code'] = execution_result.error_code
        
        return response
    
    async def _check_health(self) -> Dict[str, Any]:
        """Check provider health status"""
        health_status = {
            'healthy': True,
            'provider': self.provider_name,
            'executor': self.provider_config.executor if self.provider_config else None,
            'protocol': f"{self.provider_config.protocol}/{self.provider_config.version}" if self.provider_config else None,
            'connection_type': self.provider_config.connection.get('type') if self.provider_config else None,
            'checks': {}
        }
        
        try:
            # Check if executor is available
            if not self.executor:
                health_status['healthy'] = False
                health_status['checks']['executor'] = 'Not initialized'
            else:
                health_status['checks']['executor'] = 'Available'
            
            # Check protocol registry
            if not self.protocol_spec:
                health_status['healthy'] = False
                health_status['checks']['protocol'] = 'Not found'
            else:
                health_status['checks']['protocol'] = 'Available'
            
            # Add executor-specific health checks if available
            # (This could be extended to call executor.health_check() if implemented)
            
        except Exception as e:
            health_status['healthy'] = False
            health_status['checks']['general'] = f"Health check failed: {e}"
        
        return health_status
    
    async def on_shutdown(self):
        """Cleanup resources"""
        if self.executor:
            try:
                await self.executor.cleanup()
                logger.info(f"Cleaned up executor for {self.provider_name}")
            except Exception as e:
                logger.error(f"Failed to cleanup executor: {e}")
        
        logger.info(f"Universal Provider {self.provider_name} shut down")


async def create_universal_provider(provider_name: str) -> UniversalProvider:
    """
    Create and return a universal provider for the given provider name
    
    This is a convenience function that:
    1. Creates the provider instance
    2. Loads YAML configurations if needed
    3. Returns the ready-to-start provider
    """
    
    # Ensure YAML configurations are loaded
    from pathlib import Path
    from ..core.registry_manager import get_registry_manager
    
    registry_manager = get_registry_manager()
    protocol_dirs = [Path("gleitzeit_v5/protocols/yaml")]
    provider_dirs = [Path("gleitzeit_v5/providers/yaml")]
    
    # Load YAML configurations
    status = await registry_manager.scan_and_register_all(protocol_dirs, provider_dirs)
    
    if status.protocols_failed > 0 or status.providers_failed > 0:
        raise ProviderError(
            f"Failed to load YAML configurations: {len(status.errors)} errors",
            ErrorCode.CONFIGURATION_ERROR
        )
    
    # Create provider instance
    provider = UniversalProvider(provider_name)
    
    logger.info(f"Created universal provider for {provider_name}")
    return provider