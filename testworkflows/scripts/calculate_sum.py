#!/usr/bin/env python3
"""
Calculate sum of numbers from context.
"""

# Get numbers from context (will be passed from previous task)
if 'context' in locals() and 'numbers' in context:
    numbers = context['numbers']
else:
    # Fallback for testing
    numbers = [10, 20, 30, 40, 50]

total = sum(numbers)
average = total / len(numbers) if numbers else 0

result = {
    "sum": total,
    "average": average,
    "input_count": len(numbers)
}

print(f"Sum of {len(numbers)} numbers: {total}")
print(f"Average: {average:.2f}")