#!/usr/bin/env python3
"""
Test the new Gleitzeit Easy Syntax

This creates a simple workflow using the fluent interface and tests that
it can be exported and used with the existing Gleitzeit system.
"""

from gleitzeit.easy import t, w

def create_simple_workflow():
    """Create a simple workflow with the easy syntax."""
    return w(
        # Simple math calculation
        t("calculate", "python/v1:execute")
            .with_(file="examples/scripts/simple_math.py")
            .retry(2)
            .timeout(30)
            .on_success()
                .run("log_success", "python/v1:execute")
                .with_(
                    file="examples/scripts/simple_math.py",
                    message="Calculation successful!"
                )
            .on_error("TIMEOUT")
                .run("log_timeout", "python/v1:execute")
                .with_(
                    file="examples/scripts/simple_math.py", 
                    message="Calculation timed out"
                )
    ).name("simple_math_workflow") \
     .version("1.0.0") \
     .description("A simple workflow demonstrating the easy syntax")

def create_chained_workflow():
    """Create a workflow with dependencies."""
    return w(
        t("step1", "python/v1:execute")
            .with_(file="examples/scripts/simple_math.py")
            .timeout(10),
            
        t("step2", "python/v1:execute")
            .needs("step1")
            .with_(file="examples/scripts/simple_math.py")
            .cache(60)
            .then()  # Promise-style
                .run("success_handler", "python/v1:execute")
                .with_(file="examples/scripts/simple_math.py"),
                
        t("step3", "python/v1:execute")
            .needs("step2")
            .with_(file="examples/scripts/simple_math.py")
            .finally_()  # Always runs
                .run("cleanup", "python/v1:execute")
                .with_(file="examples/scripts/simple_math.py")
    ).name("chained_workflow") \
     .description("Workflow with sequential dependencies")

def main():
    """Test the easy syntax."""
    print("=== Testing Gleitzeit Easy Syntax ===\n")
    
    # Test simple workflow
    print("1. Creating Simple Workflow")
    simple = create_simple_workflow()
    print(f"   Tasks: {simple.get_task_count()}")
    print(f"   Event Handlers: {simple.get_event_handler_count()}")
    print(f"   Task IDs: {simple.get_task_ids()}")
    
    # Validate
    errors = simple.validate()
    if errors:
        print(f"   ❌ Validation errors: {errors}")
    else:
        print("   ✅ Validation passed")
    
    print()
    
    # Test chained workflow
    print("2. Creating Chained Workflow")
    chained = create_chained_workflow()
    print(f"   Tasks: {chained.get_task_count()}")
    print(f"   Event Handlers: {chained.get_event_handler_count()}")
    print(f"   Task IDs: {chained.get_task_ids()}")
    
    # Validate
    errors = chained.validate()
    if errors:
        print(f"   ❌ Validation errors: {errors}")
    else:
        print("   ✅ Validation passed")
    
    print()
    
    # Show generated structure
    print("3. Generated Workflow Structure")
    print("   Simple workflow:")
    import json
    workflow_dict = simple.to_dict()
    print(json.dumps(workflow_dict, indent=4))
    
    print("\n   Chained workflow:")
    chained_dict = chained.to_dict()
    print(json.dumps(chained_dict, indent=4))
    
    # Test file export
    print("\n4. Testing File Export")
    try:
        simple.save_json("/tmp/simple_workflow.json")
        print("   ✅ JSON export successful")
        
        # Try YAML if available
        try:
            simple.save_yaml("/tmp/simple_workflow.yaml") 
            print("   ✅ YAML export successful")
        except ImportError:
            print("   ⚠️  YAML export skipped (PyYAML not installed)")
            
    except Exception as e:
        print(f"   ❌ File export failed: {e}")

if __name__ == "__main__":
    main()