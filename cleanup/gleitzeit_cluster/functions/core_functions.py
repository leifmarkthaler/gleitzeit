"""
Core secure function library for Gleitzeit workflows

This module contains audited, secure functions that can be safely
executed in distributed workflows.
"""

import asyncio
import json
import math
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
import hashlib
import base64
import re


# ======================
# MATHEMATICAL FUNCTIONS
# ======================

def fibonacci_sequence(n: int) -> List[int]:
    """
    Generate Fibonacci sequence up to n terms
    
    Args:
        n: Number of terms (max 100 for safety)
        
    Returns:
        List of Fibonacci numbers
    """
    if n <= 0:
        return []
    if n > 100:  # Prevent huge calculations
        raise ValueError("Maximum 100 terms allowed")
    
    if n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    
    sequence = [0, 1]
    for i in range(2, n):
        sequence.append(sequence[i-1] + sequence[i-2])
    
    return sequence


def factorial(n: int) -> int:
    """
    Calculate factorial of n
    
    Args:
        n: Number (max 20 for safety)
        
    Returns:
        Factorial result
    """
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    if n > 20:  # Prevent huge calculations
        raise ValueError("Maximum value 20 allowed")
    
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def is_prime(n: int) -> bool:
    """
    Check if number is prime
    
    Args:
        n: Number to check (max 10^9)
        
    Returns:
        True if prime, False otherwise
    """
    if n > 1000000000:  # 1 billion limit
        raise ValueError("Number too large (max 1 billion)")
    
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    
    for i in range(3, int(math.sqrt(n)) + 1, 2):
        if n % i == 0:
            return False
    return True


def prime_factors(n: int) -> List[int]:
    """
    Find prime factors of n
    
    Args:
        n: Number to factor (max 10^6)
        
    Returns:
        List of prime factors
    """
    if n > 1000000:  # 1 million limit
        raise ValueError("Number too large (max 1 million)")
    
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1
    if n > 1:
        factors.append(n)
    return factors


def gcd(a: int, b: int) -> int:
    """Calculate greatest common divisor"""
    while b:
        a, b = b, a % b
    return abs(a)


def lcm(a: int, b: int) -> int:
    """Calculate least common multiple"""
    return abs(a * b) // gcd(a, b)


# ======================
# DATA ANALYSIS FUNCTIONS
# ======================

