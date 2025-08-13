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
from typing import Dict, List, Any, Callable, Optional
from pathlib import Path
from datetime import datetime

from .base import ProtocolProvider

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
            raise ValueError(f"Module {module_name} not in allowed modules list")
        
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
                raise ValueError("Must be a lambda expression")
            
            # Evaluate lambda in restricted environment
            func = eval(lambda_str, {"__builtins__": {}})
            self.functions[name] = func
            logger.info(f"Registered lambda function: {name}")
        
        except Exception as e:
            logger.error(f"Failed to register lambda {name}: {e}")
            raise
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC method calls"""
        
        if method == "python/execute":
            # Execute Python code directly
            return await self._execute_code(params)
        elif method == "execute":
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
                raise ValueError(f"Function {func_name} not found")
        
        elif method == "eval":
            # Evaluate a Python expression (DANGEROUS - use with caution)
            if params.get("allow_eval", False):
                return await self._eval_expression(params)
            else:
                raise ValueError("eval method is disabled for security. Set allow_eval=true to enable.")
        
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _execute_function(self, params: Dict[str, Any]) -> Any:
        """Execute a registered function"""
        func_name = params.get("function")
        if not func_name:
            raise ValueError("Missing 'function' parameter")
        
        if func_name not in self.functions:
            raise ValueError(f"Function {func_name} not found")
        
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
    
    async def _execute_code(self, params: Dict[str, Any]) -> Any:
        """Execute arbitrary Python code"""
        import sys
        from io import StringIO
        import json
        
        code = params.get("code", "")
        timeout = params.get("timeout", 30)
        context = params.get("context", {})
        
        if not code:
            return {
                "result": None,
                "output": "",
                "error": "No code provided",
                "success": False,
                "execution_time": 0
            }
        
        # Prepare execution environment
        exec_globals = {
            "__builtins__": {
                # Safe builtins
                "print": print,
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "sum": sum,
                "min": min,
                "max": max,
                "abs": abs,
                "round": round,
                "sorted": sorted,
                "reversed": reversed,
                "any": any,
                "all": all,
                "isinstance": isinstance,
                "type": type,
                "hasattr": hasattr,
                "getattr": getattr,
                "setattr": setattr,
            },
            # Safe modules
            "json": json,
            "math": __import__("math"),
            "random": __import__("random"),
            "datetime": __import__("datetime"),
            "time": __import__("time"),
        }
        
        # Add context variables
        exec_globals.update(context)
        
        exec_locals = {}
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        start_time = __import__("time").time()
        
        try:
            # Execute the code
            exec(code, exec_globals, exec_locals)
            
            execution_time = __import__("time").time() - start_time
            output = captured_output.getvalue()
            
            # Get result variable if it exists
            result = exec_locals.get('result', None)
            
            return {
                "result": result,
                "output": output,
                "success": True,
                "execution_time": execution_time,
                "variables": {k: v for k, v in exec_locals.items() if not k.startswith('_')}
            }
            
        except Exception as e:
            execution_time = __import__("time").time() - start_time
            output = captured_output.getvalue()
            
            return {
                "result": None,
                "output": output,
                "error": str(e),
                "success": False,
                "execution_time": execution_time
            }
            
        finally:
            sys.stdout = old_stdout
    
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
                raise ValueError(f"Module {module_name} not allowed")
        
        elif func_type == "serialized":
            # Deserialize a pickled function (DANGEROUS - only from trusted sources)
            if params.get("allow_pickle", False):
                func_data = base64.b64decode(params.get("data"))
                func = pickle.loads(func_data)
                self.register_function(func_name, func)
            else:
                raise ValueError("Pickle deserialization disabled for security")
        
        else:
            raise ValueError(f"Unknown function type: {func_type}")
        
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
        return ["python/execute"]


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