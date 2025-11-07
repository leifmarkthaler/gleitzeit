# How Other Workflow Libraries Handle Conditional Tasks

## Overview

This document analyzes how popular workflow orchestration libraries implement conditional task execution, providing insights for Gleitzeit's design.

## 1. Apache Airflow

### BranchPythonOperator

Airflow uses special branching operators that return the task_id to execute next:

```python
from airflow.operators.python import BranchPythonOperator

def decide_which_path():
    if condition:
        return 'task_a'  # task_id to execute
    else:
        return 'task_b'

branching = BranchPythonOperator(
    task_id='branching',
    python_callable=decide_which_path,
)

task_a = DummyOperator(task_id='task_a')
task_b = DummyOperator(task_id='task_b')

branching >> [task_a, task_b]
```

### ShortCircuitOperator

Stops downstream tasks if condition is False:

```python
from airflow.operators.python import ShortCircuitOperator

def check_condition():
    return True  # Continue if True, stop if False

short_circuit = ShortCircuitOperator(
    task_id='short_circuit',
    python_callable=check_condition,
)
```

### Trigger Rules

Tasks have trigger rules for conditional execution:

```python
task = SomeOperator(
    task_id='task',
    trigger_rule='one_success',  # Run if at least one upstream succeeds
    # Options: all_success, all_failed, one_failed, none_failed, etc.
)
```

**Key Insights:**
- Special operator types for branching (not regular tasks)
- Python callables determine flow
- Trigger rules for dependency-based conditions
- Skipped tasks propagate skip status downstream

## 2. Prefect

### Conditional Tasks with @task Decorator

Prefect uses Python's native if/else with task decorators:

```python
from prefect import flow, task

@task
def check_condition():
    return True

@task
def task_a():
    return "A"

@task
def task_b():
    return "B"

@flow
def conditional_flow():
    condition = check_condition()
    
    if condition:
        result = task_a()
    else:
        result = task_b()
    
    return result
```

### Case Statements

```python
from prefect import case

@flow
def switch_flow(x: int):
    with case(x, 1):
        result = task_one()
    with case(x, 2):
        result = task_two()
    with case(x, 3):
        result = task_three()
```

**Key Insights:**
- Native Python conditionals in flow definition
- Context managers for switch/case patterns
- Tasks are skipped at runtime based on conditions
- Very Pythonic approach

## 3. Temporal

### Workflow Logic with Conditionals

Temporal workflows use regular programming language conditionals:

```python
@workflow.defn
class ConditionalWorkflow:
    @workflow.run
    async def run(self, input: WorkflowInput):
        # Conditions are just normal code
        if input.amount > 1000:
            approval = await workflow.execute_activity(
                get_approval,
                start_to_close_timeout=timedelta(hours=1),
            )
            if not approval:
                return "Rejected"
        
        # Continue with processing
        result = await workflow.execute_activity(process_order)
        return result
```

**Key Insights:**
- Workflows are code - use native language features
- Conditions are deterministic and replayable
- No special conditional constructs needed
- Full programming language power

## 4. AWS Step Functions

### Choice State

Step Functions use explicit Choice states in state machine definition:

```json
{
  "CheckAmount": {
    "Type": "Choice",
    "Choices": [
      {
        "Variable": "$.amount",
        "NumericGreaterThan": 1000,
        "Next": "RequireApproval"
      },
      {
        "Variable": "$.amount",
        "NumericLessThanEquals": 1000,
        "Next": "AutoApprove"
      }
    ],
    "Default": "DefaultState"
  }
}
```

### Parallel Branches with Conditions

```json
{
  "Type": "Parallel",
  "Branches": [
    {
      "StartAt": "CheckCondition",
      "States": {
        "CheckCondition": {
          "Type": "Choice",
          "Choices": [...]
        }
      }
    }
  ]
}
```

**Key Insights:**
- Explicit Choice state type
- JSON-based condition expressions
- State machine approach
- Visual workflow designer support

## 5. Argo Workflows

### When Expression

Argo uses `when` expressions in YAML:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
spec:
  templates:
  - name: conditional-task
    steps:
    - - name: check-condition
        template: condition-check
    - - name: task-a
        template: task-a-template
        when: "{{steps.check-condition.outputs.result}} == 'true'"
      - name: task-b
        template: task-b-template
        when: "{{steps.check-condition.outputs.result}} == 'false'"
```

### Conditional DAG

```yaml
dag:
  tasks:
  - name: A
    template: task-a
  - name: B
    dependencies: [A]
    template: task-b
    when: "{{tasks.A.outputs.parameters.status}} == 'success'"
```

**Key Insights:**
- Template variable expressions
- `when` field on tasks
- Expression evaluation at runtime
- YAML-based workflow definition

## 6. Cadence

### Decision Tasks

Cadence uses decision tasks that return different decisions:

```go
func Workflow(ctx workflow.Context, input string) error {
    var result string
    
    // Condition evaluation
    if input == "path_a" {
        err := workflow.ExecuteActivity(ctx, ActivityA).Get(ctx, &result)
    } else {
        err := workflow.ExecuteActivity(ctx, ActivityB).Get(ctx, &result)
    }
    
    return err
}
```

**Key Insights:**
- Similar to Temporal (same heritage)
- Code-based workflows
- Native language conditionals
- Deterministic replay

## 7. Luigi

### Dynamic Dependencies

Luigi uses dynamic dependency resolution:

```python
import luigi

class ConditionalTask(luigi.Task):
    def requires(self):
        # Dynamically determine dependencies
        if self.check_condition():
            return TaskA()
        else:
            return TaskB()
    
    def check_condition(self):
        # Evaluate condition
        return True
