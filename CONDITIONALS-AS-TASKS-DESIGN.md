# Conditionals & Validators as Tasks - The Gleitzeit Way

## Core Insight

Instead of adding new constructs, treat conditions and validators as **regular tasks** that return boolean results. This maintains architectural simplicity and leverages everything we've already built!

## 1. Conditionals as Tasks

### The Beautiful Simplicity

```yaml
name: "Customer Support Workflow"
tasks:
  # Regular task
  - id: "analyze_sentiment"
    protocol: "llm/v1"
    method: "analyze"
    params:
      prompt: "Analyze sentiment: ${input.message}"
      model: "gpt-3.5-turbo"
  
  # CONDITION TASK - Just returns true/false
  - id: "is_angry_customer"
    protocol: "condition/v1"  # Or even just python/v1!
    method: "evaluate"
    params:
      expression: "${analyze_sentiment.sentiment} == 'negative' AND ${analyze_sentiment.confidence} > 0.8"
    dependencies: ["analyze_sentiment"]
  
  # This task only runs if condition is true
  - id: "escalate_to_human"
    protocol: "notify/v1"
    method: "email"
    params:
      to: "support-urgent@company.com"
      message: "Angry customer needs help"
    dependencies: ["is_angry_customer"]
    skip_if_dependency_false: true  # NEW: Skip if dependency returned false
  
  # This task runs if condition is false
  - id: "auto_respond"
    protocol: "llm/v1"
    method: "generate"
    params:
      prompt: "Generate friendly response"
    dependencies: ["is_angry_customer"]
    skip_if_dependency_true: true  # NEW: Skip if dependency returned true
```

### Even Simpler: Condition Results as Dependencies

```yaml
tasks:
  - id: "check_value"
    protocol: "python/v1"
    method: "evaluate"
    params:
      code: "return context['order']['total'] > 1000"
  
  - id: "apply_discount"
    protocol: "python/v1"
    method: "execute"
    params:
      code: "return price * 0.9"
    dependencies: ["check_value"]
    when: "${check_value.result} == true"  # Only run when condition met
  
  - id: "standard_pricing"
    protocol: "python/v1"
    method: "execute"
    params:
      code: "return price"
    dependencies: ["check_value"]
    when: "${check_value.result} == false"  # Run when condition not met
```

## 2. Validators as Tasks

### Same Pattern!

```yaml
tasks:
  - id: "generate_content"
    protocol: "llm/v1"
    method: "generate"
    params:
      prompt: "Write product description for ${product.name}"
      model: "gpt-4"
  
  # VALIDATOR TASK - Returns validation result
  - id: "validate_content"
    protocol: "validator/v1"  # Or just python/v1
    method: "validate"
    params:
      rules:
        - type: "length"
          min: 100
          max: 500
        - type: "no_pii"
        - type: "no_hallucination"
      input: "${generate_content.result}"
    dependencies: ["generate_content"]
  
  # Continue only if valid
  - id: "publish_content"
    protocol: "cms/v1"
    method: "publish"
    params:
      content: "${generate_content.result}"
    dependencies: ["validate_content"]
    when: "${validate_content.valid} == true"
  
  # Retry if invalid
  - id: "regenerate_content"
    protocol: "llm/v1"
    method: "generate"
    params:
      prompt: "Write product description. Previous attempt failed: ${validate_content.errors}"
      model: "gpt-4"
      temperature: 0.5  # Lower temperature for retry
    dependencies: ["validate_content"]
    when: "${validate_content.valid} == false"
```

## 3. The Power of Task-Based Approach

### A. Complex Branching with Multiple Conditions

```yaml
tasks:
  # Multiple condition checks (can run in parallel!)
  - id: "check_customer_tier"
    protocol: "python/v1"
    method: "evaluate"
    params:
      code: "return customer['tier'] == 'premium'"
    
  - id: "check_order_value"
    protocol: "python/v1"
    method: "evaluate"
    params:
      code: "return order['total'] > 500"
  
  - id: "check_inventory"
    protocol: "python/v1"
    method: "evaluate"
    params:
      code: "return inventory['stock'] > order['quantity']"
  
  # Combine conditions
  - id: "can_expedite"
    protocol: "condition/v1"
    method: "all"  # AND operation
    params:
      conditions: ["${check_customer_tier.result}", "${check_order_value.result}", "${check_inventory.result}"]
    dependencies: ["check_customer_tier", "check_order_value", "check_inventory"]
  
  - id: "expedite_shipping"
    protocol: "shipping/v1"
    method: "expedite"
    dependencies: ["can_expedite"]
    when: "${can_expedite.result} == true"
```

