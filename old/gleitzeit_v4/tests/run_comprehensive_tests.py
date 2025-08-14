#!/usr/bin/env python3
"""
Comprehensive Test Runner for Gleitzeit V4
Runs all test suites and provides unified reporting.
"""

import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path (since we're in tests/ subdirectory)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)


class TestRunner:
    """Comprehensive test runner for all Gleitzeit V4 tests"""
    
    def __init__(self):
        self.results = {}
        self.start_time = None
        self.total_duration = 0
        
    def run_test_file(self, test_file, description, timeout=300):
        """Run a specific test file"""
        print(f"\n{'='*60}")
        print(f"🧪 {description}")
        print(f"{'='*60}")
        print(f"Running: {test_file}")
        
        start_time = time.time()
        
        try:
            # Run the test file
            result = subprocess.run(
                [sys.executable, test_file],
                cwd=current_dir,
                env={**os.environ, 'PYTHONPATH': parent_dir},
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            duration = time.time() - start_time
            
            # Process results
            success = result.returncode == 0
            
            print(f"\n📊 Test Results:")
            print(f"  Exit Code: {result.returncode}")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Status: {'✅ PASSED' if success else '❌ FAILED'}")
            
            if result.stdout:
                print(f"\n📝 Output (last 1000 chars):")
                print(result.stdout[-1000:])
            
            if result.stderr and not success:
                print(f"\n⚠️  Errors:")
                print(result.stderr[-500:])
            
            return {
                'success': success,
                'duration': duration,
                'exit_code': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr
            }
            
        except subprocess.TimeoutExpired:
            print(f"\n⏰ Test timed out after {timeout}s")
            return {
                'success': False,
                'duration': timeout,
                'exit_code': -1,
                'stdout': '',
                'stderr': 'Test timed out'
            }
        
        except Exception as e:
            print(f"\n💥 Test crashed: {e}")
            return {
                'success': False,
                'duration': time.time() - start_time,
                'exit_code': -1,
                'stdout': '',
                'stderr': str(e)
            }
    
    def run_all_tests(self):
        """Run all available test suites"""
        print("🚀 Gleitzeit V4 - Comprehensive Test Suite Runner")
        print("=" * 70)
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.start_time = time.time()
        
        # Define test suites (files are now in the same directory)
        test_suites = [
            # Core functionality tests
            {
                'file': 'test_comprehensive_cli.py',
                'name': 'Comprehensive CLI Tests',
                'description': 'Complete CLI command coverage and functionality',
                'timeout': 300
            },
            {
                'file': 'test_cli_integration.py', 
                'name': 'CLI Integration Tests',
                'description': 'Real workflow execution through CLI',
                'timeout': 180
            },
            {
                'file': 'test_redis_full_execution.py',
                'name': 'Redis Full Execution Tests', 
                'description': 'Complete workflow execution with Redis persistence',
                'timeout': 120
            },
            {
                'file': 'run_core_tests.py',
                'name': 'Core Component Tests',
                'description': 'Core system component testing',
                'timeout': 180
            },
            
            # Backend and persistence tests
            {
                'file': 'test_sqlite_backend.py',
                'name': 'SQLite Backend Tests',
                'description': 'SQLite persistence backend functionality',
                'timeout': 60
            },
            
            # Provider tests
            {
                'file': 'test_ollama_integration.py',
                'name': 'Ollama Integration Tests',
                'description': 'Ollama LLM provider integration',
                'timeout': 120
            },
            
            # Workflow tests
            {
                'file': 'test_yaml_workflows.py',
                'name': 'YAML Workflow Tests',
                'description': 'YAML workflow parsing and execution',
                'timeout': 90
            },
        ]
        
        # Filter to only existing test files
        available_tests = []
        for test in test_suites:
            if os.path.exists(test['file']):
                available_tests.append(test)
            else:
                print(f"⚠️  Skipping {test['name']} - file not found: {test['file']}")
        
        print(f"\n📋 Running {len(available_tests)} test suites...")
        
        # Run each test suite
        for i, test in enumerate(available_tests, 1):
            print(f"\n[{i}/{len(available_tests)}] {test['name']}")
            
            result = self.run_test_file(
                test['file'],
                test['description'],
                test['timeout']
            )
            
            self.results[test['name']] = result
        
        # Generate final report
        return self.generate_final_report()
    
    def generate_final_report(self):
        """Generate comprehensive final report"""
        self.total_duration = time.time() - self.start_time
        
        print(f"\n{'='*70}")
        print("🎯 FINAL TEST REPORT")
        print(f"{'='*70}")
        
        # Summary statistics
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results.values() if r['success'])
        failed_tests = total_tests - passed_tests
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        print(f"📊 SUMMARY:")
        print(f"  Total Test Suites: {total_tests}")
        print(f"  ✅ Passed: {passed_tests}")
        print(f"  ❌ Failed: {failed_tests}")
        print(f"  📈 Success Rate: {success_rate:.1f}%")
        print(f"  ⏱️  Total Duration: {self.total_duration:.2f}s")
        
        # Detailed results
        print(f"\n📋 DETAILED RESULTS:")
        for test_name, result in self.results.items():
            status = "✅ PASSED" if result['success'] else "❌ FAILED"
            duration = result['duration']
            print(f"  {status} {test_name} ({duration:.2f}s)")
            
            if not result['success'] and result['stderr']:
                print(f"    💥 Error: {result['stderr'][:100]}...")
        
        # Overall assessment
        print(f"\n🔍 OVERALL ASSESSMENT:")
        
        if success_rate >= 90:
            print("🎉 EXCELLENT! Gleitzeit V4 is fully functional and robust!")
            print("✅ All major components working correctly")
            print("✅ Ready for production deployment")
            assessment = "EXCELLENT"
        elif success_rate >= 75:
            print("✅ GOOD! Gleitzeit V4 is mostly functional with minor issues")
            print("🔧 Some components may need fine-tuning")
            print("✅ Ready for testing and development use")
            assessment = "GOOD"
        elif success_rate >= 50:
            print("⚠️  PARTIAL! Gleitzeit V4 has basic functionality but needs work")
            print("🔨 Several components need attention")
            print("🧪 Suitable for development testing only")
            assessment = "PARTIAL"
        else:
            print("❌ POOR! Gleitzeit V4 has significant issues")
            print("🔥 Major components not working")
            print("🚫 Not recommended for use")
            assessment = "POOR"
        
        # Component status
        print(f"\n🔧 COMPONENT STATUS:")
        
        # Analyze which components are working based on test results
        cli_working = any('CLI' in name and result['success'] for name, result in self.results.items())
        persistence_working = any('Redis' in name or 'SQLite' in name and result['success'] for name, result in self.results.items())
        providers_working = any('Ollama' in name and result['success'] for name, result in self.results.items())
        workflows_working = any('Workflow' in name or 'YAML' in name and result['success'] for name, result in self.results.items())
        core_working = any('Core' in name and result['success'] for name, result in self.results.items())
        
        print(f"  CLI Interface: {'✅ Working' if cli_working else '❌ Issues'}")
        print(f"  Persistence Layer: {'✅ Working' if persistence_working else '❌ Issues'}")
        print(f"  Provider System: {'✅ Working' if providers_working else '❌ Issues'}")
        print(f"  Workflow Engine: {'✅ Working' if workflows_working else '❌ Issues'}")
        print(f"  Core Components: {'✅ Working' if core_working else '❌ Issues'}")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        
        if success_rate >= 90:
            print("  🚀 System is ready for production use")
            print("  📝 Consider adding more edge case tests")
            print("  🔄 Set up automated testing pipeline")
        elif success_rate >= 75:
            print("  🔧 Fix remaining issues before production")
            print("  📊 Monitor failed tests for patterns")
            print("  ✅ Good for development and testing")
        else:
            print("  🔨 Focus on fixing core functionality")
            print("  🐛 Debug failed components systematically")
            print("  ⚠️  Not ready for production use")
        
        print(f"\n📅 Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'success_rate': success_rate,
            'duration': self.total_duration,
            'assessment': assessment,
            'results': self.results
        }


def main():
    """Main execution"""
    runner = TestRunner()
    
    try:
        summary = runner.run_all_tests()
        
        # Return exit code based on success rate
        if summary['success_rate'] >= 75:
            print(f"\n🎉 COMPREHENSIVE TESTS PASSED!")
            return 0
        else:
            print(f"\n❌ COMPREHENSIVE TESTS NEED ATTENTION!")
            return 1
            
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Tests interrupted by user")
        return 2
        
    except Exception as e:
        print(f"\n\n💥 Test runner crashed: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)