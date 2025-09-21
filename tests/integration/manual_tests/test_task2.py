#!/usr/bin/env python3
"""Task 2: Process data from task1"""

def main(task1):
    data = task1['result']['data']
    result = {'sum': sum(data), 'count': len(data)}
    print(f'Processed: {result}')
    return result

if __name__ == "__main__":
    # For testing standalone
    task1_result = {'result': {'data': [1, 2, 3], 'status': 'ok'}}
    result = main(task1_result)
    print(result)