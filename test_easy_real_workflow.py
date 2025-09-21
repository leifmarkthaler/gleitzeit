#!/usr/bin/env python3
"""
Test the easy syntax with the actual Gleitzeit engine
"""

from gleitzeit.easy import t, w
import json
import tempfile
import os

def create_test_workflow():
    """Create a simple workflow using easy syntax and test it with the real engine."""
    print("=== Creating Real Workflow with Easy Syntax ===")
    
    # Create a simple workflow that should actually run
    task1 = (t("simple_calc", "python/v1:execute")
            .with_(file="examples/scripts/simple_math.py")
            .retry(2)
            .timeout(30))
    
    # Add event handlers
    task1.on_success().run("log_success", "python/v1:execute").with_(
        file="examples/scripts/simple_math.py"
    )
    
    task1.on_error().run("log_error", "python/v1:execute").with_(
        file="examples/scripts/simple_math.py"
    )
    
    # Create workflow
    workflow = (w(task1)
               .name("easy_syntax_test")
               .version("1.0.0")
               .description("Testing easy syntax with real Gleitzeit engine"))
    
    print(f"Created workflow: {workflow}")
    print(f"Tasks: {workflow.get_task_count()}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    
    return workflow

def save_workflow_file(workflow):
    """Save the workflow to a YAML file for gleitzeit to run."""
    workflow_dict = workflow.to_dict()
    
    # Save as JSON first to verify structure
    with open("/tmp/easy_test_workflow.json", "w") as f:
        json.dump(workflow_dict, f, indent=2)
    
    print("\n=== Generated Workflow Structure ===")
    print(json.dumps(workflow_dict, indent=2))
    
    # Try to save as YAML if PyYAML is available
    try:
        yaml_content = workflow.to_yaml()
        with open("/tmp/easy_test_workflow.yaml", "w") as f:
            f.write(yaml_content)
        print(f"\n✅ Saved workflow to /tmp/easy_test_workflow.yaml")
        return "/tmp/easy_test_workflow.yaml"
    except ImportError:
        print("⚠️  PyYAML not available, using JSON format")
        return "/tmp/easy_test_workflow.json"

def main():
    """Test the easy syntax with real Gleitzeit engine."""
    print("🧪 Testing Easy Syntax with Real Gleitzeit Engine")
    print("=" * 60)
    
    try:
        # Create workflow
        workflow = create_test_workflow()
        
        # Validate workflow
        errors = workflow.validate()
        if errors:
            print(f"\n❌ Workflow validation failed:")
            for error in errors:
                print(f"  - {error}")
            return False
        else:
            print("\n✅ Workflow validation passed!")
        
        # Save workflow file
        workflow_file = save_workflow_file(workflow)
        
        print(f"\n📁 Workflow saved to: {workflow_file}")
        print("\n🚀 Ready to test with Gleitzeit engine!")
        print("You can run this workflow with:")
        print(f"  gleitzeit run {workflow_file}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error creating workflow: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ Easy syntax workflow creation successful!")
        print("The workflow is ready to run with the Gleitzeit engine.")
    else:
        print("\n❌ Easy syntax test failed!")