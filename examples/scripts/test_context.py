#!/usr/bin/env python3
"""
Test context passing.
"""

print("=== Context Test ===")
if 'context' in locals():
    print(f"Context found: {context}")
    for key, value in context.items():
        print(f"  {key}: {value} (type: {type(value).__name__})")
else:
    print("No context found")

result = {
    "context_received": 'context' in locals(),
    "context_keys": list(context.keys()) if 'context' in locals() else [],
    "test": "success"
}

print(f"\nResult: {result}")