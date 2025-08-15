"""
Provider Factory for Dynamic Provider Creation from YAML Configurations

Creates provider instances based on YAML configurations and protocol specifications,
enabling dynamic provider instantiation without hardcoded implementations.
"""

import logging
import asyncio
import aiohttp
import subprocess
import json
from typing import Dict, Any, Optional, Type, List
from pathlib import Path
from abc import ABC, abstractmethod

from gleitzeit.core.yaml_loader import ProviderConfig, get_yaml_loader
from gleitzeit.core.protocol import get_protocol_registry, ProtocolSpec
from gleitzeit.core.errors import ProviderError, ErrorCode
from gleitzeit.base.component import SocketIOComponent

logger = logging.getLogger(__name__)


class BaseProvider(SocketIOComponent):
    """Base class for dynamically created providers"""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(
            component_type="provider",
            component_id=f"provider-{config.name}"
        )
        self.config = config
        self.protocol_spec = None
        
    async def on_ready(self):
        """Called when the provider is ready (after connecting to hub)"""
        # Get protocol specification
        protocol_registry = get_protocol_registry()
        protocol_id = f"{self.config.protocol}/{self.config.version}"
        self.protocol_spec = protocol_registry.get(protocol_id)
        
        if not self.protocol_spec:
            raise ProviderError(
                f"Protocol {protocol_id} not found",
                ErrorCode.PROTOCOL_NOT_FOUND,
                provider_id=self.config.name
            )
        
        logger.info(f"Provider {self.config.name} ready with protocol {protocol_id}")
    
    async def initialize_provider(self):
        """Initialize provider-specific resources"""
        pass
    
    @abstractmethod
    async def execute_method(self, method_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a protocol method"""
        pass
    
    async def execute_task(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task request"""
        try:
            method = request.get('method')
            params = request.get('params', {})
            task_id = request.get('id')
            
            # Validate method exists in protocol
            if not self.protocol_spec or method not in self.protocol_spec.methods:
                raise ProviderError(
                    f"Method {method} not supported",
                    ErrorCode.METHOD_NOT_SUPPORTED,
                    provider_id=self.config.name
                )
            
            # Validate parameters against protocol
            method_spec = self.protocol_spec.methods[method]
            method_spec.validate_params(params)
            
            # Execute the method
            result = await self.execute_method(method, params)
            
            return {
                'success': True,
                'result': result,
                **result  # Flatten result into response
            }
            
        except Exception as e:
            logger.error(f"Task execution failed for {self.config.name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }


class HTTPProvider(BaseProvider):
    """HTTP-based provider for REST APIs like Ollama"""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.base_url = config.connection.get('base_url')
        self.timeout = config.connection.get('timeout', 60)
        self.session = None
    
    async def initialize_provider(self):
        """Initialize HTTP provider"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        
        # Health check if configured
        health_check = self.config.connection.get('health_check')
        if health_check:
            await self._health_check(health_check)
    
    async def _health_check(self, health_config: Dict[str, Any]):
        """Perform health check"""
        endpoint = health_config.get('endpoint', '/health')
        method = health_config.get('method', 'GET').upper()
        expected_status = health_config.get('expected_status', 200)
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == 'GET':
                async with self.session.get(url) as resp:
                    if resp.status != expected_status:
                        raise ProviderError(f"Health check failed: {resp.status}")
            elif method == 'POST':
                async with self.session.post(url) as resp:
                    if resp.status != expected_status:
                        raise ProviderError(f"Health check failed: {resp.status}")
            
            logger.info(f"Health check passed for {self.config.name}")
            
        except Exception as e:
            raise ProviderError(
                f"Health check failed: {e}",
                ErrorCode.PROVIDER_UNHEALTHY,
                provider_id=self.config.name
            )
    
    async def execute_method(self, method_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP-based method"""
        
        if method_name.startswith('llm/'):
            return await self._execute_llm_method(method_name, params)
        else:
            raise ProviderError(
                f"Unsupported method type: {method_name}",
                ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.config.name
            )
    
    async def _execute_llm_method(self, method_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM methods via Ollama API"""
        
        if method_name == 'llm/chat':
            return await self._execute_chat(params)
        elif method_name == 'llm/complete':
            return await self._execute_completion(params)
        else:
            raise ProviderError(f"Unknown LLM method: {method_name}")
    
    async def _execute_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat completion"""
        model = params.get('model', 'llama3.2')
        messages = params.get('messages', [])
        
        # Convert messages to Ollama format
        if messages:
            # Use the last user message as prompt for Ollama
            user_messages = [msg for msg in messages if msg.get('role') == 'user']
            prompt = user_messages[-1].get('content', '') if user_messages else ''
        else:
            prompt = ''
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False
        }
        
        async with self.session.post(f"{self.base_url}/api/generate", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                return {
                    'response': result.get('response', ''),
                    'model': model,
                    'done': True,
                    'total_duration': result.get('total_duration'),
                    'prompt_eval_count': result.get('prompt_eval_count'),
                    'eval_count': result.get('eval_count')
                }
            else:
                error_text = await resp.text()
                raise ProviderError(f"Ollama API error {resp.status}: {error_text}")
    
    async def _execute_completion(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute text completion"""
        model = params.get('model', 'llama3.2')
        prompt = params.get('prompt', '')
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False
        }
        
        async with self.session.post(f"{self.base_url}/api/generate", json=payload) as resp:
            if resp.status == 200:
                result = await resp.json()
                return {
                    'text': result.get('response', ''),
                    'model': model,
                    'done': True
                }
            else:
                error_text = await resp.text()
                raise ProviderError(f"Ollama API error {resp.status}: {error_text}")
    
    async def on_shutdown(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()


class LocalProvider(BaseProvider):
    """Local execution provider for subprocess-based tasks"""
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.python_executable = config.connection.get('python_executable', 'python3')
        self.timeout = config.connection.get('timeout', 30)
        self.working_directory = config.connection.get('working_directory', '/tmp')
    
    async def execute_method(self, method_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute local method"""
        
        if method_name.startswith('python/'):
            return await self._execute_python_method(method_name, params)
        else:
            raise ProviderError(
                f"Unsupported method type: {method_name}",
                ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.config.name
            )
    
    async def _execute_python_method(self, method_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code via subprocess"""
        
        if method_name == 'python/execute':
            return await self._execute_python_code(params)
        else:
            raise ProviderError(f"Unknown Python method: {method_name}")
    
    async def _execute_python_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code"""
        code = params.get('code', '')
        context = params.get('context', {})
        
        # Prepare code with context and result extraction
        full_code = ""
        
        # Add context variables
        if context:
            full_code += "# Context variables\n"
            for key, value in context.items():
                full_code += f"{key} = {repr(value)}\n"
            full_code += "\n"
        
        # Add user code
        full_code += "# User code\n"
        full_code += code + "\n"
        
        # Add result extraction
        full_code += "\n# Extract result for API\n"
        full_code += "if 'result' in locals():\n"
        full_code += "    print('__RESULT__:', result)\n"
        full_code += "elif 'output' in locals():\n"
        full_code += "    print('__RESULT__:', output)\n"
        
        try:
            # Execute code via subprocess
            process = await asyncio.create_subprocess_exec(
                self.python_executable, '-c', full_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_directory
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=self.timeout
            )
            
            stdout_text = stdout.decode('utf-8')
            stderr_text = stderr.decode('utf-8')
            
            # Extract result from output
            result = None
            output_lines = []
            
            for line in stdout_text.split('\n'):
                if line.startswith('__RESULT__:'):
                    result_str = line[11:].strip()
                    try:
                        result = eval(result_str)  # Safe since we control the code
                    except:
                        result = result_str
                else:
                    if line.strip():
                        output_lines.append(line)
            
            return {
                'result': str(result) if result is not None else '',
                'output': '\n'.join(output_lines),
                'success': process.returncode == 0,
                'error': stderr_text if stderr_text else None
            }
            
        except asyncio.TimeoutError:
            raise ProviderError(
                f"Python execution timeout after {self.timeout}s",
                ErrorCode.PROVIDER_TIMEOUT,
                provider_id=self.config.name
            )
        except Exception as e:
            raise ProviderError(
                f"Python execution failed: {e}",
                ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.config.name
            )
    
    def setup_events(self):
        """Setup component-specific Socket.IO event handlers"""
        # LocalProvider uses the base component event handling
        pass
    
    def get_capabilities(self) -> List[str]:
        """Return list of capabilities this component provides"""
        return self.config.capabilities if self.config else []
    
    async def on_ready(self):
        """Called when component is registered and ready"""
        await super().on_ready()  # Call BaseProvider's on_ready
    
    async def on_shutdown(self):
        """Called during graceful shutdown for component-specific cleanup"""
        logger.info(f"LocalProvider {self.config.name if self.config else 'unknown'} shutting down")
    
    async def initialize(self, hub):
        """Initialize the provider with the hub URL"""
        # Set the hub URL for the component to connect to
        if hasattr(self, 'config') and hasattr(self.config, 'hub_url'):
            self.config.hub_url = hub
        # Initialize any provider-specific resources
        await self.initialize_provider()
    
    async def initialize_provider(self):
        """Initialize local provider resources"""
        # Create working directory if it doesn't exist
        from pathlib import Path
        working_dir = Path(self.working_directory)
        working_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalProvider {self.config.name} initialized with working directory: {working_dir}")


class ProviderFactory:
    """Factory for creating providers from YAML configurations"""
    
    def __init__(self):
        self.provider_types = {
            'http': HTTPProvider,
            'local': LocalProvider,
        }
    
    def register_provider_type(self, connection_type: str, provider_class: Type[BaseProvider]):
        """Register a new provider type"""
        self.provider_types[connection_type] = provider_class
    
    def create_provider(self, config: ProviderConfig) -> BaseProvider:
        """Create a provider instance from configuration"""
        connection_type = config.connection.get('type')
        
        if connection_type not in self.provider_types:
            raise ProviderError(
                f"Unknown connection type: {connection_type}",
                ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=config.name
            )
        
        provider_class = self.provider_types[connection_type]
        return provider_class(config)
    
    async def create_and_initialize_provider(self, config: ProviderConfig, hub) -> BaseProvider:
        """Create and initialize a provider"""
        provider = self.create_provider(config)
        await provider.initialize(hub)
        return provider


# Global factory instance
_provider_factory = ProviderFactory()


def get_provider_factory() -> ProviderFactory:
    """Get the global provider factory instance"""
    return _provider_factory


async def create_provider_from_yaml(provider_name: str, hub) -> BaseProvider:
    """Create a provider from YAML configuration (convenience function)"""
    yaml_loader = get_yaml_loader()
    loaded_providers = yaml_loader.get_loaded_providers()
    
    if provider_name not in loaded_providers:
        raise ProviderError(
            f"Provider {provider_name} not found in loaded configurations",
            ErrorCode.PROVIDER_NOT_FOUND,
            provider_id=provider_name
        )
    
    config = loaded_providers[provider_name]
    factory = get_provider_factory()
    return await factory.create_and_initialize_provider(config, hub)