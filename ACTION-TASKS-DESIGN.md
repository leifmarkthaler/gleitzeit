# Action Tasks: fail, skip, split as Task Types

## The Insight

Instead of adding fields to tasks, create **action tasks** that control workflow flow!

## Core Concept: Control Flow Tasks

```yaml
tasks:
  # Regular task
  - id: "validate_data"
    protocol: "validator/v1"
    method: "validate"
    params:
      data: "${input}"
  
  # SKIP TASK - Controls which tasks to skip
  - id: "skip_premium_if_not_eligible"
    protocol: "skip/v1"  # This is a skip control task!
    method: "evaluate"
    params:
      condition: "${validate_data.user_tier} != 'premium'"
      skip_tasks: ["premium_feature_1", "premium_feature_2", "premium_discount"]
    dependencies: ["validate_data"]
  
  # These tasks will be skipped if condition is true
  - id: "premium_feature_1"
    protocol: "feature/v1"
    method: "activate"
    dependencies: ["skip_premium_if_not_eligible"]  # The skip task must run first
  
  - id: "premium_feature_2"
    protocol: "feature/v1"
    method: "enable"
    dependencies: ["skip_premium_if_not_eligible"]
```

## The Three Control Flow Protocols

### 1. FAIL Protocol - Workflow Termination

```yaml
tasks:
  - id: "check_critical_requirement"
    protocol: "validator/v1"
    method: "validate_critical"
    params:
      data: "${input}"
  
  # FAIL TASK - Stops workflow if condition met
  - id: "fail_if_invalid"
    protocol: "fail/v1"
    method: "evaluate"
    params:
      condition: "${check_critical_requirement.valid} == false"
      error_message: "Critical validation failed: ${check_critical_requirement.errors}"
    dependencies: ["check_critical_requirement"]
  
  # This won't run if fail task triggers
  - id: "continue_processing"
    protocol: "processor/v1"
    method: "process"
    dependencies: ["fail_if_invalid"]
```

### 2. SKIP Protocol - Conditional Execution

```yaml
tasks:
  - id: "check_age"
    protocol: "validator/v1"
    method: "validate_age"
    params:
      age: "${user.age}"
  
  # SKIP TASK - Marks tasks to skip
  - id: "skip_adult_content"
    protocol: "skip/v1"
    method: "evaluate"
    params:
      condition: "${check_age.result} < 18"
      skip_tasks: ["adult_content", "mature_ads", "alcohol_offers"]
    dependencies: ["check_age"]
  
  - id: "adult_content"
    protocol: "content/v1"
    method: "serve_adult"
    dependencies: ["skip_adult_content"]
  
  - id: "general_content"
    protocol: "content/v1"
    method: "serve_general"
    dependencies: ["check_age"]  # Always runs
```

### 3. SPLIT Protocol - Dynamic Branching

```yaml
tasks:
  - id: "analyze_document"
    protocol: "llm/v1"
    method: "classify"
    params:
      prompt: "Classify this document type"
      document: "${input.text}"
  
  # SPLIT TASK - Determines which branch to activate
  - id: "route_document"
    protocol: "split/v1"
    method: "route"
    params:
      switch_on: "${analyze_document.document_type}"
      routes:
        invoice: ["process_invoice", "update_accounting", "send_receipt"]
        contract: ["legal_review", "store_contract", "notify_legal"]
        receipt: ["expense_tracking", "reimburse"]
        default: ["manual_review", "notify_admin"]
    dependencies: ["analyze_document"]
  
  # Branch tasks - only those selected by split will run
  - id: "process_invoice"
    protocol: "accounting/v1"
    method: "process_invoice"
    dependencies: ["route_document"]
    branch: "invoice"  # Metadata to indicate branch
  
  - id: "legal_review"
    protocol: "legal/v1"
    method: "review"
    dependencies: ["route_document"]
    branch: "contract"
  
  - id: "manual_review"
    protocol: "manual/v1"
    method: "queue"
    dependencies: ["route_document"]
    branch: "default"
```

