# Simplified Pure Task Conditionals

## The Challenge
Pure task-based conditionals are powerful but verbose. Can we simplify?

## Solution: Smart Defaults & Conventions

### 1. Implicit Condition Tasks

Instead of explicitly defining condition tasks, use **smart parameter expansion**:

```yaml
tasks:
  - id: "get_customer"
    protocol: "api/v1"
    method: "fetch"
    
  # BEFORE: Verbose condition task
  # - id: "is_premium"
  #   protocol: "condition/v1"
  #   method: "equals"
  #   params:
  #     value: "${get_customer.tier}"
  #     expected: "premium"
  
  # AFTER: Implicit condition with ?
  - id: "premium_feature"
    protocol: "feature/v1"
    method: "enable"
    when: "get_customer.tier == premium"  # Creates implicit condition task
    dependencies: ["get_customer"]
```

The system automatically creates the condition task behind the scenes.

### 2. Inline Action Syntax

```yaml
tasks:
  - id: "validate"
    protocol: "validator/v1"
    method: "check"
    
  # BEFORE: Separate skip task
  # - id: "skip_if_invalid"
  #   protocol: "skip/v1"
  #   method: "skip_if_false"
  #   params:
  #     condition_task: "validate"
  #     skip_tasks: ["process"]
  
  # AFTER: Inline skip directive
  - id: "process"
    protocol: "processor/v1"
    method: "run"
    skip_unless: "validate"  # Creates implicit skip task
```

### 3. Compact Action Notation

```yaml
tasks:
  - id: "check_age"
    protocol: "validator/v1"
    method: "validate_age"
    
  # Multiple actions in one place
  - id: "adult_content"
    protocol: "content/v1"
    method: "serve"
    actions:
      skip_if: "check_age.result < 18"
      fail_if: "check_age.error != null"
    dependencies: ["check_age"]
```

## Convention-Based Simplification

### Pattern 1: Question Mark for Conditions

```yaml
tasks:
  # The ? prefix auto-creates a condition task
  - id: "?is_premium"
    check: "customer.tier == premium"
    depends_on: "get_customer"
    
  - id: "premium_feature"
    if: "?is_premium"  # References the condition
```

### Pattern 2: Guard Notation

```yaml
tasks:
  - id: "process_payment"
    protocol: "payment/v1"
    method: "charge"
    guards:
      - "amount > 0"           # Auto-creates condition task
      - "payment_method.valid" # Auto-creates condition task
      - fail: "!authorized"    # Fail if not authorized
```

### Pattern 3: Switch Shorthand

```yaml
tasks:
  - id: "classify"
    protocol: "llm/v1"
    method: "classify"
    
  # Compact switch syntax
  - id: "route"
    switch: "classify.type"
    cases:
      invoice: ["process_invoice", "update_books"]
      receipt: ["track_expense"]
      default: ["manual_review"]
```

## Ultra-Compact YAML Extension

### Using YAML Anchors and Aliases

```yaml
# Define reusable conditions
conditions:
  premium: &premium
    check: "customer.tier == premium"
  high_value: &high_value
    check: "order.total > 1000"

tasks:
  - id: "vip_treatment"
    if: [*premium, *high_value]  # Both conditions must pass
```

### Using Templates

```yaml
templates:
  skip_if_not_premium: &not_premium
    skip_unless: "customer.tier == premium"
    
tasks:
  - id: "feature_1"
    <<: *not_premium
    protocol: "feature/v1"
    
  - id: "feature_2"
    <<: *not_premium
    protocol: "feature/v1"
```

## Simplified Real-World Example

### BEFORE (Verbose):
```yaml
tasks:
  - id: "get_order"
    protocol: "api/v1"
    method: "fetch"
    
  - id: "check_inventory"
    protocol: "inventory/v1"
    method: "check"
    dependencies: ["get_order"]
    
  - id: "is_in_stock"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${check_inventory.available}"
      expected: true
    dependencies: ["check_inventory"]
    
  - id: "skip_if_out_of_stock"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "is_in_stock"
      skip_tasks: ["charge_card", "ship_order"]
    dependencies: ["is_in_stock"]
    
  - id: "charge_card"
    protocol: "payment/v1"
    method: "charge"
    dependencies: ["skip_if_out_of_stock"]
```

### AFTER (Simplified):
```yaml
tasks:
  - id: "get_order"
    protocol: "api/v1"
    method: "fetch"
    
  - id: "check_inventory"
    protocol: "inventory/v1"
    method: "check"
    after: "get_order"
    
  - id: "charge_card"
    protocol: "payment/v1"
    method: "charge"
    when: "check_inventory.available"
    after: "check_inventory"
    
  - id: "ship_order"
    protocol: "shipping/v1"
    method: "ship"
    when: "check_inventory.available"
    after: "charge_card"
```

## Implementation: Expansion at Load Time

```python
class WorkflowExpander:
    """Expands simplified syntax into full task format"""
    
    def expand_workflow(self, workflow: Dict) -> Dict:
        """Convert simplified syntax to full task-based format"""
        expanded_tasks = []
        
        for task in workflow['tasks']:
            # Expand 'when' into condition task
            if 'when' in task:
                condition_task = self.create_condition_task(
                    task['id'], 
                    task['when']
                )
                expanded_tasks.append(condition_task)
                
                # Add condition to dependencies
                task.setdefault('dependencies', []).append(condition_task['id'])
                
            # Expand 'skip_unless' into skip task
            if 'skip_unless' in task:
                skip_task = self.create_skip_task(
                    task['id'],
                    task['skip_unless']
                )
                expanded_tasks.append(skip_task)
                task.setdefault('dependencies', []).append(skip_task['id'])
                
            # Expand 'guards' into multiple condition tasks
            if 'guards' in task:
                for guard in task['guards']:
                    guard_task = self.create_guard_task(task['id'], guard)
                    expanded_tasks.append(guard_task)
                    task.setdefault('dependencies', []).append(guard_task['id'])
            
            expanded_tasks.append(task)
        
        return {'tasks': expanded_tasks}
```

## Benefits of Simplified Syntax

1. **80% Less Verbose** - Common patterns are concise
2. **Still Pure Tasks** - Everything expands to tasks internally
3. **Progressive Disclosure** - Simple cases simple, complex cases possible
4. **Backward Compatible** - Can mix verbose and simplified syntax
5. **IDE Friendly** - Easy to add autocomplete for common patterns

## Cheat Sheet

| Pattern | Simplified | Expands To |
|---------|------------|------------|
| Condition | `when: "x > 5"` | Condition task + dependency |
| Skip | `skip_unless: "valid"` | Skip task + dependency |
| Fail | `fail_if: "error"` | Fail task + dependency |
| Multiple | `guards: ["a", "b"]` | Multiple condition tasks |
| Switch | `switch: "type"` | Split task with routes |

## Migration Path

1. **Phase 1**: Support both syntaxes
2. **Phase 2**: Converter tool for existing workflows
3. **Phase 3**: Simplified as default in docs
4. **Phase 4**: Deprecate verbose syntax (optional)

## Conclusion

By adding smart conventions and expansion rules, we can:
- Keep the power of pure task-based conditionals
- Reduce verbosity by 80% for common cases
- Maintain full backward compatibility
- Make workflows more readable and maintainable

The key insight: **Simplified syntax is just sugar that expands to pure tasks!**