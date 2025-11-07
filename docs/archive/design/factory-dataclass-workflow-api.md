# Factory + Dataclass Workflow API Design

## Executive Summary

This document proposes a new Python API for Gleitzeit workflows that combines factory methods with dataclasses to provide a simple, type-safe, and flexible interface for workflow definition. This approach avoids the complexity of decorators while maintaining type safety and developer experience.

## Design Goals

1. **Simplicity** - Easy to learn and use, no magic
2. **Type Safety** - Full IDE support and compile-time checking
3. **Flexibility** - Support both static and dynamic workflows
4. **Testability** - Each component easily testable
5. **Composability** - Tasks can be combined and reused
6. **Debuggability** - Clear stack traces and error messages
7. **Extensibility** - Easy to add new task types and patterns

## Core Architecture

### 1. Task Data Structure

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

@dataclass
class Task:
    """
    Core task representation with fluent interface.

    This is the fundamental building block of all workflows.
    Tasks can be chained, modified, and composed using fluent methods.
    """
    name: str
    method: str
    params: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    on_error: str = "fail"  # fail | skip | retry
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_deps(self, *deps: str) -> 'Task':
        """Add dependencies to this task"""
        self.dependencies.extend(deps)
        return self

    def with_timeout(self, seconds: int) -> 'Task':
        """Set timeout for this task"""
        self.timeout = seconds
        return self

    def with_retry(self, count: int) -> 'Task':
        """Set retry count for this task"""
        self.retry_count = count
        return self

    def on_fail(self, action: str) -> 'Task':
        """Set failure behavior: 'fail', 'skip', or 'retry'"""
        if action not in ["fail", "skip", "retry"]:
            raise ValueError(f"Invalid failure action: {action}")
        self.on_error = action
        return self

    def with_meta(self, **metadata) -> 'Task':
        """Add metadata to task"""
        self.metadata.update(metadata)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Gleitzeit workflow format"""
        result = {
            "name": self.name,
            "method": self.method,
            "params": self.params
        }

        # Add optional fields only if they exist
        if self.dependencies:
            result["dependencies"] = self.dependencies
        if self.timeout:
            result["timeout"] = self.timeout
        if self.retry_count:
            result["retry_count"] = self.retry_count
        if self.on_error != "fail":
            result["on_error"] = self.on_error
        if self.metadata:
            result["metadata"] = self.metadata

        return result

@dataclass
class Workflow:
    """
    Workflow container with builder methods.

    Provides a fluent interface for building complex workflows
    while maintaining type safety and validation.
    """
    name: str
    description: str = ""
    tasks: List[Task] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add(self, *tasks: Task) -> 'Workflow':
        """Add tasks to workflow"""
        self.tasks.extend(tasks)
        return self

    def with_meta(self, **metadata) -> 'Workflow':
        """Add workflow-level metadata"""
        self.metadata.update(metadata)
        return self

    def validate(self) -> List[str]:
        """Validate workflow and return list of issues"""
        issues = []
        task_names = {task.name for task in self.tasks}

        # Check for duplicate task names
        names = [task.name for task in self.tasks]
        duplicates = set([name for name in names if names.count(name) > 1])
        if duplicates:
            issues.append(f"Duplicate task names: {duplicates}")

        # Check dependencies exist
        for task in self.tasks:
            for dep in task.dependencies:
                if dep not in task_names:
                    issues.append(f"Task '{task.name}' depends on non-existent task '{dep}'")

        # Check for circular dependencies
        def has_cycle(task_name: str, visited: set, path: list) -> bool:
            if task_name in path:
                cycle = path[path.index(task_name):] + [task_name]
                issues.append(f"Circular dependency: {' -> '.join(cycle)}")
                return True

            if task_name in visited:
                return False

            visited.add(task_name)
            path.append(task_name)

            task = next((t for t in self.tasks if t.name == task_name), None)
            if task:
                for dep in task.dependencies:
                    if has_cycle(dep, visited, path.copy()):
                        return True

            return False

        visited = set()
        for task in self.tasks:
            if task.name not in visited:
                has_cycle(task.name, visited, [])

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Gleitzeit workflow format"""
        issues = self.validate()
        if issues:
            raise ValueError(f"Workflow validation failed: {issues}")

        return {
            "name": self.name,
            "description": self.description,
            "tasks": [task.to_dict() for task in self.tasks],
            "metadata": self.metadata
        }

    async def submit(self, client=None) -> Any:
        """Submit workflow to Gleitzeit"""
        if not client:
            from gleitzeit.client import GleitzeitClient
            async with GleitzeitClient() as client:
                return await client.submit_workflow(self.to_dict())
        else:
            return await client.submit_workflow(self.to_dict())
