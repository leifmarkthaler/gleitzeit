#!/usr/bin/env python3
"""
Gleitzeit 0.0.7 Client Usage Examples

This file demonstrates various ways to use both the Modular Client
and Easy Client for workflow orchestration.

Run any example with:
    python examples/client_examples.py
"""

import asyncio
from datetime import datetime
from gleitzeit.client import GleitzeitClient
from gleitzeit.easy import t, w


# ==============================================================================
# EASY CLIENT EXAMPLES
# ==============================================================================

def example_1_simple_workflow():
    """Example 1: Simplest possible workflow"""
    print("\n" + "="*60)
    print("Example 1: Simple Workflow with Easy Client")
    print("="*60)

    workflow = w(
        t('hello').with_code('result = "Hello, World!"')
    ).name('Hello World').submit()

    print(f"✅ Submitted workflow: {workflow['workflow_id']}")


def example_2_sequential_tasks():
    """Example 2: Sequential task execution"""
    print("\n" + "="*60)
    print("Example 2: Sequential Tasks")
    print("="*60)

    workflow = w(
        t('step1').with_code('result = 1'),
        t('step2').needs('step1').with_code('result = dependencies["step1"] + 1'),
        t('step3').needs('step2').with_code('result = dependencies["step2"] + 1')
    ).name('Sequential Pipeline')

    # Validate before submission
    errors = workflow.validate()
    if errors:
        print("❌ Validation errors:", errors)
    else:
        result = workflow.submit()
        print(f"✅ Submitted sequential workflow: {result['workflow_id']}")


def example_3_parallel_tasks():
    """Example 3: Parallel task execution"""
    print("\n" + "="*60)
    print("Example 3: Parallel Tasks")
    print("="*60)

    workflow = w(
        # These tasks have no dependencies, so they run in parallel
        t('fetch_users').with_code('result = ["Alice", "Bob", "Charlie"]'),
        t('fetch_products').with_code('result = ["Widget", "Gadget", "Doohickey"]'),
        t('fetch_orders').with_code('result = [101, 102, 103]'),

        # This task waits for all three above
        t('combine_data')
            .needs('fetch_users', 'fetch_products', 'fetch_orders')
            .with_code('''
users = dependencies["fetch_users"]
products = dependencies["fetch_products"]
orders = dependencies["fetch_orders"]
result = {
    "users": users,
    "products": products,
    "orders": orders,
    "total_count": len(users) + len(products) + len(orders)
}
''')
    ).name('Parallel Data Fetching')

    result = workflow.submit()
    print(f"✅ Submitted parallel workflow: {result['workflow_id']}")


def example_4_error_handling():
    """Example 4: Tasks with error handling"""
    print("\n" + "="*60)
    print("Example 4: Error Handling and Retries")
    print("="*60)

    workflow = w(
        t('unreliable_api')
            .with_code('''
import random
if random.random() > 0.5:
    result = {"data": "Success!"}
else:
    raise Exception("Random failure")
''')
            .retry(3)  # Retry up to 3 times
            .timeout(10),  # 10 second timeout

        t('process_result')
            .needs('unreliable_api')
            .with_code('result = f"Processed: {dependencies["unreliable_api"]}"')
    ).name('Error Handling Demo')

    result = workflow.submit()
    print(f"✅ Submitted workflow with retries: {result['workflow_id']}")


def example_5_dynamic_workflow():
    """Example 5: Building workflows dynamically"""
    print("\n" + "="*60)
    print("Example 5: Dynamic Workflow Generation")
    print("="*60)

    # Generate tasks based on data
    data_chunks = ['chunk1', 'chunk2', 'chunk3', 'chunk4']

    # Create processing tasks dynamically
    tasks = []
    for chunk in data_chunks:
        task = t(f'process_{chunk}') \
            .with_code(f'result = "Processed {chunk}"') \
            .timeout(30)
        tasks.append(task)

    # Add aggregation task that depends on all processing tasks
    aggregate_task = t('aggregate') \
        .needs(*[f'process_{chunk}' for chunk in data_chunks]) \
        .with_code('''
results = []
for dep_name, dep_value in dependencies.items():
    results.append(dep_value)
result = {"all_results": results, "count": len(results)}
''')
    tasks.append(aggregate_task)

    # Create and submit workflow
    workflow = w(*tasks).name(f'Dynamic Batch Processing - {len(data_chunks)} chunks')
    result = workflow.submit()
    print(f"✅ Submitted dynamic workflow: {result['workflow_id']}")


# ==============================================================================
# MODULAR CLIENT EXAMPLES
# ==============================================================================

