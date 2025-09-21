#!/usr/bin/env python3
"""
Test comprehensive error handling with the easy syntax
"""

from gleitzeit.easy import t, w
import json

def demo_error_handling():
    """Demonstrate comprehensive error handling capabilities."""
    print("=== Error Handling Demo ===")
    
    # Task with comprehensive error handling
    api_task = (t("unreliable_api", "python/v1:execute")
               .with_(url="https://flaky-api.com/data")
               .retry(3)
               .timeout(10))
    
    # Handle specific error types
    api_task.on_error("TIMEOUT").run("log_timeout", "python/v1:execute").with_(
        message="API call timed out, will retry",
        timestamp="{{now}}"
    )
    
    api_task.on_error("CONNECTION_ERROR").run("use_fallback", "python/v1:execute").with_(
        fallback_url="https://backup-api.com/data"
    )
    
    api_task.on_error("AUTH_ERROR").run("refresh_auth", "python/v1:execute").with_(
        service="api_auth"
    ).run("retry_original", "python/v1:execute")  # Chain multiple actions
    
    # Handle rate limiting with wait
    api_task.on_error("RATE_LIMIT").wait(30).retry_self()
    
    # General error handler (catches anything not handled above)
    api_task.on_error().run("log_general_error", "python/v1:execute").with_(
        level="warning",
        task_id="{{task_id}}",
        error_type="{{error_type}}"
    )
    
    # Final failure handler (after all retries exhausted)
    api_task.on_failure().run("alert_team", "python/v1:execute").with_(
        channel="ops-alerts",
        severity="high",
        message="API completely failed after all retries"
    )
    
    # Success handler
    api_task.on_success().run("log_success", "python/v1:execute").with_(
        message="API call succeeded!"
    )
    
    # Always-run cleanup
    api_task.finally_().run("cleanup_temp", "python/v1:execute").with_(
        temp_dir="/tmp/api_cache"
    )
    
    # Create workflow
    workflow = (w(api_task)
               .name("resilient_api_workflow")
               .description("API workflow with comprehensive error handling"))
    
    print(f"Created workflow: {workflow}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    
    # Show the generated structure
    print("\n=== Generated Error Handling Structure ===")
    workflow_dict = workflow.to_dict()
    
    # Print just the event handlers for clarity
    for i, handler in enumerate(workflow_dict.get('event_handlers', [])):
        print(f"\nHandler {i+1}: {handler['event_type']}")
        if handler['condition']:
            print(f"  Condition: {handler['condition']}")
        print(f"  Actions: {len(handler['actions'])}")
        for j, action in enumerate(handler['actions']):
            print(f"    {j+1}. {action['task_id']} ({action['protocol_method']})")
            if action['params']:
                print(f"       Params: {action['params']}")

def demo_promise_style_errors():
    """Demonstrate promise-style error handling."""
    print("\n=== Promise-Style Error Handling ===")
    
    async_task = (t("async_processing", "python/v1:execute")
                 .with_(data_file="large_dataset.json")
                 .timeout(300))
    
    # Promise-style chaining
    async_task.then().run("process_results", "python/v1:execute").with_(
        output_file="results.json"
    )
    
    async_task.catch("MEMORY_ERROR").run("reduce_batch_size", "python/v1:execute").with_(
        batch_size=100
    ).retry_self()
    
    async_task.catch("DISK_FULL").run("cleanup_space", "python/v1:execute").with_(
        min_free_gb=10
    )
    
    async_task.catch().run("handle_unknown_error", "python/v1:execute").with_(
        notify_dev_team=True
    )
    
    async_task.finally_().run("log_completion", "python/v1:execute").with_(
        status="{{task_status}}"
    )
    
    workflow = w(async_task).name("async_error_handling")
    
    print(f"Promise-style workflow: {workflow}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")

def main():
    """Run error handling demonstrations."""
    demo_error_handling()
    demo_promise_style_errors()
    
    print("\n✅ All error handling features demonstrated!")
    print("📋 Available error handling methods:")
    print("   • .on_error(code)    - Handle specific error types")
    print("   • .on_error()        - Handle any error")
    print("   • .on_failure()      - Handle final failure after retries")
    print("   • .catch(code)       - Promise-style specific error")
    print("   • .catch()           - Promise-style general error")
    print("   • .finally_()        - Always runs")
    print("   • .retry_self()      - Built-in retry action")
    print("   • .wait(seconds)     - Wait before next action")

if __name__ == "__main__":
    main()