```

### 2. Task Factory Classes

```python
from typing import Union, List

class Tasks:
    """
    Factory class for common task types.

    Provides static methods to create tasks with sensible defaults
    and proper parameter validation. Each method returns a Task
    instance that can be further customized with fluent methods.
    """

    @staticmethod
    def llm(
        name: str,
        prompt: str,
        model: str = "llama2",
        temperature: float = 0.7,
        max_tokens: int = 500,
        stream: bool = False,
        system: str = None,
        **options
    ) -> Task:
        """
        Create an LLM task for text generation.

        Args:
            name: Unique task name
            prompt: Text prompt for the model
            model: Model name (llama2, mistral, etc.)
            temperature: Generation randomness (0.0 - 1.0)
            max_tokens: Maximum tokens to generate
            stream: Enable streaming response
            system: System prompt/instructions
            **options: Additional model-specific options

        Returns:
            Task configured for LLM generation
        """
        params = {
            "prompt": prompt,
            "model": model,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                **options
            }
        }

        if stream:
            params["stream"] = stream
        if system:
            params["system"] = system

        return Task(
            name=name,
            method="ollama/generate",
            params=params
        )

    @staticmethod
    def validate(
        name: str,
        *conditions: str,
        mode: str = "all",
        on_failure: str = "skip",
        context: Dict[str, Any] = None
    ) -> Task:
        """
        Create a validation task for conditional execution.

        Args:
            name: Unique task name
            *conditions: Validation expressions to evaluate
            mode: How to combine conditions ('all', 'any', 'custom')
            on_failure: Action on validation failure ('skip', 'fail')
            context: Additional context for evaluation

        Returns:
            Task configured for validation
        """
        params = {
            "conditions": list(conditions),
            "mode": mode,
            "on_failure": on_failure
        }

        if context:
            params["context"] = context

        return Task(
            name=name,
            method="validation/evaluate",
            params=params
        )

    @staticmethod
    def python(
        name: str,
        code: str,
        capture_output: bool = True,
        env: Dict[str, str] = None
    ) -> Task:
        """
        Create a Python execution task.

        Args:
            name: Unique task name
            code: Python code to execute
            capture_output: Whether to capture stdout/stderr
            env: Environment variables

        Returns:
            Task configured for Python execution
        """
        params = {
            "code": code,
            "capture_output": capture_output
        }

        if env:
            params["env"] = env

        return Task(
            name=name,
            method="python/execute",
            params=params
        )

    @staticmethod
    def http(
        name: str,
        url: str,
        method: str = "GET",
        headers: Dict[str, str] = None,
        body: Any = None,
        params: Dict[str, str] = None
    ) -> Task:
        """
        Create an HTTP request task.

        Args:
            name: Unique task name
            url: Request URL
            method: HTTP method
            headers: Request headers
            body: Request body
            params: Query parameters

        Returns:
            Task configured for HTTP request
        """
        task_params = {
            "url": url,
            "method": method.upper()
        }

        if headers:
            task_params["headers"] = headers
        if body:
            task_params["body"] = body
        if params:
            task_params["params"] = params

        return Task(
            name=name,
            method="http/request",
            params=task_params
        )

    @staticmethod
    def wait_signal(
        name: str,
        signal_name: str,
        timeout: int = None
    ) -> Task:
        """
        Create a signal waiting task.

        Args:
            name: Unique task name
            signal_name: Name of signal to wait for
            timeout: Optional timeout in seconds

        Returns:
            Task configured to wait for signal
        """
        params = {"signal_name": signal_name}

        if timeout:
            params["timeout"] = timeout

        return Task(
            name=name,
            method="signal/wait",
            params=params
        )

    @staticmethod
    def send_signal(
        name: str,
        signal_name: str,
        payload: Any = None
    ) -> Task:
        """
        Create a signal sending task.

        Args:
            name: Unique task name
            signal_name: Name of signal to send
            payload: Optional data to send with signal

        Returns:
            Task configured to send signal
        """
        params = {"signal_name": signal_name}

        if payload:
            params["payload"] = payload

        return Task(
            name=name,
            method="signal/send",
            params=params
        )

