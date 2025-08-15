#!/usr/bin/env python3
"""
Batch Processing Test Suite for Gleitzeit V4

Runs batch processing tests in isolated subprocesses to avoid circular imports.
"""

import os
import sys
import subprocess
import time
from datetime import datetime

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)


def print_header(title: str, level: int = 1):
    """Print formatted header"""
    if level == 1:
        print(f"\n{'='*80}")
        print(f"🧪 {title}")
        print('='*80)
    elif level == 2:
        print(f"\n{'─'*60}")
        print(f"📋 {title}")
        print('─'*60)
    else:
        print(f"\n{title}")


def run_test(test_file: str, description: str, timeout: int = 30) -> tuple[bool, str, float]:
    """Run a single test and return result"""
    print(f"🔬 Running {description}...")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, test_file],
            cwd=parent_dir,
            env={**os.environ, 'PYTHONPATH': '.'},
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        execution_time = time.time() - start_time
        
        # Check if test passed
        success = result.returncode == 0
        
        if success:
            # Look for test results in output
            lines = result.stdout.strip().split('\n')
            if lines:
                # Get last meaningful line as summary
                summary = lines[-1] if "✅" in lines[-1] or "passed" in lines[-1].lower() else "Completed successfully"
            else:
                summary = "Completed successfully"
            
            print(f"✅ {description} ({execution_time:.2f}s)")
            if "✅" in result.stdout:
                # Count successful tests
                success_count = result.stdout.count("✅")
                print(f"    └── {success_count} tests passed")
            else:
                print(f"    └── {summary}")
        else:
            print(f"❌ {description} ({execution_time:.2f}s)")
            if result.stderr:
                error_lines = result.stderr.strip().split('\n')
                print(f"    └── {error_lines[0][:100]}")
            else:
                print(f"    └── Test failed")
            summary = "Failed"
        
        return success, summary, execution_time
        
    except subprocess.TimeoutExpired:
        execution_time = time.time() - start_time
        print(f"❌ {description} ({execution_time:.2f}s)")
        print(f"    └── Test timed out")
        return False, "Timed out", execution_time
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"❌ {description} ({execution_time:.2f}s)")
        print(f"    └── Error: {str(e)}")
        return False, str(e), execution_time


def main():
    """Run all batch processing tests"""
    print_header("Gleitzeit V4 Batch Processing Test Suite", 1)
    print(f"🕒 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Define test files and their descriptions
    batch_tests = [
        ("tests/test_batch_simple.py", "Simple Batch Tests"),
        ("tests/test_batch_runner.py", "Comprehensive Batch Tests"),
    ]
    
    # Integration tests that need longer timeout
    integration_tests = [
        ("tests/test_batch_processor.py", "Batch Processor Integration"),
    ]
    
    # Additional integration test - only if exists
    optional_tests = [
        ("tests/test_batch_processing.py", "Batch Processing Unit Tests (pytest)"),
    ]
    
    all_tests = []
    
    # Run batch unit tests
    print_header("Batch Processing Core Tests", 2)
    for test_file, description in batch_tests:
        if os.path.exists(test_file) or os.path.exists(os.path.join("tests", test_file.split('/')[-1])):
            result = run_test(test_file, description)
            all_tests.append((description, result))
    
    # Run integration tests with longer timeout
    print_header("Batch Processing Integration Tests", 2)
    for test_file, description in integration_tests:
        if os.path.exists(test_file) or os.path.exists(os.path.join("tests", test_file.split('/')[-1])):
            result = run_test(test_file, description, timeout=90)  # 90 seconds for integration tests
            all_tests.append((description, result))
    
    # Run optional tests if they exist
    print_header("Optional Tests", 2)
    for test_file, description in optional_tests:
        if os.path.exists(test_file) or os.path.exists(os.path.join("tests", test_file.split('/')[-1])):
            result = run_test(test_file, description, timeout=60)
            all_tests.append((description, result))
        else:
            print(f"⏭️  Skipping {description} (file not found)")
    
    # Print summary
    print_header("Test Suite Summary", 1)
    
    passed = sum(1 for _, (success, _, _) in all_tests if success)
    failed = len(all_tests) - passed
    total_time = sum(time for _, (_, _, time) in all_tests)
    
    print(f"📊 **Results Overview**")
    print(f"   • Total Tests: {len(all_tests)}")
    print(f"   • Passed: {passed}")
    print(f"   • Failed: {failed}")
    print(f"   • Success Rate: {(passed/len(all_tests)*100):.1f}%")
    print(f"   • Total Time: {total_time:.2f}s")
    
    print(f"\n📋 **Detailed Results**")
    for description, (success, summary, exec_time) in all_tests:
        status = "✅" if success else "❌"
        print(f"   {status} {description} ({exec_time:.2f}s)")
        if not success:
            print(f"       └── {summary}")
    
    # Overall status
    print()
    if failed == 0:
        print("🎉 **EXCELLENT** - All batch processing tests passed!")
        print("✅ Batch processing functionality is fully operational")
    elif passed > failed:
        print("⚠️  **GOOD** - Most tests passed but some issues remain")
        print(f"   {failed} test(s) need attention")
    else:
        print("❌ **NEEDS ATTENTION** - Multiple test failures detected")
        print(f"   {failed} test(s) failed")
    
    print(f"\n🕒 **Completed at**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Exit with appropriate code
    exit_code = 0 if failed == 0 else 1
    print(f"\n🏁 Exiting with code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())