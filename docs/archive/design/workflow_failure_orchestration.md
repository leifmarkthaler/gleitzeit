# Workflow Failure Orchestration Design

## Overview

Add workflow-level failure configuration to provide centralized control over how workflows handle failures, including global retry policies, failure thresholds, and recovery strategies.

## Problem Statement

Currently:
- Each task has independent retry configuration
- No workflow-wide failure policies
- No coordinated failure response
- No global timeout or failure limits
- No automatic cleanup or compensation

## Proposed Solution

### 1. Workflow Failure Configuration

Add a `failure_policy` section to workflow definitions:

```yaml
name: payment-processing
failure_policy:
  # Global failure handling
  max_task_failures: 3        # Fail workflow after N task failures
  failure_mode: "fast_fail"    # fast_fail | continue_all | stop_on_critical
  global_timeout: 3600         # Workflow timeout in seconds

  # Retry defaults (can be overridden per-task)
  default_retry:
    max_attempts: 3
    backoff_strategy: "exponential"
    base_delay: 1.0
    max_delay: 300.0

  # Circuit breaker configuration
  circuit_breaker:
    enabled: true
    failure_threshold: 5      # Open circuit after N failures
    timeout: 60               # Circuit reset timeout
    half_open_tests: 2        # Test requests in half-open state

  # Recovery actions
  on_failure:
    cleanup_tasks: ["cleanup_payments", "notify_failure"]
    notifications:
      - type: "webhook"
        url: "${FAILURE_WEBHOOK_URL}"
      - type: "event"
        stream: "workflow:failures:critical"

  # Task criticality
  critical_tasks: ["charge_payment", "update_inventory"]
  optional_tasks: ["send_email", "update_analytics"]

tasks:
  - id: charge_payment
    method: "payment/charge"
    params:
      amount: 100
    # Task-specific override
    retry:
      max_attempts: 5  # Override workflow default

  - id: cleanup_payments
    method: "payment/cleanup"
    params:
      reverse: true
    # Only runs on failure
    when: "on_failure"
```

### 2. Implementation Architecture

```python
# src/gleitzeit/core/failure_orchestrator.py

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from enum import Enum

class FailureMode(Enum):
    FAST_FAIL = "fast_fail"        # Fail immediately on first task failure
    CONTINUE_ALL = "continue_all"   # Continue all possible tasks
    STOP_ON_CRITICAL = "stop_on_critical"  # Only fail on critical tasks

@dataclass
class WorkflowFailurePolicy:
    """Workflow-level failure configuration"""
    max_task_failures: int = 3
    failure_mode: FailureMode = FailureMode.FAST_FAIL
    global_timeout: Optional[int] = None
    default_retry: Optional[RetryConfig] = None
    circuit_breaker: Optional[CircuitBreakerConfig] = None
    cleanup_tasks: List[str] = None
    critical_tasks: Set[str] = None
    optional_tasks: Set[str] = None

    def should_fail_workflow(self, failed_tasks: Set[str],
                            task_statuses: Dict[str, str]) -> bool:
        """Determine if workflow should fail based on policy"""

        if self.failure_mode == FailureMode.FAST_FAIL:
            return len(failed_tasks) > 0

        elif self.failure_mode == FailureMode.CONTINUE_ALL:
            return len(failed_tasks) >= self.max_task_failures

        elif self.failure_mode == FailureMode.STOP_ON_CRITICAL:
            critical_failures = failed_tasks & self.critical_tasks
            return len(critical_failures) > 0

        return False

    def get_task_retry_config(self, task_id: str,
                             task_config: Optional[RetryConfig]) -> RetryConfig:
        """Get retry config for task (task-specific or default)"""
        return task_config or self.default_retry or RetryConfig()
```

### 3. Workflow Failure Orchestrator Worker

Create a new worker to monitor and orchestrate workflow failures:

```python
# src/gleitzeit/workers/failure_orchestrator_worker.py

class FailureOrchestratorWorker(BaseWorker):
    """
    Monitors workflow execution and enforces failure policies
    """

    def get_base_streams(self) -> List[str]:
        return ["task:failed", "workflow:timeout:check"]

    async def process_message(self, stream: str, message_id: str, data: Dict):
        if stream == "task:failed":
            await self.handle_task_failure(data)
        elif stream == "workflow:timeout:check":
            await self.check_workflow_timeouts()

    async def handle_task_failure(self, data: Dict):
        workflow_id = data['workflow_id']
        task_id = data['task_id']

        # Get workflow failure policy
        policy = await self.get_workflow_policy(workflow_id)

        # Get current failure state
        failed_tasks = await self.get_failed_tasks(workflow_id)
        task_statuses = await self.get_task_statuses(workflow_id)

        # Check if we should fail the workflow
        if policy.should_fail_workflow(failed_tasks, task_statuses):
            await self.fail_workflow(workflow_id, policy)

        # Check circuit breaker
        if policy.circuit_breaker:
            await self.update_circuit_breaker(task_id, workflow_id)

    async def fail_workflow(self, workflow_id: str,
                           policy: WorkflowFailurePolicy):
        """Execute workflow failure actions"""

        # 1. Mark workflow as failing
        await self.redis.hset(
            f"workflow:status:{workflow_id}",
            "status", "failing"
        )

        # 2. Cancel pending tasks (based on policy)
        if policy.failure_mode == FailureMode.FAST_FAIL:
            await self.cancel_pending_tasks(workflow_id)

        # 3. Execute cleanup tasks
        if policy.cleanup_tasks:
            await self.execute_cleanup_tasks(workflow_id, policy.cleanup_tasks)

        # 4. Send notifications
        await self.send_failure_notifications(workflow_id, policy)

        # 5. Mark workflow as failed
        await self.redis.hset(
            f"workflow:status:{workflow_id}",
            "status", "failed"
        )

    async def execute_cleanup_tasks(self, workflow_id: str,
                                   cleanup_tasks: List[str]):
        """Execute cleanup/compensation tasks"""
        for task_id in cleanup_tasks:
            # Emit cleanup task to execution queue
            await self.redis.xadd(
                f"task:ready:{workflow_id}",
                {
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "is_cleanup": "true",
                    "priority": "high"
                }
            )
```

### 4. Circuit Breaker Implementation

```python
# src/gleitzeit/core/circuit_breaker.py

class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures
    """

    def __init__(self, redis_client, config: CircuitBreakerConfig):
        self.redis = redis_client
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker"""

        # Check circuit state
        state = await self.get_state()

        if state == CircuitState.OPEN:
            # Circuit is open, fail fast
            raise CircuitOpenError("Circuit breaker is open")

        try:
            # Try to execute
            result = await func(*args, **kwargs)

            # Success - update state
            if state == CircuitState.HALF_OPEN:
                await self.on_success_half_open()
            else:
                await self.reset_failure_count()

            return result

        except Exception as e:
            # Failure - update state
            await self.on_failure()
            raise

    async def on_failure(self):
        """Handle execution failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        # Store in Redis
        key = f"circuit:{self.name}:failures"
        await self.redis.incr(key)
        await self.redis.expire(key, self.config.timeout)

        # Check if we should open circuit
        if self.failure_count >= self.config.failure_threshold:
            await self.open_circuit()

    async def open_circuit(self):
        """Open the circuit breaker"""
        self.state = CircuitState.OPEN
        await self.redis.setex(
            f"circuit:{self.name}:state",
            self.config.timeout,
            "open"
        )
        logger.warning(f"Circuit breaker {self.name} opened")
```

### 5. Dead Letter Queue

