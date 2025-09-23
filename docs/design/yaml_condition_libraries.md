# Python Libraries for YAML Condition Evaluation

## Overview

This document evaluates Python libraries that can be used for safe condition evaluation in YAML-based workflows, particularly relevant for Gleitzeit's validation task implementation.

## 1. Expression Query Languages

### JMESPath

**What it is**: A query language for JSON/dict structures, widely used by AWS.

```python
import jmespath
import yaml

# Example: Evaluating conditions on YAML data
data = yaml.safe_load("""
order:
  total: 1500
  customer:
    type: premium
    region: US
""")

# Simple comparison
result = jmespath.search('order.total > `1000`', data)
# Note: JMESPath doesn't directly support comparisons, 
# but can extract values for comparison

total = jmespath.search('order.total', data)
condition_met = total > 1000  # True

# Complex extraction
customer_type = jmespath.search('order.customer.type', data)
is_premium = customer_type == 'premium'
```

**Pros:**
- Industry standard (AWS, Azure, Oracle)
- Well-documented
- Cross-language support
- Safe - no code execution

**Cons:**
- Limited to data extraction, not full condition evaluation
- Requires additional logic for comparisons
- No native boolean operators

### JSONPath

**What it is**: XPath for JSON, alternative to JMESPath.

```python
from jsonpath_ng import parse
import yaml

data = yaml.safe_load("""...""")
jsonpath_expr = parse('$.order.total')
matches = jsonpath_expr.find(data)
total = matches[0].value if matches else None
```

**Pros:**
- Familiar XPath-like syntax
- Good for nested data extraction

**Cons:**
- Less feature-rich than JMESPath
- Also focused on extraction, not evaluation

## 2. Safe Expression Evaluators

### SimpleEval

**What it is**: Safe, sandboxed expression evaluator.

```python
from simpleeval import SimpleEval
import yaml

# Load YAML workflow
workflow = yaml.safe_load("""
tasks:
  - id: validate
    condition: "order_total > 1000 and customer_type == 'premium'"
    params:
      order_total: 1500
      customer_type: premium
""")

# Evaluate condition
evaluator = SimpleEval()
task = workflow['tasks'][0]

# Evaluate with context
result = evaluator.eval(
    task['condition'],
    names=task['params']
)
print(result)  # True

# Custom functions
def is_weekend(day):
    return day in ['Saturday', 'Sunday']

evaluator.functions['is_weekend'] = is_weekend
result = evaluator.eval("is_weekend('Monday')")
```

**Pros:**
- Designed for safety
- Supports math, logic, comparisons
- Extensible with custom functions
- Good performance
- Simple API

**Cons:**
- Limited to expressions (no statements)
- Python-specific syntax

### ASTEval

**What it is**: Safe Python expression evaluator using AST.

```python
from asteval import Interpreter
import yaml

workflow = yaml.safe_load("""
conditions:
  - expression: "size > 1000 and status == 'active'"
    context:
      size: 1500
      status: active
""")

aeval = Interpreter()
for condition in workflow['conditions']:
    # Set context variables
    for key, value in condition['context'].items():
        aeval.symtable[key] = value
    
    # Evaluate expression
    result = aeval(condition['expression'])
    print(f"Result: {result}")
```

**Pros:**
- More Python features than SimpleEval
- Security audited
- Good for scientific computing
- Supports numpy operations

**Cons:**
- Slower than SimpleEval (4x slower than native)
- More complex API
- Potential numpy segfaults

## 3. Template Engines with Conditions

### Jinja2

**What it is**: Powerful templating engine with expression evaluation.

```python
from jinja2 import Environment, BaseLoader
import yaml

# YAML with Jinja2 expressions
yaml_template = """
tasks:
  - id: process_large
    {% if order_total > 1000 %}
    enabled: true
    {% else %}
    enabled: false
    {% endif %}
    condition: "{{ order_total > 1000 and customer_type == 'premium' }}"
"""

# Render with context
env = Environment(loader=BaseLoader())
template = env.from_string(yaml_template)
rendered = template.render(
    order_total=1500,
    customer_type='premium'
)

# Parse rendered YAML
workflow = yaml.safe_load(rendered)
print(workflow['tasks'][0]['enabled'])  # True
```

**Jinja2 for In-YAML Conditions:**