### B. Validation Chains

```yaml
tasks:
  # Chain multiple validators
  - id: "validate_schema"
    protocol: "validator/v1"
    method: "json_schema"
    params:
      schema: "${schemas.order_schema}"
      data: "${input.order}"
  
  - id: "validate_business_rules"
    protocol: "validator/v1"
    method: "business_rules"
    params:
      rules: ["credit_check", "inventory_check", "fraud_check"]
      data: "${input.order}"
    dependencies: ["validate_schema"]
    when: "${validate_schema.valid} == true"
  
  - id: "validate_with_llm"
    protocol: "llm/v1"
    method: "validate"
    params:
      prompt: "Does this order look legitimate? ${input.order}"
      model: "gpt-4"
    dependencies: ["validate_business_rules"]
    when: "${validate_business_rules.valid} == true"
```

## 4. Implementation - Minimal Changes!

### Just Add Two Fields to Task Model

```python
class Task(BaseModel):
    # Existing fields...
    dependencies: List[str] = []
    
    # NEW: Conditional execution based on dependency results
    when: Optional[str] = None  # Expression like "${task.result} == true"
    skip_if_dependency_false: Optional[str] = None  # Task ID to check
    skip_if_dependency_true: Optional[str] = None   # Task ID to check
```

### Or Even Simpler - Just Use 'when'

```python
class Task(BaseModel):
    # Existing fields...
    dependencies: List[str] = []
    
    # NEW: Single field for conditional execution
    when: Optional[str] = None  # Any expression: "${validate.valid} == true"
```

### The Execution Logic (Minimal Change)

```python
class TaskExecutor:
    async def should_execute_task(self, task: Task, context: Dict) -> bool:
        """Check if task should execute"""
        
        # Existing dependency check
        if not await self.dependencies_completed(task, context):
            return False
        
        # NEW: Check 'when' condition
        if task.when:
            # Resolve the expression using existing parameter resolver
            result = await self.parameter_resolver.resolve(task.when, context)
            
            # Evaluate the expression
            should_run = self.evaluate_expression(result)
            
            if not should_run:
                # Mark task as skipped
                task.status = TaskStatus.SKIPPED
                task.metadata["skip_reason"] = f"Condition not met: {task.when}"
                await self.save_task(task)
                
                # Emit event for observability
                await self.event_bus.emit("task.skipped", {
                    "task_id": task.id,
                    "condition": task.when,
                    "evaluated_to": result
                })
                
                return False
        
        return True
```

## 5. Built-in Condition and Validator Providers

### ConditionProvider (New)

```python
class ConditionProvider:
    """Provider for condition evaluation tasks"""
    
    async def evaluate(self, expression: str, context: Dict) -> bool:
        """Evaluate a condition expression"""
        # Safe evaluation of expressions
        return eval_expression(expression, context)
    
    async def all(self, conditions: List[bool]) -> bool:
        """AND operation"""
        return all(conditions)
    
    async def any(self, conditions: List[bool]) -> bool:
        """OR operation"""
        return any(conditions)
    
    async def compare(self, a: Any, operator: str, b: Any) -> bool:
        """Compare two values"""
        operators = {
            "==": lambda: a == b,
            "!=": lambda: a != b,
            ">": lambda: a > b,
            "<": lambda: a < b,
            ">=": lambda: a >= b,
            "<=": lambda: a <= b,
            "in": lambda: a in b,
            "contains": lambda: b in a
        }
        return operators[operator]()
```

### ValidatorProvider (New)

```python
class ValidatorProvider:
    """Provider for validation tasks"""
    
    async def validate(self, rules: List[Dict], input: Any) -> ValidationResult:
        """Run validation rules"""
        errors = []
        
        for rule in rules:
            if rule["type"] == "length":
                if len(input) < rule.get("min", 0) or len(input) > rule.get("max", float('inf')):
                    errors.append(f"Length must be between {rule.get('min')} and {rule.get('max')}")
            
            elif rule["type"] == "regex":
                if not re.match(rule["pattern"], str(input)):
                    errors.append(f"Does not match pattern: {rule['pattern']}")
            
            elif rule["type"] == "no_pii":
                if self.detect_pii(input):
                    errors.append("Contains PII")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "input": input
        }
    
    async def json_schema(self, schema: Dict, data: Any) -> ValidationResult:
        """Validate against JSON schema"""
        try:
            jsonschema.validate(data, schema)
            return {"valid": True}
        except jsonschema.ValidationError as e:
            return {"valid": False, "errors": [str(e)]}
```