```python
# src/gleitzeit/core/dead_letter_queue.py

class DeadLetterQueue:
    """
    Store unprocessable tasks for manual inspection
    """

    async def add_task(self, task: Task, error: str,
                       metadata: Dict[str, Any]):
        """Add failed task to DLQ"""

        dlq_entry = {
            "task": task.dict(),
            "error": error,
            "failed_at": datetime.utcnow().isoformat(),
            "attempts": metadata.get("attempts", 1),
            "workflow_id": task.workflow_id,
            "metadata": metadata
        }

        # Store in Redis sorted set (by timestamp)
        await self.redis.zadd(
            "dlq:tasks",
            {json.dumps(dlq_entry): time.time()}
        )

        # Emit DLQ event
        await self.redis.xadd(
            "dlq:events",
            {
                "workflow_id": task.workflow_id,
                "task_id": task.id,
                "error": error,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    async def get_tasks(self, limit: int = 100) -> List[Dict]:
        """Retrieve tasks from DLQ for inspection"""
        entries = await self.redis.zrange("dlq:tasks", 0, limit-1)
        return [json.loads(e) for e in entries]

    async def reprocess_task(self, task_id: str,
                            modifications: Dict[str, Any] = None):
        """Attempt to reprocess a DLQ task"""
        # Get task from DLQ
        # Apply modifications if provided
        # Re-emit to task:ready queue
        # Remove from DLQ if successful
```

## Benefits

### 1. Centralized Control
- Single place to configure failure behavior
- Consistent retry policies across tasks
- Clear workflow-level timeout

### 2. Better Failure Recovery
- Automatic cleanup tasks
- Compensation/rollback support
- Dead letter queue for investigation

### 3. Prevent Cascading Failures
- Circuit breakers for external services
- Fast-fail mode stops wasting resources
- Rate limiting on retries

### 4. Improved Observability
- Workflow-level failure events
- Dead letter queue visibility
- Circuit breaker state monitoring

## Implementation Plan

### Phase 1: Core Failure Policy (Week 1-2)
1. Add `WorkflowFailurePolicy` model
2. Update workflow parser to read failure_policy
3. Create `FailureOrchestratorWorker`
4. Add failure mode logic

### Phase 2: Circuit Breakers (Week 3)
1. Implement `CircuitBreaker` class
2. Integrate with task execution
3. Add circuit breaker monitoring
4. Create reset mechanisms

### Phase 3: Dead Letter Queue (Week 4)
1. Implement `DeadLetterQueue` class
2. Add DLQ CLI commands
3. Create reprocessing logic
4. Add DLQ dashboard

### Phase 4: Cleanup & Compensation (Week 5)
1. Add cleanup task support
2. Implement compensation tracking
3. Create rollback mechanisms
4. Test saga patterns

## Migration Path

### Backward Compatibility
- Workflows without `failure_policy` use current behavior
- Task-specific retry configs still honored
- No breaking changes to existing APIs

### Gradual Adoption
```yaml
# Start simple
failure_policy:
  max_task_failures: 5

# Add more control over time
failure_policy:
  max_task_failures: 5
  failure_mode: "stop_on_critical"
  critical_tasks: ["payment"]

# Full featured
failure_policy:
  # ... complete configuration
```

## Testing Strategy

### Unit Tests
- Policy evaluation logic
- Circuit breaker state transitions
- DLQ operations

### Integration Tests
- End-to-end failure scenarios
- Cleanup task execution
- Circuit breaker with real Redis

### Chaos Testing
- Random task failures
- Network partitions
- Redis failures

## Monitoring & Metrics

### Key Metrics
- Workflow failure rate by policy
- Circuit breaker state changes
- DLQ size and age
- Cleanup task success rate

### Dashboards
- Failure policy effectiveness
- Circuit breaker status
- DLQ inspection UI
- Failure pattern analysis

## Conclusion

This workflow failure orchestration system would give Gleitzeit enterprise-grade failure handling while maintaining its stateless, scalable architecture. The phased implementation allows for gradual adoption and testing.