class Patterns:
    """
    Higher-level workflow patterns and utilities.

    Provides common workflow patterns as reusable components,
    reducing boilerplate for frequent use cases.
    """

    @staticmethod
    def chain_of_thought(
        base_name: str,
        problem: str,
        model: str = "llama2",
        steps: int = 3
    ) -> List[Task]:
        """
        Create a chain-of-thought reasoning workflow.

        Args:
            base_name: Base name for generated tasks
            problem: Problem to solve
            model: LLM model to use
            steps: Number of reasoning steps

        Returns:
            List of tasks implementing chain-of-thought
        """
        tasks = []

        # Step 1: Analyze the problem
        tasks.append(
            Tasks.llm(
                f"{base_name}_analyze",
                f"Analyze this problem step by step: {problem}",
                model=model,
                temperature=0.3
            )
        )

        # Step 2: Generate reasoning steps
        tasks.append(
            Tasks.llm(
                f"{base_name}_plan",
                "Based on the analysis: {{" + f"{base_name}_analyze.result.response" + "}}, create a step-by-step plan:",
                model=model,
                temperature=0.2
            ).with_deps(f"{base_name}_analyze")
        )

        # Step 3: Execute reasoning
        for i in range(steps):
            step_name = f"{base_name}_step_{i}"
            tasks.append(
                Tasks.llm(
                    step_name,
                    f"Execute step {i+1} of the plan: {{" + f"{base_name}_plan.result.response" + "}}",
                    model=model,
                    temperature=0.2
                ).with_deps(f"{base_name}_plan")
            )

        # Final synthesis
        tasks.append(
            Tasks.llm(
                f"{base_name}_synthesize",
                "Synthesize the final answer from all reasoning steps: " +
                " ".join([f"{{{base_name}_step_{i}.result.response}}" for i in range(steps)]),
                model=model,
                temperature=0.1
            ).with_deps(*[f"{base_name}_step_{i}" for i in range(steps)])
        )

        return tasks

    @staticmethod
    def conditional_branch(
        condition_task_name: str,
        condition: str,
        if_true: List[Task],
        if_false: List[Task] = None
    ) -> List[Task]:
        """
        Create conditional execution branches.

        Args:
            condition_task_name: Name of task whose result to check
            condition: Boolean condition to evaluate
            if_true: Tasks to run if condition is true
            if_false: Tasks to run if condition is false

        Returns:
            List of tasks with conditional execution
        """
        tasks = []

        # Validation gates
        true_gate = Tasks.validate(
            f"{condition_task_name}_true_gate",
            condition,
            on_failure="skip"
        ).with_deps(condition_task_name)

        false_gate = Tasks.validate(
            f"{condition_task_name}_false_gate",
            f"not ({condition})",
            on_failure="skip"
        ).with_deps(condition_task_name)

        tasks.extend([true_gate, false_gate])

        # Add conditional tasks
        for task in if_true:
            task.with_deps(f"{condition_task_name}_true_gate")
            tasks.append(task)

        if if_false:
            for task in if_false:
                task.with_deps(f"{condition_task_name}_false_gate")
                tasks.append(task)

        return tasks

    @staticmethod
    def parallel_ensemble(
        base_name: str,
        input_data: str,
        agents: List[Dict[str, Any]],
        combiner_prompt: str = None
    ) -> List[Task]:
        """
        Create parallel agent ensemble with result combination.

        Args:
            base_name: Base name for generated tasks
            input_data: Input data for all agents
            agents: List of agent configurations
            combiner_prompt: Optional prompt for combining results

        Returns:
            List of tasks for parallel execution
        """
        tasks = []
        agent_names = []

        # Create parallel agent tasks
        for i, agent_config in enumerate(agents):
            agent_name = f"{base_name}_agent_{i}"
            agent_names.append(agent_name)

            task = Tasks.llm(
                agent_name,
                agent_config.get("prompt", f"Process: {input_data}"),
                model=agent_config.get("model", "llama2"),
                temperature=agent_config.get("temperature", 0.7)
            )

            tasks.append(task)

        # Optional combiner
        if combiner_prompt:
            combiner = Tasks.llm(
                f"{base_name}_combiner",
                combiner_prompt + " Results: " +
                " ".join([f"{{{name}.result.response}}" for name in agent_names]),
                model="llama2"
            ).with_deps(*agent_names)

            tasks.append(combiner)

        return tasks
