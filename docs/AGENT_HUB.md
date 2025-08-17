# AgentHub Documentation

## Overview

The AgentHub is a new component in Gleitzeit that provides intelligent agent capabilities for orchestrating complex tasks. It follows Gleitzeit's established Hub architecture pattern and enables agents to plan, execute multi-step tasks, maintain conversation state, and leverage other Gleitzeit providers.

**Version**: 0.1.0 (Initial Implementation)  
**Status**: Implemented and Tested  
**Location**: `src/gleitzeit/hub/agent_hub.py`

## Architecture

### Design Philosophy

The AgentHub implementation follows these key principles:

1. **Hub Pattern Compliance**: Extends `ResourceHub` base class, consistent with OllamaHub and DockerHub
2. **Provider Orchestration**: Agents can leverage existing providers (LLM, Python, MCP) through ResourceManager
3. **Session Management**: Maintains conversation context across interactions
4. **Resource Management**: Built-in health checks, metrics, and lifecycle management

### System Integration

```
┌──────────────────────────────────────────────┐
│                Workflows                      │
│         (YAML definitions, CLI)               │
└────────────────┬─────────────────────────────┘
                 │ Uses
┌────────────────▼─────────────────────────────┐
│            ResourceManager                    │
│    (Orchestrates all hubs)                   │
└────────────────┬─────────────────────────────┘
                 │ Manages
┌────────────────▼─────────────────────────────┐
│              AgentHub                         │
│  • Agent instance management                  │
│  • Session persistence                        │
│  • Tool orchestration                         │
└────────────────┬─────────────────────────────┘
                 │ Uses
┌────────────────▼─────────────────────────────┐
│           Other Hubs                          │
│  • OllamaHub (LLM calls)                     │
│  • DockerHub (Python execution)              │
│  • MCPHub (External tools)                   │
└───────────────────────────────────────────────┘
```

## Agent Types

### 1. Research Agent
- **Purpose**: Gather and synthesize information on topics
- **Capabilities**: 
  - Multi-step planning
  - Information synthesis
  - Report generation
- **Method**: `agent/research`

### 2. Code Agent
- **Purpose**: Generate, test, and explain code
- **Capabilities**:
  - Code generation in multiple languages
  - Automatic testing (Python)
  - Code explanation
  - Error correction
- **Method**: `agent/code`

### 3. Chat Agent
- **Purpose**: Interactive conversation with memory
- **Capabilities**:
  - Session-based memory
  - Context awareness
  - Tool usage detection
- **Method**: `agent/chat`

### 4. Analysis Agent
- **Purpose**: Analyze content and answer questions
- **Capabilities**:
  - Content analysis
  - Question answering
  - Summary generation
- **Method**: `agent/analyze`

## Implementation Details

### Core Classes

#### AgentHub
```python
class AgentHub(ResourceHub[AgentConfig]):
    """
    Hub for managing agent instances
    Provides agent orchestration capabilities within Gleitzeit's architecture
    """
    
    def __init__(self, hub_id: str = "agent_hub", 
                 resource_manager: Optional[ResourceManager] = None,
                 max_agents: int = 10)
```

**Key Methods**:
- `execute_agent_task()`: Main entry point for agent execution
- `start_instance()`: Create new agent instance
- `stop_instance()`: Terminate agent instance
- `cleanup_sessions()`: Remove expired sessions
- `get_agent_status()`: Get detailed status information

#### AgentInstance
```python
class AgentInstance:
    """Represents a running agent instance"""
    
    def __init__(self, instance_id: str, 
                 config: AgentConfig,
                 resource_manager: Optional[ResourceManager] = None)
```

**Key Methods**:
- `execute()`: Execute agent method (research, code, chat, analyze)
- `_plan_steps()`: Generate execution plan using LLM
- `_execute_tool()`: Execute specific tool (LLM, Python, etc.)
- `_get_or_create_session()`: Manage conversation sessions

#### AgentConfig
```python
@dataclass
class AgentConfig:
    agent_type: AgentType
    model: str = "llama3.2"
    max_iterations: int = 10
    temperature: float = 0.7
    tools: List[str] = field(default_factory=lambda: ["llm", "python"])
    memory_enabled: bool = True
    session_ttl: int = 3600  # seconds
```

### Session Management

