"""
Python Function Provider for Gleitzeit V4

Allows execution of arbitrary Python functions as protocol methods.
Supports both built-in functions and custom user-defined functions.
"""

import asyncio
import inspect
import importlib
import logging
import sys
import json
import pickle
import base64
import tempfile
from typing import Dict, List, Any, Callable, Optional
from pathlib import Path
from datetime import datetime

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import (
    ProviderError, InvalidParameterError, MethodNotSupportedError,
    ConfigurationError, ErrorCode
)

logger = logging.getLogger(__name__)


class PythonFunctionProvider(ProtocolProvider):
    """
    Provider that executes Python functions as protocol methods
    
    Supports:
    - Built-in Python functions
    - User-defined functions from modules
    - Lambda functions
    - Async functions
    - Dynamic function registration
    - Function serialization/deserialization
    """
    
    def __init__(self, provider_id: str = "python-function-1", allowed_modules: Optional[List[str]] = None):
        super().__init__(
            provider_id=provider_id,
            protocol_id="python/v1",
            name="Python Function Provider",
            description="Execute Python functions as protocol methods"
        )
        
        # Registry of available functions
        self.functions: Dict[str, Callable] = {}
        
        # Security: List of allowed modules to import from
        self.allowed_modules = allowed_modules or [
            "math", "statistics", "json", "re", "datetime", 
            "collections", "itertools", "functools", "operator",
            "urllib.parse", "hashlib", "base64", "uuid"
        ]
        
        # Register built-in functions
        self._register_builtin_functions()
    
    def _register_builtin_functions(self):
        """Register commonly used built-in functions"""
        
        # Math functions
        import math
        self.functions["math.sqrt"] = math.sqrt
        self.functions["math.sin"] = math.sin
        self.functions["math.cos"] = math.cos
        self.functions["math.factorial"] = math.factorial
        
        # String functions
        self.functions["str.upper"] = str.upper
        self.functions["str.lower"] = str.lower
        self.functions["str.strip"] = str.strip
        
        # List functions
        self.functions["len"] = len
        self.functions["sum"] = sum
        self.functions["max"] = max
        self.functions["min"] = min
        self.functions["sorted"] = sorted
        
        # JSON functions
        self.functions["json.dumps"] = json.dumps
        self.functions["json.loads"] = json.loads
        
        logger.info(f"Registered {len(self.functions)} built-in functions")
    
    async def initialize(self) -> None:
        """Initialize the Python function provider"""
        logger.info(f"Python function provider {self.provider_id} initialized")
    
    async def shutdown(self) -> None:
        """Shutdown the Python function provider"""
        logger.info(f"Python function provider {self.provider_id} shutdown")
    
    def register_function(self, name: str, func: Callable) -> None:
        """
        Register a Python function to be available as a method
        
        Args:
            name: Method name to register as
            func: Python function to execute
        """
        self.functions[name] = func
        logger.info(f"Registered function: {name}")
    
    def register_module_functions(self, module_name: str, function_names: Optional[List[str]] = None) -> None:
        """
        Register functions from a Python module
        
        Args:
            module_name: Name of the module to import from
            function_names: Specific functions to register (None = all)
        """
        if module_name not in self.allowed_modules:
            raise ConfigurationError(
                f"Module {module_name} not in allowed modules list"
            )
        
        try:
            module = importlib.import_module(module_name)
            
            if function_names:
                # Register specific functions
                for func_name in function_names:
                    if hasattr(module, func_name):
                        func = getattr(module, func_name)
                        if callable(func):
                            self.functions[f"{module_name}.{func_name}"] = func
                            logger.info(f"Registered {module_name}.{func_name}")
            else:
                # Register all callable attributes
                for attr_name in dir(module):
                    if not attr_name.startswith('_'):
                        attr = getattr(module, attr_name)
                        if callable(attr):
                            self.functions[f"{module_name}.{attr_name}"] = attr
                            logger.info(f"Registered {module_name}.{attr_name}")
        
        except ImportError as e:
            logger.error(f"Failed to import module {module_name}: {e}")
            raise
    
    def register_lambda(self, name: str, lambda_str: str) -> None:
        """
        Register a lambda function from string
        
        Args:
            name: Method name to register as
            lambda_str: Lambda function as string (e.g., "lambda x: x * 2")
        """
        try:
            # Security: Only allow simple lambda expressions
            if not lambda_str.strip().startswith("lambda"):
                raise InvalidParameterError(
                    "function",
                    "Must be a lambda expression"
                )
            
            # Evaluate lambda in restricted environment
            func = eval(lambda_str, {"__builtins__": {}})
            self.functions[name] = func
            logger.info(f"Registered lambda function: {name}")
        
        except Exception as e:
            logger.error(f"Failed to register lambda {name}: {e}")
            raise
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC method calls"""
        
        # Handle both with and without protocol prefix
        if method.startswith("python/"):
            method = method[7:]  # Remove "python/" prefix
        
        if method == "execute":
            # Check if we're executing a file or a function
            if 'file' in params or 'file_path' in params:
                return await self._execute_file(params)
            else:
                # Execute a registered function
                return await self._execute_function(params)
        
        elif method == "register":
            # Dynamically register a new function
            return await self._register_dynamic_function(params)
        
        elif method == "list":
            # List available functions
            return {
                "functions": list(self.functions.keys()),
                "count": len(self.functions)
            }
        
        elif method == "info":
            # Get information about a function
            func_name = params.get("function")
            if func_name in self.functions:
                func = self.functions[func_name]
                return {
                    "name": func_name,
                    "doc": func.__doc__,
                    "signature": str(inspect.signature(func)) if hasattr(func, '__code__') else "N/A",
                    "is_async": inspect.iscoroutinefunction(func)
                }
            else:
                raise InvalidParameterError(
                "function",
                f"Function {func_name} not found"
            )
        
        elif method == "eval":
            # Evaluate a Python expression (DANGEROUS - use with caution)
            if params.get("allow_eval", False):
                return await self._eval_expression(params)
            else:
                raise ConfigurationError(
                    "eval method is disabled for security. Set allow_eval=true to enable."
                )
        
        else:
            raise MethodNotSupportedError(method, self.provider_id)
    
    async def _execute_file(self, params: Dict[str, Any]) -> Any:
        """Execute a Python file"""
        import subprocess
        import sys
        from pathlib import Path
        
        # Get file path (support both 'file' and 'file_path' parameters)
        file_path = params.get('file') or params.get('file_path')
        if not file_path:
            raise InvalidParameterError(
                "file",
                "Missing 'file' or 'file_path' parameter"
            )
        
        # Check if file exists
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Python file not found: {file_path}")
        
        # Get timeout (default to 10 seconds)
        timeout = params.get('timeout', 10)
        
        # Get context variables if provided
        context = params.get('context', {})
        
        try:
            # Execute the Python file
            # Create a temporary script that sets up context and executes the file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                # Write context setup
                temp_file.write("import json\n")
                # Use repr to preserve the actual Python objects
                temp_file.write(f"context = {repr(context)}\n")
                temp_file.write("result = None\n")
                temp_file.write(f"exec(open('{file_path}').read())\n")
                temp_file.write("if 'result' in locals():\n")
                temp_file.write("    if isinstance(result, (dict, list)):\n")
                temp_file.write("        print(json.dumps(result))\n")
                temp_file.write("    else:\n")
                temp_file.write("        print(result)\n")
                temp_file_path = temp_file.name
            
            # Run the script
            process = await asyncio.create_subprocess_exec(
                sys.executable, temp_file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=timeout
                )
            finally:
                # Clean up temp file
                Path(temp_file_path).unlink(missing_ok=True)
            
            # Parse result
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Python execution failed"
                logger.error(f"Python file execution failed: {error_msg}")
                return {
                    "file": file_path,
                    "error": error_msg,
                    "success": False,
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Parse stdout
            stdout_text = stdout.decode().strip()
            
            # Split stdout into output lines and potential JSON result
            output_lines = []
            json_result = None
            
            for line in stdout_text.split('\n'):
                if line.strip().startswith('{') or line.strip().startswith('['):
                    try:
                        json_result = json.loads(line.strip())
                        break  # Found JSON result, stop looking
                    except json.JSONDecodeError:
                        output_lines.append(line)
                else:
                    output_lines.append(line)
            
            # Determine the result value
            if json_result:
                # Return the actual object, not a string representation
                result = json_result
            else:
                # Use the last non-empty line as result if no JSON found
                result = output_lines[-1] if output_lines else ""
            
            return {
                "result": result,  # Primary result (actual object if JSON, string otherwise)
                "output": '\n'.join(output_lines),  # Full stdout
                "success": True,
                "execution_time": timeout  # Will be replaced with actual time later
            }
            
        except asyncio.TimeoutError:
            logger.error(f"Python file execution timed out after {timeout} seconds: {file_path}")
            return {
                "file": file_path,
                "error": f"Execution timed out after {timeout} seconds",
                "success": False,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to execute Python file {file_path}: {e}")
            return {
                "file": file_path,
                "error": str(e),
                "success": False,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _execute_function(self, params: Dict[str, Any]) -> Any:
        """Execute a registered function"""
        func_name = params.get("function")
        if not func_name:
            raise InvalidParameterError(
                "function",
                "Missing 'function' parameter"
            )
        
        if func_name not in self.functions:
            raise InvalidParameterError(
                "function",
                f"Function {func_name} not found"
            )
        
        func = self.functions[func_name]
        
        # Get function arguments
        args = params.get("args", [])
        kwargs = params.get("kwargs", {})
        
        try:
            # Check if function is async
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                # Run sync function in executor to avoid blocking
                loop = asyncio.get_event_loop()
                # Create a wrapper function that properly handles args and kwargs
                from functools import partial
                func_with_args = partial(func, *args, **kwargs)
                result = await loop.run_in_executor(None, func_with_args)
            
            return {
                "function": func_name,
                "result": result,
                "success": True,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Function execution failed for {func_name}: {e}")
            return {
                "function": func_name,
                "error": str(e),
                "success": False,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _register_dynamic_function(self, params: Dict[str, Any]) -> Any:
        """Dynamically register a new function"""
        func_name = params.get("name")
        func_type = params.get("type", "lambda")  # lambda, module, serialized
        
        if func_type == "lambda":
            lambda_str = params.get("lambda")
            self.register_lambda(func_name, lambda_str)
            
        elif func_type == "module":
            module_name = params.get("module")
            function_name = params.get("function")
            if module_name in self.allowed_modules:
                module = importlib.import_module(module_name)
                func = getattr(module, function_name)
                self.register_function(func_name, func)
            else:
                raise ConfigurationError(
                    f"Module {module_name} not allowed"
                )
        
        elif func_type == "serialized":
            # Deserialize a pickled function (DANGEROUS - only from trusted sources)
            if params.get("allow_pickle", False):
                func_data = base64.b64decode(params.get("data"))
                func = pickle.loads(func_data)
                self.register_function(func_name, func)
            else:
                raise ConfigurationError(
                    "Pickle deserialization disabled for security"
                )
        
        else:
            raise InvalidParameterError(
                "func_type",
                f"Unknown function type: {func_type}"
            )
        
        return {
            "registered": func_name,
            "type": func_type,
            "success": True
        }
    
    async def _eval_expression(self, params: Dict[str, Any]) -> Any:
        """Evaluate a Python expression (use with extreme caution)"""
        expression = params.get("expression")
        context = params.get("context", {})
        
        # Create safe evaluation environment
        safe_dict = {
            "__builtins__": {
                "len": len,
                "sum": sum,
                "max": max,
                "min": min,
                "abs": abs,
                "round": round,
                "sorted": sorted,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
            }
        }
        safe_dict.update(context)
        
        try:
            result = eval(expression, safe_dict)
            return {
                "expression": expression,
                "result": result,
                "success": True
            }
        except Exception as e:
            return {
                "expression": expression,
                "error": str(e),
                "success": False
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        return {
            "status": "healthy",
            "details": f"Python function provider with {len(self.functions)} registered functions",
            "provider_id": self.provider_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["python/execute", "python/register", "python/list", "python/info", "python/eval"]


class CustomFunctionProvider(PythonFunctionProvider):
    """
    Extended provider for custom user functions
    
    Allows loading functions from user-defined Python files
    """
    
    def __init__(self, provider_id: str = "custom-python-1", 
                 functions_dir: Optional[Path] = None):
        super().__init__(provider_id=provider_id)
        
        self.functions_dir = functions_dir or Path.home() / ".gleitzeit" / "functions"
        self.functions_dir.mkdir(parents=True, exist_ok=True)
        
        # Load user functions
        self._load_user_functions()
    
    def _load_user_functions(self):
        """Load functions from user Python files"""
        # Look for Python files in functions directory
        for py_file in self.functions_dir.glob("*.py"):
            module_name = py_file.stem
            
            try:
                # Add directory to path temporarily
                sys.path.insert(0, str(self.functions_dir))
                
                # Import module
                module = importlib.import_module(module_name)
                
                # Register all functions from module
                for attr_name in dir(module):
                    if not attr_name.startswith('_'):
                        attr = getattr(module, attr_name)
                        if callable(attr):
                            self.register_function(f"{module_name}.{attr_name}", attr)
                
                logger.info(f"Loaded functions from {py_file}")
                
            except Exception as e:
                logger.error(f"Failed to load {py_file}: {e}")
            
            finally:
                # Remove from path
                sys.path.pop(0)
    
    def create_function_file(self, name: str, code: str) -> None:
        """
        Create a new Python file with user functions
        
        Args:
            name: Name for the Python file (without .py)
            code: Python code containing functions
        """
        file_path = self.functions_dir / f"{name}.py"
        
        # Add safety header
        safe_code = f'''"""
User-defined functions for Gleitzeit V4
Created: {datetime.utcnow().isoformat()}
"""

{code}
'''
        
        file_path.write_text(safe_code)
        logger.info(f"Created function file: {file_path}")
        
        # Reload to pick up new functions
        self._load_user_functions()