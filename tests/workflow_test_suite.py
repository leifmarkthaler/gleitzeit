#!/usr/bin/env python3
"""
Simple workflow test suite using CLI infrastructure
"""

import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple

# Test configuration
WORKFLOWS = [
    # (workflow_file, description, requires_ollama)
    ("examples/simple_llm_workflow.yaml", "Simple LLM", True),
    ("examples/llm_workflow.yaml", "LLM Workflow", True),
    ("examples/dependent_workflow.yaml", "Dependent", True),
    ("examples/parallel_workflow.yaml", "Parallel", False),
    ("examples/mixed_workflow.yaml", "Mixed Provider", True),
    ("examples/vision_workflow.yaml", "Vision", True),
    ("examples/batch_text_dynamic.yaml", "Batch Text", True),
    ("examples/batch_image_dynamic.yaml", "Batch Images", True),
    ("examples/python_only_workflow.yaml", "Python Only", False),
    ("examples/test_context_workflow.yaml", "Context Passing", False),
]


def check_ollama() -> bool:
    """Check if Ollama is running"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            timeout=2
        )
        return result.returncode == 0
    except:
        return False


def run_workflow(workflow_file: str, timeout: int = 60) -> Tuple[bool, str]:
    """Run a workflow using the CLI"""
    if not Path(workflow_file).exists():
        return False, "File not found"
    
    try:
        # Run workflow using CLI
        cmd = [
            sys.executable,
            "src/gleitzeit/cli/gleitzeit_cli.py",
            "run",
            workflow_file
        ]
        
        env = {**subprocess.os.environ, "PYTHONPATH": "src"}
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        
        # Check output for success indicators
        output = result.stdout + result.stderr
        
        if "✅ Workflow completed!" in output:
            # Count completed tasks
            completed_count = output.count("✅") - 1  # Subtract the main completion message
            return True, f"Completed ({completed_count} tasks)"
        elif "❌" in output:
            # Extract error if present
            lines = output.split('\n')
            for line in lines:
                if "Error:" in line or "failed" in line:
                    return False, line.strip()[:100]
            return False, "Workflow failed"
        else:
            return False, f"Unknown result (exit code: {result.returncode})"
            
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s)"
    except Exception as e:
        return False, f"Error: {str(e)[:50]}"


def validate_workflow(workflow_file: str) -> Tuple[bool, str]:
    """Validate a workflow file"""
    try:
        # Use Python to load and validate
        sys.path.insert(0, "src")
        from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
        
        workflow = load_workflow_from_file(workflow_file)
        errors = validate_workflow(workflow)
        
        if errors:
            return False, f"Validation errors: {', '.join(errors[:3])}"
        return True, "Valid"
    except Exception as e:
        return False, f"Load error: {str(e)[:50]}"


def main():
    """Run all tests"""
    print("🧪 Gleitzeit Workflow Test Suite")
    print("=" * 60)
    
    # Check Ollama availability
    ollama_available = check_ollama()
    if ollama_available:
        print("✅ Ollama is running")
    else:
        print("⚠️  Ollama not available - LLM tests will be skipped")
    print()
    
    # Test results
    passed = 0
    failed = 0
    skipped = 0
    
    # Run validation tests
    print("📝 Validation Tests")
    print("-" * 40)
    
    for workflow_file, description, _ in WORKFLOWS:
        print(f"{description:<20} ", end="", flush=True)
        
        valid, message = validate_workflow(workflow_file)
        
        if valid:
            print(f"✅ {message}")
            passed += 1
        else:
            print(f"❌ {message}")
            failed += 1
    
    print()
    
    # Run execution tests (if requested)
    if "--execute" in sys.argv:
        print("🚀 Execution Tests")
        print("-" * 40)
        
        for workflow_file, description, requires_ollama in WORKFLOWS:
            print(f"{description:<20} ", end="", flush=True)
            
            # Skip if requires Ollama and it's not available
            if requires_ollama and not ollama_available:
                print("⏭️  Skipped (no Ollama)")
                skipped += 1
                continue
            
            # Use longer timeout for vision and batch workflows
            if "batch images" in description.lower():
                success, message = run_workflow(workflow_file, timeout=120)
            elif "vision" in description.lower() or "batch" in description.lower():
                success, message = run_workflow(workflow_file, timeout=90)
            else:
                success, message = run_workflow(workflow_file, timeout=60)
            
            if success:
                print(f"✅ {message}")
                passed += 1
            else:
                print(f"❌ {message}")
                failed += 1
        
        print()
    
    # Summary
    print("=" * 60)
    print("📊 Summary")
    print(f"  Passed:  {passed}")
    print(f"  Failed:  {failed}")
    print(f"  Skipped: {skipped}")
    
    if passed > 0 and failed == 0:
        print("\n✅ All tests passed!")
        return 0
    else:
        print(f"\n❌ {failed} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())