Sessions maintain conversation context and allow agents to remember previous interactions:

```python
@dataclass
class AgentSession:
    session_id: str
    agent_id: str
    created_at: datetime
    last_activity: datetime
    context: Dict[str, Any]  # Working memory
    history: List[Dict[str, Any]]  # Conversation history
    metadata: Dict[str, Any]  # Additional data
```

## Usage

### Python API

```python
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentHub

async def use_agents():
    # Initialize resource manager
    resource_manager = ResourceManager()
    await resource_manager.start()
    
    # Create required hubs
    await resource_manager.create_ollama_hub()  # For LLM
    agent_hub = await resource_manager.create_agent_hub()  # For agents
    
    # Execute research task
    result = await agent_hub.execute_agent_task(
        method="research",
        parameters={
            "topic": "quantum computing applications",
            "max_steps": 5
        }
    )
    print(result["report"])
    
    # Interactive chat with session
    session_id = "my_session"
    
    # First message
    response1 = await agent_hub.execute_agent_task(
        method="chat",
        parameters={
            "message": "What is machine learning?",
            "session_id": session_id
        }
    )
    
    # Follow-up (maintains context)
    response2 = await agent_hub.execute_agent_task(
        method="chat",
        parameters={
            "message": "Can you give me an example?",
            "session_id": session_id  # Same session
        }
    )
```

### Workflow YAML

```yaml
name: "Agent Workflow Example"
version: "1.0"

tasks:
  # Research task
  - id: "research"
    name: "Research Topic"
    protocol: "agent"
    method: "research"
    params:
      topic: "Benefits of automated testing"
      max_steps: 5
  
  # Generate code based on research
  - id: "generate_code"
    name: "Generate Code"
    protocol: "agent"
    method: "code"
    dependencies: ["research"]
    params:
      task: "Create test examples based on: ${research.report}"
      language: "python"
  
  # Analyze results
  - id: "analyze"
    name: "Analyze Results"
    protocol: "agent"
    method: "analyze"
    dependencies: ["research", "generate_code"]
    params:
      content: "${research.report}"
      code: "${generate_code.code}"
      question: "Is the code aligned with the research findings?"
```

## Current State & Limitations

### What's Working ✅

1. **Core Functionality**
   - All agent types (Research, Code, Chat, Analysis) implemented
   - Session management with persistent memory
   - Integration with ResourceManager
   - Health checks and metrics collection
   - Resource limits (max agents)
   - Session cleanup

2. **Testing**
   - 28 comprehensive tests all passing
   - Unit tests for AgentHub and AgentInstance
   - Integration tests with workflows
   - Session persistence tests
   - Resource limit tests

3. **Integration**
   - Works with existing Hub architecture
   - Can access OllamaHub for LLM calls
   - Can access DockerHub for Python execution
   - Compatible with workflow system

### Current Limitations ⚠️

1. **LLM Dependency**
   - Requires Ollama to be running for real execution
   - Falls back to mock responses in tests
   - Quality depends on underlying LLM model

2. **Tool Access**
   - Limited to providers available in ResourceManager
   - No direct web search (MCP provider needed)
   - Python execution requires DockerHub

3. **Planning Capabilities**
   - Planning quality depends on LLM
   - No sophisticated reasoning loop (like ReAct)
   - Limited error recovery in planning

4. **Memory Management**
   - Sessions are in-memory only (not persisted)
   - Memory grows with session history
   - No automatic context window management

5. **CLI Integration**
   - Not yet integrated into CLI commands
   - Workflows must use protocol: "agent"
   - No dedicated agent CLI commands

### Not Yet Implemented 🚧

1. **Advanced Features**
   - Tool learning/adaptation
   - Multi-agent collaboration
   - Long-term memory persistence
   - Custom agent types
   - Agent fine-tuning

2. **Production Features**
   - Distributed agent execution
   - Agent pooling/warming
   - Cost tracking
   - Rate limiting
   - Security sandboxing

## Testing

### Test Coverage

The implementation includes comprehensive test coverage:

```bash
# Run all agent tests
pytest tests/experimental/agents/test_agent_hub.py -v
pytest tests/workflows/test_agent_workflow.py -v

# Results: 28/28 tests passing
```

### Test Categories

