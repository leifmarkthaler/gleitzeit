# Agent Workflow Execution Guide

## Current State of Agent Workflow Execution

This document describes how to execute agent workflows in the current Gleitzeit implementation.

## Prerequisites

### Required Components
1. **Gleitzeit Core**: Installed and configured
2. **Ollama** (for real execution): Running with appropriate models
3. **Docker** (optional): For Python code execution
4. **Python 3.8+**: For running Gleitzeit

### Check Installation
```bash
# Check Python
python --version

# Check Ollama (if using real LLMs)
ollama list

# Check Docker (if using code execution)
docker --version
```

## Workflow Definition

### Basic Agent Workflow Structure

```yaml
name: "My Agent Workflow"
version: "1.0"
description: "Workflow using agents"

tasks:
  # Agent task definition
  - id: "task_id"
    name: "Task Name"
    protocol: "agent"  # MUST be "agent" for agent tasks
    method: "research|code|chat|analyze"  # Choose one
    params:
      # Method-specific parameters
    dependencies: []  # Optional task dependencies
```

### Available Agent Methods

#### 1. Research Method
```yaml
- id: "research_task"
  name: "Research Topic"
  protocol: "agent"
  method: "research"
  params:
    topic: "Your research topic"
    max_steps: 5  # Number of research steps
    session_id: "optional_session_id"
```

#### 2. Code Method
```yaml
- id: "code_task"
  name: "Generate Code"
  protocol: "agent"
  method: "code"
  params:
    task: "Description of code to generate"
    language: "python"  # Programming language
    context: "Optional context or requirements"
```

#### 3. Chat Method
```yaml
- id: "chat_task"
  name: "Chat Interaction"
  protocol: "agent"
  method: "chat"
  params:
    message: "Your message"
    session_id: "session_123"  # Important for context
```

#### 4. Analyze Method
```yaml
- id: "analyze_task"
  name: "Analyze Content"
  protocol: "agent"
  method: "analyze"
  params:
    content: "Content to analyze"
    question: "Specific question about the content"
```

## Execution Methods

### Method 1: Python Script (Recommended for Testing)

```python
#!/usr/bin/env python
"""Execute agent workflow programmatically"""

import asyncio
import yaml
from pathlib import Path

from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentHub

async def run_agent_workflow():
    # Initialize resource manager
    resource_manager = ResourceManager("workflow-manager")
    await resource_manager.start()
    
    # Create necessary hubs
    try:
        # Ollama hub for LLM (will auto-discover local Ollama)
        ollama_hub = await resource_manager.create_ollama_hub()
        print(f"✓ Ollama hub created")
    except Exception as e:
        print(f"⚠ Ollama hub failed: {e}")
        print("  Agents will use mock responses")
    
    # Create agent hub
    agent_hub = await resource_manager.create_agent_hub(max_agents=5)
    print(f"✓ Agent hub created")
    
    # Execute agent task
    result = await agent_hub.execute_agent_task(
        method="chat",
        parameters={
            "message": "Hello! What can you help me with?",
            "session_id": "demo_session"
        }
    )
    
    print(f"\nAgent Response: {result.get('response', 'No response')}")
    
    # Cleanup
    await resource_manager.stop()

if __name__ == "__main__":
    asyncio.run(run_agent_workflow())
```

### Method 2: Direct Workflow Execution

```python
import asyncio
from gleitzeit.core.workflow_loader import load_workflow_from_file
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter

async def execute_workflow_file(workflow_path: str):
    # Initialize components
    persistence = UnifiedPersistenceAdapter()
    await persistence.initialize()
    
    resource_manager = ResourceManager()
    await resource_manager.start()
    
    # Create hubs
    await resource_manager.create_ollama_hub()
    await resource_manager.create_agent_hub()
    
    # Create execution engine
    engine = ExecutionEngine(
        persistence=persistence,
        resource_manager=resource_manager
    )
    
    # Load and execute workflow
    workflow = load_workflow_from_file(workflow_path)
    execution = await engine.execute_workflow(workflow)
    
    print(f"Workflow Status: {execution.status}")
    
    # Cleanup
    await engine.stop()
    await resource_manager.stop()

# Run
asyncio.run(execute_workflow_file("my_agent_workflow.yaml"))
```

### Method 3: CLI Execution (Limited Support)

**Note**: CLI support for agents is limited. The workflow must be properly formatted.

```bash
# Basic command structure (may not work fully)
python src/gleitzeit/cli/gleitzeit_cli.py run agent_workflow.yaml
```

## Complete Example Workflows

### Example 1: Simple Q&A Workflow

```yaml
# simple_qa.yaml
name: "Simple Q&A"
version: "1.0"

tasks:
  - id: "question"
    name: "Ask Question"
    protocol: "agent"
    method: "chat"
    params:
      message: "What are the benefits of Python programming?"
      session_id: "qa_session"
  
  - id: "followup"
    name: "Follow-up"
    protocol: "agent"
    method: "chat"
    dependencies: ["question"]
    params:
      message: "Can you give me 3 specific examples?"
      session_id: "qa_session"  # Same session for context
```

### Example 2: Research and Code Generation

