#!/usr/bin/env python3
"""
Demo script for ShellProvider

Shows how to use the ShellProvider from Python code
for system administration and DevOps tasks.
"""

import asyncio
import json
from pathlib import Path
from gleitzeit import GleitzeitClient
from gleitzeit.providers import ShellProvider


async def basic_shell_examples():
    """Basic shell command examples"""
    
    async with GleitzeitClient(mode="native") as client:
        print("=== Basic Shell Command Examples ===\n")
        
        # Simple command
        result = await client.execute_task({
            "id": "hello",
            "method": "shell/exec",
            "parameters": {
                "command": "echo",
                "args": ["Hello from ShellProvider!"]
            }
        })
        print(f"Echo result: {result.output['stdout']}")
        
        # Command with environment variables
        result = await client.execute_task({
            "id": "env_test",
            "method": "shell/exec",
            "parameters": {
                "command": "echo",
                "args": ["Running in $ENV_MODE mode"],
                "env": {"ENV_MODE": "production"}
            }
        })
        print(f"Env result: {result.output['stdout']}")
        
        # Get system information
        result = await client.execute_task({
            "id": "sys_info",
            "method": "shell/exec",
            "parameters": {
                "command": "uname",
                "args": ["-a"]
            }
        })
        print(f"System: {result.output['stdout'].strip()}")


async def piped_commands_example():
    """Example using piped commands"""
    
    async with GleitzeitClient(mode="native") as client:
        print("\n=== Piped Commands Example ===\n")
        
        # Count Python files in current directory
        result = await client.execute_task({
            "id": "count_py_files",
            "method": "shell/pipe",
            "parameters": {
                "commands": [
                    "find . -name '*.py' -type f",
                    "head -20",
                    "wc -l"
                ]
            }
        })
        
        count = result.output['stdout'].strip()
        print(f"Found {count} Python files (showing first 20)")
        
        # Process list filtering
        result = await client.execute_task({
            "id": "python_processes",
            "method": "shell/pipe",
            "parameters": {
                "commands": [
                    "ps aux",
                    "grep python",
                    "grep -v grep",
                    "wc -l"
                ]
            }
        })
        
        print(f"Python processes running: {result.output['stdout'].strip()}")


async def batch_execution_example():
    """Example of batch command execution"""
    
    async with GleitzeitClient(mode="native") as client:
        print("\n=== Batch Execution Example ===\n")
        
        # Setup project structure
        result = await client.execute_task({
            "id": "setup_project",
            "method": "shell/batch",
            "parameters": {
                "commands": [
                    "mkdir -p /tmp/demo_project/src",
                    "mkdir -p /tmp/demo_project/tests",
                    "mkdir -p /tmp/demo_project/docs",
                    "echo '# Demo Project' > /tmp/demo_project/README.md",
                    "echo 'print(\"Hello\")' > /tmp/demo_project/src/main.py",
                    "ls -la /tmp/demo_project"
                ],
                "stop_on_error": True
            }
        })
        
        if result.output['success']:
            print("✅ Project structure created successfully")
            print(f"Executed {result.output['executed']} of {result.output['total']} commands")
        else:
            print("❌ Project setup failed")
            
        # Cleanup
        await client.execute_task({
            "id": "cleanup",
            "method": "shell/exec",
            "parameters": {
                "command": "rm",
                "args": ["-rf", "/tmp/demo_project"]
            }
        })


