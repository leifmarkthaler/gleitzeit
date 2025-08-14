# Python Provider Security Fix Strategy

## Current Security Issues

### 1. Direct `exec()` Usage
- **Problem**: Uses `exec()` with restricted globals but still allows arbitrary code execution
- **Risk**: Potential for code injection, resource exhaustion, system access attempts
- **Current Mitigation**: Limited builtins and modules, but not comprehensive

### 2. No Resource Limits
- **Problem**: No CPU time, memory, or output size limits
- **Risk**: Infinite loops, memory exhaustion, large output generation
- **Current Mitigation**: Basic timeout parameter (not enforced at OS level)

### 3. Limited Module Restrictions
- **Problem**: Allowed modules still have dangerous capabilities
- **Risk**: `time.sleep()` for DoS, `random.seed()` for reproducibility issues
- **Current Mitigation**: Whitelist of "safe" modules

## Proposed Security Strategy

### Option 1: RestrictedPython (RECOMMENDED)
**Use the RestrictedPython library for safe code execution**

```python
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import guarded_iter_unpack_sequence
from RestrictedPython.Guards import safe_builtins

def execute_restricted_code(code: str, context: dict, timeout: int = 5):
    # Compile code with restrictions
    byte_code = compile_restricted(code, '<string>', 'exec')
    
    # Create safe execution environment
    restricted_globals = {
        '__builtins__': safe_builtins,
        '_iter_unpack_sequence_': guarded_iter_unpack_sequence,
        '_getattr_': getattr,  # Can be customized for attribute access control
        'result': None,
        'print': RestrictedPrint(),  # Custom print that limits output
    }
    
    # Add safe modules with limited functionality
    restricted_globals.update({
        'math': SafeMath(),  # Wrapper with only safe math functions
        'json': SafeJSON(),  # Limited JSON operations
        'datetime': SafeDateTime(),  # Read-only datetime
    })
    
    # Execute with resource limits
    with timeout_context(timeout):
        with memory_limit(100 * 1024 * 1024):  # 100MB limit
            exec(byte_code, restricted_globals)
    
    return restricted_globals.get('result')
```

**Advantages:**
- Battle-tested library used by Zope/Plone
- Prevents dangerous operations at compile time
- Customizable security policies
- No direct access to file system, network, or processes

### Option 2: Docker/Container Isolation
**Run Python code in isolated containers**

```python
import docker
import tempfile
import json

class DockerPythonExecutor:
    def __init__(self):
        self.client = docker.from_env()
        self.image = "python:3.11-slim"
        
    async def execute_code(self, code: str, timeout: int = 5):
        # Create temporary file with code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Wrap code to capture result
            wrapped_code = f'''
import json
import sys

# User code
{code}

# Output result
if 'result' in locals():
    print(json.dumps({{"result": result}}))
'''
            f.write(wrapped_code)
            code_file = f.name
        
        try:
            # Run in container with strict limits
            container = self.client.containers.run(
                self.image,
                f"python /code/script.py",
                volumes={code_file: {'bind': '/code/script.py', 'mode': 'ro'}},
                mem_limit='100m',  # 100MB memory limit
                cpu_quota=50000,   # 50% CPU limit
                network_disabled=True,  # No network access
                read_only=True,    # Read-only filesystem
                remove=True,       # Auto-remove container
                timeout=timeout,
                stdout=True,
                stderr=True
            )
            
            # Parse result
            output = container.decode('utf-8')
            if output:
                return json.loads(output)
            return {"result": None}
            
        finally:
            os.unlink(code_file)
```

**Advantages:**
- Complete isolation from host system
- Resource limits enforced by kernel
- No possibility of escaping sandbox
- Can use any Python libraries safely

**Disadvantages:**
- Requires Docker
- Higher overhead
- More complex setup

### Option 3: AST-based Code Analysis & Execution
**Parse and validate code before execution**

