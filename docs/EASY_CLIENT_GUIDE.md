# Gleitzeit Easy Client Guide

## Quick Start in 30 Seconds

```python
from gleitzeit.easy import t, w

# Create and submit a workflow in one line!
w(
    t('hello').with_code('result = "Hello, World!"')
).submit()
```

That's it! You've just submitted your first workflow using the Easy Client.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Core Concepts](#core-concepts)
3. [Task Building](#task-building)
4. [Workflow Composition](#workflow-composition)
5. [Common Patterns](#common-patterns)
6. [Real-World Examples](#real-world-examples)
7. [Tips & Tricks](#tips--tricks)

---

## Introduction

The Easy Client is designed to make workflow creation as simple as writing regular Python code. No more complex dictionary structures or verbose configurations - just intuitive, chainable methods.

### Why Easy Client?

**Without Easy Client:**
```python
workflow = {
    "workflow": {
        "name": "Data Processing",
        "tasks": [
            {
                "name": "fetch_data",
                "protocol": "python",
                "method": "python/execute",
                "params": {
                    "code": "result = fetch_data()",
                    "retry_count": 3,
                    "timeout": 30
                }
            },
            {
                "name": "process_data",
                "protocol": "python",
                "method": "python/execute",
                "params": {
                    "code": "result = process(dependencies['fetch_data'])"
                },
                "dependencies": ["fetch_data"]
            }
        ]
    },
    "workflow_id": "data-pipeline"
}
client.submit_workflow(workflow["workflow"], workflow["workflow_id"])
```

**With Easy Client:**
```python
w(
    t('fetch_data').with_code('result = fetch_data()').retry(3).timeout(30),
    t('process_data').needs('fetch_data').with_code('result = process(dependencies["fetch_data"])')
).name('Data Processing').id('data-pipeline').submit()
```

**60% less code, 100% more readable!**

---

## Core Concepts

### The `t()` Function - Task Builder

Creates a task with fluent interface:
```python
t('task_name')  # Creates a TaskBuilder
```

### The `w()` Function - Workflow Builder

Creates a workflow from tasks:
```python
w(task1, task2, task3)  # Creates a WorkflowBuilder
```

### Method Chaining

Every method returns the builder for chaining:
```python
t('task')
    .with_code('...')
    .retry(3)
    .timeout(30)
    .priority(10)
```

---

## Task Building

### Basic Task Creation

```python
# Minimal task
task = t('calculate').with_code('result = 42')

# With all options
task = t('complex_task')
    .with_code('result = complex_calculation()')
    .needs('dependency1', 'dependency2')
    .retry(3)
    .timeout(60)
    .priority(100)
    .cache(300)
    .env(API_KEY='secret')
```

### Task Parameters

#### Code Execution
```python
# Inline code
t('inline').with_code('result = {"answer": 42}')

# From file
t('from_file').with_file('scripts/process.py')

# With output capture
t('capture').with_code('print("Hello"); result = "Done"').capture_output()
```

#### Dependencies
```python
# Single dependency
t('task2').needs('task1')

# Multiple dependencies
t('task3').needs('task1', 'task2')

# Alternative syntax
t('task4').depends_on('task3')
```

#### Error Handling
```python
# Retry configuration
t('unreliable_api')
    .with_code('result = call_flaky_api()')
    .retry(5)  # Retry up to 5 times

# Timeout protection
t('slow_operation')
    .with_code('result = long_running_task()')
    .timeout(300)  # 5 minutes max
```

#### Performance
```python
# High priority task
t('critical').priority(100)

# Cache results
t('expensive').cache(3600)  # Cache for 1 hour
```

#### Environment
```python
t('secure_task')
    .with_code('import os; key = os.environ["API_KEY"]')
    .env(
        API_KEY='your-key',
        DEBUG='true',
        ENV='production'
    )
```

---

## Workflow Composition

### Creating Workflows

```python
# From tasks
workflow = w(
    t('task1').with_code('result = 1'),
    t('task2').with_code('result = 2')
)

# With metadata
workflow = w(
    t('main').with_code('result = "done"')
).name('My Workflow') \
 .id('unique-id-123') \
 .version('1.0.0') \
 .description('This workflow does X') \
 .metadata(
     team='data-science',
     project='analytics',
     environment='production'
 )
```

### Adding Tasks Dynamically

```python
workflow = w()

# Add individual task
workflow.add_task(
    t('dynamic').with_code('result = "added later"')
)

# Add parallel tasks
workflow.parallel(
    t('parallel1').with_code('result = 1'),
    t('parallel2').with_code('result = 2'),
    t('parallel3').with_code('result = 3')
)

# Add sequential tasks (each depends on previous)
workflow.sequential(
    t('step1').with_code('result = 1'),
    t('step2').with_code('result = dependencies["step1"] + 1'),
    t('step3').with_code('result = dependencies["step2"] + 1')
)
```

### Workflow Operations

```python
# Validate before submission
errors = workflow.validate()
if errors:
    print("Validation errors:", errors)
else:
    # Submit
    result = workflow.submit()

    # Or submit and wait
    result = workflow.submit_and_wait(
        timeout=300,
        poll_interval=2
    )
```

### Export Options

```python
# To dictionary (for manual submission)
workflow_dict = workflow.to_dict()

# To JSON string
json_str = workflow.to_json(indent=2)

# To YAML (requires PyYAML)
yaml_str = workflow.to_yaml()

# Debug structure
workflow.print_structure()
```

---

## Common Patterns

### 1. Map-Reduce Pattern

```python
# Map phase - parallel processing
map_workflow = w(
    t('process_chunk_1')
        .with_code('result = process(data[0:1000])'),

    t('process_chunk_2')
        .with_code('result = process(data[1000:2000])'),

    t('process_chunk_3')
        .with_code('result = process(data[2000:3000])'),

    # Reduce phase - combine results
    t('combine_results')
        .needs('process_chunk_1', 'process_chunk_2', 'process_chunk_3')
        .with_code('''
chunk1 = dependencies["process_chunk_1"]
chunk2 = dependencies["process_chunk_2"]
chunk3 = dependencies["process_chunk_3"]
result = combine([chunk1, chunk2, chunk3])
''')
).name('Map-Reduce Pipeline')
```

### 2. Pipeline Pattern

```python
# Sequential data pipeline
pipeline = w().sequential(
    t('extract').with_code('result = extract_from_source()'),
    t('transform').with_code('result = transform(dependencies["extract"])'),
    t('load').with_code('result = load_to_destination(dependencies["transform"])')
).name('ETL Pipeline')
```

### 3. Fan-Out/Fan-In Pattern

```python
workflow = w(
    # Fan-out: trigger multiple parallel tasks
    t('trigger').with_code('result = {"ids": [1, 2, 3, 4, 5]}'),

    # Parallel processing
    t('process_1').needs('trigger').with_code('result = process(1)'),
    t('process_2').needs('trigger').with_code('result = process(2)'),
    t('process_3').needs('trigger').with_code('result = process(3)'),
    t('process_4').needs('trigger').with_code('result = process(4)'),
    t('process_5').needs('trigger').with_code('result = process(5)'),

    # Fan-in: collect all results
    t('aggregate')
        .needs('process_1', 'process_2', 'process_3', 'process_4', 'process_5')
        .with_code('result = aggregate_all(dependencies)')
)
```

### 4. Conditional Execution Pattern

```python
workflow = w(
    t('check_condition').with_code('''
if some_condition():
    result = {"next": "path_a"}
else:
    result = {"next": "path_b"}
'''),

    t('path_a')
        .needs('check_condition')
        .with_code('''
if dependencies["check_condition"]["next"] == "path_a":
    result = process_path_a()
else:
    result = {"skipped": True}
'''),

    t('path_b')
        .needs('check_condition')
        .with_code('''
if dependencies["check_condition"]["next"] == "path_b":
    result = process_path_b()
else:
    result = {"skipped": True}
''')
)
```

### 5. Retry with Backoff Pattern

```python
workflow = w(
    t('unreliable_service')
        .with_code('''
import random
if random.random() > 0.7:  # 30% success rate
    result = {"success": True, "data": "payload"}
else:
    raise Exception("Service temporarily unavailable")
''')
        .retry(5)
        .timeout(10)
)
```

---

## Real-World Examples

### Data Analysis Pipeline

```python
from gleitzeit.easy import t, w

analysis_workflow = w(
    # Data collection
    t('fetch_sales_data')
        .with_code('result = fetch_from_database("sales", last_30_days)')
        .timeout(30)
        .cache(3600),

    t('fetch_customer_data')
        .with_code('result = fetch_from_database("customers", active=True)')
        .timeout(30)
        .cache(3600),

    # Data processing
    t('clean_data')
        .needs('fetch_sales_data', 'fetch_customer_data')
        .with_code('''
sales = dependencies["fetch_sales_data"]
customers = dependencies["fetch_customer_data"]
result = {
    "sales": clean_sales_data(sales),
    "customers": clean_customer_data(customers)
}
'''),

    # Analysis
    t('calculate_metrics')
        .needs('clean_data')
        .with_code('''
data = dependencies["clean_data"]
result = {
    "total_revenue": sum(s["amount"] for s in data["sales"]),
    "avg_order_value": calculate_aov(data["sales"]),
    "customer_segments": segment_customers(data["customers"])
}
''')
        .retry(2),

    # Reporting
    t('generate_report')
        .needs('calculate_metrics')
        .with_code('''
metrics = dependencies["calculate_metrics"]
result = {
    "report": create_pdf_report(metrics),
    "summary": create_executive_summary(metrics)
}
'''),

    t('send_notifications')
        .needs('generate_report')
        .with_code('''
report = dependencies["generate_report"]
send_email(executives, report["summary"])
upload_to_s3(report["report"])
result = {"notifications_sent": True}
''')

).name('Daily Sales Analysis') \
 .id(f'sales-analysis-{datetime.now().strftime("%Y%m%d")}') \
 .metadata(
     schedule='daily',
     owner='analytics-team',
     priority='high'
 )

# Submit and wait for completion
result = analysis_workflow.submit_and_wait(timeout=600)
print(f"Analysis complete: {result['status']}")
```

### Machine Learning Pipeline

```python
ml_workflow = w(
    # Data preparation
    t('load_dataset')
        .with_file('scripts/load_data.py')
        .env(DATASET_PATH='/data/training.csv'),

    t('split_data')
        .needs('load_dataset')
        .with_code('''
from sklearn.model_selection import train_test_split
data = dependencies["load_dataset"]
X_train, X_test, y_train, y_test = train_test_split(
    data["features"], data["labels"], test_size=0.2
)
result = {
    "X_train": X_train, "X_test": X_test,
    "y_train": y_train, "y_test": y_test
}
'''),

    # Feature engineering
    t('feature_engineering')
        .needs('split_data')
        .with_file('scripts/feature_engineering.py')
        .timeout(300),

    # Model training (parallel)
    t('train_random_forest')
        .needs('feature_engineering')
        .with_file('models/random_forest.py')
        .timeout(600),

    t('train_gradient_boost')
        .needs('feature_engineering')
        .with_file('models/gradient_boost.py')
        .timeout(600),

    t('train_neural_network')
        .needs('feature_engineering')
        .with_file('models/neural_network.py')
        .timeout(1200),

    # Model evaluation
    t('evaluate_models')
        .needs('train_random_forest', 'train_gradient_boost', 'train_neural_network')
        .with_code('''
models = {
    "rf": dependencies["train_random_forest"],
    "gb": dependencies["train_gradient_boost"],
    "nn": dependencies["train_neural_network"]
}

best_model = max(models.items(), key=lambda x: x[1]["accuracy"])
result = {
    "best_model": best_model[0],
    "accuracy": best_model[1]["accuracy"],
    "all_results": models
}
'''),

    # Deploy best model
    t('deploy_model')
        .needs('evaluate_models')
        .with_code('''
best = dependencies["evaluate_models"]
deploy_to_production(best["best_model"])
result = {"deployed": True, "model": best["best_model"]}
''')
        .priority(100)

).name('ML Model Training Pipeline') \
 .description('Train and deploy the best performing model')

result = ml_workflow.submit_and_wait(timeout=1800)  # 30 minutes
```

---

## Tips & Tricks

### 1. Use List Comprehension for Dynamic Tasks

```python
# Create tasks dynamically
task_ids = ['dataset1', 'dataset2', 'dataset3']
tasks = [
    t(f'process_{id}').with_code(f'result = process("{id}")')
    for id in task_ids
]
workflow = w(*tasks)
```

### 2. Build Workflows Programmatically

```python
def create_pipeline(steps):
    tasks = []
    prev_task = None

    for i, step in enumerate(steps):
        task = t(f'step_{i}').with_code(step['code'])
        if prev_task:
            task.needs(prev_task)
        tasks.append(task)
        prev_task = f'step_{i}'

    return w(*tasks)

pipeline = create_pipeline([
    {'code': 'result = step1()'},
    {'code': 'result = step2(dependencies["step_0"])'},
    {'code': 'result = step3(dependencies["step_1"])'}
])
```

### 3. Reusable Task Templates

```python
def create_api_task(name, endpoint, **params):
    return t(name) \
        .with_code(f'result = call_api("{endpoint}", {params})') \
        .retry(3) \
        .timeout(30)

workflow = w(
    create_api_task('get_user', '/users/123'),
    create_api_task('get_orders', '/orders', user_id=123),
    create_api_task('get_products', '/products', category='electronics')
)
```

### 4. Error Recovery Patterns

```python
# Task with fallback
t('primary_source')
    .with_code('''
try:
    result = fetch_from_primary()
except Exception:
    result = fetch_from_backup()
''')
    .retry(2)
```

### 5. Debug Mode

```python
# Add debug logging to all tasks
def debug_task(name, code):
    debug_code = f'''
print(f"Starting task: {name}")
{code}
print(f"Task {name} result: {{result}}")
'''
    return t(name).with_code(debug_code)
```

---

## Advanced Features

### Custom Protocols

While Python execution is the default, you can specify other protocols:

```python
# HTTP request task
t('api_call', 'http/v1:get')
    .with_(url='https://api.example.com/data')

# Database query task
t('query', 'sql/v1:select')
    .with_(query='SELECT * FROM users')

# Shell command task
t('backup', 'shell/v1:execute')
    .with_(command='tar -czf backup.tar.gz /data')
```

### Task Composition

```python
# Reuse task configurations
base_config = t('base').retry(3).timeout(30)

# Create variants
task1 = t('task1').with_code('result = 1').retry(3).timeout(30)
task2 = t('task2').with_code('result = 2').retry(3).timeout(30)
```

### Workflow Composition

```python
# Combine workflows
workflow1 = w(t('a').with_code('result = 1'))
workflow2 = w(t('b').with_code('result = 2'))

# Merge into larger workflow
combined = w(
    *workflow1.tasks,
    *workflow2.tasks,
    t('combine').needs('a', 'b').with_code('result = dependencies["a"] + dependencies["b"]')
)
```

---

## Troubleshooting

### Common Issues

**Issue: Circular dependencies detected**
```python
# This will fail
w(
    t('a').needs('b'),
    t('b').needs('a')  # Circular!
)

# Solution: Restructure dependencies
w(
    t('a'),
    t('b').needs('a')
)
```

**Issue: Task not found in dependencies**
```python
# This will fail
t('task2').needs('task1')  # But task1 doesn't exist!

# Solution: Ensure all dependencies are included
w(
    t('task1').with_code('result = 1'),
    t('task2').needs('task1').with_code('result = 2')
)
```

**Issue: Workflow won't submit**
```python
# Always validate first
errors = workflow.validate()
if errors:
    for error in errors:
        print(f"Fix this: {error}")
```

---

## Summary

The Easy Client makes workflow creation intuitive and enjoyable. Remember:

- **`t()`** creates tasks
- **`w()`** creates workflows
- **Chain methods** for configuration
- **`.submit()`** to execute

Start simple, add complexity as needed, and let the Easy Client handle the details!

Happy workflow building! 🚀