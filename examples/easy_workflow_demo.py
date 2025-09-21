#!/usr/bin/env python3
"""
Demo of the new Gleitzeit Easy Syntax

This demonstrates the fluent interface for creating workflows with significantly
less boilerplate code while maintaining full power and replayability.
"""

from gleitzeit.easy import t, w

# Create a simple workflow using the fluent interface
demo_workflow = w(
    # Task 1: Get customer data
    t("get_customer", "python/v1:execute")
        .with_(file="examples/scripts/get_customer.py")
        .retry(3)
        .timeout(10)
        .on_success()
            .run("log_customer_retrieved", "python/v1:execute")
            .with_(file="examples/scripts/log_success.py")
        .on_error("CUSTOMER_NOT_FOUND")
            .run("create_new_customer", "python/v1:execute")
            .with_(file="examples/scripts/create_customer.py"),
    
    # Task 2: Process payment - depends on customer
    t("process_payment", "python/v1:execute")
        .needs("get_customer")
        .with_(file="examples/scripts/process_payment.py")
        .timeout(30)
        .retry(2)
        .then()  # Promise-style syntax for success
            .run("send_receipt", "python/v1:execute")
            .with_(file="examples/scripts/send_receipt.py")
            .run("update_accounting", "python/v1:execute")
            .with_(file="examples/scripts/update_ledger.py")
        .catch("PAYMENT_DECLINED")  # Promise-style syntax for specific error
            .run("notify_declined", "python/v1:execute")
            .with_(file="examples/scripts/notify_customer.py")
        .catch()  # Any other error
            .run("log_payment_error", "python/v1:execute")
            .with_(file="examples/scripts/log_error.py")
        .finally_()  # Always runs (note underscore to avoid Python keyword)
            .run("cleanup_session", "python/v1:execute")
            .with_(file="examples/scripts/cleanup.py"),
    
    # Task 3: Send confirmation - only if payment succeeded
    t("send_confirmation", "python/v1:execute")
        .needs("process_payment")
        .with_(file="examples/scripts/send_confirmation.py")
        .cache(300)  # Cache for 5 minutes
        .on_timeout()
            .run("send_sms_fallback", "python/v1:execute")
            .with_(file="examples/scripts/send_sms.py")

).name("payment_processing_demo") \
 .version("1.0.0") \
 .description("Demo workflow showcasing the new fluent syntax")

def main():
    """Demo the workflow builder"""
    print("=== Gleitzeit Easy Syntax Demo ===\n")
    
    print(f"Workflow: {demo_workflow}")
    print(f"Tasks: {demo_workflow.get_task_count()}")
    print(f"Event Handlers: {demo_workflow.get_event_handler_count()}")
    print(f"Task IDs: {demo_workflow.get_task_ids()}")
    
    # Validate the workflow
    errors = demo_workflow.validate()
    if errors:
        print("\n❌ Validation Errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\n✅ Workflow validation passed!")
    
    # Show the generated workflow structure
    print("\n=== Generated Workflow Dictionary ===")
    import json
    workflow_dict = demo_workflow.to_dict()
    print(json.dumps(workflow_dict, indent=2))
    
    # Show YAML format
    print("\n=== YAML Format ===")
    try:
        print(demo_workflow.to_yaml())
    except ImportError:
        print("PyYAML not installed - cannot show YAML format")
        print("Install with: pip install pyyaml")

if __name__ == "__main__":
    main()