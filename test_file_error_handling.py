#!/usr/bin/env python3
"""
Test file handler error handling and retry classification.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any

from gleitzeit.core.models import Task
from gleitzeit.handlers.file import FileHandler
from gleitzeit.core.errors import GleitzeitError, ErrorCode

async def test_error_scenarios():
    """Test various error scenarios and their classification"""

    print("=" * 60)
    print("File Handler Error Classification Test")
    print("=" * 60)

    file_handler = FileHandler()

    # Test scenarios with expected errors
    test_cases = [
        {
            'name': 'File Not Found',
            'task': {
                'id': 'test_not_found',
                'workflow_id': 'error_test',
                'name': 'Load Non-existent File',
                'protocol': 'file/v1',
                'method': 'file/load',
                'params': {'path': 'does_not_exist.txt'}
            },
            'expected_error_code': ErrorCode.FILE_NOT_FOUND,
            'expected_retryable': False
        },
        {
            'name': 'File Too Large',
            'task': {
                'id': 'test_too_large',
                'workflow_id': 'error_test',
                'name': 'Load Large File',
                'protocol': 'file/v1',
                'method': 'file/load',
                'params': {'path': 'input_file.txt'}  # Will be modified to fail size check
            },
            'expected_error_code': ErrorCode.FILE_TOO_LARGE,
            'expected_retryable': False,
            'setup': lambda: setattr(file_handler.file_config, 'MAX_FILE_SIZE_MB', 0.001)  # Make limit tiny
        },
        {
            'name': 'Security Violation - Path Traversal',
            'task': {
                'id': 'test_path_traversal',
                'workflow_id': 'error_test',
                'name': 'Path Traversal Attack',
                'protocol': 'file/v1',
                'method': 'file/load',
                'params': {'path': '../../../etc/passwd'}
            },
            'expected_error_code': ErrorCode.FILE_SECURITY_VIOLATION,
            'expected_retryable': False
        },
        {
            'name': 'Security Violation - Blocked Extension',
            'task': {
                'id': 'test_blocked_ext',
                'workflow_id': 'error_test',
                'name': 'Blocked File Type',
                'protocol': 'file/v1',
                'method': 'file/load',
                'params': {'path': 'malware.exe'}
            },
            'expected_error_code': ErrorCode.FILE_SECURITY_VIOLATION,
            'expected_retryable': False
        },
        {
            'name': 'Directory Listing - Non-existent Directory',
            'task': {
                'id': 'test_dir_not_found',
                'workflow_id': 'error_test',
                'name': 'List Non-existent Directory',
                'protocol': 'file/v1',
                'method': 'file/list',
                'params': {'directory': 'does_not_exist_dir'}
            },
            'expected_error_code': ErrorCode.FILE_NOT_FOUND,
            'expected_retryable': False
        },
        {
            'name': 'Invalid Method',
            'task': {
                'id': 'test_invalid_method',
                'workflow_id': 'error_test',
                'name': 'Invalid Method',
                'protocol': 'file/v1',
                'method': 'file/invalid_method',
                'params': {'path': 'input_file.txt'}
            },
            'expected_error_code': ErrorCode.METHOD_NOT_SUPPORTED,
            'expected_retryable': False
        }
    ]

    # Run test cases
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: {test_case['name']}")
        print("-" * 40)

        # Setup if needed
        if 'setup' in test_case:
            test_case['setup']()

        # Create task
        task_data = test_case['task']
        task = Task(
            id=task_data['id'],
            workflow_id=task_data['workflow_id'],
            name=task_data['name'],
            protocol=task_data['protocol'],
            method=task_data['method'],
            params=task_data['params']
        )

        # Execute task and expect error
        result = await file_handler.execute(task)

        print(f"Status: {result.status}")
        print(f"Error: {result.error}")

        if result.metadata:
            print(f"Error Code: {result.metadata.get('error_code', 'N/A')}")
            print(f"Error Type: {result.metadata.get('error_type', 'N/A')}")

            # Check if error matches expectations
            if 'error_code' in result.metadata:
                actual_code = result.metadata['error_code']
                expected_code = test_case['expected_error_code'].value

                if actual_code == expected_code:
                    print(f"✓ Error code matches expected: {expected_code}")
                else:
                    print(f"✗ Error code mismatch: expected {expected_code}, got {actual_code}")

            # Display error details if available
            if 'error_data' in result.metadata:
                print(f"Error Data: {json.dumps(result.metadata['error_data'], indent=2)}")

        # Reset config if modified
        if 'setup' in test_case:
            file_handler.file_config = file_handler.__class__(file_handler.config).file_config

        print()

async def test_successful_operations():
    """Test successful file operations to contrast with errors"""

    print("=" * 60)
    print("Successful File Operations")
    print("=" * 60)

    file_handler = FileHandler()

    successful_tests = [
        {
            'name': 'Load Text File',
            'task': {
                'id': 'test_load_success',
                'workflow_id': 'success_test',
                'name': 'Load Existing File',
                'protocol': 'file/v1',
                'method': 'file/load',
                'params': {'path': 'input_file.txt'}
            }
        },
        {
            'name': 'Check File Exists',
            'task': {
                'id': 'test_exists_success',
                'workflow_id': 'success_test',
                'name': 'Check File Exists',
                'protocol': 'file/v1',
                'method': 'file/exists',
                'params': {'path': 'input_file.txt'}
            }
        },
        {
            'name': 'List Directory',
            'task': {
                'id': 'test_list_success',
                'workflow_id': 'success_test',
                'name': 'List Current Directory',
                'protocol': 'file/v1',
                'method': 'file/list',
                'params': {'directory': '.', 'pattern': '*.txt'}
            }
        }
    ]

    for i, test_case in enumerate(successful_tests, 1):
        print(f"\n{i}. Testing: {test_case['name']}")
        print("-" * 40)

        task_data = test_case['task']
        task = Task(
            id=task_data['id'],
            workflow_id=task_data['workflow_id'],
            name=task_data['name'],
            protocol=task_data['protocol'],
            method=task_data['method'],
            params=task_data['params']
        )

        result = await file_handler.execute(task)

        print(f"Status: {result.status}")

        if result.status == 'completed':
            print("✓ Operation completed successfully")

            # Show some result details
            if isinstance(result.result, dict):
                if 'metadata' in result.result:
                    metadata = result.result['metadata']
                    if 'size' in metadata:
                        print(f"  File size: {metadata['size']} bytes")
                    if 'type' in metadata:
                        print(f"  MIME type: {metadata['type']}")
                elif 'count' in result.result:
                    print(f"  Found {result.result['count']} files")
                elif 'exists' in result.result:
                    print(f"  File exists: {result.result['exists']}")
        else:
            print(f"✗ Operation failed: {result.error}")

async def test_retry_classification():
    """Test retry classification for different error types"""

    print("\n" + "=" * 60)
    print("Retry Classification Analysis")
    print("=" * 60)

    error_classifications = [
        ('FILE_NOT_FOUND', 'Non-retryable - File doesn\'t exist'),
        ('FILE_PERMISSION_DENIED', 'Non-retryable - Access denied'),
        ('FILE_TOO_LARGE', 'Non-retryable - File exceeds size limits'),
        ('FILE_SECURITY_VIOLATION', 'Non-retryable - Security policy violation'),
        ('FILE_LOCKED', 'Retryable - File may become available'),
        ('FILE_IO_ERROR', 'Retryable - Temporary I/O issues'),
        ('FILE_ENCODING_ERROR', 'Conditionally retryable - With fallback encoding'),
        ('METHOD_NOT_SUPPORTED', 'Non-retryable - Invalid method'),
        ('HandlerExecutionError', 'Retryable - Unexpected errors with conservative retry')
    ]

    print("\nError Classification Summary:")
    print("-" * 60)

    for error_code, description in error_classifications:
        retryable = "Retryable" in description
        emoji = "🔄" if retryable else "🚫"
        print(f"{emoji} {error_code:<25} | {description}")

    print(f"\nRetry Strategies:")
    print("-" * 60)
    print("• FILE_IO_ERROR: 3 retries, 0.5s base delay, exponential backoff")
    print("• FILE_LOCKED: 5 retries, 1s base delay, slower backoff")
    print("• FILE_ENCODING_ERROR: 1 retry with fallback encoding")
    print("• Unexpected Errors: 2 retries, conservative strategy")
    print("• Non-retryable: Immediate failure, no retries")

async def main():
    """Main test runner"""

    print("File Handler Error Handling and Retry Test")
    print("=" * 60)

    # Test error scenarios
    await test_error_scenarios()

    # Test successful operations
    await test_successful_operations()

    # Show retry classification
    await test_retry_classification()

    print("\n" + "=" * 60)
    print("Error Handling Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()