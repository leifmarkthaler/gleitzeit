"""
Example Python functions for Gleitzeit V4 workflows

These functions can be called from workflows using the python/v1 protocol.
"""

import json
import hashlib
import statistics
from datetime import datetime
from typing import List, Dict, Any


def process_text(text: str, operations: List[str]) -> str:
    """
    Process text with a series of operations
    
    Args:
        text: Input text
        operations: List of operations to apply (upper, lower, strip, reverse)
    
    Returns:
        Processed text
    """
    result = text
    for op in operations:
        if op == "upper":
            result = result.upper()
        elif op == "lower":
            result = result.lower()
        elif op == "strip":
            result = result.strip()
        elif op == "reverse":
            result = result[::-1]
    return result


def analyze_data(numbers: List[float]) -> Dict[str, float]:
    """
    Perform statistical analysis on a list of numbers
    
    Args:
        numbers: List of numbers to analyze
    
    Returns:
        Dictionary with statistical metrics
    """
    if not numbers:
        return {"error": "Empty list"}
    
    return {
        "count": len(numbers),
        "sum": sum(numbers),
        "mean": statistics.mean(numbers),
        "median": statistics.median(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "std_dev": statistics.stdev(numbers) if len(numbers) > 1 else 0,
        "variance": statistics.variance(numbers) if len(numbers) > 1 else 0
    }


def transform_json(data: Dict[str, Any], transformations: Dict[str, str]) -> Dict[str, Any]:
    """
    Transform JSON data structure
    
    Args:
        data: Input JSON data
        transformations: Dictionary mapping old keys to new keys
    
    Returns:
        Transformed data
    """
    result = {}
    for old_key, new_key in transformations.items():
        if old_key in data:
            result[new_key] = data[old_key]
    
    # Add untransformed keys
    for key, value in data.items():
        if key not in transformations and key not in result:
            result[key] = value
    
    return result


def generate_hash(text: str, algorithm: str = "sha256") -> str:
    """
    Generate hash of text
    
    Args:
        text: Input text
        algorithm: Hash algorithm (md5, sha1, sha256, sha512)
    
    Returns:
        Hex digest of hash
    """
    algorithms = {
        "md5": hashlib.md5,
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512
    }
    
    if algorithm not in algorithms:
        raise ValueError(f"Unknown algorithm: {algorithm}")
    
    hasher = algorithms[algorithm]()
    hasher.update(text.encode('utf-8'))
    return hasher.hexdigest()


def merge_results(*results) -> Dict[str, Any]:
    """
    Merge multiple task results into a single dictionary
    
    Args:
        *results: Variable number of result dictionaries
    
    Returns:
        Merged dictionary
    """
    merged = {
        "merged_at": datetime.utcnow().isoformat(),
        "source_count": len(results),
        "data": {}
    }
    
    for i, result in enumerate(results):
        merged["data"][f"result_{i+1}"] = result
    
    return merged


def validate_data(data: Any, rules: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate data against rules
    
    Args:
        data: Data to validate
        rules: Validation rules
    
    Returns:
        Validation result with status and errors
    """
    errors = []
    
    # Type validation
    if "type" in rules:
        expected_type = rules["type"]
        if expected_type == "string" and not isinstance(data, str):
            errors.append(f"Expected string, got {type(data).__name__}")
        elif expected_type == "number" and not isinstance(data, (int, float)):
            errors.append(f"Expected number, got {type(data).__name__}")
        elif expected_type == "list" and not isinstance(data, list):
            errors.append(f"Expected list, got {type(data).__name__}")
        elif expected_type == "dict" and not isinstance(data, dict):
            errors.append(f"Expected dict, got {type(data).__name__}")
    
    # Length validation for strings and lists
    if isinstance(data, (str, list)):
        if "min_length" in rules and len(data) < rules["min_length"]:
            errors.append(f"Length {len(data)} is less than minimum {rules['min_length']}")
        if "max_length" in rules and len(data) > rules["max_length"]:
            errors.append(f"Length {len(data)} exceeds maximum {rules['max_length']}")
    
    # Range validation for numbers
    if isinstance(data, (int, float)):
        if "min_value" in rules and data < rules["min_value"]:
            errors.append(f"Value {data} is less than minimum {rules['min_value']}")
        if "max_value" in rules and data > rules["max_value"]:
            errors.append(f"Value {data} exceeds maximum {rules['max_value']}")
    
    # Pattern validation for strings
    if isinstance(data, str) and "pattern" in rules:
        import re
        if not re.match(rules["pattern"], data):
            errors.append(f"Value does not match pattern {rules['pattern']}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "data": data
    }


async def async_process(data: Any, delay: float = 1.0) -> Dict[str, Any]:
    """
    Async function example - process data with delay
    
    Args:
        data: Input data
        delay: Processing delay in seconds
    
    Returns:
        Processed result
    """
    import asyncio
    
    # Simulate async processing
    await asyncio.sleep(delay)
    
    return {
        "processed": True,
        "data": data,
        "delay": delay,
        "timestamp": datetime.utcnow().isoformat()
    }


def calculate_fibonacci(n: int) -> List[int]:
    """
    Calculate Fibonacci sequence up to n numbers
    
    Args:
        n: Number of Fibonacci numbers to generate
    
    Returns:
        List of Fibonacci numbers
    """
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    
    return fib