# Validation Behavior Guide

## Overview

Validation tasks control downstream task execution through the `on_failure` parameter. There are three behaviors when validation returns `valid: false`:

1. **`skip`** - Task doesn't run (wasn't needed)
2. **`fail`** - Task can't run (critical failure)
3. **`block`** - Task is blocked (waiting/prevented)

## Behavior Definitions

### Skip (Default)
- **Status**: `SKIPPED`
- **Meaning**: Task was optional and conditions weren't met
- **Workflow Impact**: Continues normally, task is just skipped
- **Use When**: Task is conditional/optional

### Fail
- **Status**: `FAILED`
- **Meaning**: Task was required but can't proceed
- **Workflow Impact**: Can cause workflow failure
- **Use When**: Critical validations, mandatory requirements

### Block
- **Status**: `BLOCKED`
- **Meaning**: Task is prevented from running (unrecoverable)
- **Workflow Impact**: Causes workflow to FAIL (like failed tasks)
- **Use When**: Gate control failed, manual intervention would be needed

## Configuration

Set `on_failure` in the validation task:

```yaml
# Skip behavior (default)
- name: validate_optional
  protocol: validation/v1
  method: validation/evaluate
  params:
    conditions:
      - expression: "user_type == 'premium'"
    on_failure: "skip"  # Optional features skipped for basic users

# Fail behavior
- name: validate_critical
  protocol: validation/v1
  method: validation/evaluate
  params:
    conditions:
      - expression: "auth_token is not None"
    on_failure: "fail"  # Security requirement - must pass

# Block behavior
- name: validate_gate
  protocol: validation/v1
  method: validation/evaluate
  params:
    conditions:
      - expression: "approval_received == true"
    on_failure: "block"  # Wait for approval
```

## Examples

### Example 1: Skip Optional Processing

```yaml
tasks:
  - name: check_premium_features
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "subscription == 'premium'"
      on_failure: "skip"
      context:
        subscription: "${user.subscription}"

  - name: advanced_analytics
    dependencies: [check_premium_features]
    # SKIPPED for basic users, runs for premium users
    protocol: python/v1
    method: python/execute
```

### Example 2: Fail on Security Violation

```yaml
tasks:
  - name: security_check
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "api_key is not None"
        - expression: "api_key_valid == true"
      mode: "all"
      on_failure: "fail"

  - name: access_api
    dependencies: [security_check]
    # FAILED if security check fails - workflow stops
    protocol: http/v1
    method: post
```

### Example 3: Block Until Approval

```yaml
tasks:
  - name: approval_gate
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "manager_approved == true"
      on_failure: "block"

  - name: execute_transaction
    dependencies: [approval_gate]
    # BLOCKED until approval received
    protocol: python/v1
    method: python/execute
```

## Workflow Status Impact

Different behaviors affect overall workflow status differently:

```
Scenario 1: Tasks with "skip"
├── validate_optional (valid=false)
└── optional_task (SKIPPED)
Workflow Status: COMPLETED (with skips)

Scenario 2: Tasks with "fail"
├── validate_critical (valid=false)
└── critical_task (FAILED)
Workflow Status: FAILED

Scenario 3: Tasks with "block"
├── validate_gate (valid=false)
└── gated_task (BLOCKED)
Workflow Status: FAILED (has blocked tasks)
```

## Decision Guide

### Use SKIP when:
- ✅ Feature flags / A/B testing
- ✅ Optional enhancements
- ✅ Conditional branches
- ✅ Graceful degradation

### Use FAIL when:
- ❌ Security requirements
- ❌ Data integrity checks
- ❌ Critical preconditions
- ❌ Compliance validation

### Use BLOCK when:
- 🚫 Gate check failed permanently
- 🚫 Access denied (no retry possible)
- 🚫 Quota exceeded (won't reset in workflow)
- 🚫 Feature not available

## Best Practices

1. **Default to skip** for most conditional logic
2. **Use fail sparingly** - only for critical failures
3. **Use block** for external dependencies
4. **Document your choice** in task description
5. **Test all paths** - valid and invalid cases

## Key Differences

| Behavior | Status | Recoverable | Workflow Result | Use Case |
|----------|--------|-------------|-----------------|----------|
| **skip** | SKIPPED | N/A | Continues normally | Optional tasks |
| **fail** | FAILED | Via retry | Fails | Critical requirements |
| **block** | BLOCKED | No | Fails | Permanent gates |

## Implementation Notes

- The `on_failure` parameter is set on the validation task
- It applies to ALL tasks that depend on that validation
- There is no per-task override (keeps it simple)
- Default behavior is `skip` if not specified