```yaml
# research_and_code.yaml
name: "Research and Code"
version: "1.0"

tasks:
  - id: "research"
    name: "Research Topic"
    protocol: "agent"
    method: "research"
    params:
      topic: "Best practices for Python unit testing"
      max_steps: 3
  
  - id: "generate"
    name: "Generate Code"
    protocol: "agent"
    method: "code"
    dependencies: ["research"]
    params:
      task: "Create unit test examples based on: ${research.report}"
      language: "python"
  
  - id: "review"
    name: "Review Code"
    protocol: "agent"
    method: "analyze"
    dependencies: ["generate"]
    params:
      content: "${generate.code}"
      question: "Does this follow the best practices from the research?"
```

### Example 3: Multi-Stage Analysis

```yaml
# analysis_pipeline.yaml
name: "Analysis Pipeline"
version: "1.0"

tasks:
  - id: "initial_analysis"
    name: "Initial Analysis"
    protocol: "agent"
    method: "analyze"
    params:
      content: |
        Python is a high-level programming language.
        It emphasizes code readability and simplicity.
        Python supports multiple programming paradigms.
      question: "What are the key characteristics mentioned?"
  
  - id: "deep_dive"
    name: "Deep Analysis"
    protocol: "agent"
    method: "research"
    dependencies: ["initial_analysis"]
    params:
      topic: "Details about: ${initial_analysis.analysis}"
      max_steps: 5
  
  - id: "summary"
    name: "Create Summary"
    protocol: "agent"
    method: "analyze"
    dependencies: ["initial_analysis", "deep_dive"]
    params:
      content: "${deep_dive.report}"
      question: "Create a comprehensive summary of all findings"
```

## Testing and Validation

### Test Execution Script

```python
# test_agents.py
import asyncio
from gleitzeit.hub.resource_manager import ResourceManager

async def test_agents():
    """Test agent functionality"""
    
    resource_manager = ResourceManager()
    await resource_manager.start()
    
    # Create agent hub (Ollama optional)
    agent_hub = await resource_manager.create_agent_hub()
    
    # Test different agent types
    tests = [
        ("chat", {"message": "Hello!", "session_id": "test"}),
        ("research", {"topic": "Python", "max_steps": 2}),
        ("code", {"task": "Hello world function", "language": "python"}),
        ("analyze", {"content": "Test content", "question": "What is this?"})
    ]
    
    for method, params in tests:
        print(f"\nTesting {method}...")
        try:
            result = await agent_hub.execute_agent_task(
                method=method,
                parameters=params
            )
            print(f"✓ {method} successful")
            if "response" in result:
                print(f"  Response: {result['response'][:100]}...")
            elif "report" in result:
                print(f"  Report: {result['report'][:100]}...")
            elif "code" in result:
                print(f"  Code generated: {len(result['code'])} chars")
        except Exception as e:
            print(f"✗ {method} failed: {e}")
    
    await resource_manager.stop()

asyncio.run(test_agents())
```

## Execution Results

### Expected Output Structure

#### Research Method Output
```python
{
    "report": "Comprehensive research report...",
    "steps_executed": 5,
    "session_id": "research_session_abc123",
    "success": True
}
```

#### Code Method Output
```python
{
    "code": "def example():\n    return 'Hello'",
    "explanation": "This function...",
    "language": "python",
    "test_result": {"success": True, "output": "..."}
}
```

#### Chat Method Output
```python
{
    "response": "Agent's response to your message",
    "session_id": "chat_session_123",
    "tools_used": False
}
```

#### Analyze Method Output
```python
{
    "analysis": "Detailed analysis of the content...",
    "question": "Original question",
    "success": True
}
```

## Troubleshooting

### Common Issues and Solutions

#### 1. "No Ollama hub available"
**Problem**: Ollama is not running or not accessible  
**Solution**: 
- Start Ollama: `ollama serve`
- Agents will use mock responses if Ollama unavailable

#### 2. "Maximum number of agents reached"
**Problem**: Too many agent instances created  
**Solution**:
- Increase limit: `create_agent_hub(max_agents=20)`
- Clean up sessions: `agent_hub.cleanup_sessions()`

#### 3. Session context not maintained
**Problem**: Different session IDs used  
**Solution**: Use consistent session_id across related tasks

#### 4. Workflow execution fails
**Problem**: Incorrect workflow format  
**Solution**: Ensure protocol: "agent" and valid method names

### Debug Mode

Enable verbose logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Performance Considerations

### With Mock Providers (Testing)
- Response time: <50ms per task
- Memory usage: Minimal
- Concurrent tasks: Unlimited

### With Real Ollama
- Response time: 1-10s per task (depends on model)
- Memory usage: Depends on model size
- Concurrent tasks: Limited by Ollama

### Optimization Tips
1. Reuse session IDs for related tasks
2. Limit max_steps for research tasks
3. Use appropriate models for tasks
4. Clean up old sessions periodically

## Current Limitations

1. **CLI Integration**: Limited CLI support, use Python API
2. **Session Persistence**: Sessions are in-memory only
3. **Error Recovery**: Limited automatic retry
4. **Tool Access**: Only tools available through ResourceManager
5. **Cost Tracking**: No LLM usage tracking

## Summary

The agent workflow system is functional and tested but requires:
- Ollama for real LLM execution (falls back to mocks)
- Python API for best experience (CLI limited)
- Proper workflow formatting with protocol: "agent"
- Session ID management for conversational context

For production use, consider:
- Implementing session persistence
- Adding monitoring and metrics
- Setting up proper error handling
- Configuring resource limits

---

*Last Updated: August 17, 2024*  
*Status: Functional with limitations*  
*Recommended: Use Python API for execution*