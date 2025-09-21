"""Example tasks for the workflow."""

import random


def generate_numbers():
    """Generate a list of random numbers."""
    numbers = [random.randint(1, 100) for _ in range(5)]
    print(f"Generated numbers: {numbers}")
    return {"numbers": numbers}


def calculate_sum(context):
    """Calculate sum of the generated numbers."""
    numbers = context["generate_numbers"]["numbers"]
    total = sum(numbers)
    print(f"Sum of {numbers} = {total}")
    return {"sum": total}


def calculate_average(context):
    """Calculate average of the generated numbers."""
    numbers = context["generate_numbers"]["numbers"]
    avg = sum(numbers) / len(numbers)
    print(f"Average of {numbers} = {avg:.2f}")
    return {"average": avg}


def final_report(context):
    """Generate final report with all statistics."""
    numbers = context["generate_numbers"]["numbers"]
    total = context["calculate_sum"]["sum"]
    avg = context["calculate_average"]["average"]
    
    print("=" * 40)
    print("FINAL REPORT")
    print("=" * 40)
    print(f"Numbers: {numbers}")
    print(f"Sum: {total}")
    print(f"Average: {avg:.2f}")
    print(f"Min: {min(numbers)}")
    print(f"Max: {max(numbers)}")
    print("=" * 40)
    
    return {
        "numbers": numbers,
        "sum": total,
        "average": avg,
        "min": min(numbers),
        "max": max(numbers)
    }