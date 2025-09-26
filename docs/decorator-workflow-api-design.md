# Decorator + Dataclass Workflow API Design

## Executive Summary

This document proposes a new Python API for Gleitzeit workflow definitions that combines decorators and dataclasses to provide a type-safe, testable, and developer-friendly interface for creating workflows.

## Goals

1. **Reduce boilerplate** when defining workflows
2. **Provide type safety** and IDE support
3. **Enable testing** of workflow logic
4. **Support reusability** of task definitions
5. **Maintain compatibility** with existing JSON/YAML workflow format

## Core Design

### 1. Task Configuration via Dataclasses

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class TaskConfig:
    """Base configuration for all tasks"""
    name: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    on_error: str = "fail"  # fail|skip|retry
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LLMConfig(TaskConfig):
    """Configuration for LLM tasks"""
    prompt: str
    model: str = "llama2"
    temperature: float = 0.7
    max_tokens: int = 500
    stream: bool = False
    system_prompt: Optional[str] = None

@dataclass
class ValidationConfig(TaskConfig):
    """Configuration for validation tasks"""
    conditions: List[str]
    on_failure: str = "skip"
    mode: str = "all"  # all|any|custom
    context: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PythonConfig(TaskConfig):
    """Configuration for Python execution tasks"""
    code: str
    capture_output: bool = True
    env: Dict[str, str] = field(default_factory=dict)

@dataclass
class HTTPConfig(TaskConfig):
    """Configuration for HTTP tasks"""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    params: Dict[str, str] = field(default_factory=dict)
```

### 2. Workflow Class with Decorators

```python
from functools import wraps
from typing import Callable, Type, TypeVar

T = TypeVar('T', bound=TaskConfig)

