# FIXME: Inline Code Execution Security Issue

## Issue
The PythonProvider currently allows inline code execution through the `code` parameter, which is a security vulnerability.

## Location
`src/gleitzeit/providers/python_provider.py` lines 139-146

## Current Behavior
```python
async def _execute_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a Python file or code"""
    file_path = params.get('file') or params.get('file_path')
    code = params.get('code')
    
    # If code is provided, create a temporary file
    if code and not file_path:
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
        temp_file.write(code)
        temp_file.close()
        file_path = temp_file.name
        is_temp = True
```

## Problem
- Allows arbitrary code execution via the `code` parameter
- Creates temporary files that could be exploited
- Bypasses file trust validation by marking temp files as trusted (line 179)

## Required Fix
1. Remove support for the `code` parameter entirely
2. Only allow execution of actual Python files that exist on disk
3. Enforce trust validation for all files without exceptions

## Security Impact
- **Severity**: HIGH
- **Risk**: Remote code execution vulnerability
- **Attack Vector**: Any client can execute arbitrary Python code by passing it in the `code` parameter

## Temporary Workaround
For testing purposes, create actual Python files in a trusted directory instead of using inline code.