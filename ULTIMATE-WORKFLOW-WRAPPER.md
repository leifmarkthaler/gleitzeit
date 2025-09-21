# Ultimate Workflow Wrapper - Implementation Analysis

## Current Gleitzeit Architecture

```python
# Current: Everything goes through these core classes
from gleitzeit.core.models import Task, Workflow, WorkflowDefinition
from gleitzeit.client import GleitzeitClient

# Tasks are submitted as dictionaries or Task objects
task = Task(
    id="my_task",
    protocol="python/v1",
    method="run",
    params={"code": "print('hello')"}
)
```

## Wrapper Complexity: EASY to MODERATE

The wrapper would be **surprisingly straightforward** because Gleitzeit already has:

1. **Task-based architecture** - Everything is already tasks
2. **Protocol/method system** - Maps cleanly to our simplified syntax
3. **Dependency tracking** - Already handles task dependencies
4. **Parameter resolution** - Already resolves ${references}

## Implementation Approach

### Layer 1: Core Wrapper Classes (~200 lines)

```python
# gleitzeit/workflow/builder.py

from typing import Any, Callable, Dict, List, Optional, Union
from gleitzeit.core.models import Task, Workflow
import inspect
import uuid

class FluentTask:
    """Fluent task builder that compiles to Gleitzeit Task"""
    
    def __init__(self, id: str = None, protocol: str = None, method: str = None):
        self.id = id or str(uuid.uuid4())
        self.protocol = protocol
        self.method = method
        self._conditions = []
        self._guards = []
        self._dependencies = []
        self._params = {}
        self._actions = []
        
    def when(self, condition: Union[str, Callable]) -> 'FluentTask':
        """Add execution condition"""
        self._conditions.append(condition)
        return self
    
    def guards(self, *conditions) -> 'FluentTask':
        """Add multiple guard conditions"""
        self._guards.extend(conditions)
        return self
    
    def depends_on(self, *tasks) -> 'FluentTask':
        """Add dependencies"""
        for task in tasks:
            if hasattr(task, 'id'):
                self._dependencies.append(task.id)
            else:
                self._dependencies.append(str(task))
        return self
    
    def params(self, **kwargs) -> 'FluentTask':
        """Set parameters"""
        self._params.update(kwargs)
        return self
    
    def fail_if(self, condition, message: str = None) -> 'FluentTask':
        """Fail workflow if condition is true"""
        self._actions.append(('fail_if', condition, message))
        return self
    
    def skip_if(self, condition, reason: str = None) -> 'FluentTask':
        """Skip task if condition is true"""
        self._actions.append(('skip_if', condition, reason))
        return self
    
    def _compile(self) -> List[Task]:
        """Compile to Gleitzeit tasks"""
        tasks = []
        
        # Generate condition tasks
        for i, cond in enumerate(self._conditions):
            cond_task = self._create_condition_task(f"{self.id}_cond_{i}", cond)
            tasks.append(cond_task)
            self._dependencies.append(cond_task.id)
        
        # Generate action tasks
        for i, (action_type, condition, param) in enumerate(self._actions):
            action_task = self._create_action_task(
                f"{self.id}_action_{i}", 
                action_type, 
                condition, 
                param
            )
            tasks.append(action_task)
            self._dependencies.append(action_task.id)
        
        # Create main task
        main_task = Task(
            id=self.id,
            protocol=self.protocol,
            method=self.method,
            params=self._params,
            dependencies=self._dependencies
        )
        tasks.append(main_task)
        
        return tasks
    
    def _create_condition_task(self, task_id: str, condition) -> Task:
        """Create a condition evaluation task"""
        if callable(condition):
            # Lambda condition - needs special handling
            return Task(
                id=task_id,
                protocol="condition/v1",
                method="evaluate_lambda",
                params={"lambda": inspect.getsource(condition).strip()}
            )
        else:
            # String expression
            return Task(
                id=task_id,
                protocol="condition/v1",
                method="evaluate",
                params={"expression": condition}
            )
    
    def _create_action_task(self, task_id: str, action: str, condition, param) -> Task:
        """Create an action task (skip/fail)"""
        if action == "skip_if":
            return Task(
                id=task_id,
                protocol="skip/v1",
                method="skip_if_true",
                params={
                    "condition": self._serialize_condition(condition),
                    "skip_tasks": [self.id],
                    "reason": param
                }
            )
        elif action == "fail_if":
            return Task(
                id=task_id,
                protocol="fail/v1",
                method="fail_if_true",
                params={
                    "condition": self._serialize_condition(condition),
                    "error_message": param
                }
            )
```