```

### 3. Advanced Utilities

```python
class WorkflowBuilder:
    """
    Advanced workflow builder with utilities and validation.

    Provides additional methods for complex workflow construction,
    template management, and workflow composition.
    """

    @staticmethod
    def from_template(template_name: str, **variables) -> Workflow:
        """Load workflow from template with variable substitution"""
        # Implementation would load from templates directory
        pass

    @staticmethod
    def merge_workflows(*workflows: Workflow) -> Workflow:
        """
        Merge multiple workflows into one.

        Handles task name conflicts and dependency resolution.
        """
        merged = Workflow(f"merged_{len(workflows)}_workflows")

        task_counter = {}
        for workflow in workflows:
            for task in workflow.tasks:
                # Handle name conflicts
                original_name = task.name
                if original_name in task_counter:
                    task_counter[original_name] += 1
                    task.name = f"{original_name}_{task_counter[original_name]}"
                else:
                    task_counter[original_name] = 0

                merged.add(task)

        return merged

    @staticmethod
    def create_pipeline(*steps: List[Task]) -> Workflow:
        """
        Create a linear pipeline from task groups.

        Each step runs in parallel, steps run sequentially.
        """
        workflow = Workflow("pipeline")

        previous_step_names = []
        for i, step_tasks in enumerate(steps):
            current_step_names = []

            for task in step_tasks:
                # Add dependencies on previous step
                if previous_step_names:
                    task.with_deps(*previous_step_names)

                current_step_names.append(task.name)
                workflow.add(task)

            previous_step_names = current_step_names

        return workflow

