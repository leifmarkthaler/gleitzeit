#!/usr/bin/env python3
"""
Test runner for Gleitzeit V4

This script provides different ways to run the test suite with various options
for development, CI, and performance testing.
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def run_command(cmd, **kwargs):
    """Run a shell command and return the result"""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    return result.returncode == 0


def install_dependencies():
    """Install test dependencies"""
    print("Installing test dependencies...")
    return run_command([
        sys.executable, "-m", "pip", "install", "-r", "tests/requirements.txt"
    ])


def run_basic_tests():
    """Run basic unit tests"""
    print("Running basic unit tests...")
    return run_command([
        sys.executable, "-m", "pytest", 
        "tests/",
        "-v",
        "--tb=short",
        "-m", "not slow and not distributed"
    ])


def run_all_tests():
    """Run all tests including slow ones"""
    print("Running all tests...")
    return run_command([
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short"
    ])


def run_integration_tests():
    """Run integration tests"""
    print("Running integration tests...")
    return run_command([
        sys.executable, "-m", "pytest",
        "tests/",
        "-v", 
        "--tb=short",
        "-m", "integration"
    ])


def run_distributed_tests():
    """Run distributed coordination tests"""
    print("Running distributed tests...")
    return run_command([
        sys.executable, "-m", "pytest",
        "tests/test_distributed_coordination.py",
        "-v",
        "--tb=short"
    ])


def run_performance_tests():
    """Run performance tests"""
    print("Running performance tests...")
    return run_command([
        sys.executable, "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short", 
        "-m", "performance"
    ])


def run_coverage_tests():
    """Run tests with coverage reporting"""
    print("Running tests with coverage...")
    return run_command([
        sys.executable, "-m", "pytest",
        "tests/",
        "--cov=gleitzeit_v4",
        "--cov-report=html",
        "--cov-report=term",
        "--cov-fail-under=80"
    ])


def run_specific_test(test_path):
    """Run a specific test file or test function"""
    print(f"Running specific test: {test_path}")
    return run_command([
        sys.executable, "-m", "pytest",
        test_path,
        "-v",
        "--tb=long"
    ])


def run_manual_tests():
    """Run manual test scripts for debugging"""
    print("Running manual tests...")
    
    manual_tests = [
        "tests/test_parameter_substitution.py",
        "tests/test_distributed_coordination.py", 
        "tests/test_provider_management.py"
    ]
    
    success = True
    for test_file in manual_tests:
        if os.path.exists(test_file):
            print(f"\n=== Running manual test: {test_file} ===")
            if not run_command([sys.executable, test_file, "manual"]):
                success = False
        else:
            print(f"Manual test not found: {test_file}")
    
    return success


def lint_code():
    """Run code linting"""
    print("Running code linting...")
    
    # Try to run linting tools if available
    tools = [
        (["python", "-m", "flake8", "gleitzeit_v4/"], "flake8"),
        (["python", "-m", "black", "--check", "gleitzeit_v4/"], "black"),
        (["python", "-m", "mypy", "gleitzeit_v4/"], "mypy")
    ]
    
    success = True
    for cmd, tool in tools:
        try:
            print(f"Running {tool}...")
            if not run_command(cmd, capture_output=True):
                print(f"⚠️  {tool} found issues (non-critical)")
        except FileNotFoundError:
            print(f"⚠️  {tool} not installed, skipping")
    
    return success


def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="Gleitzeit V4 Test Runner")
    parser.add_argument("command", nargs="?", default="basic",
                       choices=["basic", "all", "integration", "distributed", 
                               "performance", "coverage", "manual", "lint", "install"],
                       help="Test command to run")
    parser.add_argument("--test", "-t", help="Run specific test file or function")
    parser.add_argument("--install-deps", action="store_true", 
                       help="Install test dependencies first")
    
    args = parser.parse_args()
    
    # Change to project directory
    os.chdir(project_root)
    
    # Install dependencies if requested
    if args.install_deps or args.command == "install":
        if not install_dependencies():
            print("❌ Failed to install dependencies")
            return 1
        
        if args.command == "install":
            print("✅ Test dependencies installed successfully")
            return 0
    
    # Run specific test if provided
    if args.test:
        success = run_specific_test(args.test)
        return 0 if success else 1
    
    # Run command
    commands = {
        "basic": run_basic_tests,
        "all": run_all_tests,
        "integration": run_integration_tests,
        "distributed": run_distributed_tests,
        "performance": run_performance_tests,
        "coverage": run_coverage_tests,
        "manual": run_manual_tests,
        "lint": lint_code
    }
    
    command_func = commands.get(args.command)
    if not command_func:
        print(f"Unknown command: {args.command}")
        return 1
    
    print(f"🚀 Running Gleitzeit V4 tests: {args.command}")
    success = command_func()
    
    if success:
        print(f"✅ {args.command.title()} tests completed successfully")
        return 0
    else:
        print(f"❌ {args.command.title()} tests failed")
        return 1


if __name__ == "__main__":
    exit(main())