### Layer 2: Decorator Support (~150 lines)

```python
# gleitzeit/workflow/decorators.py

from functools import wraps
from typing import Type
import inspect

class WorkflowMeta(type):
    """Metaclass that collects decorated methods"""
    
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Collect all decorated task methods
        cls._tasks = []
        for attr_name, attr_value in namespace.items():
            if hasattr(attr_value, '_task_config'):
                cls._tasks.append((attr_name, attr_value))
        
        return cls

def workflow(cls: Type) -> Type:
    """Class decorator for workflows"""
    
    class WorkflowWrapper(cls, metaclass=WorkflowMeta):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._compiled_tasks = []
            self._compile_workflow()
        
        def _compile_workflow(self):
            """Compile all decorated methods to tasks"""
            for task_name, task_method in self._tasks:
                # Get the fluent config
                config = task_method._task_config
                
                # Call the method to get final config
                if inspect.iscoroutinefunction(task_method):
                    # Async method
                    result = task_method(self)
                else:
                    # Sync method
                    result = task_method(self)
                
                # Compile to tasks
                if isinstance(result, FluentTask):
                    self._compiled_tasks.extend(result._compile())
                elif hasattr(config, '_compile'):
                    self._compiled_tasks.extend(config._compile())
        
        def to_workflow(self) -> Workflow:
            """Convert to Gleitzeit Workflow"""
            return Workflow(tasks=self._compiled_tasks)
        
        async def run(self, client: 'GleitzeitClient', **inputs):
            """Execute the workflow"""
            workflow = self.to_workflow()
            return await client.submit_workflow(workflow, inputs=inputs)
    
    return WorkflowWrapper

def task(protocol: str, method: str = None):
    """Task decorator factory"""
    
    def decorator(func):
        # Create fluent task
        fluent = FluentTask(
            id=func.__name__,
            protocol=protocol,
            method=method or func.__name__
        )
        
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Execute the function
            result = func(self, *args, **kwargs)
            
            # If it returns a FluentTask, merge configs
            if isinstance(result, FluentTask):
                result.protocol = result.protocol or fluent.protocol
                result.method = result.method or fluent.method
                result.id = result.id or fluent.id
                return result
            
            # Otherwise, return the fluent task
            return fluent
        
        # Attach config for later compilation
        wrapper._task_config = fluent
        
        # Allow chaining on the decorator itself
        wrapper.when = lambda cond: fluent.when(cond) and wrapper
        wrapper.guards = lambda *g: fluent.guards(*g) and wrapper
        wrapper.depends_on = lambda *d: fluent.depends_on(*d) and wrapper
        wrapper.fail_if = lambda c, m=None: fluent.fail_if(c, m) and wrapper
        wrapper.skip_if = lambda c, r=None: fluent.skip_if(c, r) and wrapper
        
        return wrapper
    
    return decorator
```

### Layer 3: Translation Layer (~100 lines)

```python
# gleitzeit/workflow/translator.py

class ConditionTranslator:
    """Translates lambda conditions to executable expressions"""
    
    @staticmethod
    def translate_lambda(lambda_func) -> str:
        """Convert lambda to expression string"""
        # Get source
        source = inspect.getsource(lambda_func).strip()
        
        # Extract expression after 'lambda c:'
        expr = source.split(':', 1)[1].strip()
        
        # Transform c.task.field to ${task.field}
        import re
        expr = re.sub(r'c\.(\w+)', r'${\1}', expr)
        
        return expr

class WorkflowCompiler:
    """Compiles simplified workflow to Gleitzeit format"""
    
    def compile(self, workflow_def) -> Workflow:
        """Main compilation entry point"""
        
        if hasattr(workflow_def, 'to_workflow'):
            # Already a workflow wrapper
            return workflow_def.to_workflow()
        
        if hasattr(workflow_def, '_compiled_tasks'):
            # Decorated class
            return Workflow(tasks=workflow_def._compiled_tasks)
        
        # Direct task list
        all_tasks = []
        for item in workflow_def:
            if isinstance(item, FluentTask):
                all_tasks.extend(item._compile())
            elif isinstance(item, Task):
                all_tasks.append(item)
        
        return Workflow(tasks=all_tasks)
```