class TaskValidation:
    """
    Validation utilities for tasks and workflows.
    """

    @staticmethod
    def validate_task(task: Task) -> List[str]:
        """Validate individual task configuration"""
        issues = []

        # Check required fields
        if not task.name.strip():
            issues.append("Task name cannot be empty")

        if not task.method.strip():
            issues.append("Task method cannot be empty")

        # Validate method format
        if not "/" in task.method:
            issues.append(f"Invalid method format: {task.method} (expected 'protocol/method')")

        # Validate timeout
        if task.timeout and task.timeout <= 0:
            issues.append("Timeout must be positive")

        # Validate retry count
        if task.retry_count and task.retry_count < 0:
            issues.append("Retry count cannot be negative")

        # Validate on_error action
        if task.on_error not in ["fail", "skip", "retry"]:
            issues.append(f"Invalid on_error action: {task.on_error}")

        return issues

    @staticmethod
    def suggest_optimizations(workflow: Workflow) -> List[str]:
        """Suggest workflow optimizations"""
        suggestions = []

        # Check for parallelizable tasks
        for task in workflow.tasks:
            if not task.dependencies:
                parallel_candidates = [
                    t.name for t in workflow.tasks
                    if not t.dependencies and t.name != task.name
                ]
                if parallel_candidates:
                    suggestions.append(
                        f"Tasks {task.name} and {parallel_candidates} can run in parallel"
                    )
                    break

        # Check for unnecessary dependencies
        task_outputs = set()
        for task in workflow.tasks:
            # Analyze if dependencies are actually used
            for dep in task.dependencies:
                if f"{dep}.result" not in str(task.params):
                    suggestions.append(
                        f"Task {task.name} depends on {dep} but doesn't use its output"
                    )

        return suggestions
```

## Usage Examples

### 1. Basic Agent Workflow

```python
# Simple sentiment analysis agent
workflow = Workflow("sentiment_agent", "Analyze sentiment and respond")

workflow.add(
    Tasks.llm(
        "analyze",
        "What is the sentiment of this text: 'I love this product!'",
        temperature=0.1
    ),

    Tasks.validate("is_positive", "'positive' in analyze.result.response")
        .with_deps("analyze"),

    Tasks.llm("respond", "Generate a positive response")
        .with_deps("is_positive")
        .with_timeout(30)
)

# Submit workflow
async with GleitzeitClient() as client:
    result = await workflow.submit(client)
    print(f"Workflow ID: {result.workflow_id}")
```

### 2. Agent with Tool Use

```python
# Agent that routes to different tools based on classification
def create_tool_agent(query: str) -> Workflow:
    workflow = Workflow("tool_agent", "Agent with dynamic tool routing")

    # Classify intent
    classify = Tasks.llm(
        "classify",
        f"Classify this query: '{query}' as 'math', 'search', or 'general'",
        temperature=0.1,
        max_tokens=10
    )

    # Math tool branch
    math_tasks = Patterns.conditional_branch(
        "classify",
        "'math' in classify.result.response.lower()",
        if_true=[
            Tasks.python(
                "calculator",
                f"""
import re
query = "{query}"
# Extract and evaluate math expression
numbers = re.findall(r'\\d+', query)
if len(numbers) >= 2:
    result = f"{numbers[0]} + {numbers[1]} = {int(numbers[0]) + int(numbers[1])}"
else:
    result = "Could not parse math expression"
                """
            )
        ]
    )

    # Search tool branch
    search_tasks = Patterns.conditional_branch(
        "classify",
        "'search' in classify.result.response.lower()",
        if_true=[
            Tasks.http(
                "search",
                "https://api.search.com/v1/search",
                params={"q": query}
            )
        ]
    )

    # General response branch
    general_tasks = Patterns.conditional_branch(
        "classify",
        "'general' in classify.result.response.lower()",
        if_true=[
            Tasks.llm("general_response", f"Respond to: {query}")
        ]
    )

    # Combine results
    final_response = Tasks.llm(
        "final_response",
        """
        Based on the results below, provide a final answer:
        Calculator: {{calculator.result if calculator else 'Not used'}}
        Search: {{search.result if search else 'Not used'}}
        General: {{general_response.result.response if general_response else 'Not used'}}
        """,
        model="llama2"
    ).with_deps("calculator", "search", "general_response")

    # Build workflow
    workflow.add(classify)
    workflow.add(*math_tasks)
    workflow.add(*search_tasks)
    workflow.add(*general_tasks)
    workflow.add(final_response)

    return workflow

