# Conditionals & Validators Design for Gleitzeit

## Overview

Adding conditionals and validators would enable dynamic workflows that adapt based on results and ensure data quality throughout execution. Our event-driven architecture and pause-rewind capability make this particularly powerful.

## 1. Conditionals (Dynamic Workflow Branching)

### Core Concept
Tasks can define conditions that determine:
- Whether they execute
- Which tasks execute next
- Whether to continue or halt the workflow

### Design Approaches

#### Approach A: Declarative Conditions in Task Definition
```yaml
name: "Dynamic Customer Support Workflow"
tasks:
  - id: "analyze_sentiment"
    method: "llm/analyze"
    params:
      prompt: "Analyze sentiment: ${input.message}"
      model: "gpt-3.5-turbo"
  
  - id: "escalate_to_human"
    method: "notify/email"
    params:
      to: "support-urgent@company.com"
      message: "Angry customer needs help: ${input.message}"
    conditions:
      # Only execute if sentiment is negative
      - field: "${analyze_sentiment.sentiment}"
        operator: "equals"
        value: "negative"
      - field: "${analyze_sentiment.confidence}"
        operator: "greater_than"
        value: 0.8
    
  - id: "auto_respond"
    method: "llm/generate"
    params:
      prompt: "Generate friendly response to: ${input.message}"
    conditions:
      # Only if sentiment is positive/neutral
      - field: "${analyze_sentiment.sentiment}"
        operator: "in"
        value: ["positive", "neutral"]
```

#### Approach B: Conditional Task Groups
```python
# Task groups that execute based on conditions
workflow = Workflow(
    name="Conditional Workflow",
    tasks=[
        Task(id="evaluate", method="python/eval", params={"code": "..."}),
    ],
    conditional_groups=[
        ConditionalGroup(
            condition="${evaluate.result} > 100",
            tasks=[
                Task(id="high_value_path_1", ...),
                Task(id="high_value_path_2", ...)
            ]
        ),
        ConditionalGroup(
            condition="${evaluate.result} <= 100",
            tasks=[
                Task(id="low_value_path_1", ...),
                Task(id="low_value_path_2", ...)
            ]
        )
    ]
)
```

#### Approach C: Switch/Case Pattern
```yaml
tasks:
  - id: "categorize"
    method: "llm/classify"
    params:
      categories: ["technical", "billing", "general"]
      text: "${input.message}"
  
  - id: "router"
    type: "switch"
    switch_on: "${categorize.category}"
    cases:
      technical:
        tasks:
          - id: "tech_support"
            method: "route/technical"
      billing:
        tasks:
          - id: "billing_support"
            method: "route/billing"
      default:
        tasks:
          - id: "general_support"
            method: "route/general"
```

#### Approach D: Dynamic Task Generation
```python
class DynamicTaskConditional:
    """Generate tasks based on runtime conditions"""
    
    async def evaluate_and_generate_tasks(self, workflow: Workflow, context: Dict):
        """Dynamically create tasks based on current state"""
        
        # Evaluate current state
        if context.get("customer_value") > 1000:
            # High-value customer gets premium treatment
            new_tasks = [
                Task(id="assign_senior_agent", ...),
                Task(id="priority_queue", ...),
                Task(id="send_gift", ...)
            ]
        else:
            # Standard flow
            new_tasks = [
                Task(id="standard_queue", ...)
            ]
        
        # Inject into workflow
        await self.inject_tasks(workflow, new_tasks, after_task="current")
```

### Integration with Our Architecture

```python
class ConditionalExecutor:
    """Fits into our ExecutionEngine"""
    
    async def should_execute_task(self, task: Task, workflow_context: Dict) -> bool:
        """Evaluate if task should execute"""
        
        if not task.conditions:
            return True
        
        for condition in task.conditions:
            # Resolve references like ${other_task.field}
            actual_value = await self.parameter_resolver.resolve(
                condition.field, 
                workflow_context
            )
            
            # Evaluate condition
            if not self.evaluate_condition(actual_value, condition.operator, condition.value):
                # Log skip event
                await self.event_bus.emit(
                    "task.skipped",
                    {"task_id": task.id, "condition": condition}
                )
                return False
        
        return True
    
    def evaluate_condition(self, actual, operator: str, expected) -> bool:
        """Evaluate a single condition"""
        operators = {
            "equals": lambda a, e: a == e,
            "not_equals": lambda a, e: a != e,
            "greater_than": lambda a, e: a > e,
            "less_than": lambda a, e: a < e,
            "contains": lambda a, e: e in a,
            "matches_regex": lambda a, e: bool(re.match(e, str(a))),
            "in": lambda a, e: a in e,
            "not_in": lambda a, e: a not in e,
            "exists": lambda a, e: a is not None,
            "is_empty": lambda a, e: not a
        }
        return operators.get(operator, lambda a, e: False)(actual, expected)
```