async def example_6_modular_client_basic():
    """Example 6: Basic modular client usage"""
    print("\n" + "="*60)
    print("Example 6: Modular Client - Basic Usage")
    print("="*60)

    async with GleitzeitClient('http://localhost:8000') as client:
        # Submit a workflow
        workflow = {
            'name': 'Modular Client Demo',
            'tasks': [
                {
                    'name': 'task1',
                    'protocol': 'python',
                    'method': 'python/execute',
                    'params': {
                        'code': 'result = {"message": "From modular client!"}'
                    }
                }
            ]
        }

        response = await client.submit_workflow(workflow)
        print(f"✅ Submitted with modular client: {response.workflow_id}")

        # Check status
        status = await client.get_workflow_status(response.workflow_id)
        print(f"   Status: {status.status}")


async def example_7_modular_client_monitoring():
    """Example 7: Monitoring and health checks"""
    print("\n" + "="*60)
    print("Example 7: Modular Client - Monitoring")
    print("="*60)

    async with GleitzeitClient() as client:
        # Health check
        health = await client.health_check()
        print(f"✅ API Health: {health['status']}")

        # System health
        system_health = await client.get_system_health()
        print(f"   Redis connected: {system_health.redis_connected}")
        print(f"   Worker count: {system_health.worker_count}")
        print(f"   Active workflows: {system_health.active_workflows}")

        # Worker status
        workers = await client.get_workers_status()
        print(f"   Workers online: {len(workers)}")


async def example_8_batch_operations():
    """Example 8: Batch workflow submission"""
    print("\n" + "="*60)
    print("Example 8: Batch Operations")
    print("="*60)

    async with GleitzeitClient() as client:
        # Create multiple workflows
        workflows = []
        for i in range(5):
            workflow = {
                'name': f'Batch Workflow {i}',
                'tasks': [
                    {
                        'name': 'process',
                        'protocol': 'python',
                        'method': 'python/execute',
                        'params': {
                            'code': f'result = "Batch item {i} processed"'
                        }
                    }
                ]
            }
            workflows.append(workflow)

        # Submit all at once with concurrency control
        responses = await client.submit_workflows_batch(
            workflows,
            max_concurrent=3
        )

        print(f"✅ Submitted {len(responses)} workflows in batch")
        for resp in responses:
            print(f"   - {resp.workflow_id}: {resp.status}")


async def example_9_wait_for_completion():
    """Example 9: Submit and wait for completion"""
    print("\n" + "="*60)
    print("Example 9: Wait for Completion")
    print("="*60)

    async with GleitzeitClient() as client:
        # Submit workflow
        workflow = {
            'name': 'Wait Demo',
            'tasks': [
                {
                    'name': 'slow_task',
                    'protocol': 'python',
                    'method': 'python/execute',
                    'params': {
                        'code': '''
import time
time.sleep(2)
result = "Task completed after delay"
'''
                    }
                }
            ]
        }

        response = await client.submit_workflow(
            workflow,
            workflow_id=f'wait-demo-{int(datetime.now().timestamp())}'
        )
        print(f"✅ Submitted: {response.workflow_id}")
        print("⏳ Waiting for completion...")

        # Wait for completion (with timeout)
        try:
            final_status = await client.wait_for_workflow(
                response.workflow_id,
                timeout=30,
                poll_interval=1
            )
            print(f"✅ Completed with status: {final_status.status}")
        except TimeoutError:
            print("❌ Workflow did not complete in time")


# ==============================================================================
# COMBINED EXAMPLES
# ==============================================================================

async def example_10_easy_with_modular():
    """Example 10: Using Easy Client to build, Modular Client to monitor"""
    print("\n" + "="*60)
    print("Example 10: Combined Easy + Modular Client")
    print("="*60)

    # Build workflow with Easy Client
    workflow = w(
        t('step1').with_code('result = "Starting"'),
        t('step2').needs('step1').with_code('result = "Processing"'),
        t('step3').needs('step2').with_code('result = "Complete"')
    ).name('Combined Example')

    # Get the workflow dict
    workflow_dict = workflow.to_dict()

    # Submit and monitor with Modular Client
    async with GleitzeitClient() as client:
        response = await client.submit_workflow(
            workflow_dict['workflow'],
            workflow_id=workflow_dict['workflow_id']
        )
        print(f"✅ Submitted: {response.workflow_id}")

        # Monitor progress
        for i in range(10):
            status = await client.get_workflow_status(response.workflow_id)
            print(f"   [{i+1}s] Status: {status.status}")

            if status.status in ['completed', 'failed']:
                break

            await asyncio.sleep(1)


# ==============================================================================
# REAL WORLD EXAMPLE
# ==============================================================================