# Usage
agent = create_tool_agent("What is 15 + 27?")
result = asyncio.run(agent.submit())
```

### 3. Multi-Agent Conversation

```python
# Multi-agent debate system
def create_debate_workflow(topic: str) -> Workflow:
    workflow = Workflow("debate", f"Multi-agent debate on: {topic}")

    # Moderator introduction
    intro = Tasks.llm("moderator", f"Introduce debate topic: {topic}")

    # Parallel agent perspectives
    agents = Patterns.parallel_ensemble(
        "debate",
        topic,
        agents=[
            {"prompt": f"Argue FOR: {topic}", "model": "llama2"},
            {"prompt": f"Argue AGAINST: {topic}", "model": "llama2"},
            {"prompt": f"Provide neutral analysis of: {topic}", "model": "llama2"}
        ],
        combiner_prompt="Summarize this debate fairly:"
    )

    # Rebuttal round
    rebuttal = Tasks.llm(
        "rebuttal",
        "Based on all arguments: {{debate_combiner.result.response}}, provide final thoughts",
        model="llama2"
    ).with_deps("debate_combiner")

    workflow.add(intro)
    workflow.add(*agents)
    workflow.add(rebuttal)

    return workflow

# Usage
debate = create_debate_workflow("Should AI be regulated?")
result = asyncio.run(debate.submit())
```

### 4. Chain of Thought Reasoning

```python
# Complex reasoning workflow
def solve_math_problem(problem: str) -> Workflow:
    workflow = Workflow("math_solver", "Chain-of-thought math solving")

    # Use pattern for chain-of-thought
    cot_tasks = Patterns.chain_of_thought(
        "math",
        problem,
        model="llama2",
        steps=4
    )

    workflow.add(*cot_tasks)
    return workflow

# Usage
problem = "If a train travels 120km in 2 hours, then slows to half speed for 1 hour, how far total?"
solver = solve_math_problem(problem)
result = asyncio.run(solver.submit())
```

### 5. Dynamic Workflow Generation

```python
# Create workflows programmatically
def create_analysis_pipeline(documents: List[str]) -> Workflow:
    workflow = Workflow("document_analysis", f"Analyze {len(documents)} documents")

    # Process each document in parallel
    analysis_tasks = []
    for i, doc in enumerate(documents):
        task_name = f"analyze_doc_{i}"
        analysis_tasks.append(
            Tasks.llm(
                task_name,
                f"Analyze this document: {doc}",
                model="llama2"
            )
        )

    # Combine all analyses
    combine_prompt = "Synthesize insights from: " + \
                    " ".join([f"{{analyze_doc_{i}.result.response}}"
                             for i in range(len(documents))])

    combiner = Tasks.llm(
        "synthesis",
        combine_prompt,
        model="llama2"
    ).with_deps(*[f"analyze_doc_{i}" for i in range(len(documents))])

    # Build workflow
    workflow.add(*analysis_tasks)
    workflow.add(combiner)

    return workflow

# Usage
docs = ["Document 1 content...", "Document 2 content...", "Document 3 content..."]
pipeline = create_analysis_pipeline(docs)
result = asyncio.run(pipeline.submit())
```

## Benefits

### 1. **Type Safety & IDE Support**
- Full autocompletion for all methods and parameters
- Compile-time error checking with type hints
- Refactoring tools work correctly
- IntelliSense shows documentation

### 2. **Simplicity & Clarity**
```python
# Clear, readable workflow definition
workflow.add(
    Tasks.llm("step1", "First step"),
    Tasks.validate("check", "condition").with_deps("step1"),
    Tasks.llm("step2", "Second step").with_deps("check")
)
```

### 3. **Testability**
```python
def test_sentiment_task():
    task = Tasks.llm("test", "Analyze: happy text", temperature=0.1)
    assert task.params["model"] == "llama2"
    assert task.params["options"]["temperature"] == 0.1
    assert "happy text" in task.params["prompt"]

def test_workflow_structure():
    wf = create_sentiment_workflow("test")
    assert len(wf.tasks) == 3
    assert wf.tasks[1].dependencies == ["analyze"]