def analyze_numbers(numbers: List[Union[int, float]]) -> Dict[str, Any]:
    """
    Analyze a list of numbers
    
    Args:
        numbers: List of numeric values (max 10000 items)
        
    Returns:
        Statistical analysis results
    """
    if not numbers:
        return {"error": "Empty list provided"}
    
    if len(numbers) > 10000:  # Prevent excessive memory usage
        raise ValueError("Maximum 10000 numbers allowed")
    
    # Convert to floats for calculation
    nums = [float(x) for x in numbers]
    
    sorted_nums = sorted(nums)
    n = len(nums)
    
    # Calculate median
    if n % 2 == 0:
        median = (sorted_nums[n//2 - 1] + sorted_nums[n//2]) / 2
    else:
        median = sorted_nums[n//2]
    
    # Calculate mode (most frequent value)
    from collections import Counter
    counts = Counter(nums)
    max_count = max(counts.values())
    modes = [num for num, count in counts.items() if count == max_count]
    
    return {
        "count": n,
        "sum": sum(nums),
        "mean": sum(nums) / n,
        "median": median,
        "mode": modes[0] if len(modes) == 1 else modes,
        "min": min(nums),
        "max": max(nums),
        "range": max(nums) - min(nums),
        "variance": sum((x - sum(nums)/n) ** 2 for x in nums) / n,
        "std_deviation": math.sqrt(sum((x - sum(nums)/n) ** 2 for x in nums) / n),
        "unique_count": len(set(nums))
    }


def histogram_data(numbers: List[Union[int, float]], bins: int = 10) -> Dict[str, Any]:
    """
    Generate histogram data for numbers
    
    Args:
        numbers: List of numeric values
        bins: Number of bins (max 100)
        
    Returns:
        Histogram bin data
    """
    if not numbers:
        return {"error": "Empty list provided"}
    
    if bins > 100:
        bins = 100  # Limit bins
    
    nums = [float(x) for x in numbers]
    min_val, max_val = min(nums), max(nums)
    
    if min_val == max_val:
        return {
            "bins": [{"range": [min_val, max_val], "count": len(nums)}],
            "total": len(nums)
        }
    
    bin_width = (max_val - min_val) / bins
    bin_data = []
    
    for i in range(bins):
        bin_start = min_val + i * bin_width
        bin_end = min_val + (i + 1) * bin_width
        
        if i == bins - 1:  # Last bin includes max value
            count = sum(1 for x in nums if bin_start <= x <= bin_end)
        else:
            count = sum(1 for x in nums if bin_start <= x < bin_end)
        
        bin_data.append({
            "range": [round(bin_start, 6), round(bin_end, 6)],
            "count": count
        })
    
    return {
        "bins": bin_data,
        "total": len(nums),
        "bin_width": round(bin_width, 6)
    }


# ======================
# TEXT PROCESSING FUNCTIONS  
# ======================

def text_statistics(text: str) -> Dict[str, Any]:
    """
    Calculate comprehensive text statistics
    
    Args:
        text: Input text (max 100KB)
        
    Returns:
        Text analysis results
    """
    if not text:
        return {"error": "Empty text provided"}
    
    if len(text) > 100000:  # 100KB limit
        raise ValueError("Text too large (max 100KB)")
    
    words = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    paragraphs = text.split('\n\n')
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    # Character analysis
    char_counts = {}
    for char in text.lower():
        if char.isalpha():
            char_counts[char] = char_counts.get(char, 0) + 1
    
    return {
        "character_count": len(text),
        "character_count_no_spaces": len(text.replace(' ', '')),
        "word_count": len(words),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "average_word_length": sum(len(word) for word in words) / len(words) if words else 0,
        "average_sentence_length": sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0,
        "longest_word": max(words, key=len) if words else "",
        "shortest_word": min(words, key=len) if words else "",
        "unique_words": len(set(word.lower() for word in words)),
        "most_common_chars": sorted(char_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        "readability_score": len(words) / len(sentences) if sentences else 0  # Simple readability metric
    }


def word_frequency(text: str, top_n: int = 10) -> Dict[str, Any]:
    """
    Calculate word frequency in text
    
    Args:
        text: Input text
        top_n: Number of top words to return (max 100)
        
    Returns:
        Word frequency analysis
    """
    if not text:
        return {"error": "Empty text provided"}
    
    if top_n > 100:
        top_n = 100
    
    # Clean and tokenize
    words = re.findall(r'\b\w+\b', text.lower())
    
    # Common stop words to filter out
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
        'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'
    }
    
    # Filter stop words
    filtered_words = [word for word in words if word not in stop_words and len(word) > 2]
    
    from collections import Counter
    word_counts = Counter(filtered_words)
    
    return {
        "total_words": len(words),
        "unique_words": len(set(words)),
        "filtered_words": len(filtered_words),
        "top_words": word_counts.most_common(top_n),
        "vocabulary_richness": len(set(words)) / len(words) if words else 0
    }


def text_similarity(text1: str, text2: str) -> Dict[str, Any]:
    """
    Calculate similarity between two texts
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity metrics
    """
    if not text1 or not text2:
        return {"error": "Both texts must be provided"}
    
    # Simple word-based similarity
    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    jaccard_similarity = len(intersection) / len(union) if union else 0
    
    # Character-based similarity
    chars1 = set(text1.lower())
    chars2 = set(text2.lower())
    char_intersection = chars1.intersection(chars2)
    char_union = chars1.union(chars2)
    char_similarity = len(char_intersection) / len(char_union) if char_union else 0
    
    return {
        "jaccard_similarity": jaccard_similarity,
        "character_similarity": char_similarity,
        "common_words": len(intersection),
        "total_unique_words": len(union),
        "text1_unique": len(words1 - words2),
        "text2_unique": len(words2 - words1)
    }


# ======================
# UTILITY FUNCTIONS
# ======================

def hash_text(text: str, algorithm: str = "sha256") -> str:
    """
    Generate hash of text
    
    Args:
        text: Text to hash
        algorithm: Hash algorithm (sha256, sha1, md5)
        
    Returns:
        Hexadecimal hash string
    """
    algorithms = {"sha256": hashlib.sha256, "sha1": hashlib.sha1, "md5": hashlib.md5}
    
    if algorithm not in algorithms:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    
    hasher = algorithms[algorithm]()
    hasher.update(text.encode('utf-8'))
    return hasher.hexdigest()


def encode_base64(text: str) -> str:
    """Encode text to base64"""
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def decode_base64(encoded_text: str) -> str:
    """Decode base64 to text"""
    try:
        return base64.b64decode(encoded_text).decode('utf-8')
    except Exception:
        raise ValueError("Invalid base64 encoding")


def generate_uuid() -> str:
    """Generate a UUID string"""
    import uuid
    return str(uuid.uuid4())


def current_timestamp() -> Dict[str, Any]:
    """Get current timestamp in multiple formats"""
    now = datetime.now()
    utc_now = datetime.utcnow()
    
    return {
        "unix_timestamp": int(time.time()),
        "iso_format": now.isoformat(),
        "utc_iso": utc_now.isoformat() + "Z",
        "readable": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date_only": now.strftime("%Y-%m-%d"),
        "time_only": now.strftime("%H:%M:%S")
    }


def format_bytes(bytes_size: int) -> str:
    """Format bytes in human-readable form"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def random_data(data_type: str = "numbers", count: int = 10, **kwargs) -> List[Any]:
    """
    Generate random data for testing
    
    Args:
        data_type: Type of data (numbers, words, booleans)
        count: Number of items to generate (max 1000)
        **kwargs: Additional parameters
        
    Returns:
        List of random data
    """
    if count > 1000:
        count = 1000  # Limit for safety
    
    if data_type == "numbers":
        min_val = kwargs.get("min", 0)
        max_val = kwargs.get("max", 100)
        return [random.randint(min_val, max_val) for _ in range(count)]
    
    elif data_type == "floats":
        min_val = kwargs.get("min", 0.0)
        max_val = kwargs.get("max", 100.0)
        return [random.uniform(min_val, max_val) for _ in range(count)]
    
    elif data_type == "words":
        words = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape",
                "honeydew", "kiwi", "lemon", "mango", "nectarine", "orange", "papaya",
                "quince", "raspberry", "strawberry", "tangerine", "ugli", "vanilla"]
        return [random.choice(words) for _ in range(count)]
    
    elif data_type == "booleans":
        return [random.choice([True, False]) for _ in range(count)]
    
    else:
        raise ValueError(f"Unsupported data type: {data_type}")


# ======================
# ASYNC FUNCTIONS
# ======================

async def async_batch_process(items: List[Any], batch_size: int = 10, delay: float = 0.1) -> Dict[str, Any]:
    """
    Process items in batches with async delays
    
    Args:
        items: Items to process (max 1000)
        batch_size: Size of each batch (max 100)
        delay: Delay between batches in seconds
        
    Returns:
        Processing results
    """
    if len(items) > 1000:
        raise ValueError("Maximum 1000 items allowed")
    
    if batch_size > 100:
        batch_size = 100
    
    if delay > 10:
        delay = 10  # Max 10 second delay
    
    batches = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        
        # Simulate async processing
        await asyncio.sleep(delay)
        
        # Simple processing - count items by type
        batch_result = {
            "batch_number": len(batches) + 1,
            "items_processed": len(batch),
            "item_types": {}
        }
        
        for item in batch:
            item_type = type(item).__name__
            batch_result["item_types"][item_type] = batch_result["item_types"].get(item_type, 0) + 1
        
        batches.append(batch_result)
    
    return {
        "total_items": len(items),
        "total_batches": len(batches),
        "batch_size": batch_size,
        "processing_delay": delay,
        "batches": batches,
        "summary": {
            "total_processed": sum(b["items_processed"] for b in batches)
        }
    }


async def async_timer(duration: float, message: str = "Timer complete") -> Dict[str, Any]:
    """
    Async timer function
    
    Args:
        duration: Duration in seconds (max 300 = 5 minutes)
        message: Message to return
        
    Returns:
        Timer result
    """
    if duration > 300:  # 5 minute max
        raise ValueError("Maximum duration is 300 seconds (5 minutes)")
    
    start_time = time.time()
    await asyncio.sleep(duration)
    end_time = time.time()
    
    return {
        "message": message,
        "requested_duration": duration,
        "actual_duration": end_time - start_time,
        "completed_at": datetime.now().isoformat()
    }


# ======================
# FUNCTION REGISTRY
# ======================

# Export all safe functions for registration
SAFE_FUNCTIONS = {
    # Mathematical
    "fibonacci": fibonacci_sequence,
    "factorial": factorial,
    "is_prime": is_prime,
    "prime_factors": prime_factors,
    "gcd": gcd,
    "lcm": lcm,
    
    # Data analysis
    "analyze_numbers": analyze_numbers,
    "histogram": histogram_data,
    
    # Text processing
    "text_stats": text_statistics,
    "word_frequency": word_frequency,
    "text_similarity": text_similarity,
    
    # Utilities
    "hash_text": hash_text,
    "encode_base64": encode_base64,
    "decode_base64": decode_base64,
    "generate_uuid": generate_uuid,
    "current_timestamp": current_timestamp,
    "format_bytes": format_bytes,
    "random_data": random_data,
    
    # Async functions
    "async_batch_process": async_batch_process,
    "async_timer": async_timer,
}


# Function metadata for CLI help
FUNCTION_DOCS = {
    name: {
        "doc": func.__doc__.strip() if func.__doc__ else "No description available",
        "is_async": asyncio.iscoroutinefunction(func)
    }
    for name, func in SAFE_FUNCTIONS.items()
}