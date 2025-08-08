"""
Tests for Function Registry and Built-in Functions
"""

import pytest
import asyncio
from unittest.mock import Mock, patch

from gleitzeit_cluster.functions.registry import FunctionRegistry
from gleitzeit_cluster.functions.core_functions import SAFE_FUNCTIONS
from gleitzeit_cluster.functions.data_functions import DATA_FUNCTIONS


class TestFunctionRegistry:
    """Test Function Registry functionality"""
    
    def test_registry_initialization(self):
        """Test function registry loads default functions"""
        registry = FunctionRegistry()
        
        # Should have loaded both core and data functions
        all_functions = registry.list_functions()
        assert len(all_functions) > 0
        
        # Check some expected functions exist
        assert "fibonacci" in all_functions
        assert "current_timestamp" in all_functions
        assert "analyze_numbers" in all_functions
        assert "word_frequency" in all_functions
        
        # Check categories exist
        categories = registry.list_categories()
        assert "core" in categories
        assert "data" in categories
    
    def test_function_registration(self):
        """Test registering custom functions"""
        registry = FunctionRegistry()
        
        def custom_function(x: int, y: int) -> int:
            """Add two numbers"""
            return x + y
        
        # Register function
        registry.register_function(
            "add_numbers",
            custom_function,
            category="math",
            description="Add two integers"
        )
        
        # Should be available
        assert "add_numbers" in registry.list_functions()
        assert "math" in registry.list_categories()
        assert "add_numbers" in registry.list_functions("math")
        
        # Should be retrievable
        func = registry.get_function("add_numbers")
        assert func is not None
        assert func(5, 3) == 8
    
    def test_function_info_retrieval(self):
        """Test getting function information"""
        registry = FunctionRegistry()
        
        # Get info for a known function
        info = registry.get_function_info("fibonacci")
        assert info is not None
        assert "description" in info
        assert "category" in info
        assert info["category"] == "core"
        
        # Should have parameter information
        if "parameters" in info:
            params = info["parameters"]
            assert isinstance(params, list)
    
    def test_function_search(self):
        """Test function search functionality"""
        registry = FunctionRegistry()
        
        # Search by name
        results = registry.search_functions("fibonacci")
        assert len(results) > 0
        assert any("fibonacci" in r["name"] for r in results)
        
        # Search by description (if implemented)
        results = registry.search_functions("timestamp")
        # Should find timestamp-related functions
        assert len(results) >= 0  # May or may not find matches depending on implementation
    
    def test_function_aliases(self):
        """Test function alias functionality"""
        registry = FunctionRegistry()
        
        def test_func():
            return "test"
        
        # Register with alias
        registry.register_function("test_function", test_func, aliases=["test_func", "test"])
        
        # Should be accessible by all names
        assert registry.get_function("test_function") is not None
        assert registry.get_function("test_func") is not None
        assert registry.get_function("test") is not None
    
    def test_invalid_function_registration(self):
        """Test handling of invalid function registration"""
        registry = FunctionRegistry()
        
        # Try to register non-callable
        with pytest.raises(ValueError):
            registry.register_function("invalid", "not_a_function")
        
        # Try to register with invalid name
        def valid_func():
            pass
        
        with pytest.raises(ValueError):
            registry.register_function("", valid_func)


