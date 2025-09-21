#!/usr/bin/env python3
"""
Demo of Gleitzeit Easy Syntax Draft Implementation

This demonstrates the fluent interface for creating workflows with 
significantly less boilerplate than traditional YAML definitions.
"""

from gleitzeit.easy import t, w
import json

def demo_basic_syntax():
    """Demonstrate the basic task and workflow creation."""
    print("=== Basic Task and Workflow Creation ===")
    
    # Create tasks with fluent interface
    fetch_data = (t("fetch_data", "python/v1:execute")
                 .with_(url="https://api.example.com/data")
                 .retry(3)
                 .timeout(30))
    
    process_data = (t("process_data", "python/v1:execute")
                   .needs("fetch_data")  # Dependency
                   .with_(script="process.py")
                   .cache(300))  # 5 minute cache
    
    send_results = (t("send_results", "python/v1:execute")
                   .needs("process_data")
                   .with_(endpoint="https://api.example.com/results"))
    
    # Create workflow
    workflow = (w(fetch_data, process_data, send_results)
               .name("data_pipeline")
               .version("1.0.0")
               .description("Simple data processing pipeline"))
    
    print(f"Created workflow: {workflow}")
    print(f"Tasks: {workflow.get_task_count()}")
    print(f"Validation: {'✅ Passed' if not workflow.validate() else '❌ Failed'}")
    print()
    
    return workflow

def demo_event_handlers():
    """Demonstrate event handlers for error handling and flow control."""
    print("=== Event Handlers for Error Handling ===")
    
    # Create task with event handlers added separately
    api_call = (t("api_call", "python/v1:execute")
               .with_(url="https://unreliable-api.com/data")
               .retry(2)
               .timeout(10))
    
    # Add event handlers
    api_call.on_success().run("log_success", "python/v1:execute").with_(message="API call succeeded!")
    api_call.on_error("TIMEOUT").run("fallback_data", "python/v1:execute").with_(source="cache")
    api_call.on_failure().run("alert_ops", "python/v1:execute").with_(severity="high")
    
    # Create workflow
    workflow = (w(api_call)
               .name("resilient_api_workflow")
               .description("API workflow with comprehensive error handling"))
    
    print(f"Created workflow: {workflow}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    print()
    
    return workflow

def demo_promise_style():
    """Demonstrate promise-style syntax with then/catch."""
    print("=== Promise-Style Syntax ===")
    
    # Promise-style task creation
    async_task = (t("async_operation", "python/v1:execute")
                 .with_(operation="heavy_computation")
                 .timeout(60))
    
    # Use promise-style methods
    async_task.then().run("handle_success", "python/v1:execute").with_(action="save_result")
    async_task.catch("MEMORY_ERROR").run("cleanup_memory", "python/v1:execute")
    async_task.catch().run("general_error_handler", "python/v1:execute").with_(notify=True)
    async_task.finally_().run("cleanup", "python/v1:execute")
    
    workflow = (w(async_task)
               .name("async_workflow")
               .description("Demonstrates promise-style error handling"))
    
    print(f"Created workflow: {workflow}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    print()
    
    return workflow

def compare_with_yaml():
    """Compare easy syntax with equivalent YAML."""
    print("=== Comparison with Traditional YAML ===")
    
    # Easy syntax
    task = (t("complex_task", "python/v1:execute")
           .with_(script="analyze.py", data_source="database")
           .needs("prep_task")
           .retry(3)
           .timeout(120)
           .cache(600))
    
    task.on_success().run("notify_success", "python/v1:execute").with_(channel="slack")
    task.on_error("DATABASE_ERROR").retry_self()
    task.on_failure().run("escalate", "python/v1:execute").with_(priority="urgent")
    
    workflow = w(task).name("analysis_workflow")
    
    print("Easy Syntax (Python):")
    print("─" * 50)
    print(f"""
task = (t("complex_task", "python/v1:execute")
       .with_(script="analyze.py", data_source="database")
       .needs("prep_task")
       .retry(3)
       .timeout(120)
       .cache(600))

task.on_success().run("notify_success", "python/v1:execute").with_(channel="slack")
task.on_error("DATABASE_ERROR").retry_self()
task.on_failure().run("escalate", "python/v1:execute").with_(priority="urgent")

workflow = w(task).name("analysis_workflow")
""")
    
    print("\nEquivalent YAML (traditional):")
    print("─" * 50)
    yaml_equivalent = workflow.to_dict()
    print(json.dumps(yaml_equivalent, indent=2))
    print()

def main():
    """Run all demonstrations."""
    print("🚀 Gleitzeit Easy Syntax Demo")
    print("═" * 60)
    print()
    
    # Run all demos
    basic_workflow = demo_basic_syntax()
    event_workflow = demo_event_handlers()
    promise_workflow = demo_promise_style()
    compare_with_yaml()
    
    # Show final statistics
    print("=== Summary ===")
    print(f"Basic Workflow: {basic_workflow.get_task_count()} tasks, {basic_workflow.get_event_handler_count()} handlers")
    print(f"Event Workflow: {event_workflow.get_task_count()} tasks, {event_workflow.get_event_handler_count()} handlers")
    print(f"Promise Workflow: {promise_workflow.get_task_count()} tasks, {promise_workflow.get_event_handler_count()} handlers")
    print()
    print("✅ All demonstrations completed successfully!")
    print("📝 The easy syntax provides a fluent, chainable interface for workflow creation")
    print("🔧 Event handlers enable sophisticated error handling and flow control")
    print("🎯 Promise-style methods offer familiar async programming patterns")

if __name__ == "__main__":
    main()