## 6. Advanced Patterns

### A. Retry with Different Conditions

```yaml
tasks:
  - id: "attempt_1"
    protocol: "llm/v1"
    method: "generate"
    params:
      model: "gpt-3.5-turbo"
      temperature: 1.0
  
  - id: "validate_1"
    protocol: "validator/v1"
    method: "validate"
    params:
      input: "${attempt_1.result}"
    dependencies: ["attempt_1"]
  
  - id: "attempt_2"
    protocol: "llm/v1"
    method: "generate"
    params:
      model: "gpt-4"  # Better model
      temperature: 0.7  # Lower temperature
    dependencies: ["validate_1"]
    when: "${validate_1.valid} == false"  # Only if first attempt failed
  
  - id: "validate_2"
    protocol: "validator/v1"
    method: "validate"
    params:
      input: "${attempt_2.result}"
    dependencies: ["attempt_2"]
    when: "${attempt_2.status} == 'completed'"  # Only if attempt_2 ran
  
  - id: "final_result"
    protocol: "python/v1"
    method: "select_result"
    params:
      # Choose the valid result
      code: |
        if context.get('validate_1', {}).get('valid'):
            return context['attempt_1']['result']
        else:
            return context['attempt_2']['result']
    dependencies: ["validate_1", "validate_2"]
```

### B. Dynamic Router Pattern

```yaml
tasks:
  - id: "route_decision"
    protocol: "python/v1"
    method: "determine_route"
    params:
      code: |
        if customer['tier'] == 'premium':
            return 'premium_flow'
        elif order['total'] > 1000:
            return 'high_value_flow'
        else:
            return 'standard_flow'
  
  # Premium path
  - id: "premium_task_1"
    protocol: "service/v1"
    method: "premium_processing"
    dependencies: ["route_decision"]
    when: "${route_decision.result} == 'premium_flow'"
  
  # High value path
  - id: "high_value_task_1"
    protocol: "service/v1"
    method: "priority_processing"
    dependencies: ["route_decision"]
    when: "${route_decision.result} == 'high_value_flow'"
  
  # Standard path
  - id: "standard_task_1"
    protocol: "service/v1"
    method: "standard_processing"
    dependencies: ["route_decision"]
    when: "${route_decision.result} == 'standard_flow'"
```

## 7. Benefits of This Approach

### Architectural Simplicity ✨
- **No new concepts** - Everything is just a task
- **Reuses existing infrastructure** - Dependencies, parameter resolution, events
- **Consistent mental model** - Developers only learn one pattern

### Power Through Composition 🔨
- **Conditions can depend on conditions** - Build complex logic trees
- **Validators can validate validators** - Meta-validation!
- **Parallel evaluation** - Multiple conditions checked simultaneously

### Perfect Fit with Existing Features 🎯
- **Pause-Rewind**: Failed validation task → rewind to fix
- **Events**: Every condition/validation emits events
- **Monitoring**: Conditions and validators show up in task metrics
- **Dependencies**: Natural flow control

### Testability 🧪
```python
# Conditions and validators are just tasks - test them like any task!
async def test_condition_task():
    condition = Task(
        protocol="condition/v1",
        method="evaluate",
        params={"expression": "5 > 3"}
    )
    result = await executor.execute_task(condition)
    assert result.result == True
```

## 8. Migration Path

### Phase 1: Add 'when' field (1 day)
- Add optional 'when' field to Task model
- Update TaskExecutor to check 'when' condition
- Tasks with false conditions get SKIPPED status

### Phase 2: Create Providers (3 days)
- Implement ConditionProvider
- Implement ValidatorProvider
- Register with protocol registry

### Phase 3: Enhanced Features (1 week)
- Complex expression evaluation
- Custom validator types
- Condition composition helpers

## Conclusion

By treating conditions and validators as **tasks**, we get:

1. **Zero new concepts** - Everything builds on what exists
2. **Maximum flexibility** - Compose conditions like Lego blocks
3. **Full observability** - Every decision is a task with events
4. **Natural parallelism** - Multiple conditions evaluated simultaneously
5. **Rewind compatibility** - Failed validations can trigger rewind

This approach is MORE POWERFUL than special conditional constructs because tasks can:
- Have their own dependencies
- Run in parallel
- Be monitored/logged/traced
- Be paused/resumed/rewound
- Emit events
- Have retry logic

**This is the Gleitzeit way: Simple primitives, powerful composition!**