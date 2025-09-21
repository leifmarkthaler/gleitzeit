# Conditional Actions: fail, skip, split

## The Brilliant Insight

Instead of just "conditions", we have **action directives** that clearly state what happens based on task results!

## Core Concept: Actions Based on Results

```python
class ConditionalAction(BaseModel):
    """What to do based on a dependency's result"""
    when: str  # Expression to evaluate: "${task.result} == false"
    action: str  # "fail", "skip", "split", "pause", "rewind"
    target: Optional[str] = None  # For split: which path to take
    reason: Optional[str] = None  # For logging/debugging

class Task(BaseModel):
    dependencies: List[str] = []
    
    # NEW: Actions based on dependency results
    on_dependency: Optional[Dict[str, List[ConditionalAction]]] = None
```

## Action Types

### 1. SKIP - Continue workflow but skip this task

```yaml
tasks:
  - id: "check_age"
    protocol: "validator/v1"
    method: "validate"
    params:
      value: "${user.age}"
      min: 18
  
  - id: "adult_content"
    protocol: "content/v1"
    method: "serve_adult"
    dependencies: ["check_age"]
    on_dependency:
      check_age:
        - when: "${result} == false"
          action: "skip"
          reason: "User under 18"
  
  - id: "regular_content"
    protocol: "content/v1"
    method: "serve_regular"
    dependencies: ["check_age"]  # Always runs regardless
```

### 2. FAIL - Stop workflow with error

```yaml
tasks:
  - id: "validate_payment"
    protocol: "payment/v1"
    method: "validate_card"
    params:
      card: "${order.card}"
  
  - id: "charge_card"
    protocol: "payment/v1"
    method: "charge"
    dependencies: ["validate_payment"]
    on_dependency:
      validate_payment:
        - when: "${result.valid} == false"
          action: "fail"
          reason: "Invalid payment method: ${result.error}"
```

### 3. SPLIT - Choose different paths

```yaml
tasks:
  - id: "analyze_risk"
    protocol: "risk/v1"
    method: "assess"
    params:
      data: "${application}"
    # Returns: {score: 1-10, category: "low|medium|high"}
  
  - id: "router"
    protocol: "router/v1"
    method: "route"
    dependencies: ["analyze_risk"]
    on_dependency:
      analyze_risk:
        - when: "${result.category} == 'low'"
          action: "split"
          target: "auto_approve_path"
        - when: "${result.category} == 'medium'"
          action: "split"
          target: "review_path"
        - when: "${result.category} == 'high'"
          action: "split"
          target: "reject_path"
  
  # Define paths
  - id: "auto_approve_path"
    protocol: "approval/v1"
    method: "auto_approve"
    dependencies: ["router"]
    split_group: "auto_approve_path"  # Only runs if split to this path
  
  - id: "review_path"
    protocol: "approval/v1"
    method: "queue_review"
    dependencies: ["router"]
    split_group: "review_path"
  
  - id: "reject_path"
    protocol: "approval/v1"
    method: "reject"
    dependencies: ["router"]
    split_group: "reject_path"
```

## Even Cleaner: Inline Actions

```yaml
tasks:
  - id: "check_inventory"
    protocol: "inventory/v1"
    method: "check"
    params:
      sku: "${order.sku}"
      quantity: "${order.quantity}"
  
  - id: "reserve_inventory"
    protocol: "inventory/v1"
    method: "reserve"
    dependencies: ["check_inventory"]
    # Simple inline syntax
    skip_if: "${check_inventory.available} < ${order.quantity}"
    fail_if: "${check_inventory.error} != null"
```

## Advanced: Combination Actions

```yaml
tasks:
  - id: "complex_validation"
    protocol: "validator/v1"
    method: "validate_complex"
  
  - id: "process"
    dependencies: ["complex_validation"]
    on_dependency:
      complex_validation:
        # Multiple conditions, different actions
        - when: "${result.score} < 30"
          action: "fail"
          reason: "Score too low"
        
        - when: "${result.score} < 60"
          action: "pause"
          reason: "Needs manual review"
        
        - when: "${result.needs_enrichment} == true"
          action: "rewind"
          target: "data_enrichment"
          reason: "Missing required data"
        
        - when: "${result.use_alternate} == true"
          action: "split"
          target: "alternate_processing"
```

## The SPLIT Pattern - Most Powerful

Split enables **dynamic workflow branching**:

```yaml
tasks:
  # Classifier determines path
  - id: "classify_document"
    protocol: "llm/v1"
    method: "classify"
    params:
      prompt: "Classify this document: ${document}"
      categories: ["invoice", "receipt", "contract", "other"]
  
  # Router task with split logic
  - id: "route_document"
    protocol: "router/v1"
    method: "route"
    dependencies: ["classify_document"]
    on_dependency:
      classify_document:
        - when: "${result.category} == 'invoice'"
          action: "split"
          target: "invoice_flow"
        - when: "${result.category} == 'receipt'"
          action: "split"
          target: "receipt_flow"
        - when: "${result.category} == 'contract'"
          action: "split"
          target: "contract_flow"
        - when: "true"  # Default
          action: "split"
          target: "manual_flow"
  
  # Each flow is independent
  - id: "extract_invoice_data"
    split_group: "invoice_flow"
    protocol: "extraction/v1"
    method: "extract_invoice"
    dependencies: ["route_document"]
  
  - id: "process_invoice"
    split_group: "invoice_flow"
    protocol: "accounting/v1"
    method: "process_invoice"
    dependencies: ["extract_invoice_data"]
  
  - id: "extract_receipt_data"
    split_group: "receipt_flow"
    protocol: "extraction/v1"
    method: "extract_receipt"
    dependencies: ["route_document"]
  
  # ... more flows
```

