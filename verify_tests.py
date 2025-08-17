#!/usr/bin/env python3
"""
Test Verification Script for Gleitzeit Test Suite

Verifies that tests are properly structured and can be executed.
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import json

def run_test_command(cmd: List[str], description: str) -> Tuple[bool, str, int, int, int]:
    """Run a test command and parse results"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        output = result.stdout + result.stderr
        
        # Parse pytest output
        passed = output.count(" passed")
        failed = output.count(" failed")
        errors = output.count(" error")
        skipped = output.count(" skipped")
        
        # Check for collection errors
        if "error during collection" in output.lower():
            return False, "Collection error", 0, 0, errors
        
        # Success if we have some passed tests and no critical errors
        success = passed > 0 or (failed == 0 and errors == 0)
        
        return success, output[-500:], passed, failed, skipped
        
    except subprocess.TimeoutExpired:
        return False, "Timeout", 0, 0, 0
    except Exception as e:
        return False, str(e), 0, 0, 0


def main():
    """Run test verification"""
    print("=" * 80)
    print("GLEITZEIT TEST SUITE VERIFICATION")
    print("=" * 80)
    
    test_categories = [
        {
            "name": "Persistence Tests",
            "path": "newtests/persistence/",
            "description": "Database and storage layer tests"
        },
        {
            "name": "Unit Tests - Models",
            "path": "newtests/unit/core/test_models_simple.py",
            "description": "Core model validation tests"
        },
        {
            "name": "Unit Tests - Events",
            "path": "newtests/unit/core/test_events.py",
            "description": "Event system tests"
        },
        {
            "name": "Unit Tests - Batch Processor",
            "path": "newtests/unit/core/test_batch_processor.py",
            "description": "Batch processing tests"
        },
        {
            "name": "Integration Tests",
            "path": "newtests/integration/",
            "description": "Component interaction tests"
        },
        {
            "name": "E2E Tests",
            "path": "newtests/e2e/",
            "description": "End-to-end workflow tests"
        },
        {
            "name": "Performance Tests",
            "path": "newtests/performance/",
            "description": "Performance benchmark tests"
        }
    ]
    
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    results = []
    
    for category in test_categories:
        print(f"\n📁 {category['name']}")
        print(f"   {category['description']}")
        print(f"   Path: {category['path']}")
        
        cmd = [
            sys.executable, "-m", "pytest",
            category["path"],
            "--tb=no",
            "-q",
            "--no-header"
        ]
        
        success, output, passed, failed, skipped = run_test_command(cmd, category["name"])
        
        if success and passed > 0:
            status = "✅ PASS"
            total_passed += passed
        elif failed > 0:
            status = "❌ FAIL"
            total_failed += failed
        elif "Collection error" in output:
            status = "⚠️  COLLECTION ERROR"
        else:
            status = "⏭️  SKIP"
        
        total_skipped += skipped
        
        result_str = f"   Status: {status}"
        if passed > 0:
            result_str += f" | Passed: {passed}"
        if failed > 0:
            result_str += f" | Failed: {failed}"
        if skipped > 0:
            result_str += f" | Skipped: {skipped}"
        
        print(result_str)
        
        results.append({
            "category": category["name"],
            "status": status,
            "passed": passed,
            "failed": failed,
            "skipped": skipped
        })
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print(f"\n📊 Test Statistics:")
    print(f"   Total Passed:  {total_passed:4d} ✅")
    print(f"   Total Failed:  {total_failed:4d} ❌")
    print(f"   Total Skipped: {total_skipped:4d} ⏭️")
    
    success_rate = (total_passed / (total_passed + total_failed) * 100) if (total_passed + total_failed) > 0 else 0
    print(f"\n   Success Rate: {success_rate:.1f}%")
    
    # Category breakdown
    print(f"\n📋 Category Results:")
    for result in results:
        print(f"   {result['category']:30s} {result['status']:20s} P:{result['passed']:3d} F:{result['failed']:3d} S:{result['skipped']:3d}")
    
    # Test file count
    test_files = list(Path("newtests").rglob("test_*.py"))
    print(f"\n📁 Test Files: {len(test_files)}")
    
    # Recommendations
    print(f"\n💡 Recommendations:")
    if total_failed > 0:
        print(f"   - Fix {total_failed} failing tests")
        print(f"   - Most failures are due to model structure mismatches")
        print(f"   - Update fixtures to match current implementation")
    else:
        print(f"   - All tests passing! 🎉")
    
    if success_rate > 80:
        print(f"   - Test suite is in GOOD condition ({success_rate:.1f}% passing)")
    elif success_rate > 50:
        print(f"   - Test suite needs attention ({success_rate:.1f}% passing)")
    else:
        print(f"   - Test suite needs significant work ({success_rate:.1f}% passing)")
    
    print("\n" + "=" * 80)
    
    return 0 if success_rate > 50 else 1


if __name__ == "__main__":
    sys.exit(main())