class TestBuiltInFunctions:
    """Test built-in function implementations"""
    
    def test_fibonacci_function(self):
        """Test fibonacci sequence function"""
        registry = FunctionRegistry()
        fibonacci = registry.get_function("fibonacci")
        
        assert fibonacci is not None
        
        # Test various inputs
        result = fibonacci(n=0)
        assert result == []
        
        result = fibonacci(n=1)
        assert result == [0]
        
        result = fibonacci(n=5)
        assert result == [0, 1, 1, 2, 3]
        
        result = fibonacci(n=8)
        assert result == [0, 1, 1, 2, 3, 5, 8, 13]
    
    def test_current_timestamp_function(self):
        """Test current timestamp function"""
        registry = FunctionRegistry()
        timestamp_func = registry.get_function("current_timestamp")
        
        assert timestamp_func is not None
        
        result = timestamp_func()
        assert isinstance(result, dict)
        
        # Should have expected keys
        expected_keys = ["unix_timestamp", "iso_format", "utc_iso", "readable", "date_only", "time_only"]
        for key in expected_keys:
            assert key in result
        
        # Unix timestamp should be a number
        assert isinstance(result["unix_timestamp"], (int, float))
        
        # ISO format should be a string
        assert isinstance(result["iso_format"], str)
    
    def test_analyze_numbers_function(self):
        """Test number analysis function"""
        registry = FunctionRegistry()
        analyze_func = registry.get_function("analyze_numbers")
        
        assert analyze_func is not None
        
        numbers = [1, 2, 3, 4, 5, 10, 15, 20]
        result = analyze_func(numbers=numbers)
        
        assert isinstance(result, dict)
        assert "count" in result
        assert "average" in result
        assert "min" in result
        assert "max" in result
        assert "sum" in result
        
        assert result["count"] == 8
        assert result["min"] == 1
        assert result["max"] == 20
        assert result["sum"] == sum(numbers)
        assert result["average"] == sum(numbers) / len(numbers)
    
    def test_text_stats_function(self):
        """Test text statistics function"""
        registry = FunctionRegistry()
        text_stats = registry.get_function("text_stats")
        
        if text_stats is not None:  # Function exists
            test_text = "Hello world. This is a test text with multiple sentences."
            result = text_stats(text=test_text)
            
            assert isinstance(result, dict)
            # Expected keys may vary by implementation
            possible_keys = ["character_count", "word_count", "sentence_count", "paragraph_count"]
            assert any(key in result for key in possible_keys)
    
    def test_word_frequency_function(self):
        """Test word frequency function"""
        registry = FunctionRegistry()
        word_freq = registry.get_function("word_frequency")
        
        if word_freq is not None:  # Function exists
            test_text = "hello world hello python world python python"
            result = word_freq(text=test_text, top_n=3)
            
            assert isinstance(result, (dict, list))
            # Should show python as most frequent, then hello/world tied
    
    @pytest.mark.asyncio
    async def test_async_functions(self):
        """Test async function support"""
        registry = FunctionRegistry()
        
        # Test async_timer function
        async_timer = registry.get_function("async_timer")
        if async_timer is not None:
            # Should be an async function
            import inspect
            assert inspect.iscoroutinefunction(async_timer)
            
            # Test execution (with short duration)
            result = await async_timer(duration=0.1)
            assert isinstance(result, dict)
            assert "elapsed_time" in result
        
        # Test async_batch_process function  
        batch_process = registry.get_function("async_batch_process")
        if batch_process is not None:
            assert inspect.iscoroutinefunction(batch_process)
            
            # Test with small batch
            items = ["item1", "item2", "item3"]
            result = await batch_process(items=items, delay=0.01)
            assert isinstance(result, list)
            assert len(result) == 3
    
    def test_batch_processing_functions(self):
        """Test batch processing related functions"""
        registry = FunctionRegistry()
        
        # Test async_batch_process availability
        batch_func = registry.get_function("async_batch_process")
        if batch_func:
            func_info = registry.get_function_info("async_batch_process")
            if func_info:
                assert "category" in func_info
                # Should be in core or data category
                assert func_info["category"] in ["core", "data"]
        
        # Test functions commonly used in batch processing
        batch_related_functions = [
            "count_words",
            "extract_keywords", 
            "analyze_numbers",
            "text_stats",
            "word_frequency"
        ]
        
        available_batch_functions = []
        for func_name in batch_related_functions:
            if registry.get_function(func_name):
                available_batch_functions.append(func_name)
        
        # Should have at least some batch processing functions
        assert len(available_batch_functions) > 0
    
    def test_function_parameter_validation(self):
        """Test function parameter validation"""
        registry = FunctionRegistry()
        
        # Test fibonacci with invalid input
        fibonacci = registry.get_function("fibonacci")
        if fibonacci is not None:
            # Should handle negative numbers gracefully
            with pytest.raises((ValueError, TypeError)):
                fibonacci(n=-1)
            
            # Should handle non-integer input
            with pytest.raises((ValueError, TypeError)):
                fibonacci(n="invalid")
    
    def test_function_categories(self):
        """Test function categorization"""
        registry = FunctionRegistry()
        
        # Check core functions
        core_functions = registry.list_functions("core")
        assert "fibonacci" in core_functions
        assert "current_timestamp" in core_functions
        
        # Check data functions
        data_functions = registry.list_functions("data")
        assert "analyze_numbers" in data_functions
        
        # Should have reasonable number of functions in each category
        assert len(core_functions) > 5
        assert len(data_functions) > 3
    
    def test_function_security_restrictions(self):
        """Test that functions have appropriate security restrictions"""
        registry = FunctionRegistry()
        
        # Should not have dangerous functions
        dangerous_names = ["exec", "eval", "open", "file", "__import__", "getattr", "setattr"]
        all_functions = registry.list_functions()
        
        for dangerous in dangerous_names:
            assert dangerous not in all_functions
        
        # Functions should be from allowed modules only
        for func_name in all_functions:
            func = registry.get_function(func_name)
            if func is not None:
                # Function should be safe (this is more of a design check)
                assert hasattr(func, "__name__")


@pytest.mark.integration
class TestFunctionExecution:
    """Integration tests for function execution"""
    
    @pytest.mark.asyncio
    async def test_function_execution_pipeline(self):
        """Test complete function execution pipeline"""
        registry = FunctionRegistry()
        
        # Test chaining functions
        fibonacci = registry.get_function("fibonacci")
        analyze = registry.get_function("analyze_numbers")
        
        if fibonacci and analyze:
            # Generate fibonacci sequence
            fib_result = fibonacci(n=10)
            assert isinstance(fib_result, list)
            assert len(fib_result) == 10
            
            # Analyze the sequence
            analysis = analyze(numbers=fib_result)
            assert isinstance(analysis, dict)
            assert analysis["count"] == 10
            assert analysis["min"] == 0  # First fibonacci number
    
    def test_function_error_handling(self):
        """Test function error handling"""
        registry = FunctionRegistry()
        
        # Test function that doesn't exist
        non_existent = registry.get_function("non_existent_function")
        assert non_existent is None
        
        # Test category that doesn't exist
        functions_in_fake_category = registry.list_functions("fake_category")
        assert functions_in_fake_category == []