1. **Unit Tests** (`test_agent_hub.py`)
   - AgentHub initialization
   - Agent instance lifecycle
   - Session management
   - Metrics collection
   - Resource limits

2. **Integration Tests** (`test_agent_workflow.py`)
   - Workflow execution
   - Dependency handling
   - Parameter substitution
   - Session persistence
   - Multi-agent scenarios

## Configuration

### Environment Variables
```bash
# No specific env vars required
# Uses standard Gleitzeit configuration
```

### Configuration File
```yaml
# ~/.gleitzeit/config.yaml
hubs:
  agent:
    max_agents: 10
    default_model: "llama3.2"
    session_ttl: 3600
    tools:
      - llm
      - python
```

## Metrics & Monitoring

### Available Metrics

Each agent tracks:
- `total_requests`: Number of tasks executed
- `total_steps`: Total planning steps taken
- `avg_steps_per_request`: Average steps per task
- `total_errors`: Number of failures
- `active_sessions`: Current session count

### Status Monitoring

```python
# Get agent hub status
status = await agent_hub.get_agent_status()

# Returns:
{
    "total_agents": 2,
    "max_agents": 10,
    "agents": [
        {
            "id": "agent_abc123",
            "type": "research",
            "model": "llama3.2",
            "metrics": {...},
            "sessions": 1
        }
    ]
}
```

## Best Practices

### 1. Session Management
- Use consistent session IDs for related conversations
- Clean up old sessions periodically
- Don't store sensitive data in sessions

### 2. Task Design
- Keep research topics focused
- Provide clear context for code generation
- Use specific questions for analysis

### 3. Resource Management
- Monitor agent count vs max_agents
- Clean up unused agents
- Set appropriate timeouts

### 4. Error Handling
- Check for "success" in results
- Handle empty reports gracefully
- Validate code generation results

## Migration Guide

### From Direct LLM Calls

**Before:**
```yaml
- id: "ask_llm"
  protocol: "llm"
  method: "chat"
  params:
    model: "llama3.2"
    messages:
      - role: "user"
        content: "Research quantum computing"
```

**After:**
```yaml
- id: "research_task"
  protocol: "agent"
  method: "research"
  params:
    topic: "quantum computing"
    max_steps: 5
```

### From Manual Workflow Orchestration

**Before:** Multiple separate LLM tasks with manual coordination

**After:** Single agent task with built-in planning and execution

## Troubleshooting

### Common Issues

1. **"No Ollama hub available"**
   - Ensure Ollama is running: `ollama serve`
   - Check ResourceManager has OllamaHub created

2. **"Maximum number of agents reached"**
   - Clean up unused agents
   - Increase max_agents limit
   - Reuse existing agents

3. **Session not maintaining context**
   - Verify same session_id is used
   - Check session hasn't expired
   - Ensure agent type supports sessions

4. **Code execution failing**
   - Verify DockerHub is available
   - Check Python provider is configured
   - Ensure Docker is running

## Future Roadmap

### Short Term (v0.2)
- [ ] CLI integration
- [ ] Persistent session storage
- [ ] Web search capability
- [ ] Better error recovery

### Medium Term (v0.3)
- [ ] Multi-agent collaboration
- [ ] Custom agent types
- [ ] Advanced planning (ReAct, CoT)
- [ ] Context window management

### Long Term (v1.0)
- [ ] Distributed execution
- [ ] Agent marketplace
- [ ] Fine-tuning support
- [ ] Production monitoring

## Contributing

### Adding New Agent Types

1. Define agent type in `AgentType` enum
2. Implement execution method in `AgentInstance`
3. Add tests for new agent type
4. Update documentation

### Improving Planning

The planning system uses LLM prompts in `_plan_steps()`. Improvements can be made by:
- Enhancing prompt engineering
- Adding validation logic
- Implementing retry mechanisms

## References

- [Gleitzeit Architecture](ARCHITECTURE.md)
- [Hub Development Guide](HUB_DEVELOPMENT.md)
- [ResourceHub Base Class](../src/gleitzeit/hub/base.py)
- [Test Suite](../tests/experimental/agents/)

## Support

For issues or questions:
1. Check this documentation
2. Review test examples
3. Open an issue on GitHub
4. Check Gleitzeit discussions

---

*Last Updated: August 2024*  
*Version: 0.1.0*  
*Status: Implemented and Tested*