### Layer 4: Integration (~50 lines)

```python
# gleitzeit/workflow/__init__.py

from .builder import FluentTask
from .decorators import workflow, task
from .translator import WorkflowCompiler

class UltimateClient:
    """Extended client with fluent support"""
    
    def __init__(self, base_client: GleitzeitClient):
        self.client = base_client
        self.compiler = WorkflowCompiler()
    
    async def run(self, workflow_def, **inputs):
        """Run a workflow defined with decorators/fluent API"""
        
        # Compile to standard Gleitzeit workflow
        workflow = self.compiler.compile(workflow_def)
        
        # Submit using standard client
        return await self.client.submit_workflow(workflow, inputs=inputs)

# Convenience functions
def flow(*tasks) -> Workflow:
    """Create workflow from fluent tasks"""
    compiler = WorkflowCompiler()
    return compiler.compile(tasks)

async def run_workflow(workflow_class: Type, **inputs):
    """Instantiate and run a decorated workflow class"""
    instance = workflow_class()
    client = UltimateClient(GleitzeitClient())
    return await client.run(instance, **inputs)
```

## Usage Example

```python
from gleitzeit.workflow import workflow, task, run_workflow

@workflow
class MyWorkflow:
    
    @task("api/v1", "fetch")
    def get_data(self):
        return self.when(lambda c: c.input.url != None) \
                   .params(url="${input.url}") \
                   .timeout(30)
    
    @task("processor/v1", "process")
    def process(self):
        return self.depends_on(self.get_data) \
                   .when(lambda c: c.get_data.status == 200) \
                   .fail_if(lambda c: c.get_data.size > 1000000, "Too large")

# Run it
result = await run_workflow(MyWorkflow, url="https://example.com")
```

## Total Implementation Effort

### Core Components (1-2 days)
- FluentTask builder: ~200 lines ✓
- Decorator system: ~150 lines ✓  
- Translation layer: ~100 lines ✓
- Integration: ~50 lines ✓
- **Total: ~500 lines of code**

### Additional Features (1-2 days)
- Switch/case support
- Parallel execution helpers
- Retry configuration
- Event handlers
- **Total: ~300 lines**

### Testing & Documentation (1 day)
- Unit tests: ~500 lines
- Integration tests: ~300 lines
- Documentation: ~200 lines

## Why It's Not Hard

1. **Gleitzeit is Already Task-Based**
   - No fundamental architecture changes needed
   - Just a translation layer on top

2. **Clean Separation**
   - Wrapper is a separate package
   - Doesn't modify core Gleitzeit
   - Can evolve independently

3. **Simple Translation**
   - Fluent API → Task objects (straightforward)
   - Lambdas → Expressions (regex transformation)
   - Decorators → Method collection (standard Python)

4. **Existing Infrastructure**
   - Parameter resolution already works
   - Dependency tracking already works
   - Execution engine unchanged

## Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Lambda serialization | Convert to expression strings at compile time |
| Decorator stacking | Collect all decorators in metaclass |
| Type safety | Use Protocol types and generics |
| Backward compatibility | Separate package, no core changes |
| Debugging | Keep mapping of fluent→tasks for debugging |

## Implementation Plan

### Phase 1: Basic Wrapper (Day 1)
```python
# This alone would be useful
task = FluentTask("api/v1", "fetch") \
    .when("input.valid") \
    .params(url="${input.url}")

workflow = flow(task)
client.submit_workflow(workflow)
```

### Phase 2: Decorators (Day 2)
```python
@workflow
class MyFlow:
    @task("api/v1", "fetch")
    def get_data(self): ...
```

### Phase 3: Advanced Features (Day 3)
- Switch/case patterns
- Parallel execution
- Retry strategies

### Phase 4: Polish (Day 4)
- Type hints
- IDE support
- Documentation

## Conclusion

**Difficulty: 3/10** - This is a straightforward wrapper that:

1. **Requires ~800 lines** of production code
2. **Takes 3-5 days** for a complete implementation
3. **No core changes** to Gleitzeit needed
4. **High value** - Makes workflows 80% more concise
5. **Low risk** - Just a translation layer

The wrapper is essentially a **compiler** that transforms nice syntax into standard Gleitzeit tasks. Since Gleitzeit already does all the hard work (execution, persistence, retries), we just need to generate the right Task objects!