## 2. Validators (Data Quality & Safety)

### Core Concept
Validators ensure:
- Input data meets requirements before task execution
- Output data is valid before proceeding
- Workflow state is consistent

### Types of Validators

#### A. Input Validators
```yaml
tasks:
  - id: "process_payment"
    method: "payment/charge"
    params:
      amount: "${order.total}"
      card: "${customer.card}"
    validators:
      input:
        - type: "range"
          field: "amount"
          min: 0.01
          max: 10000
          error: "Payment amount must be between $0.01 and $10,000"
        
        - type: "regex"
          field: "card"
          pattern: "^[0-9]{13,19}$"
          error: "Invalid card number format"
        
        - type: "custom"
          function: "validate_card_checksum"
          field: "card"
          error: "Invalid card number (checksum failed)"
```

#### B. Output Validators
```yaml
tasks:
  - id: "generate_summary"
    method: "llm/summarize"
    params:
      text: "${document.content}"
      max_length: 500
    validators:
      output:
        - type: "length"
          field: "summary"
          max: 500
          error: "Summary exceeds maximum length"
        
        - type: "llm_validate"
          prompt: "Does this summary contain any PII? ${result.summary}"
          expected: "no"
          error: "Summary contains PII"
        
        - type: "similarity"
          field: "summary"
          compare_to: "${document.content}"
          min_similarity: 0.3  # Must be somewhat related
          error: "Summary doesn't match source document"
```

#### C. Schema Validators
```python
class SchemaValidator:
    """Validate complex data structures"""
    
    schema = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "pattern": "^CUS-[0-9]+$"},
            "order_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "price": {"type": "number", "minimum": 0}
                    },
                    "required": ["sku", "quantity", "price"]
                }
            },
            "total": {"type": "number", "minimum": 0}
        },
        "required": ["customer_id", "order_items", "total"]
    }
    
    async def validate(self, data: Any) -> ValidationResult:
        """Validate against JSON schema"""
        try:
            jsonschema.validate(data, self.schema)
            return ValidationResult(valid=True)
        except jsonschema.ValidationError as e:
            return ValidationResult(
                valid=False,
                errors=[str(e)],
                path=e.path
            )
```

#### D. Business Logic Validators
```python
class BusinessRuleValidator:
    """Complex business rule validation"""
    
    async def validate_order(self, order: Dict) -> ValidationResult:
        """Validate order meets business rules"""
        errors = []
        
        # Rule 1: High-value orders need approval
        if order["total"] > 5000 and not order.get("approved_by"):
            errors.append("Orders over $5000 require manager approval")
        
        # Rule 2: Check inventory
        for item in order["items"]:
            stock = await self.check_inventory(item["sku"])
            if stock < item["quantity"]:
                errors.append(f"Insufficient stock for {item['sku']}")
        
        # Rule 3: Credit check for payment terms
        if order.get("payment_terms") == "NET30":
            credit_ok = await self.check_credit(order["customer_id"])
            if not credit_ok:
                errors.append("Customer not approved for NET30 terms")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors
        )
```

### Validator Integration Points

#### 1. Pre-Execution Validation
```python
class TaskExecutor:
    """Enhanced with validation"""
    
    async def execute_task(self, task: Task) -> TaskResult:
        """Execute with validation gates"""
        
        # Input validation
        if task.validators and task.validators.input:
            validation = await self.validate_inputs(task)
            if not validation.valid:
                # Emit validation failure event
                await self.event_bus.emit("task.validation_failed", {
                    "task_id": task.id,
                    "errors": validation.errors,
                    "phase": "input"
                })
                
                # Options for handling failure:
                if task.validation_policy == "strict":
                    raise ValidationError(validation.errors)
                elif task.validation_policy == "pause":
                    await self.pause_workflow(task.workflow_id, 
                        reason=f"Validation failed: {validation.errors}")
                elif task.validation_policy == "skip":
                    return TaskResult(status="skipped", reason="validation_failed")
        
        # Execute task
        result = await self._execute(task)
        
        # Output validation
        if task.validators and task.validators.output:
            validation = await self.validate_outputs(task, result)
            if not validation.valid:
                # Handle output validation failure
                await self.handle_output_validation_failure(task, result, validation)
        
        return result
```

