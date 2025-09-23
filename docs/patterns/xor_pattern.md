# XOR Pattern with Validation Tasks

## Overview

The XOR (exclusive OR) pattern ensures exactly one of multiple paths executes in a workflow. This is achieved using validation tasks with the `skip` behavior - each path has a validation gate, and only the path whose validation passes will execute.

## How It Works

1. **Each path gets a validation task** that checks if it should run
2. **Validation conditions are mutually exclusive** - only one can be true
3. **Failed validations cause tasks to skip** using `on_failure: "skip"`
4. **Downstream tasks can depend on all paths** - skipped dependencies are ignored

## Basic XOR Example

```yaml
workflow:
  name: XOR Payment Processing
  description: Process exactly one payment method

  tasks:
    # Determine which payment method to use
    - name: get_payment_info
      protocol: python/v1
      method: python/execute
      params:
        code: |
          # In practice, this comes from user input or database
          payment_type = "paypal"  # Could be: credit_card, paypal, or crypto
          amount = 100
          result = {'payment_type': payment_type, 'amount': amount}

    # ===== XOR VALIDATIONS - Exactly one will pass =====

    # Path 1: Credit Card validation
    - name: validate_credit_card
      protocol: validation/v1
      method: validation/evaluate
      dependencies: [get_payment_info]
      params:
        conditions:
          - expression: "payment_type == 'credit_card'"
            name: "is_credit_card"
        on_failure: "skip"
        context:
          payment_type: "${get_payment_info.payment_type}"  # Resolved before validation

    # Path 2: PayPal validation
    - name: validate_paypal
      protocol: validation/v1
      method: validation/evaluate
      dependencies: [get_payment_info]
      params:
        conditions:
          - expression: "payment_type == 'paypal'"
            name: "is_paypal"
        on_failure: "skip"
        context:
          payment_type: "${get_payment_info.payment_type}"

    # Path 3: Crypto validation
    - name: validate_crypto
      protocol: validation/v1
      method: validation/evaluate
      dependencies: [get_payment_info]
      params:
        conditions:
          - expression: "payment_type == 'crypto'"
            name: "is_crypto"
        on_failure: "skip"
        context:
          payment_type: "${get_payment_info.payment_type}"

    # ===== XOR EXECUTION - Only one will run =====

    - name: process_credit_card
      protocol: python/v1
      method: python/execute
      dependencies: [validate_credit_card]  # SKIPPED if validation fails
      params:
        code: |
          amount = ${get_payment_info.amount}
          print(f"Charging ${amount} to credit card")
          result = {'method': 'credit_card', 'charged': amount}

    - name: process_paypal
      protocol: python/v1
      method: python/execute
      dependencies: [validate_paypal]  # SKIPPED if validation fails
      params:
        code: |
          amount = ${get_payment_info.amount}
          print(f"Processing ${amount} via PayPal")
          result = {'method': 'paypal', 'charged': amount}

    - name: process_crypto
      protocol: python/v1
      method: python/execute
      dependencies: [validate_crypto]  # SKIPPED if validation fails
      params:
        code: |
          amount = ${get_payment_info.amount}
          print(f"Processing ${amount} in cryptocurrency")
          result = {'method': 'crypto', 'charged': amount}

    # ===== CONVERGENCE - Continue after XOR =====

    - name: send_receipt
      protocol: python/v1
      method: python/execute
      dependencies: [process_credit_card, process_paypal, process_crypto]
      # Exactly ONE dependency will have completed, others will be SKIPPED
      params:
        code: |
          print("Payment processed successfully, sending receipt")
          result = {'receipt_sent': True}
```

## Multi-Condition XOR

You can create XOR patterns with complex conditions:

```yaml
tasks:
  # Generate data with multiple values
  - name: get_order_info
    protocol: python/v1
    method: python/execute
    params:
      code: |
        result = {
          'size': 150,
          'priority': 'high',
          'region': 'US'
        }

  # Path 1: Small orders (any region)
  - name: validate_small
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [get_order_info]
    params:
      conditions:
        - expression: "size <= 100"
          name: "is_small"
      on_failure: "skip"
      context:
        size: "${get_order_info.size}"

  # Path 2: Medium high-priority US orders
  - name: validate_express
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [get_order_info]
    params:
      conditions:
        - expression: "size > 100 and size <= 500 and priority == 'high' and region == 'US'"
          name: "is_express"
      on_failure: "skip"
      context:
        size: "${get_order_info.size}"
        priority: "${get_order_info.priority}"
        region: "${get_order_info.region}"

  # Path 3: Everything else
  - name: validate_standard
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [get_order_info]
    params:
      conditions:
        - expression: "size > 500 or (size > 100 and priority != 'high') or region != 'US'"
          name: "is_standard"
      on_failure: "skip"
      context:
        size: "${get_order_info.size}"
        priority: "${get_order_info.priority}"
        region: "${get_order_info.region}"

  # Only the matching path executes
  - name: process_small
    dependencies: [validate_small]
    # Runs only for small orders

  - name: process_express
    dependencies: [validate_express]
    # Runs only for express orders

  - name: process_standard
    dependencies: [validate_standard]
    # Runs for everything else
```