```

### 4. **Composability & Reusability**
```python
# Define once, reuse everywhere
def create_summarizer(name: str, text: str) -> Task:
    return Tasks.llm(name, f"Summarize: {text}", temperature=0.3)

# Use in multiple workflows
wf1.add(create_summarizer("sum1", "text1"))
wf2.add(create_summarizer("sum2", "text2"))
```

### 5. **Flexibility**
```python
# Static workflows
workflow = Workflow("static")
workflow.add(Tasks.llm("task", "prompt"))

# Dynamic workflows
for i in range(n):
    workflow.add(Tasks.llm(f"task_{i}", f"Process item {i}"))

# Conditional workflows
if condition:
    workflow.add(Tasks.llm("conditional", "special handling"))
```

## Comparison with Alternatives

| Feature | **Factory+Dataclass** | **Decorators** | **Raw Dicts** | **Easy Client** |
|---------|----------------------|----------------|---------------|-----------------|
| **Type Safety** | ✅ Full | ✅ Full | ❌ None | ⚠️ Partial |
| **IDE Support** | ✅ Complete | ✅ Good | ❌ None | ✅ Good |
| **Testability** | ✅ Excellent | ⚠️ Config only | ✅ Full | ✅ Good |
| **Dynamic Workflows** | ✅ Full support | ❌ Limited | ✅ Full | ✅ Full |
| **Learning Curve** | ✅ Gentle | ❌ Steep | ✅ Simple | ✅ Simple |
| **Debugging** | ✅ Clear traces | ❌ Complex | ✅ Clear | ✅ Clear |
| **Reusability** | ✅ Excellent | ⚠️ Limited | ⚠️ Manual | ✅ Good |
| **Validation** | ✅ Built-in | ✅ At definition | ❌ Runtime only | ⚠️ Limited |

## Implementation Roadmap

### Phase 1: Core Implementation
1. Implement `Task` and `Workflow` dataclasses
2. Create basic factory methods (`Tasks.llm`, `Tasks.validate`, `Tasks.python`)
3. Add fluent interface methods (`with_deps`, `with_timeout`, etc.)
4. Implement workflow validation and conversion

### Phase 2: Advanced Features
1. Add `Patterns` class with common workflow patterns
2. Implement `WorkflowBuilder` utilities
3. Add template system and workflow composition
4. Create validation and optimization suggestions

### Phase 3: Developer Experience
1. Add comprehensive documentation and examples
2. Create IDE plugins or language server support
3. Build workflow visualization tools
4. Add debugging and profiling utilities

### Phase 4: Integration
1. Integrate with existing Gleitzeit client
2. Add backward compatibility layers
3. Create migration tools from YAML/JSON workflows
4. Performance optimization and benchmarking

## Conclusion

The Factory + Dataclass approach provides the optimal balance of simplicity, type safety, and flexibility for Gleitzeit workflow definitions. It avoids the complexity of decorators while maintaining all the benefits of type safety and IDE support.

Key advantages:
- **Simple mental model**: Functions create objects, objects compose workflows
- **Type safe**: Full IDE support and compile-time checking
- **Flexible**: Works for static and dynamic use cases
- **Testable**: Every component can be tested independently
- **Extensible**: Easy to add new task types and patterns
- **Debuggable**: Clear stack traces and error messages

This design makes Gleitzeit workflows as easy to write as any Python code while maintaining the power and scalability of the underlying distributed execution engine.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content": "Create design document for factory + dataclass workflow API", "status": "completed", "activeForm": "Creating design document for factory + dataclass workflow API"}, {"content": "Define core dataclass structures", "status": "completed", "activeForm": "Defining core dataclass structures"}, {"content": "Design factory methods and API", "status": "in_progress", "activeForm": "Designing factory methods and API"}, {"content": "Create usage examples and patterns", "status": "pending", "activeForm": "Creating usage examples and patterns"}]