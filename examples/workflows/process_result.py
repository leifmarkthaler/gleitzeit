#!/usr/bin/env python3
"""Process result from previous task."""

# The context should contain the result from the previous task
# Try to get it from globals (where context might be injected)
import json

# Check if context is available (might be injected by provider)
if 'context' in globals():
    previous_result = context.get('previous_result', {})
else:
    # Fallback for testing
    previous_result = {"sum": 150, "count": 5, "average": 30.0}
print(f"Received result from calculate task: {previous_result}")

# Extract values - handle both direct dict and result wrapper
if isinstance(previous_result, dict):
    # Check if it's wrapped in a result structure
    if 'output' in previous_result:
        data = previous_result['output']
    else:
        data = previous_result
    
    sum_value = data.get('sum', 0)
    avg_value = data.get('average', 0)
else:
    sum_value = 0
    avg_value = 0

# Do some processing
doubled = sum_value * 2
print(f"Original sum: {sum_value}")
print(f"Doubled sum: {doubled}")
print(f"Average was: {avg_value}")

output = {
    "original_sum": sum_value,
    "doubled_sum": doubled,
    "average": avg_value,
    "message": f"Successfully processed: sum={sum_value}, doubled={doubled}"
}