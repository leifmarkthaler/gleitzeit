"""
Base Executor Classes for Gleitzeit V5 Provider Architecture

Defines the interface and base implementations for protocol executors that can be
dynamically loaded and integrated with YAML-defined protocols and providers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Type
from dataclasses import dataclass

from .errors import ProviderError, ErrorCode
from .yaml_loader import ProviderConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Context information passed to executors"""
    provider_config: ProviderConfig
    task_id: str
    correlation_id: Optional[str] = None
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ExecutionResult:
    """Result of method execution"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: Optional[float] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MethodExecutor(ABC):
    """
    Base class for method executors
    
    Each executor handles one or more specific methods for a protocol.
    Executors are lightweight and stateless - all state is passed via context.
    """
    
    @property
    @abstractmethod
    def supported_methods(self) -> List[str]:
        """List of method names this executor supports"""
        pass
    
    @property
    @abstractmethod
    def required_connection_types(self) -> List[str]:
        """List of connection types this executor requires (e.g., 'http', 'local')"""
        pass
    
    @abstractmethod
    async def execute(
        self, 
        method_name: str, 
        params: Dict[str, Any], 
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        Execute a method with given parameters
        
        Args:
            method_name: The method to execute (e.g., 'llm/chat')
            params: Method parameters (already validated against protocol)
            context: Execution context with provider config and metadata
            
        Returns:
            ExecutionResult with success status and data
        """
        pass
    
    async def initialize(self, provider_config: ProviderConfig) -> None:
        """
        Initialize executor with provider configuration
        
        Called once when the provider starts up. Override for setup logic.
        """
        pass
    
    async def cleanup(self) -> None:
        """
        Cleanup executor resources
        
        Called when the provider shuts down. Override for cleanup logic.
        """
        pass


class HTTPExecutor(MethodExecutor):
    """
    Base class for HTTP-based executors
    
    Provides common HTTP functionality like session management and health checks.
    """
    
    def __init__(self):
        self.session = None
        self.base_url = None
        self.timeout = 60
    
    @property
    def required_connection_types(self) -> List[str]:
        return ['http']
    
    async def initialize(self, provider_config: ProviderConfig) -> None:
        """Initialize HTTP session and connection settings"""
        import aiohttp
        
        self.base_url = provider_config.connection.get('base_url')
        self.timeout = provider_config.connection.get('timeout', 60)
        
        if not self.base_url:
            raise ProviderError(
                "HTTP executors require 'base_url' in connection config",
                ErrorCode.CONFIGURATION_ERROR
            )
        
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        
        # Perform health check if configured
        health_check = provider_config.connection.get('health_check')
        if health_check:
            await self._health_check(health_check)
        
        logger.info(f"HTTP executor initialized for {self.base_url}")
    
    async def cleanup(self) -> None:
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _health_check(self, health_config: Dict[str, Any]) -> None:
        """Perform HTTP health check"""
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
            
            logger.info(f"Health check passed for {self.base_url}")
            
        except Exception as e:
            raise ProviderError(
                f"Health check failed: {e}",
                ErrorCode.PROVIDER_UNHEALTHY
            )


class LocalExecutor(MethodExecutor):
    """
    Base class for local execution (subprocess, direct calls, etc.)
    
    Provides common functionality for local execution environments.
    """
    
    def __init__(self):
        self.working_directory = None
        self.timeout = 30
    
    @property
    def required_connection_types(self) -> List[str]:
        return ['local']
    
    async def initialize(self, provider_config: ProviderConfig) -> None:
        """Initialize local execution environment"""
        from pathlib import Path
        
        self.working_directory = provider_config.connection.get('working_directory', '/tmp/gleitzeit')
        self.timeout = provider_config.connection.get('timeout', 30)
        
        # Ensure working directory exists
        Path(self.working_directory).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Local executor initialized with working dir: {self.working_directory}")


