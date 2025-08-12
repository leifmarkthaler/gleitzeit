"""
YAML-based Provider Component for Gleitzeit V5

A SocketIO component that can execute any protocol method based on YAML configurations.
This bridges YAML protocol definitions with actual provider execution.
"""

import asyncio
import logging
import aiohttp
import subprocess
import json
from typing import Dict, Any, Optional
from pathlib import Path

from ..base.component import SocketIOComponent
from ..core.yaml_loader import ProviderConfig, get_yaml_loader
from ..core.protocol import get_protocol_registry
from ..core.errors import ProviderError, ErrorCode

logger = logging.getLogger(__name__)


class YAMLProvider(SocketIOComponent):
    """
    Universal provider that can execute any protocol method based on YAML configuration
    
    This component:
    1. Loads provider configuration from YAML
    2. Validates requests against protocol specifications
    3. Executes methods based on connection type (HTTP, local, etc.)
    4. Integrates with the SocketIO event system
    """
    
    def __init__(self, provider_name: str):
        super().__init__(
            component_type="provider",
            component_id=f"yaml-provider-{provider_name}"
        )
        self.provider_name = provider_name
        self.provider_config: Optional[ProviderConfig] = None
        self.protocol_spec = None
        self.session = None  # For HTTP providers
    
    async def on_ready(self):
        """Initialize after connecting to hub"""
        logger.info(f"YAML Provider {self.provider_name} is ready")
        
        # Load provider configuration
        await self._load_provider_config()
        
        # Initialize based on connection type
        await self._initialize_connection()
        
        # Register event handlers
        await self._register_handlers()
        
        logger.info(f"Provider {self.provider_name} fully initialized")
    
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
    
    async def _initialize_connection(self):
        """Initialize connection based on provider type"""
        connection_type = self.provider_config.connection.get('type')
        
        if connection_type == 'http':
            await self._initialize_http_connection()
        elif connection_type == 'local':
            await self._initialize_local_connection()
        else:
            raise ProviderError(
                f"Unsupported connection type: {connection_type}",
                ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                provider_id=self.provider_name
            )
    
    async def _initialize_http_connection(self):
        """Initialize HTTP connection"""
        timeout = self.provider_config.connection.get('timeout', 60)
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        )
        
        # Perform health check if configured
        health_check = self.provider_config.connection.get('health_check')
        if health_check:
            await self._http_health_check(health_check)
        
        logger.info(f"HTTP connection initialized for {self.provider_name}")
    
    async def _initialize_local_connection(self):
        """Initialize local execution environment"""
        # For local providers, just verify the working directory exists
        working_dir = self.provider_config.connection.get('working_directory', '/tmp')
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"Local execution environment ready for {self.provider_name}")
    
    async def _http_health_check(self, health_config: Dict[str, Any]):
        """Perform HTTP health check"""
        base_url = self.provider_config.connection.get('base_url')
        endpoint = health_config.get('endpoint', '/health')
        method = health_config.get('method', 'GET').upper()
        expected_status = health_config.get('expected_status', 200)
        
        url = f"{base_url}{endpoint}"
        
        try:
            if method == 'GET':
                async with self.session.get(url) as resp:
                    if resp.status != expected_status:
                        raise ProviderError(f"Health check failed: {resp.status}")
            elif method == 'POST':
                async with self.session.post(url) as resp:
                    if resp.status != expected_status:
                        raise ProviderError(f"Health check failed: {resp.status}")
            
            logger.info(f"Health check passed for {self.provider_name}")
            
        except Exception as e:
            raise ProviderError(
                f"Health check failed: {e}",
                ErrorCode.PROVIDER_UNHEALTHY,
                provider_id=self.provider_name
            )
    
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
                        'provider_id': self.provider_name
                    },
                    correlation_id=data.get('correlation_id')
                )
        
        logger.info(f"Event handlers registered for {self.provider_name}")
    
    async def _execute_task_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task request"""
        method = request_data.get('method')
        params = request_data.get('params', {})
        task_id = request_data.get('id')
        
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
        
        # Execute based on protocol type
        if method.startswith('llm/'):
            result = await self._execute_llm_method(method, params)
        elif method.startswith('python/'):
            result = await self._execute_python_method(method, params)
        else:
            raise ProviderError(
                f"Unsupported method type: {method}",
                ErrorCode.METHOD_NOT_SUPPORTED,
                provider_id=self.provider_name
            )
        
        return {
            'success': True,
            'task_id': task_id,
            'method': method,
            'provider': self.provider_name,
            'result': result,
            **result  # Flatten result into response
        }
    
    async def _execute_llm_method(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM methods via HTTP"""
        if self.provider_config.connection.get('type') != 'http':
            raise ProviderError("LLM methods require HTTP connection")
        
        base_url = self.provider_config.connection.get('base_url')
        
        if method == 'llm/chat':
            return await self._execute_ollama_chat(base_url, params)
        elif method == 'llm/complete':
            return await self._execute_ollama_completion(base_url, params)
        else:
            raise ProviderError(f"Unknown LLM method: {method}")
    
    async def _execute_ollama_chat(self, base_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat via Ollama API"""
        model = params.get('model', 'llama3.2')
        messages = params.get('messages', [])
        
        # Convert messages to Ollama prompt format
        if messages:
            user_messages = [msg for msg in messages if msg.get('role') == 'user']
            prompt = user_messages[-1].get('content', '') if user_messages else ''
        else:
            prompt = ''
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False
        }
        
        async with self.session.post(f"{base_url}/api/generate", json=payload) as resp:
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
    
    async def _execute_ollama_completion(self, base_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute completion via Ollama API"""
        model = params.get('model', 'llama3.2')
        prompt = params.get('prompt', '')
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False
        }
        
        async with self.session.post(f"{base_url}/api/generate", json=payload) as resp:
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
    
    async def _execute_python_method(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python methods via subprocess"""
        if self.provider_config.connection.get('type') != 'local':
            raise ProviderError("Python methods require local connection")
        
        if method == 'python/execute':
            return await self._execute_python_code(params)
        else:
            raise ProviderError(f"Unknown Python method: {method}")
    
    async def _execute_python_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code via subprocess"""
        code = params.get('code', '')
        context = params.get('context', {})
        timeout = params.get('timeout', self.provider_config.connection.get('timeout', 30))
        
        python_executable = self.provider_config.connection.get('python_executable', 'python3')
        working_directory = self.provider_config.connection.get('working_directory', '/tmp')
        
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
                python_executable, '-c', full_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=timeout
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
                'error': stderr_text if stderr_text else None,
                'execution_time': 0.0  # Could add timing if needed
            }
            
        except asyncio.TimeoutError:
            raise ProviderError(
                f"Python execution timeout after {timeout}s",
                ErrorCode.PROVIDER_TIMEOUT,
                provider_id=self.provider_name
            )
        except Exception as e:
            raise ProviderError(
                f"Python execution failed: {e}",
                ErrorCode.TASK_EXECUTION_FAILED,
                provider_id=self.provider_name
            )
    
    async def on_shutdown(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
        logger.info(f"YAML Provider {self.provider_name} shut down")