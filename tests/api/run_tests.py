#!/usr/bin/env python3
"""
Test runner for Gleitzeit API tests
"""

import sys
import pytest
from pathlib import Path

# Add parent directories to path
test_dir = Path(__file__).parent
sys.path.insert(0, str(test_dir.parent.parent / "src"))


def run_tests(args=None):
    """Run the API test suite"""
    if args is None:
        args = []
    
    # Default pytest arguments
    default_args = [
        str(test_dir),  # Test directory
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--asyncio-mode=auto",  # Auto async mode
        "--color=yes",  # Colored output
    ]
    
    # Add coverage if requested
    if "--coverage" in args:
        args.remove("--coverage")
        default_args.extend([
            "--cov=gleitzeit.api",
            "--cov-report=term-missing",
            "--cov-report=html:coverage_html"
        ])
    
    # Add markers if requested
    if "--unit" in args:
        args.remove("--unit")
        default_args.append("-m not integration")
    elif "--integration" in args:
        args.remove("--integration")
        default_args.append("-m integration")
    
    # Combine with any additional args
    all_args = default_args + args
    
    # Run pytest
    return pytest.main(all_args)


if __name__ == "__main__":
    print("=" * 60)
    print("Running Gleitzeit API Test Suite")
    print("=" * 60)
    
    # Parse simple command line options
    args = sys.argv[1:]
    
    if "--help" in args:
        print("""
Usage: python run_tests.py [options]

Options:
    --coverage      Run with coverage report
    --unit          Run unit tests only
    --integration   Run integration tests only
    --help          Show this help message
    
Any additional arguments are passed to pytest.

Examples:
    python run_tests.py                    # Run all tests
    python run_tests.py --coverage         # Run with coverage
    python run_tests.py -k test_submit     # Run tests matching 'test_submit'
    python run_tests.py test_system.py     # Run specific test file
        """)
        sys.exit(0)
    
    # Run tests
    exit_code = run_tests(args)
    
    if exit_code == 0:
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Some tests failed")
        print("=" * 60)
    
    sys.exit(exit_code)