## Implementation: Action Task Providers

```python
class SkipProvider:
    """Provider for skip/v1 protocol"""
    
    async def evaluate(self, condition: str, skip_tasks: List[str], context: Dict) -> Dict:
        """Evaluate condition and mark tasks to skip"""
        
        # Evaluate the condition
        should_skip = await self.evaluate_expression(condition, context)
        
        if should_skip:
            # Mark tasks in context as skipped
            for task_id in skip_tasks:
                await self.mark_task_skipped(task_id, f"Skipped by condition: {condition}")
            
            return {
                "skipped": True,
                "skipped_tasks": skip_tasks,
                "reason": condition
            }
        
        return {
            "skipped": False,
            "skipped_tasks": []
        }

class FailProvider:
    """Provider for fail/v1 protocol"""
    
    async def evaluate(self, condition: str, error_message: str, context: Dict) -> Dict:
        """Evaluate condition and fail workflow if true"""
        
        should_fail = await self.evaluate_expression(condition, context)
        
        if should_fail:
            # Fail the entire workflow
            raise WorkflowFailure(error_message)
        
        return {
            "passed": True
        }

class SplitProvider:
    """Provider for split/v1 protocol"""
    
    async def route(self, switch_on: str, routes: Dict[str, List[str]], context: Dict) -> Dict:
        """Determine which branch to activate"""
        
        # Get the value to switch on
        switch_value = await self.resolve_value(switch_on, context)
        
        # Find matching route
        selected_tasks = routes.get(switch_value, routes.get("default", []))
        
        # Mark all other tasks as skipped
        all_tasks = set()
        for task_list in routes.values():
            all_tasks.update(task_list)
        
        skipped_tasks = all_tasks - set(selected_tasks)
        
        for task_id in skipped_tasks:
            await self.mark_task_skipped(task_id, f"Not in selected branch: {switch_value}")
        
        return {
            "selected_branch": switch_value,
            "active_tasks": selected_tasks,
            "skipped_tasks": list(skipped_tasks)
        }
```

## Advanced Patterns

### Pattern 1: Multi-Condition Skip

```yaml
tasks:
  # Multiple skip conditions
  - id: "skip_based_on_tier"
    protocol: "skip/v1"
    method: "evaluate"
    params:
      condition: "${user.tier} == 'free'"
      skip_tasks: ["premium_features", "priority_support"]
  
  - id: "skip_based_on_region"
    protocol: "skip/v1"
    method: "evaluate"
    params:
      condition: "${user.region} != 'US'"
      skip_tasks: ["us_only_feature", "state_tax_calculation"]
  
  # Task needs both skip checks to pass
  - id: "premium_features"
    dependencies: ["skip_based_on_tier", "skip_based_on_region"]
```

### Pattern 2: Nested Splits

```yaml
tasks:
  # First level split
  - id: "route_by_type"
    protocol: "split/v1"
    method: "route"
    params:
      switch_on: "${input.type}"
      routes:
        customer: ["customer_flow_start"]
        vendor: ["vendor_flow_start"]
        employee: ["employee_flow_start"]
  
  # Second level split (within customer flow)
  - id: "route_by_tier"
    protocol: "split/v1"
    method: "route"
    params:
      switch_on: "${customer.tier}"
      routes:
        vip: ["vip_treatment"]
        regular: ["standard_treatment"]
    dependencies: ["customer_flow_start"]
```

### Pattern 3: Fail with Cleanup

```yaml
tasks:
  - id: "allocate_resources"
    protocol: "resource/v1"
    method: "allocate"
  
  - id: "process"
    protocol: "processor/v1"
    method: "process"
    dependencies: ["allocate_resources"]
  
  # Fail task with cleanup
  - id: "fail_if_error"
    protocol: "fail/v1"
    method: "evaluate_with_cleanup"
    params:
      condition: "${process.error} != null"
      error_message: "Processing failed: ${process.error}"
      cleanup_tasks: ["deallocate_resources"]  # Run these before failing
    dependencies: ["process"]
  
  - id: "deallocate_resources"
    protocol: "resource/v1"
    method: "deallocate"
    dependencies: ["fail_if_error"]
```

