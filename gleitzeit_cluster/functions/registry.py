"""
Function Registry Manager

Manages secure function registration, discovery, and execution for Gleitzeit workflows.
"""

import asyncio
import inspect
import importlib
from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path

from .core_functions import SAFE_FUNCTIONS, FUNCTION_DOCS
from .data_functions import DATA_FUNCTIONS, DATA_FUNCTION_DOCS


class FunctionRegistry:
    """
    Centralized registry for secure workflow functions
    
    Manages function registration, validation, and metadata for safe execution
    in distributed workflows.
    """
    
    def __init__(self):
        self._functions: Dict[str, Callable] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._categories: Dict[str, Set[str]] = {}
        self._aliases: Dict[str, str] = {}
        
        # Load default secure functions
        self.load_default_functions()
    
    def load_default_functions(self):
        """Load default secure function libraries"""
        # Load core functions
        self.register_functions(SAFE_FUNCTIONS, category="core")
        for name, doc_info in FUNCTION_DOCS.items():
            if name in self._functions:
                self._metadata[name].update(doc_info)
        
        # Load data functions
        self.register_functions(DATA_FUNCTIONS, category="data")
        for name, doc_info in DATA_FUNCTION_DOCS.items():
            if name in self._functions:
                self._metadata[name].update(doc_info)
    
    def register_function(self, name: str, func: Callable, 
                         category: str = "custom", 
                         description: str = None,
                         aliases: List[str] = None) -> bool:
        """
        Register a single function
        
        Args:
            name: Function name
            func: Function to register
            category: Function category
            description: Function description
            aliases: Alternative names
            
        Returns:
            True if registered successfully
        """
        if not callable(func):
            raise ValueError(f"'{name}' is not callable")
        
        if name in self._functions:
            raise ValueError(f"Function '{name}' already registered")
        
        # Validate function safety (basic checks)
        self._validate_function(func)
        
        # Register function
        self._functions[name] = func
        
        # Store metadata
        self._metadata[name] = {
            "name": name,
            "category": category,
            "description": description or (func.__doc__.strip() if func.__doc__ else ""),
            "is_async": asyncio.iscoroutinefunction(func),
            "signature": str(inspect.signature(func)),
            "module": func.__module__ if hasattr(func, '__module__') else None
        }
        
        # Add to category
        if category not in self._categories:
            self._categories[category] = set()
        self._categories[category].add(name)
        
        # Register aliases
        if aliases:
            for alias in aliases:
                if alias in self._functions or alias in self._aliases:
                    raise ValueError(f"Alias '{alias}' already exists")
                self._aliases[alias] = name
        
        return True
    
    def register_functions(self, functions: Dict[str, Callable], 
                          category: str = "custom") -> int:
        """
        Register multiple functions
        
        Args:
            functions: Dictionary of name -> function
            category: Category for all functions
            
        Returns:
            Number of functions registered
        """
        count = 0
        for name, func in functions.items():
            try:
                self.register_function(name, func, category)
                count += 1
            except ValueError as e:
                print(f"Warning: Failed to register '{name}': {e}")
        
        return count
    
    def get_function(self, name: str) -> Optional[Callable]:
        """Get function by name or alias"""
        # Check direct name
        if name in self._functions:
            return self._functions[name]
        
        # Check alias
        if name in self._aliases:
            return self._functions[self._aliases[name]]
        
        return None
    
    def list_functions(self, category: str = None) -> List[str]:
        """List available functions, optionally filtered by category"""
        if category:
            return sorted(self._categories.get(category, set()))
        return sorted(self._functions.keys())
    
    def list_categories(self) -> List[str]:
        """List all function categories"""
        return sorted(self._categories.keys())
    
    def get_function_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a function"""
        if name not in self._functions:
            # Check aliases
            if name in self._aliases:
                name = self._aliases[name]
            else:
                return None
        
        info = self._metadata[name].copy()
        
        # Add parameter information
        func = self._functions[name]
        try:
            sig = inspect.signature(func)
            info["parameters"] = []
            
            for param_name, param in sig.parameters.items():
                param_info = {
                    "name": param_name,
                    "type": str(param.annotation) if param.annotation != param.empty else "Any",
                    "default": param.default if param.default != param.empty else None,
                    "required": param.default == param.empty
                }
                info["parameters"].append(param_info)
            
            # Return type
            if sig.return_annotation != sig.empty:
                info["return_type"] = str(sig.return_annotation)
            
        except Exception:
            pass  # Skip if signature inspection fails
        
        return info
    
    def search_functions(self, query: str) -> List[Dict[str, Any]]:
        """
        Search functions by name or description
        
        Args:
            query: Search query
            
        Returns:
            List of matching function info
        """
        results = []
        query_lower = query.lower()
        
        for name in self._functions:
            info = self._metadata[name]
            
            # Search in name
            if query_lower in name.lower():
                results.append({**info, "match_type": "name"})
                continue
            
            # Search in description
            description = info.get("description", "").lower()
            if query_lower in description:
                results.append({**info, "match_type": "description"})
        
        return results
    
    def validate_function_call(self, name: str, args: List[Any], kwargs: Dict[str, Any]) -> bool:
        """
        Validate function call parameters
        
        Args:
            name: Function name
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            True if call is valid
        """
        func = self.get_function(name)
        if not func:
            return False
        
        try:
            # Check if parameters match signature
            sig = inspect.signature(func)
            sig.bind(*args, **kwargs)
            return True
        except TypeError:
            return False
    
    def unregister_function(self, name: str) -> bool:
        """
        Unregister a function
        
        Args:
            name: Function name to remove
            
        Returns:
            True if function was removed
        """
        if name not in self._functions:
            return False
        
        # Remove from functions
        del self._functions[name]
        
        # Remove metadata
        if name in self._metadata:
            category = self._metadata[name].get("category")
            del self._metadata[name]
            
            # Remove from category
            if category and category in self._categories:
                self._categories[category].discard(name)
        
        # Remove aliases pointing to this function
        aliases_to_remove = [alias for alias, target in self._aliases.items() if target == name]
        for alias in aliases_to_remove:
            del self._aliases[alias]
        
        return True
    
    def clear_category(self, category: str) -> int:
        """
        Remove all functions from a category
        
        Args:
            category: Category to clear
            
        Returns:
            Number of functions removed
        """
        if category not in self._categories:
            return 0
        
        functions_to_remove = list(self._categories[category])
        count = 0
        
        for name in functions_to_remove:
            if self.unregister_function(name):
                count += 1
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        return {
            "total_functions": len(self._functions),
            "total_categories": len(self._categories),
            "total_aliases": len(self._aliases),
            "categories": {
                cat: len(funcs) for cat, funcs in self._categories.items()
            },
            "async_functions": len([
                name for name, info in self._metadata.items() 
                if info.get("is_async", False)
            ])
        }
    
    def export_function_list(self, format: str = "json") -> str:
        """
        Export function list for documentation
        
        Args:
            format: Export format (json, markdown)
            
        Returns:
            Formatted function list
        """
        if format == "json":
            import json
            return json.dumps({
                name: self.get_function_info(name) 
                for name in sorted(self._functions.keys())
            }, indent=2, default=str)
        
        elif format == "markdown":
            lines = ["# Gleitzeit Function Library\n"]
            
            for category in sorted(self._categories.keys()):
                lines.append(f"## {category.title()} Functions\n")
                
                for name in sorted(self._categories[category]):
                    info = self._metadata[name]
                    lines.append(f"### `{name}`")
                    
                    if info.get("description"):
                        lines.append(f"{info['description']}\n")
                    
                    if info.get("is_async"):
                        lines.append("*Async function*\n")
                    
                    if info.get("signature"):
                        lines.append(f"**Signature:** `{info['signature']}`\n")
                    
                    lines.append("")
            
            return "\n".join(lines)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _validate_function(self, func: Callable) -> None:
        """
        Basic function safety validation
        
        Args:
            func: Function to validate
            
        Raises:
            ValueError: If function is deemed unsafe
        """
        # Get function source if possible for basic checks
        try:
            source = inspect.getsource(func)
            
            # Check for dangerous patterns
            dangerous_patterns = [
                "eval(",
                "exec(",
                "__import__",
                "open(",
                "file(",
                "subprocess",
                "os.system",
                "os.popen",
                "__builtins__"
            ]
            
            source_lower = source.lower()
            for pattern in dangerous_patterns:
                if pattern in source_lower:
                    print(f"Warning: Function contains potentially unsafe pattern: {pattern}")
                    # Don't block, just warn for now
            
        except (OSError, TypeError):
            # Can't get source (built-in function, etc.)
            pass


# Global function registry instance
_global_registry = None


def get_function_registry() -> FunctionRegistry:
    """Get global function registry instance"""
    global _global_registry
    if _global_registry is None:
        _global_registry = FunctionRegistry()
    return _global_registry


def reset_function_registry() -> FunctionRegistry:
    """Reset global function registry"""
    global _global_registry
    _global_registry = FunctionRegistry()
    return _global_registry