```

**Key Insights:**
- Dynamic dependency resolution
- Python method returns dependencies
- No explicit conditional syntax
- Determined at task scheduling time

## 8. Celery

### Canvas with Groups and Chains

Celery uses signatures and canvas for conditional execution:

```python
from celery import group, chain, signature

@app.task
def evaluate_condition(data):
    return data['value'] > 100

@app.task
def conditional_router(result, data):
    if result:
        # Execute task A
        signature('task_a', args=[data]).apply_async()
    else:
        # Execute task B
        signature('task_b', args=[data]).apply_async()

# Chain tasks
workflow = chain(
    evaluate_condition.s(data),
    conditional_router.s(data)
)
```

**Key Insights:**
- Task chaining with callbacks
- Dynamic task invocation
- Signature-based composition
- Callback-style conditionals

## 9. Apache NiFi

### RouteOnAttribute Processor

NiFi uses processors that route data based on attributes:

```xml
<processor>
  <type>RouteOnAttribute</type>
  <properties>
    <property name="Route Strategy">Route to Property name</property>
    <property name="large_file">${fileSize:gt(1000000)}</property>
    <property name="small_file">${fileSize:le(1000000)}</property>
  </properties>
</processor>
```

**Key Insights:**
- Expression Language for conditions
- Visual flow-based programming
- Routing processors for branching
- Data-flow oriented

## 10. Dagster

### Dynamic Orchestration

Dagster uses Python conditionals with op outputs:

```python
@op
def condition_op(context, data):
    if data > 100:
        yield Output(data, "large")
    else:
        yield Output(data, "small")

@op(
    ins={"input_data": In()},
    out={"large": Out(is_required=False), "small": Out(is_required=False)}
)
def router_op(context, input_data):
    if input_data > threshold:
        yield Output(input_data, "large")
    else:
        yield Output(input_data, "small")

@job
def conditional_job():
    result = router_op()
    process_large(result.large)
    process_small(result.small)
```

**Key Insights:**
- Multiple outputs from ops
- Optional outputs for branching
- Python-native conditionals
- Type-safe with schema validation

## Comparison Table

| Library | Approach | Mechanism | Evaluation Time | Pros | Cons |
|---------|----------|-----------|-----------------|------|------|
| **Airflow** | Special Operators | BranchOperator, ShortCircuit | Runtime | Clear branching | Special operator types |
| **Prefect** | Native Python | if/else in flow | Definition time | Pythonic | Less declarative |
| **Temporal** | Code as Workflow | Native language | Runtime | Full language power | Requires determinism |
| **Step Functions** | Choice States | JSON state machine | Runtime | Visual design | Verbose JSON |
| **Argo** | When Expressions | Template expressions | Runtime | Declarative | YAML complexity |
| **Cadence** | Code Decisions | Native language | Runtime | Flexible | Complex replay |
| **Luigi** | Dynamic Dependencies | Python methods | Schedule time | Simple | Limited branching |
| **Celery** | Task Signatures | Callbacks/routing | Runtime | Dynamic | Callback hell |
| **NiFi** | Route Processors | Expression language | Runtime | Visual | Data-flow only |
| **Dagster** | Multiple Outputs | Python yields | Runtime | Type safe | Complex outputs |

## Common Patterns

### 1. Special Conditional Operators
- Airflow: BranchPythonOperator
- Step Functions: Choice State
- NiFi: RouteOnAttribute

### 2. Native Language Conditionals
- Temporal/Cadence: if/else in workflow code
- Prefect: Python if/else
- Dagster: Python conditionals

### 3. Expression-Based
- Argo: When expressions
- Step Functions: JSONPath
- NiFi: Expression Language

### 4. Dynamic Dependencies
- Luigi: requires() method
- Celery: Dynamic signatures

## Lessons for Gleitzeit

### What Works Well

1. **Explicit Conditional Tasks** (Airflow, Step Functions)
   - Clear workflow visualization
   - Easy to debug
   - Predictable behavior

2. **Expression Languages** (Argo, NiFi)
   - Declarative and safe
   - No code execution needed
   - Good for simple conditions

3. **Native Code** (Temporal, Prefect)
   - Powerful and flexible
   - Natural for developers
   - But requires determinism

### What to Avoid

1. **Callback Hell** (Celery)
   - Hard to follow flow
   - Difficult debugging

2. **Over-complexity** (Step Functions JSON)
   - Verbose definitions
   - Hard to maintain

3. **Hidden Magic** (Luigi dynamic deps)
   - Unclear execution flow
   - Surprising behavior

## Recommendations for Gleitzeit

Based on this analysis, the **Validation Task** approach aligns well with successful patterns:

1. **Similar to Airflow's BranchOperator**: Special task type for decisions
2. **Like Argo's When**: Expression-based conditions
3. **Echoes Step Functions**: Explicit conditional states
4. **Matches NiFi's Routing**: Clear data flow

### Why Validation Tasks Fit Gleitzeit

1. **Explicit**: Like Airflow and Step Functions, conditions are visible tasks
2. **Safe**: Like Argo, uses expressions not arbitrary code
3. **Distributable**: Unlike Temporal/Prefect, doesn't require local execution
4. **Observable**: Unlike Luigi, execution flow is clear
5. **Simple**: Unlike Celery, no callback complexity

### Unique Advantages for Gleitzeit

1. **Task Reusability**: Validation logic in handlers
2. **Distributed**: Can scale validation separately
3. **Cached**: Results can be cached in Redis
4. **Traced**: Full observability with handler tracking
5. **Typed**: Clear protocol definitions

The Validation Task pattern combines the best aspects of other systems while avoiding their pitfalls, making it ideal for Gleitzeit's distributed, task-based architecture.