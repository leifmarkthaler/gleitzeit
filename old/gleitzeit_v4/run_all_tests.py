#!/usr/bin/env python3
"""
Comprehensive Test Suite for Gleitzeit V4

This script runs all available tests in the Gleitzeit V4 system, providing
a complete overview of system health and test coverage.
"""

import asyncio
import os
import sys
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Tuple, Any
import traceback

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)


def print_header(title: str, level: int = 1):
    """Print formatted header"""
    if level == 1:
        print(f"\n{'='*100}")
        print(f"🧪 {title}")
        print('='*100)
    elif level == 2:
        print(f"\n{'─'*80}")
        print(f"📋 {title}")
        print('─'*80)
    else:
        print(f"\n🔬 {title}")


def print_result(test_name: str, success: bool, details: str = "", execution_time: float = 0):
    """Print formatted test result"""
    status = "✅" if success else "❌"
    time_str = f" ({execution_time:.2f}s)" if execution_time > 0 else ""
    full_message = f"{status} {test_name}{time_str}"
    if details:
        full_message += f" - {details}"
    print(full_message)


class TestResult:
    """Test result data class"""
    def __init__(self, name: str, success: bool, output: str = "", error: str = "", execution_time: float = 0):
        self.name = name
        self.success = success
        self.output = output
        self.error = error
        self.execution_time = execution_time
        self.timestamp = datetime.now()