async def json_processing_example():
    """Example of JSON data processing with shell commands"""
    
    async with GleitzeitClient(mode="native") as client:
        print("\n=== JSON Processing Example ===\n")
        
        # Generate JSON data
        data = {
            "users": [
                {"id": 1, "name": "Alice", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
                {"id": 3, "name": "Charlie", "role": "user"}
            ],
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        # Echo JSON (will be auto-parsed)
        result = await client.execute_task({
            "id": "json_data",
            "method": "shell/exec",
            "parameters": {
                "command": "echo",
                "args": [json.dumps(data)]
            }
        })
        
        # The output is automatically parsed as JSON
        parsed_data = result.output['output']
        print(f"Users in system: {len(parsed_data['users'])}")
        for user in parsed_data['users']:
            print(f"  - {user['name']} ({user['role']})")


async def secure_execution_example():
    """Example with security restrictions"""
    
    # Create provider with security restrictions
    secure_provider = ShellProvider(
        provider_id="secure-shell",
        allowed_commands=["echo", "ls", "cat", "grep", "wc"],
        blocked_commands=["rm", "dd", "curl", "wget"],
        allowed_dirs=["/tmp", str(Path.home() / "Downloads")],
        sandbox_mode="restricted",
        timeout=10
    )
    
    async with GleitzeitClient(mode="native") as client:
        # Register the secure provider
        client.registry.register_provider("shell/v1", secure_provider)
        
        print("\n=== Secure Execution Example ===\n")
        
        # This should work (echo is allowed)
        try:
            result = await client.execute_task({
                "id": "allowed_cmd",
                "method": "shell/exec",
                "parameters": {
                    "command": "echo",
                    "args": ["This is allowed"]
                }
            })
            print(f"✅ Allowed command succeeded: {result.output['stdout'].strip()}")
        except Exception as e:
            print(f"❌ Command failed: {e}")
        
        # This should fail (wget is blocked)
        try:
            result = await client.execute_task({
                "id": "blocked_cmd",
                "method": "shell/exec",
                "parameters": {
                    "command": "wget",
                    "args": ["http://example.com"]
                }
            })
            print("Command succeeded (unexpected)")
        except Exception as e:
            print(f"✅ Blocked command rejected: wget not in allowlist")
        
        # This should fail (rm is dangerous)
        try:
            result = await client.execute_task({
                "id": "dangerous_cmd",
                "method": "shell/exec",
                "parameters": {
                    "command": "rm",
                    "args": ["-rf", "/tmp/test"]
                }
            })
            print("Command succeeded (unexpected)")
        except Exception as e:
            print(f"✅ Dangerous command blocked: rm is forbidden")


async def git_workflow_example():
    """Example Git workflow using shell commands"""
    
    async with GleitzeitClient(mode="native") as client:
        print("\n=== Git Workflow Example ===\n")
        
        # Check if git is available
        result = await client.execute_task({
            "id": "check_git",
            "method": "shell/exec",
            "parameters": {
                "command": "which",
                "args": ["git"]
            }
        })
        
        if result.output['success']:
            print("✅ Git is available")
            
            # Get git status
            result = await client.execute_task({
                "id": "git_status",
                "method": "shell/exec",
                "parameters": {
                    "command": "git",
                    "args": ["status", "--short"]
                }
            })
            
            if result.output['stdout']:
                print(f"Git status:\n{result.output['stdout']}")
            else:
                print("Working directory is clean")
            
            # Get current branch
            result = await client.execute_task({
                "id": "git_branch",
                "method": "shell/exec",
                "parameters": {
                    "command": "git",
                    "args": ["branch", "--show-current"]
                }
            })
            
            print(f"Current branch: {result.output['stdout'].strip()}")
            
            # Get last commit
            result = await client.execute_task({
                "id": "last_commit",
                "method": "shell/exec",
                "parameters": {
                    "command": "git",
                    "args": ["log", "-1", "--oneline"]
                }
            })
            
            print(f"Last commit: {result.output['stdout'].strip()}")
        else:
            print("❌ Git is not available")


async def main():
    """Run all examples"""
    
    print("🚀 ShellProvider Demo\n")
    print("=" * 50)
    
    # Initialize providers
    shell_provider = ShellProvider(
        provider_id="shell",
        sandbox_mode="none",  # For demo purposes
        timeout=30
    )
    
    # Run examples
    await basic_shell_examples()
    await piped_commands_example()
    await batch_execution_example()
    await json_processing_example()
    await secure_execution_example()
    await git_workflow_example()
    
    print("\n" + "=" * 50)
    print("✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(main())