#### 2. Progressive Validation
```python
class ProgressiveValidator:
    """Validate as workflow progresses"""
    
    async def validate_workflow_state(self, workflow: Workflow, after_task: str):
        """Validate workflow invariants after each task"""
        
        # Check workflow-level constraints
        constraints = workflow.metadata.get("constraints", [])
        
        for constraint in constraints:
            if constraint["type"] == "budget":
                total_cost = await self.calculate_total_cost(workflow)
                if total_cost > constraint["max_value"]:
                    await self.pause_workflow(
                        workflow.id,
                        reason=f"Budget exceeded: ${total_cost}"
                    )
            
            elif constraint["type"] == "time":
                elapsed = datetime.now() - workflow.started_at
                if elapsed > constraint["max_duration"]:
                    await self.handle_timeout(workflow)
            
            elif constraint["type"] == "quality":
                avg_quality = await self.calculate_avg_quality(workflow)
                if avg_quality < constraint["min_threshold"]:
                    # Trigger rewind to improve quality
                    await self.pause_workflow_with_rewind(
                        workflow.id,
                        rewind_to_task=constraint["rewind_to"],
                        reason="Quality threshold not met"
                    )
```

## 3. Integration with Pause-Rewind

### Validation-Triggered Rewind
```python
class ValidationRewindHandler:
    """Use rewind to fix validation failures"""
    
    async def handle_validation_failure(self, task: Task, validation: ValidationResult):
        """Smart handling of validation failures"""
        
        if validation.is_recoverable():
            # Try to fix and rewind
            fix_task = await self.generate_fix_task(validation)
            
            # Insert fix task before the failed task
            await self.inject_task(fix_task, before=task.id)
            
            # Rewind to fix task
            await self.pause_workflow_with_rewind(
                task.workflow_id,
                rewind_to_task=fix_task.id,
                reason=f"Auto-fixing: {validation.errors[0]}"
            )
            
            # Auto-resume after fix
            await asyncio.sleep(1)
            await self.resume_workflow(task.workflow_id)
```

## 4. Conditional + Validator Combinations

### Example: LLM Output Validation with Conditional Retry
```yaml
tasks:
  - id: "generate_content"
    method: "llm/generate"
    params:
      prompt: "Write a product description"
      model: "gpt-4"
    validators:
      output:
        - type: "length"
          min: 100
          max: 500
        - type: "no_hallucination"
          fact_check: true
    retry_on_validation_failure:
      max_attempts: 3
      with_conditions:
        - if: "attempt == 2"
          then:
            modify_params:
              temperature: 0.5  # Lower temperature
        - if: "attempt == 3"
          then:
            modify_params:
              model: "gpt-4-turbo"  # Try different model
```

## 5. Implementation Strategy

### Phase 1: Simple Conditionals
- Basic operators (equals, greater_than, etc.)
- Skip task execution based on conditions
- Simple if/then branching

### Phase 2: Input/Output Validators
- Schema validation
- Range/format checks
- Pre/post execution validation

### Phase 3: Advanced Features
- Dynamic task generation
- Complex business rules
- Validation-triggered rewind
- Progressive validation

### Phase 4: LLM-Specific
- Hallucination detection
- Output quality validation
- Cost-based conditions
- Token limit validation

## Benefits for Our Architecture

1. **Event-Driven**: Every condition check and validation emits events for observability
2. **Pause-Rewind**: Failed validations can trigger automatic rewind to fix issues
3. **Redis Streams**: Store validation history for audit and learning
4. **Multi-Protocol**: Different validators for different task types (LLM vs Python vs Shell)
5. **SystemManager**: Centralized validation rules management

## Example Use Cases

### 1. Customer Support Workflow
```yaml
# Route based on sentiment and value
conditions:
  - if: sentiment == "angry" AND customer_value > 1000
    then: escalate_to_senior
  - elif: sentiment == "angry"
    then: escalate_to_support
  - else: auto_respond
```

### 2. Data Processing Pipeline
```yaml
# Validate data quality at each step
validators:
  - stage: "after_extraction"
    check: "row_count > 0"
    on_fail: "pause"
  - stage: "after_transformation"
    check: "no_null_values"
    on_fail: "rewind_to_extraction"
```

### 3. LLM Content Generation
```yaml
# Ensure quality and safety
validators:
  - type: "toxicity"
    max_score: 0.1
  - type: "relevance"
    min_score: 0.8
  - type: "factual_accuracy"
    check_against: "knowledge_base"
```

## Conclusion

Conditionals and validators would transform Gleitzeit from a workflow orchestrator into an intelligent, self-healing system. The combination with pause-rewind makes it uniquely powerful - workflows can automatically detect problems, rewind, and fix themselves.

This would be a killer feature for enterprise LLM workflows where quality and safety are critical.