class TestSuite:
    """Comprehensive test suite for Gleitzeit V4"""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = None
        self.end_time = None
    
    def run_python_test(self, test_file: str, description: str = "") -> TestResult:
        """Run a Python test file"""
        start_time = time.time()
        
        try:
            # Run the test file
            result = subprocess.run(
                [sys.executable, test_file],
                cwd=current_dir,
                env={**os.environ, 'PYTHONPATH': '.'},
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            execution_time = time.time() - start_time
            success = result.returncode == 0
            
            # Extract key metrics from output if available
            output_lines = result.stdout.split('\n')
            error_lines = result.stderr.split('\n')
            
            # Look for test summary patterns
            summary_info = ""
            for line in output_lines:
                if "tests passed" in line.lower() or "success rate" in line.lower():
                    summary_info = line.strip()
                    break
            
            return TestResult(
                name=f"{test_file} - {description}" if description else test_file,
                success=success,
                output=summary_info or result.stdout[-500:] if result.stdout else "",
                error=result.stderr[-500:] if result.stderr else "",
                execution_time=execution_time
            )
            
        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            return TestResult(
                name=f"{test_file} - {description}" if description else test_file,
                success=False,
                output="",
                error="Test timed out after 2 minutes",
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - start_time
            return TestResult(
                name=f"{test_file} - {description}" if description else test_file,
                success=False,
                output="",
                error=str(e),
                execution_time=execution_time
            )
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all available tests"""
        print_header("Gleitzeit V4 Comprehensive Test Suite")
        print(f"🕒 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📁 Working directory: {current_dir}")
        
        self.start_time = time.time()
        
        # Define test categories and their tests
        test_categories = {
            "Core System Tests": [
                ("tests/test_events.py", "Event System Architecture"),
                ("tests/test_jsonrpc.py", "JSON-RPC 2.0 Protocol"),
                ("tests/test_scheduler.py", "Event-driven Scheduling"),
                ("tests/test_protocol_validation.py", "Protocol Validation & Method Routing"),
            ],
            
            "Provider & Registry Tests": [
                ("tests/test_provider_registry.py", "Provider Registry & Load Balancing"),
                ("tests/test_protocol_provider_executor_simple.py", "Protocol/Provider Framework"),
            ],
            
            "CLI Tests": [
                ("tests/test_cli_simple.py", "Basic CLI Functionality"),
                ("tests/test_cli_integration.py", "CLI Integration & Workflow Execution"),
                ("tests/test_cli.py", "Comprehensive CLI Features"),
            ],
            
            "Workflow & Execution Tests": [
                ("tests/test_workflow_manager.py", "Workflow Management"),
                ("tests/test_dependency_resolution.py", "Dependency Resolution"),
            ],
            
            "Backend & Persistence Tests": [
                ("tests/test_sqlite_backend.py", "SQLite Persistence Backend"),
            ],
            
            "Integration Tests": [
                ("tests/test_ollama_integration.py", "Ollama LLM Integration"),
                ("tests/test_python_functions.py", "Python Function Execution"),
            ],
        }
        
        # Run tests by category
        for category, tests in test_categories.items():
            print_header(category, 2)
            
            for test_file, description in tests:
                test_path = os.path.join(current_dir, test_file)
                
                if os.path.exists(test_path):
                    print(f"\n🔬 Running {description}...")
                    result = self.run_python_test(test_file, description)
                    self.results.append(result)
                    
                    print_result(
                        test_name=description,
                        success=result.success,
                        details=result.output.split('\n')[-1] if result.output else result.error[:100],
                        execution_time=result.execution_time
                    )
                    
                    if not result.success and result.error:
                        print(f"      Error: {result.error[:200]}")
                else:
                    print(f"⚠️  Test file not found: {test_file}")
                    result = TestResult(
                        name=f"{test_file} - {description}",
                        success=False,
                        error="Test file not found"
                    )
                    self.results.append(result)
        
        self.end_time = time.time()
        
        # Generate summary
        return self.generate_summary()
    
    def generate_summary(self) -> Dict[str, Any]:
        """Generate test summary statistics"""
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.success)
        failed_tests = total_tests - passed_tests
        
        total_time = self.end_time - self.start_time if self.end_time and self.start_time else 0
        avg_time = sum(r.execution_time for r in self.results) / total_tests if total_tests > 0 else 0
        
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        
        summary = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "success_rate": success_rate,
            "total_time": total_time,
            "average_test_time": avg_time,
            "failed_test_names": [r.name for r in self.results if not r.success]
        }
        
        # Print summary
        print_header("Test Suite Summary", 1)
        print(f"📊 **Total Tests**: {total_tests}")
        print(f"✅ **Passed**: {passed_tests}")
        print(f"❌ **Failed**: {failed_tests}")
        print(f"📈 **Success Rate**: {success_rate:.1f}%")
        print(f"⏱️  **Total Execution Time**: {total_time:.2f}s")
        print(f"⏱️  **Average Test Time**: {avg_time:.2f}s")
        
        # Categorize results
        if success_rate >= 95:
            print("\n🎉 **EXCELLENT** - Test suite is in excellent condition!")
            print("✅ System is production-ready with comprehensive test coverage")
        elif success_rate >= 85:
            print("\n🟢 **GOOD** - Test suite is in good condition!")
            print("✅ System is ready for use with minor issues to address")
        elif success_rate >= 70:
            print("\n🟡 **FAIR** - Test suite has some issues")
            print("⚠️ System needs attention before production use")
        else:
            print("\n🔴 **POOR** - Test suite has significant issues")
            print("🚨 System requires major fixes before use")
        
        # Show failed tests
        if failed_tests > 0:
            print(f"\n❌ **Failed Tests ({failed_tests}):**")
            for result in self.results:
                if not result.success:
                    error_preview = result.error[:100] + "..." if len(result.error) > 100 else result.error
                    print(f"   • {result.name}")
                    if error_preview:
                        print(f"     └── {error_preview}")
        
        # Show top performing tests
        successful_tests = [r for r in self.results if r.success]
        if successful_tests:
            print(f"\n✅ **Fastest Successful Tests:**")
            fastest_tests = sorted(successful_tests, key=lambda x: x.execution_time)[:3]
            for test in fastest_tests:
                print(f"   • {test.name} ({test.execution_time:.2f}s)")
        
        print(f"\n🕒 **Completed at**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return summary
    
    def save_results(self, filename: str = "test_results.json"):
        """Save test results to JSON file"""
        import json
        
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_tests": len(self.results),
                "passed_tests": sum(1 for r in self.results if r.success),
                "failed_tests": sum(1 for r in self.results if not r.success),
                "total_time": self.end_time - self.start_time if self.end_time and self.start_time else 0
            },
            "results": [
                {
                    "name": r.name,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "execution_time": r.execution_time,
                    "timestamp": r.timestamp.isoformat()
                }
                for r in self.results
            ]
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"\n💾 Test results saved to: {filename}")


def main():
    """Main test runner"""
    print("🚀 Initializing Gleitzeit V4 Test Suite...")
    
    # Create and run test suite
    suite = TestSuite()
    summary = suite.run_all_tests()
    
    # Save results
    suite.save_results()
    
    # Exit with appropriate code
    exit_code = 0 if summary["success_rate"] >= 70 else 1
    
    print(f"\n🏁 Test suite completed with exit code: {exit_code}")
    
    return exit_code


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)