```python
from jinja2 import Environment, select_autoescape
import yaml

class ConditionalYAMLEvaluator:
    def __init__(self):
        self.env = Environment(
            autoescape=select_autoescape(),
            # Restrict available functions for safety
            globals={
                'len': len,
                'min': min,
                'max': max,
                'abs': abs,
            }
        )
    
    def evaluate_condition(self, expression: str, context: dict) -> bool:
        """Safely evaluate a Jinja2 expression"""
        template = self.env.from_string(f"{{{{ {expression} }}}}")
        result = template.render(**context)
        return result.lower() == 'true'

# Usage in YAML
yaml_workflow = """
tasks:
  - id: validate_order
    condition: "order.total > 1000 and customer.type == 'premium'"
    context_from: previous_task
"""

evaluator = ConditionalYAMLEvaluator()
workflow = yaml.safe_load(yaml_workflow)

context = {
    'order': {'total': 1500},
    'customer': {'type': 'premium'}
}

for task in workflow['tasks']:
    if 'condition' in task:
        result = evaluator.evaluate_condition(
            task['condition'], 
            context
        )
        print(f"Task {task['id']}: {result}")
```

**Pros:**
- Very powerful
- Industry standard
- Good documentation
- Supports complex logic

**Cons:**
- Designed for templates, not pure expressions
- Can be overpowered for simple conditions
- Requires careful security configuration

## 4. Specialized Rule Engines

### Python Rules Engines

Several Python rules engines can work with YAML:

```python
# Example using py-rules-engine (conceptual)
import yaml
from rules_engine import RulesEngine

rules_yaml = """
rules:
  - name: large_order_check
    condition:
      all:
        - field: order_total
          operator: greater_than
          value: 1000
        - field: customer_type
          operator: equals
          value: premium
    action: process_premium_order
"""

rules = yaml.safe_load(rules_yaml)
engine = RulesEngine(rules['rules'])
result = engine.evaluate({'order_total': 1500, 'customer_type': 'premium'})
```

## 5. Comparison for Gleitzeit

| Library | Safety | Performance | YAML-Native | Complexity | Best For |
|---------|--------|-------------|-------------|------------|----------|
| **SimpleEval** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ❌ | Low | Simple expressions |
| **ASTEval** | ⭐⭐⭐⭐ | ⭐⭐ | ❌ | Medium | Complex math |
| **JMESPath** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ❌ | Low | Data extraction |
| **Jinja2** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | High | Templates |
| **Custom AST** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ | High | Full control |

## Recommended Approach for Gleitzeit

### Option 1: SimpleEval for Validation Tasks (RECOMMENDED)

```python
# In ValidationHandler
from simpleeval import SimpleEval

class ValidationHandler(BaseHandler):
    def __init__(self):
        self.evaluator = SimpleEval()
        # Add safe functions
        self.evaluator.functions = {
            'len': len,
            'abs': abs,
            'min': min,
            'max': max,
            'now': datetime.now,
            'timedelta': timedelta,
        }
    
    async def _evaluate_condition(self, expression: str, context: dict) -> bool:
        """Safely evaluate condition"""
        try:
            result = self.evaluator.eval(expression, names=context)
            return bool(result)
        except Exception as e:
            logger.error(f"Condition evaluation failed: {e}")
            return False
```

### Option 2: JMESPath for Data Extraction + Python for Logic

```python
import jmespath

class ValidationHandler(BaseHandler):
    async def _evaluate_condition(self, condition: dict, context: dict) -> bool:
        """Evaluate using JMESPath extraction + Python logic"""
        
        # Extract values
        left = jmespath.search(condition['left'], context)
        right = jmespath.search(condition['right'], context)
        
        # Apply operator
        operator = condition['operator']
        if operator == '>':
            return left > right
        elif operator == '==':
            return left == right
        # etc.
```

### Option 3: Custom DSL with AST

```python
import ast
import operator

class SafeConditionEvaluator:
    """Custom condition evaluator using Python AST"""
    
    ALLOWED_OPERATORS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.And: lambda x, y: x and y,
        ast.Or: lambda x, y: x or y,
        ast.Not: operator.not_,
    }
    
    def evaluate(self, expression: str, context: dict) -> bool:
        """Safely evaluate expression"""
        tree = ast.parse(expression, mode='eval')
        return self._eval_node(tree.body, context)
    
    def _eval_node(self, node, context):
        # Safe AST evaluation implementation
        # ...
```

## Conclusion

For Gleitzeit's validation tasks:

1. **SimpleEval** is the best choice for general expression evaluation:
   - Safe by design
   - Simple API
   - Good performance
   - Supports all needed operators

2. **JMESPath** is ideal if you need complex data extraction:
   - Industry standard
   - AWS/cloud compatible
   - Very safe

3. **Custom AST** evaluator gives most control but requires more work:
   - Perfect safety
   - Exact feature set
   - Best performance

The recommendation is to use **SimpleEval** for the ValidationHandler implementation, as it provides the right balance of safety, simplicity, and features for evaluating conditions in YAML workflows.