## Why This is Clean

### 1. **Everything is a Task**
- No special fields or complex conditions
- Control flow is just another task type
- Full observability - skip/fail/split show in logs

### 2. **Composable**
```yaml
# Chain control tasks
validate → skip_invalid → fail_critical → split_by_type → process
```

### 3. **Explicit Dependencies**
```yaml
# Clear that skip task must run before
- id: "premium_feature"
  dependencies: ["skip_if_not_premium"]
```

### 4. **Testable**
```python
# Control tasks are just tasks - test them normally
async def test_skip_task():
    task = Task(
        protocol="skip/v1",
        method="evaluate",
        params={
            "condition": "true",
            "skip_tasks": ["task1", "task2"]
        }
    )
    result = await executor.execute(task)
    assert result["skipped"] == True
```

## Real-World Example: LLM Content Pipeline

```yaml
tasks:
  # Generate content
  - id: "generate"
    protocol: "llm/v1"
    method: "generate"
    params:
      prompt: "Write article about ${topic}"
  
  # Check for issues
  - id: "check_toxicity"
    protocol: "validator/v1"
    method: "toxicity_check"
    dependencies: ["generate"]
  
  # FAIL if toxic
  - id: "fail_if_toxic"
    protocol: "fail/v1"
    method: "evaluate"
    params:
      condition: "${check_toxicity.score} > 0.7"
      error_message: "Content too toxic: score ${check_toxicity.score}"
    dependencies: ["check_toxicity"]
  
  # Check length
  - id: "check_length"
    protocol: "validator/v1"
    method: "length_check"
    dependencies: ["fail_if_toxic"]
  
  # SKIP if too short
  - id: "skip_if_short"
    protocol: "skip/v1"
    method: "evaluate"
    params:
      condition: "${check_length.word_count} < 100"
      skip_tasks: ["add_images", "format_article", "add_citations"]
    dependencies: ["check_length"]
  
  # SPLIT by quality
  - id: "route_by_quality"
    protocol: "split/v1"
    method: "route"
    params:
      switch_on: "${check_length.quality_tier}"
      routes:
        high: ["publish_immediately"]
        medium: ["human_review", "publish_after_review"]
        low: ["regenerate", "review_regenerated"]
    dependencies: ["skip_if_short"]
  
  # ... rest of tasks
```

## Execution Flow

```python
class TaskExecutor:
    async def execute_task(self, task: Task, context: Dict):
        """Execute task based on protocol"""
        
        # Check if this task was marked as skipped
        if context.get(f"{task.id}.skipped"):
            task.status = TaskStatus.SKIPPED
            return
        
        # Execute based on protocol
        if task.protocol == "skip/v1":
            result = await self.skip_provider.evaluate(task.params, context)
            # Mark tasks to skip in context
            for skip_id in result.get("skipped_tasks", []):
                context[f"{skip_id}.skipped"] = True
                
        elif task.protocol == "fail/v1":
            result = await self.fail_provider.evaluate(task.params, context)
            # Will raise exception if condition met
            
        elif task.protocol == "split/v1":
            result = await self.split_provider.route(task.params, context)
            # Mark non-selected tasks as skipped
            for skip_id in result.get("skipped_tasks", []):
                context[f"{skip_id}.skipped"] = True
        
        else:
            # Normal task execution
            result = await self.providers[task.protocol].execute(task)
        
        return result
```

## Conclusion

Using `fail`, `skip`, and `split` as **task protocols** gives us:

1. **Consistency** - Everything is a task
2. **Clarity** - Control flow is explicit in the workflow
3. **Power** - Full conditional execution without new concepts
4. **Observability** - Control tasks appear in logs/metrics
5. **Testability** - Control flow can be unit tested

This is the ultimate expression of "simple primitives, powerful composition" - workflow control flow is just another type of task!