## True Binary XOR (A XOR B)

For a true XOR where exactly one of two conditions must be true:

```yaml
tasks:
  - name: check_conditions
    protocol: python/v1
    method: python/execute
    params:
      code: |
        # Example: user has premium OR trial, but not both
        has_premium = True
        has_trial = False
        result = {'has_premium': has_premium, 'has_trial': has_trial}

  # Path A: Premium only (not trial)
  - name: validate_premium_only
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [check_conditions]
    params:
      conditions:
        - expression: "has_premium == True and has_trial == False"
          name: "premium_only"
      on_failure: "skip"
      context:
        has_premium: "${check_conditions.has_premium}"
        has_trial: "${check_conditions.has_trial}"

  # Path B: Trial only (not premium)
  - name: validate_trial_only
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [check_conditions]
    params:
      conditions:
        - expression: "has_premium == False and has_trial == True"
          name: "trial_only"
      on_failure: "skip"
      context:
        has_premium: "${check_conditions.has_premium}"
        has_trial: "${check_conditions.has_trial}"

  - name: handle_premium
    dependencies: [validate_premium_only]
    # Runs if user has premium but not trial

  - name: handle_trial
    dependencies: [validate_trial_only]
    # Runs if user has trial but not premium
```

## Important Concepts

### Context Resolution

The `context` values are resolved BEFORE the validation task runs:

```yaml
context:
  payment_type: "${get_payment_info.payment_type}"  # Becomes actual value like "paypal"
```

The validation handler receives:
```python
{
  'payment_type': 'paypal'  # Already resolved
}
```

### Variable Names Must Match

The keys in `context` must match the variable names in expressions:

```yaml
# CORRECT
conditions:
  - expression: "payment_type == 'credit_card'"  # Uses 'payment_type'
context:
  payment_type: "${previous.payment_type}"  # Key is 'payment_type'

# WRONG
conditions:
  - expression: "payment_type == 'credit_card'"  # Uses 'payment_type'
context:
  type: "${previous.payment_type}"  # Key is 'type' - won't work!
```

### Skip Propagation

When a validation fails with `on_failure: "skip"`:
1. The validation task itself completes successfully
2. Tasks depending on it are marked as SKIPPED
3. Skipped tasks don't block downstream execution
4. Tasks can depend on multiple paths - skipped ones are ignored

## Patterns Enabled

### Switch Statement

```yaml
# Multiple exclusive cases
- name: validate_case_a
  params:
    conditions:
      - expression: "value == 'A'"

- name: validate_case_b
  params:
    conditions:
      - expression: "value == 'B'"

- name: validate_case_c
  params:
    conditions:
      - expression: "value == 'C'"

- name: validate_default
  params:
    conditions:
      - expression: "value not in ['A', 'B', 'C']"
```

### If-Then-Else

```yaml
# Binary choice
- name: validate_if
  params:
    conditions:
      - expression: "score >= 80"

- name: validate_else
  params:
    conditions:
      - expression: "score < 80"

- name: then_branch
  dependencies: [validate_if]

- name: else_branch
  dependencies: [validate_else]
```

### Multi-Way Branching

```yaml
# Complex routing logic
- name: validate_route_1
  params:
    conditions:
      - expression: "region == 'US' and premium == True"

- name: validate_route_2
  params:
    conditions:
      - expression: "region == 'EU' or (region == 'US' and premium == False)"

- name: validate_route_3
  params:
    conditions:
      - expression: "region not in ['US', 'EU']"
```

## Testing XOR Patterns

The test file `test_xor_simple.py` demonstrates that XOR patterns work correctly:

```python
# Test results show exactly one validation passes:
Results: [False, True, False]  # [credit_card, paypal, crypto]
Passed count: 1
✅ XOR satisfied - exactly one validation passed!

# In workflow execution:
- process_credit_card: SKIPPED
- process_paypal: RUNS
- process_crypto: SKIPPED
```

## Best Practices

1. **Ensure Mutual Exclusivity**: Design conditions so exactly one can be true
2. **Cover All Cases**: Include a default/catch-all validation if needed
3. **Use Descriptive Names**: Name validations clearly (e.g., `validate_premium_path`)
4. **Test All Paths**: Verify each condition triggers the correct path
5. **Keep Context Simple**: Pass only needed values to reduce complexity

## Performance Considerations

- Validations run in parallel when they have the same dependencies
- Validation results are cached in Redis
- Skipped tasks have minimal overhead
- The pattern scales well with many paths

## Limitations

- Conditions must be deterministic (same input = same output)
- All paths evaluate even if one already matched (no short-circuit)
- Complex conditions may be hard to debug

## Conclusion

XOR patterns are fully supported using validation tasks with `on_failure: "skip"`. This enables sophisticated control flow while maintaining Gleitzeit's simple task-based model. The pattern is clean, observable, and scales well for complex workflows.