def example_11_real_world_etl():
    """Example 11: Real-world ETL pipeline"""
    print("\n" + "="*60)
    print("Example 11: Real-World ETL Pipeline")
    print("="*60)

    etl_workflow = w(
        # Extract phase
        t('extract_customers')
            .with_code('''
# Simulate database extraction
customers = [
    {"id": 1, "name": "Acme Corp", "revenue": 100000},
    {"id": 2, "name": "Tech Inc", "revenue": 250000},
    {"id": 3, "name": "Sales Co", "revenue": 75000}
]
result = {"customers": customers}
print(f"Extracted {len(customers)} customers")
''')
            .timeout(30)
            .retry(3),

        t('extract_orders')
            .with_code('''
# Simulate order extraction
orders = [
    {"id": 101, "customer_id": 1, "amount": 5000},
    {"id": 102, "customer_id": 2, "amount": 12000},
    {"id": 103, "customer_id": 1, "amount": 3000},
    {"id": 104, "customer_id": 3, "amount": 8000}
]
result = {"orders": orders}
print(f"Extracted {len(orders)} orders")
''')
            .timeout(30)
            .retry(3),

        # Transform phase
        t('transform_data')
            .needs('extract_customers', 'extract_orders')
            .with_code('''
customers = dependencies["extract_customers"]["customers"]
orders = dependencies["extract_orders"]["orders"]

# Create customer summary
customer_summary = {}
for customer in customers:
    customer_summary[customer["id"]] = {
        "name": customer["name"],
        "revenue": customer["revenue"],
        "order_count": 0,
        "order_total": 0
    }

# Aggregate order data
for order in orders:
    cid = order["customer_id"]
    if cid in customer_summary:
        customer_summary[cid]["order_count"] += 1
        customer_summary[cid]["order_total"] += order["amount"]

# Calculate metrics
for cid in customer_summary:
    summary = customer_summary[cid]
    summary["avg_order_value"] = (
        summary["order_total"] / summary["order_count"]
        if summary["order_count"] > 0 else 0
    )

result = {
    "customer_summary": customer_summary,
    "total_customers": len(customer_summary),
    "total_orders": len(orders)
}
print(f"Transformed data for {len(customer_summary)} customers")
''')
            .timeout(60),

        # Load phase
        t('load_to_warehouse')
            .needs('transform_data')
            .with_code('''
summary = dependencies["transform_data"]

# Simulate loading to data warehouse
print("Loading to data warehouse...")
for cid, data in summary["customer_summary"].items():
    print(f"  Customer {data['name']}: {data['order_count']} orders, "
          f"${data['order_total']:,.2f} total")

result = {
    "status": "loaded",
    "records_loaded": summary["total_customers"],
    "timestamp": __import__('datetime').datetime.now().isoformat()
}
print(f"Successfully loaded {summary['total_customers']} records")
''')
            .priority(100),

        # Notification
        t('send_report')
            .needs('load_to_warehouse')
            .with_code('''
load_result = dependencies["load_to_warehouse"]
report = f"""
ETL Pipeline Completed Successfully!
====================================
Status: {load_result["status"]}
Records: {load_result["records_loaded"]}
Time: {load_result["timestamp"]}
"""
print(report)
result = {"report_sent": True, "report": report}
''')

    ).name('Customer ETL Pipeline') \
     .id(f'etl-{datetime.now().strftime("%Y%m%d-%H%M%S")}') \
     .metadata(
         environment='production',
         owner='data-team',
         schedule='daily'
     )

    # Show structure
    etl_workflow.print_structure()

    # Submit
    result = etl_workflow.submit()
    print(f"\n✅ Submitted ETL pipeline: {result['workflow_id']}")


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def run_all_examples():
    """Run all examples"""
    print("\n" + "="*60)
    print(" GLEITZEIT 0.0.7 CLIENT EXAMPLES")
    print("="*60)

    # Easy Client examples
    example_1_simple_workflow()
    example_2_sequential_tasks()
    example_3_parallel_tasks()
    example_4_error_handling()
    example_5_dynamic_workflow()

    # Modular Client examples (async)
    asyncio.run(example_6_modular_client_basic())
    asyncio.run(example_7_modular_client_monitoring())
    asyncio.run(example_8_batch_operations())
    asyncio.run(example_9_wait_for_completion())

    # Combined example
    asyncio.run(example_10_easy_with_modular())

    # Real-world example
    example_11_real_world_etl()

    print("\n" + "="*60)
    print(" ALL EXAMPLES COMPLETED!")
    print("="*60)


if __name__ == "__main__":
    # Run specific example or all
    import sys

    if len(sys.argv) > 1:
        example_num = sys.argv[1]
        if example_num == "1":
            example_1_simple_workflow()
        elif example_num == "2":
            example_2_sequential_tasks()
        elif example_num == "3":
            example_3_parallel_tasks()
        elif example_num == "4":
            example_4_error_handling()
        elif example_num == "5":
            example_5_dynamic_workflow()
        elif example_num == "6":
            asyncio.run(example_6_modular_client_basic())
        elif example_num == "7":
            asyncio.run(example_7_modular_client_monitoring())
        elif example_num == "8":
            asyncio.run(example_8_batch_operations())
        elif example_num == "9":
            asyncio.run(example_9_wait_for_completion())
        elif example_num == "10":
            asyncio.run(example_10_easy_with_modular())
        elif example_num == "11":
            example_11_real_world_etl()
        else:
            print(f"Unknown example: {example_num}")
            print("Usage: python client_examples.py [1-11]")
    else:
        run_all_examples()