class ExecutorRegistry:
    """
    Registry for method executors
    
    Manages the mapping between methods and their executors.
    """
    
    def __init__(self):
        self._executors: Dict[str, MethodExecutor] = {}
        self._method_mapping: Dict[str, str] = {}  # method -> executor_id
    
    def register_executor(self, executor_id: str, executor: MethodExecutor) -> None:
        """Register an executor"""
        self._executors[executor_id] = executor
        
        # Map all supported methods to this executor
        for method in executor.supported_methods:
            if method in self._method_mapping:
                logger.warning(f"Method {method} already mapped to {self._method_mapping[method]}, overriding with {executor_id}")
            self._method_mapping[method] = executor_id
        
        logger.info(f"Registered executor {executor_id} for methods: {executor.supported_methods}")
    
    def get_executor_for_method(self, method_name: str) -> Optional[MethodExecutor]:
        """Get the executor for a specific method"""
        executor_id = self._method_mapping.get(method_name)
        if executor_id:
            return self._executors.get(executor_id)
        return None
    
    def list_supported_methods(self) -> List[str]:
        """List all supported methods"""
        return list(self._method_mapping.keys())
    
    def list_executors(self) -> Dict[str, MethodExecutor]:
        """Get all registered executors"""
        return self._executors.copy()
    
    async def initialize_all(self, provider_config: ProviderConfig) -> None:
        """Initialize all registered executors"""
        connection_type = provider_config.connection.get('type')
        
        for executor_id, executor in self._executors.items():
            # Only initialize executors that support this connection type
            if connection_type in executor.required_connection_types:
                try:
                    await executor.initialize(provider_config)
                    logger.info(f"Initialized executor {executor_id}")
                except Exception as e:
                    logger.error(f"Failed to initialize executor {executor_id}: {e}")
                    raise
    
    async def cleanup_all(self) -> None:
        """Cleanup all registered executors"""
        for executor_id, executor in self._executors.items():
            try:
                await executor.cleanup()
                logger.info(f"Cleaned up executor {executor_id}")
            except Exception as e:
                logger.error(f"Failed to cleanup executor {executor_id}: {e}")


# Example executor implementations

class OllamaLLMExecutor(HTTPExecutor):
    """Executor for Ollama LLM methods"""
    
    @property
    def supported_methods(self) -> List[str]:
        return ['llm/chat', 'llm/complete']
    
    async def execute(
        self, 
        method_name: str, 
        params: Dict[str, Any], 
        context: ExecutionContext
    ) -> ExecutionResult:
        """Execute Ollama LLM methods"""
        
        try:
            if method_name == 'llm/chat':
                result = await self._execute_chat(params)
            elif method_name == 'llm/complete':
                result = await self._execute_completion(params)
            else:
                raise ProviderError(f"Unsupported method: {method_name}")
            
            return ExecutionResult(
                success=True,
                data=result
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                data={},
                error=str(e),
                error_code=type(e).__name__
            )
    
    async def _execute_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat completion via Ollama"""
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
        """Execute text completion via Ollama"""
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


class PythonExecutor(LocalExecutor):
    """Executor for Python code execution"""
    
    @property
    def supported_methods(self) -> List[str]:
        return ['python/execute']
    
    async def execute(
        self, 
        method_name: str, 
        params: Dict[str, Any], 
        context: ExecutionContext
    ) -> ExecutionResult:
        """Execute Python code"""
        
        try:
            if method_name == 'python/execute':
                result = await self._execute_python_code(params, context)
            else:
                raise ProviderError(f"Unsupported method: {method_name}")
            
            return ExecutionResult(
                success=True,
                data=result
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                data={},
                error=str(e),
                error_code=type(e).__name__
            )
    
    async def _execute_python_code(self, params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """Execute Python code via subprocess"""
        code = params.get('code', '')
        code_context = params.get('context', {})
        timeout = params.get('timeout', self.timeout)
        
        python_executable = context.provider_config.connection.get('python_executable', 'python3')
        
        # Prepare code with context and result extraction
        full_code = ""
        
        # Add context variables
        if code_context:
            full_code += "# Context variables\n"
            for key, value in code_context.items():
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
                cwd=self.working_directory
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
                ErrorCode.PROVIDER_TIMEOUT
            )
        except Exception as e:
            raise ProviderError(
                f"Python execution failed: {e}",
                ErrorCode.TASK_EXECUTION_FAILED
            )


# Global registry instance
_executor_registry = ExecutorRegistry()


def get_executor_registry() -> ExecutorRegistry:
    """Get the global executor registry"""
    return _executor_registry


def register_executor(executor_id: str, executor: MethodExecutor) -> None:
    """Register an executor (convenience function)"""
    _executor_registry.register_executor(executor_id, executor)


# Register built-in executors
def register_builtin_executors():
    """Register the built-in executors"""
    register_executor('ollama-llm', OllamaLLMExecutor())
    register_executor('python-local', PythonExecutor())


# Auto-register built-in executors when module is imported
register_builtin_executors()