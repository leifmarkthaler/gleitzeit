#!/usr/bin/env python3
"""
Data transformation task for testing.
"""

def transform_text(text, operation="upper"):
    """Transform text based on operation."""
    print(f"Transforming text: '{text}' with operation: {operation}")
    
    if operation == "upper":
        result = text.upper()
    elif operation == "lower":
        result = text.lower()
    elif operation == "reverse":
        result = text[::-1]
    elif operation == "title":
        result = text.title()
    else:
        result = text
    
    print(f"Transformed result: '{result}'")
    return result

def combine_results(results):
    """Combine multiple results into one."""
    print(f"Combining {len(results)} results")
    
    combined = {
        "all_results": results,
        "count": len(results),
        "summary": f"Combined {len(results)} results"
    }
    
    # If results are numbers, add statistics
    if all(isinstance(r, (int, float)) for r in results):
        combined["sum"] = sum(results)
        combined["average"] = sum(results) / len(results) if results else 0
        combined["max"] = max(results) if results else None
        combined["min"] = min(results) if results else None
    
    print(f"Combined result: {combined}")
    return combined

# For direct execution testing
if __name__ == "__main__":
    print("Testing transform_text('hello world', 'upper'):", transform_text('hello world', 'upper'))
    print("Testing combine_results([1, 2, 3]):", combine_results([1, 2, 3]))