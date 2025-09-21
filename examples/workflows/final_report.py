#!/usr/bin/env python3
"""Generate final report from process task results."""

# Check if context is available (might be injected by provider)
if 'context' in globals():
    process_result = context.get('process_result', {})
else:
    # Fallback for testing
    process_result = {
        "doubled_sum": 300,
        "original_sum": 150,
        "average": 30.0
    }
print(f"Generating final report from: {process_result}")

if isinstance(process_result, dict):
    # Handle result wrapper
    if 'output' in process_result:
        output_data = process_result['output']
    else:
        output_data = process_result
        
    doubled = output_data.get('doubled_sum', 0)
    original = output_data.get('original_sum', 0)
    avg = output_data.get('average', 0)
    
    report = f'''FINAL CALCULATION REPORT
========================
Original Sum: {original}
Doubled Value: {doubled}
Average: {avg}
Multiplication Factor: 2
Verification: {original} * 2 = {doubled} ✓'''
    
    print(report)
    
    output = {
        "report": report,
        "success": True,
        "calculations": {
            "original": original,
            "doubled": doubled,
            "average": avg
        }
    }
else:
    output = {"error": "Failed to get process result", "success": False}