## Implementation: Clean and Simple

```python
class TaskExecutor:
    async def process_task_actions(self, task: Task, context: Dict) -> TaskStatus:
        """Process conditional actions based on dependencies"""
        
        if not task.on_dependency:
            return TaskStatus.PENDING  # Normal execution
        
        for dep_id, actions in task.on_dependency.items():
            dep_result = context.get(dep_id, {}).get('result')
            
            for action in actions:
                if self.evaluate_condition(action.when, dep_result):
                    return await self.execute_action(task, action)
        
        return TaskStatus.PENDING  # No conditions matched, proceed normally
    
    async def execute_action(self, task: Task, action: ConditionalAction) -> TaskStatus:
        """Execute the specified action"""
        
        if action.action == "skip":
            task.status = TaskStatus.SKIPPED
            task.metadata = {"skip_reason": action.reason}
            await self.emit_event("task.skipped", task)
            return TaskStatus.SKIPPED
            
        elif action.action == "fail":
            task.status = TaskStatus.FAILED
            task.error = action.reason
            await self.emit_event("task.failed", task)
            # This will fail the entire workflow
            raise WorkflowFailure(action.reason)
            
        elif action.action == "split":
            # Mark this task's split choice
            task.metadata = {"split_target": action.target}
            # Only tasks in the target split_group will run
            await self.activate_split_group(task.workflow_id, action.target)
            return TaskStatus.COMPLETED
            
        elif action.action == "pause":
            await self.pause_workflow(task.workflow_id, action.reason)
            return TaskStatus.PAUSED
            
        elif action.action == "rewind":
            await self.pause_workflow_with_rewind(
                task.workflow_id, 
                rewind_to=action.target,
                reason=action.reason
            )
            return TaskStatus.REWOUND
```

## Why This is Superior

### 1. **Explicit Intent**
```yaml
# Crystal clear what happens
fail_if: "${validation.errors} > 0"
skip_if: "${user.age} < 18"
split_on: "${document.type}"
```

### 2. **Multiple Actions per Task**
```yaml
on_dependency:
  validate:
    - when: "${result.critical_error}"
      action: "fail"
    - when: "${result.warning}"
      action: "pause"
    - when: "${result.needs_enrichment}"
      action: "rewind"
```

### 3. **Dynamic Workflows**
SPLIT enables workflows that adapt to data:
- Document type determines processing flow
- Customer tier determines service level
- Risk score determines approval path

### 4. **Self-Healing Workflows**
```yaml
- when: "${validation.missing_data}"
  action: "rewind"
  target: "data_enrichment"
  reason: "Attempting to fix missing data"
```

## Comparison with Simple Conditions

| Simple Conditions | Action Directives |
|------------------|-------------------|
| `if condition then run` | `if condition then skip/fail/split/pause/rewind` |
| Binary (run or don't) | Multiple outcomes |
| Static workflows | Dynamic workflows |
| Limited error handling | Rich error handling |

## Real-World Example: E-commerce Order

```yaml
tasks:
  - id: "validate_order"
    protocol: "validator/v1"
    method: "validate_order"
  
  - id: "check_fraud"
    protocol: "fraud/v1"
    method: "check"
    dependencies: ["validate_order"]
    on_dependency:
      validate_order:
        - when: "${result.valid} == false"
          action: "fail"
          reason: "Invalid order: ${result.errors}"
  
  - id: "check_inventory"
    protocol: "inventory/v1"
    method: "check"
    dependencies: ["check_fraud"]
    on_dependency:
      check_fraud:
        - when: "${result.risk_score} > 80"
          action: "pause"
          reason: "High fraud risk - needs review"
        - when: "${result.risk_score} > 95"
          action: "fail"
          reason: "Fraudulent order detected"
  
  - id: "route_fulfillment"
    protocol: "router/v1"
    method: "route"
    dependencies: ["check_inventory"]
    on_dependency:
      check_inventory:
        - when: "${result.all_in_stock} == true"
          action: "split"
          target: "immediate_fulfillment"
        - when: "${result.partial_stock} == true"
          action: "split"
          target: "partial_fulfillment"
        - when: "true"
          action: "split"
          target: "backorder_flow"
```

## Conclusion

Using `fail`, `skip`, `split` (and `pause`, `rewind`) as action directives is:

1. **More Expressive** - Clearly states what happens
2. **More Powerful** - Enables dynamic workflows
3. **More Intuitive** - Reads like business logic
4. **More Flexible** - Multiple actions per condition
5. **More Aligned** - Works perfectly with pause-rewind

This transforms Gleitzeit from "workflows with conditions" to "intelligent, self-adapting workflows"!