class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.tasks = []
        self._task_registry = {}
        self._current_context = {}

    def task(self, method: str, config_class: Type[T] = TaskConfig):
        """
        Decorator to register a task in the workflow.

        Args:
            method: The Gleitzeit method (e.g., "ollama/generate")
            config_class: Expected configuration class for validation
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Dict[str, Any]:
                # Get configuration from function
                config = func(*args, **kwargs)

                # Validate config type
                if not isinstance(config, config_class):
                    raise TypeError(f"Expected {config_class.__name__}, got {type(config).__name__}")

                # Build task definition
                task_def = self._build_task_def(func.__name__, method, config)

                # Store for later use
                self._task_registry[func.__name__] = task_def

                return task_def

            # Add to workflow's namespace for easy access
            setattr(self, func.__name__, wrapper)
            return wrapper
        return decorator

    def _build_task_def(self, func_name: str, method: str, config: TaskConfig) -> Dict[str, Any]:
        """Convert config to Gleitzeit task definition"""
        task_def = {
            "name": config.name or func_name,
            "method": method,
            "params": {}
        }

        # Handle specific config types
        if isinstance(config, LLMConfig):
            task_def["params"] = {
                "prompt": config.prompt,
                "model": config.model,
                "options": {
                    "temperature": config.temperature,
                    "num_predict": config.max_tokens
                },
                "stream": config.stream
            }
            if config.system_prompt:
                task_def["params"]["system"] = config.system_prompt

        elif isinstance(config, ValidationConfig):
            task_def["params"] = {
                "conditions": config.conditions,
                "on_failure": config.on_failure,
                "mode": config.mode,
                "context": config.context
            }

        elif isinstance(config, PythonConfig):
            task_def["params"] = {
                "code": config.code,
                "capture_output": config.capture_output,
                "env": config.env
            }

        elif isinstance(config, HTTPConfig):
            task_def["params"] = {
                "url": config.url,
                "method": config.method,
                "headers": config.headers,
                "body": config.body,
                "params": config.params
            }

        # Add common fields
        if config.dependencies:
            task_def["dependencies"] = config.dependencies
        if config.timeout:
            task_def["timeout"] = config.timeout
        if config.retry_count:
            task_def["retry_count"] = config.retry_count
        if config.metadata:
            task_def["metadata"] = config.metadata

        return task_def

    def add(self, *tasks) -> 'Workflow':
        """Add task definitions to workflow"""
        for task in tasks:
            if callable(task):
                task_def = task()
            else:
                task_def = task
            self.tasks.append(task_def)
        return self

    def build(self) -> Dict[str, Any]:
        """Build the complete workflow definition"""
        return {
            "name": self.name,
            "description": self.description,
            "tasks": self.tasks
        }

    async def submit(self, client=None):
        """Submit workflow directly if client provided"""
        if not client:
            from gleitzeit.client import GleitzeitClient
            client = GleitzeitClient()

        workflow_def = self.build()
        return await client.submit_workflow(workflow_def)
```

### 3. Usage Example

```python
# Define a workflow
wf = Workflow("document_analyzer", "Analyze and summarize documents")

@wf.task("ollama/generate", LLMConfig)
def extract_topics(document: str) -> LLMConfig:
    """Extract main topics from document"""
    return LLMConfig(
        prompt=f"Extract the main topics from this document:\n{document}",
        model="llama2",
        temperature=0.3,
        max_tokens=200
    )

@wf.task("validation/evaluate", ValidationConfig)
def has_technical_content() -> ValidationConfig:
    """Check if document contains technical content"""
    return ValidationConfig(
        conditions=[
            "'technology' in extract_topics.result.response.lower()",
            "'software' in extract_topics.result.response.lower()"
        ],
        mode="any",
        dependencies=["extract_topics"],
        on_failure="skip"
    )

@wf.task("ollama/generate", LLMConfig)
def technical_summary(document: str) -> LLMConfig:
    """Generate technical summary"""
    return LLMConfig(
        prompt=f"Create a technical summary of:\n{document}",
        model="llama2",
        dependencies=["has_technical_content"],
        temperature=0.2,
        max_tokens=500
    )

@wf.task("ollama/generate", LLMConfig)
def general_summary(document: str) -> LLMConfig:
    """Generate general summary"""
    return LLMConfig(
        prompt=f"Summarize this document for a general audience:\n{document}",
        model="llama2",
        dependencies=["extract_topics"],
        temperature=0.5,
        max_tokens=300
    )

# Build and submit workflow
doc_content = "Long document text here..."
wf.add(
    extract_topics(doc_content),
    has_technical_content(),
    technical_summary(doc_content),
    general_summary(doc_content)
)

# Submit to Gleitzeit
async def run():
    async with GleitzeitClient() as client:
        result = await wf.submit(client)
        print(f"Workflow submitted: {result.workflow_id}")

asyncio.run(run())
```

## Benefits

### 1. **Type Safety and IDE Support**
- Full auto-completion for all configuration fields
- Type checking catches errors at development time
- IDE can show parameter documentation
- Refactoring tools work correctly

### 2. **Testability**
```python
def test_extract_topics():
    config = extract_topics("test document")
    assert config.model == "llama2"
    assert config.temperature == 0.3
    assert "main topics" in config.prompt
```

### 3. **Reusability**
```python
# Define once
@task_library.register("ollama/generate", LLMConfig)
def summarize_text(text: str, max_words: int = 100) -> LLMConfig:
    return LLMConfig(prompt=f"Summarize in {max_words} words: {text}")

# Use in multiple workflows
workflow1.add(summarize_text("text1", 50))
workflow2.add(summarize_text("text2", 200))
```

### 4. **Clear Documentation**
```python
@wf.task("ollama/generate", LLMConfig)
def analyze_sentiment(text: str) -> LLMConfig:
    """
    Analyze the sentiment of the provided text.

    Args:
        text: The text to analyze

    Returns:
        LLMConfig with sentiment analysis prompt
    """
    return LLMConfig(...)
```

### 5. **Validation at Definition Time**
```python
@dataclass
class LLMConfig(TaskConfig):
    prompt: str
    model: str = "llama2"

    def __post_init__(self):
        if len(self.prompt) > 10000:
            raise ValueError("Prompt exceeds maximum length")
        if self.model not in ["llama2", "mistral", "codellama"]:
            raise ValueError(f"Unsupported model: {self.model}")
```

## Problems and Limitations

### 1. **Dynamic Workflow Construction**

**Problem**: Decorators are evaluated at import time, making dynamic workflows harder.

```python
# This is awkward
def create_workflow(num_steps: int):
    wf = Workflow("dynamic")

    # Can't use decorators dynamically
    for i in range(num_steps):
        # Have to manually create tasks
        task_def = {
            "name": f"step_{i}",
            "method": "ollama/generate",
            "params": {"prompt": f"Step {i}"}
        }
        wf.tasks.append(task_def)

    return wf
```

### 2. **Parameter References Between Tasks**

**Problem**: How to reference other task results cleanly?

```python
@wf.task("ollama/generate", LLMConfig)
def step2() -> LLMConfig:
    # This won't work - step1 hasn't run yet
    # previous_result = step1().result

    # Have to use string templates
    return LLMConfig(
        prompt="Continue from: {{step1.result.response}}",  # String template
        dependencies=["step1"]
    )
```

### 3. **Conditional Task Execution**

**Problem**: Complex conditional logic is hard to express.

```python
@wf.task("ollama/generate", LLMConfig)
def conditional_task() -> LLMConfig:
    # How to express: "Only run if task A succeeded AND task B returned 'yes'"?
    return LLMConfig(
        prompt="...",
        dependencies=["task_a", "task_b"],
        # No clean way to express complex conditions
    )
```

### 4. **Task Reuse with Different Parameters**

**Problem**: Can't easily call the same decorated function multiple times with different params.

```python
@wf.task("ollama/generate", LLMConfig)
def analyze(text: str) -> LLMConfig:
    return LLMConfig(prompt=f"Analyze: {text}")

# Want to use it twice in same workflow
wf.add(
    analyze("text1"),  # Creates task named "analyze"
    analyze("text2"),  # ERROR: Duplicate task name!
)
```

### 5. **Mixing Decorated and Non-Decorated Tasks**

**Problem**: Inconsistent API when mixing approaches.

```python
# Decorated task
@wf.task("ollama/generate", LLMConfig)
def decorated_task() -> LLMConfig:
    return LLMConfig(prompt="...")

# Manual task (for dynamic cases)
manual_task = {
    "name": "manual",
    "method": "python/execute",
    "params": {"code": "..."}
}

# Inconsistent usage
wf.add(
    decorated_task(),  # Call function
    manual_task       # Pass dict directly
)
```

### 6. **Learning Curve**

**Problem**: Decorators + dataclasses + workflow concepts = steep learning curve.

```python
# New users need to understand:
# 1. Decorators
# 2. Dataclasses
# 3. Type hints
# 4. Gleitzeit's workflow model
# 5. Task dependencies
# 6. Parameter templating
```

### 7. **Debugging Complexity**

**Problem**: Stack traces become complex with decorator layers.

```
Traceback (most recent call last):
  File "workflow.py", line 45, in wrapper
  File "workflow.py", line 32, in decorator
  File "workflow.py", line 28, in _build_task_def
  File "dataclasses.py", line 85, in __init__
ValueError: Invalid prompt length
```

### 8. **Serialization Issues**

**Problem**: Dataclasses with complex types may not serialize correctly.

```python
from datetime import datetime
import numpy as np

@dataclass
class CustomConfig(TaskConfig):
    timestamp: datetime  # How to serialize?
    matrix: np.ndarray   # Not JSON serializable
    callback: Callable   # Can't serialize functions
```

### 9. **Version Compatibility**

**Problem**: Dataclass changes break existing workflows.

```python
# Version 1
@dataclass
class LLMConfig(TaskConfig):
    prompt: str
    model: str

# Version 2 - Added required field
@dataclass
class LLMConfig(TaskConfig):
    prompt: str
    model: str
    temperature: float  # Old workflows break!
```

### 10. **Testing Paradox**

**Problem**: Functions don't actually execute their logic.

```python
@wf.task("ollama/generate", LLMConfig)
def process_data(data: str) -> LLMConfig:
    # This logic never runs - just returns config
    # processed = complex_processing(data)  # Never executed
    # return LLMConfig(prompt=processed)

    # Have to return config directly
    return LLMConfig(prompt=f"Process: {data}")

# Test is testing configuration, not logic
def test_process_data():
    config = process_data("test")
    # Can only test the config, not actual processing
    assert config.prompt == "Process: test"
```

## Proposed Solutions

### Solution 1: Hybrid Approach

Support both decorated and builder patterns:

```python
# Decorated for static workflows
@wf.task("ollama/generate", LLMConfig)
def static_task() -> LLMConfig:
    return LLMConfig(prompt="...")

# Builder for dynamic workflows
wf.add_task(
    name="dynamic_task",
    method="ollama/generate",
    prompt="...",
    model="llama2"
)
```

### Solution 2: Task Factory Pattern

Don't use decorators, use factory functions:

```python
class TaskFactory:
    @staticmethod
    def llm(name: str, prompt: str, **kwargs) -> Task:
        """Factory method that returns Task instance"""
        return Task(
            name=name,
            method="ollama/generate",
            config=LLMConfig(prompt=prompt, **kwargs)
        )

# Usage - Clean and flexible
wf = Workflow("example")
wf.add(
    TaskFactory.llm("step1", "First prompt"),
    TaskFactory.llm("step2", "Second: {{step1.result}}"),
    TaskFactory.validate("check", "step1.success", deps=["step1"])
)
```

### Solution 3: Task Templates

Pre-defined task templates that can be customized:

```python
class TaskTemplates:
    summarize = LLMConfig(
        prompt="Summarize: {text}",
        model="llama2",
        temperature=0.3
    )

    classify = LLMConfig(
        prompt="Classify into categories: {text}",
        model="llama2",
        temperature=0.1
    )

# Usage
wf.add_task("summary", TaskTemplates.summarize.format(text=doc))
wf.add_task("classify", TaskTemplates.classify.format(text=doc))
```

### Solution 4: Context Managers

Use context managers for workflow building:

```python
with Workflow("example") as wf:
    # Tasks auto-register in context
    step1 = wf.llm("Analyze this", name="analyze")
    step2 = wf.validate("'positive' in analyze.result", deps=[step1])
    step3 = wf.llm("Generate response", deps=[step2])

# Workflow is built on context exit
result = await wf.submit()
```

### Solution 5: Functional Composition

Pure functional approach:

```python
from functools import partial

# Define task generators
llm = partial(create_task, method="ollama/generate")
validate = partial(create_task, method="validation/evaluate")

# Compose workflow
workflow = compose_workflow(
    "example",
    llm(name="step1", prompt="..."),
    validate(name="check", conditions=["..."], deps=["step1"]),
    llm(name="step2", prompt="...", deps=["check"])
)
```

## Recommended Approach

Based on the analysis, I recommend **Solution 2: Task Factory Pattern** with dataclasses for configuration:

```python
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class Task:
    """Single task representation"""
    name: str
    method: str
    params: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    timeout: Optional[int] = None
    retry_count: Optional[int] = None

    def with_deps(self, *deps: str) -> 'Task':
        """Fluent method to add dependencies"""
        self.dependencies.extend(deps)
        return self

    def with_timeout(self, seconds: int) -> 'Task':
        """Fluent method to set timeout"""
        self.timeout = seconds
        return self

class Tasks:
    """Task factory with common patterns"""

    @staticmethod
    def llm(name: str, prompt: str, model: str = "llama2", **options) -> Task:
        return Task(
            name=name,
            method="ollama/generate",
            params={"prompt": prompt, "model": model, "options": options}
        )

    @staticmethod
    def validate(name: str, *conditions: str, on_failure: str = "skip") -> Task:
        return Task(
            name=name,
            method="validation/evaluate",
            params={"conditions": list(conditions), "on_failure": on_failure}
        )

    @staticmethod
    def python(name: str, code: str) -> Task:
        return Task(
            name=name,
            method="python/execute",
            params={"code": code}
        )

class Workflow:
    """Workflow builder"""

    def __init__(self, name: str):
        self.name = name
        self.tasks: List[Task] = []

    def add(self, *tasks: Task) -> 'Workflow':
        """Add tasks to workflow"""
        self.tasks.extend(tasks)
        return self

    def build(self) -> Dict[str, Any]:
        """Build workflow definition"""
        return {
            "name": self.name,
            "tasks": [
                {
                    "name": task.name,
                    "method": task.method,
                    "params": task.params,
                    **{"dependencies": task.dependencies} if task.dependencies else {},
                    **{"timeout": task.timeout} if task.timeout else {},
                    **{"retry_count": task.retry_count} if task.retry_count else {}
                }
                for task in self.tasks
            ]
        }

# Usage - Clean, testable, and flexible
wf = Workflow("document_analyzer")
wf.add(
    Tasks.llm("extract", "Extract topics from: {doc}", temperature=0.3),

    Tasks.validate("has_tech", "'technology' in extract.result")
        .with_deps("extract"),

    Tasks.llm("tech_summary", "Technical summary of: {doc}")
        .with_deps("has_tech")
        .with_timeout(30),

    Tasks.llm("general_summary", "General summary of: {doc}")
        .with_deps("extract")
)

# Submit
async with GleitzeitClient() as client:
    result = await client.submit_workflow(wf.build())
```

### Why This Approach Works Best

1. **Simple and Clear** - No decorator magic, just functions and data
2. **Testable** - Each component can be tested independently
3. **Flexible** - Works for both static and dynamic workflows
4. **Type Safe** - Full type hints and IDE support
5. **Composable** - Tasks can be built, modified, and reused
6. **Familiar** - Uses standard Python patterns
7. **Debuggable** - Simple stack traces
8. **Extensible** - Easy to add new task types

## Conclusion

While the decorator + dataclass approach offers elegance and type safety, it introduces significant complexity and limitations for workflow definition. The Task Factory pattern provides a better balance of simplicity, flexibility, and developer experience while maintaining the benefits of type safety through dataclasses.

The recommended approach:
- Uses dataclasses for configuration (type safety)
- Uses factory methods for task creation (simplicity)
- Uses fluent interface for task modification (ergonomics)
- Avoids decorator complexity (debuggability)
- Supports both static and dynamic workflows (flexibility)

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content": "Create design document for decorator+dataclass workflow API", "status": "completed", "activeForm": "Creating design document for decorator+dataclass workflow API"}, {"content": "Identify benefits of the approach", "status": "in_progress", "activeForm": "Identifying benefits of the approach"}, {"content": "Identify problems and limitations", "status": "pending", "activeForm": "Identifying problems and limitations"}, {"content": "Propose solutions and alternatives", "status": "pending", "activeForm": "Proposing solutions and alternatives"}]