```python
import ast
import sys
from io import StringIO

class SafePythonExecutor:
    # Whitelist of allowed AST node types
    ALLOWED_NODES = {
        # Literals and variables
        ast.Module, ast.Expr, ast.Load, ast.Store, ast.Del,
        ast.Constant, ast.Num, ast.Str, ast.Bytes, ast.NameConstant,
        ast.Name, ast.List, ast.Tuple, ast.Dict, ast.Set,
        
        # Operations
        ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
        ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd,
        ast.FloorDiv, ast.Not, ast.UAdd, ast.USub, ast.Eq, ast.NotEq,
        ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
        ast.And, ast.Or,
        
        # Control flow (limited)
        ast.If, ast.For, ast.While, ast.Break, ast.Continue,
        ast.ListComp, ast.DictComp, ast.SetComp,
        
        # Functions (limited)
        ast.Call, ast.keyword, ast.Return,
        
        # Assignment
        ast.Assign, ast.AugAssign,
    }
    
    # Whitelist of allowed function calls
    ALLOWED_CALLS = {
        'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
        'range', 'enumerate', 'zip', 'sum', 'min', 'max', 'abs', 'round',
        'sorted', 'reversed', 'any', 'all', 'print',
    }
    
    def validate_ast(self, node, depth=0):
        """Recursively validate AST nodes"""
        if depth > 100:  # Prevent deep recursion
            raise ValueError("Code too complex (max depth exceeded)")
        
        if type(node) not in self.ALLOWED_NODES:
            raise ValueError(f"Forbidden operation: {type(node).__name__}")
        
        # Check function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in self.ALLOWED_CALLS:
                    raise ValueError(f"Forbidden function: {node.func.id}")
        
        # Check imports (none allowed)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("Import statements not allowed")
        
        # Recursively validate child nodes
        for child in ast.iter_child_nodes(node):
            self.validate_ast(child, depth + 1)
    
    def execute_safe(self, code: str, timeout: int = 5):
        # Parse code into AST
        try:
            tree = ast.parse(code, mode='exec')
        except SyntaxError as e:
            return {"error": f"Syntax error: {e}", "success": False}
        
        # Validate AST
        try:
            self.validate_ast(tree)
        except ValueError as e:
            return {"error": str(e), "success": False}
        
        # Compile validated AST
        compiled = compile(tree, '<string>', 'exec')
        
        # Execute with restricted globals
        safe_globals = {
            '__builtins__': {
                'len': len, 'str': str, 'int': int, 'float': float,
                'bool': bool, 'list': list, 'dict': dict, 'set': set,
                'tuple': tuple, 'range': range, 'enumerate': enumerate,
                'zip': zip, 'sum': sum, 'min': min, 'max': max,
                'abs': abs, 'round': round, 'sorted': sorted,
                'reversed': reversed, 'any': any, 'all': all,
                'print': print,
            }
        }
        
        safe_locals = {}
        
        # Capture output
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            # Execute with timeout using signal (Unix only)
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Code execution timed out")
            
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)
            
            try:
                exec(compiled, safe_globals, safe_locals)
            finally:
                signal.alarm(0)  # Cancel alarm
            
            return {
                "result": safe_locals.get('result'),
                "output": captured_output.getvalue(),
                "success": True,
                "variables": {k: v for k, v in safe_locals.items() if not k.startswith('_')}
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "output": captured_output.getvalue(),
                "success": False
            }
        finally:
            sys.stdout = old_stdout
```

**Advantages:**
- Pure Python solution
- Fine-grained control over allowed operations
- Fast execution (no external processes)
- Good for simple computational tasks

**Disadvantages:**
- Complex to maintain
- May miss edge cases
- Limited functionality

## Recommended Implementation Plan

### Phase 1: Immediate Security Hardening (2 hours)
1. Implement AST validation (Option 3) as immediate fix
2. Add output size limits (max 10MB)
3. Add recursion depth limit
4. Remove dangerous builtins (getattr, setattr, hasattr)
5. Add memory monitoring with resource module

### Phase 2: Production Security (4-6 hours)
1. Integrate RestrictedPython (Option 1)
2. Add proper timeout enforcement using threading
3. Implement output sanitization
4. Add rate limiting per provider instance
5. Create security test suite

### Phase 3: Enterprise Security (Optional, 8+ hours)
1. Implement Docker isolation (Option 2) as optional backend
2. Add code signing and verification
3. Implement audit logging for all executions
4. Add security policy configuration (allow/deny lists)

## Security Test Cases

```python
# Test cases that should be blocked
dangerous_code = [
    # File system access
    "open('/etc/passwd', 'r').read()",
    "__import__('os').system('ls')",
    
    # Network access
    "__import__('urllib').request.urlopen('http://evil.com')",
    "__import__('socket').socket()",
    
    # Resource exhaustion
    "while True: pass",
    "[0] * (10**10)",
    
    # Introspection attacks
    "__builtins__.__import__('os')",
    "eval('__import__(\"os\")')",
    
    # Recursion bombs
    "def f(): f()\nf()",
]

# Test cases that should work
safe_code = [
    # Basic computation
    "result = sum([1, 2, 3, 4, 5])",
    
    # Data processing
    "result = [x**2 for x in range(10)]",
    
    # String manipulation
    "result = 'hello world'.upper()",
    
    # Math operations
    "import math\nresult = math.sqrt(16)",
]
```

## Migration Strategy

1. Create new `SecurePythonProvider` class alongside existing
2. Implement chosen security option
3. Add feature flag to switch between providers
4. Gradually migrate workflows to secure provider
5. Deprecate and remove old provider

## Configuration

```yaml
# providers/python_secure.yaml
provider:
  id: python-secure
  type: python/v2
  config:
    security_level: "restricted"  # restricted | isolated | container
    max_execution_time: 5
    max_memory_mb: 100
    max_output_size_mb: 10
    allowed_modules:
      - math
      - json
      - datetime
    denied_operations:
      - import
      - eval
      - exec
      - compile
    rate_limit:
      requests_per_minute: 60
      burst_size: 10
```

## Success Criteria

- [ ] No code can access file system
- [ ] No code can make network requests
- [ ] No code can import arbitrary modules
- [ ] No code can execute system commands
- [ ] No code can exhaust memory (>100MB)
- [ ] No code can run longer than timeout
- [ ] No code can cause stack overflow
- [ ] All safe computational code still works
- [ ] Performance overhead < 50ms per execution
- [ ] Clear error messages for security violations