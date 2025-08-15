#!/usr/bin/env python3
"""
Format a report from context data.
"""
from datetime import datetime

# Get data from context
if 'context' in locals():
    sum_data = context.get('sum_data', {})
    number_data = context.get('number_data', {})
else:
    # Fallback for testing
    sum_data = {"sum": 150, "average": 30}
    number_data = {"numbers": [10, 20, 30, 40, 50], "count": 5}

# Create report
report = f"""
=== Python Calculation Report ===
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Numbers Generated: {number_data.get('count', 0)}
Values: {number_data.get('numbers', [])}

Statistics:
- Sum: {sum_data.get('sum', 0)}
- Average: {sum_data.get('average', 0):.2f}

Status: Complete
"""

result = {
    "report": report,
    "timestamp": datetime.now().isoformat(),
    "success": True
}

print(report)