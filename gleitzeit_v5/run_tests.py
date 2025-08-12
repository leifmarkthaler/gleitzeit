#!/usr/bin/env python3
"""
Test runner for Gleitzeit V5

Provides different test run configurations:
- Unit tests only (fast)
- Integration tests (slower, requires more setup)
- All tests
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and print results"""
    print(f"\n{'='*50}")
    print(f"🧪 {description}")
    print(f"{'='*50}")
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        print(f"✅ {description} - PASSED")
    else:
        print(f"❌ {description} - FAILED")
    
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Gleitzeit V5 Test Runner")
    parser.add_argument(
        '--type', 
        choices=['unit', 'integration', 'all', 'examples'],
        default='unit',
        help='Type of tests to run'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--coverage',
        action='store_true',
        help='Run with coverage reporting'
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    base_cmd = ['python', '-m', 'pytest']
    
    if args.verbose:
        base_cmd.extend(['-v', '-s'])
    
    if args.coverage:
        base_cmd.extend(['--cov=gleitzeit_v5', '--cov-report=html', '--cov-report=term'])
    
    # Test directory
    test_dir = Path(__file__).parent / "tests"
    
    success = True
    
    if args.type == 'unit':
        # Run unit tests (exclude integration tests)
        cmd = base_cmd + [str(test_dir), '-m', 'not integration']
        success = run_command(cmd, "Unit Tests")
    
    elif args.type == 'integration':
        # Run integration tests only
        cmd = base_cmd + [str(test_dir), '-m', 'integration']
        success = run_command(cmd, "Integration Tests")
    
    elif args.type == 'examples':
        # Test just the example workflows
        cmd = base_cmd + [str(test_dir / "test_integration.py::TestWorkflowFiles")]
        success = run_command(cmd, "Example Workflow Tests")
    
    elif args.type == 'all':
        # Run unit tests first
        print("🏃 Running all tests...")
        
        cmd = base_cmd + [str(test_dir), '-m', 'not integration']
        unit_success = run_command(cmd, "Unit Tests")
        
        cmd = base_cmd + [str(test_dir), '-m', 'integration']
        integration_success = run_command(cmd, "Integration Tests")
        
        success = unit_success and integration_success
    
    # Summary
    print(f"\n{'='*50}")
    if success:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Your Gleitzeit V5 CLI is working correctly!")
    else:
        print("💥 SOME TESTS FAILED!")
        print("❌ Please check the output above for details.")
    print(f"{'='*50}")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())