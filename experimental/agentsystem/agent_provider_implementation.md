# Agent Provider Implementation Plan

## Executive Summary

This document outlines a practical implementation of agents as a Gleitzeit provider. The Agent Provider pattern treats agents as specialized providers that can internally orchestrate multiple tool calls without workflow overhead, while still being usable within workflows for complex multi-agent scenarios.

**IMPORTANT NOTE**: This implementation requires modifications to Gleitzeit's core architecture. The current registry does not support providers accessing other providers directly. This document represents a proposed enhancement, not something immediately implementable with the current codebase.

## Core Architecture

### Design Principles

1. **Agents as Providers**: Agents are implemented as a provider type, not a new system
2. **Internal Orchestration**: Agents handle their own multi-step logic internally
3. **Workflow Compatible**: Agents can be used in workflows like any other provider
4. **Minimal Core Changes**: Only need registry access in providers
5. **Progressive Enhancement**: Start simple, add capabilities incrementally

### System Integration

```
┌────────────────────────────────────────┐
│            Workflows (Optional)         │
│     Can orchestrate multiple agents     │
└────────────────┬───────────────────────┘
                 │ Uses
┌────────────────▼───────────────────────┐
│          Agent Provider                 │
│  • Planning & Reasoning                 │
│  • Memory Management                    │
│  • Tool Orchestration                   │
└────────────────┬───────────────────────┘
                 │ Calls directly
┌────────────────▼───────────────────────┐
│     Other Providers (Tools)             │
│  • OllamaProvider (LLM)                │
│  • PythonProvider (Code)                │
│  • MCPProvider (External Tools)         │
└────────────────────────────────────────┘
```

## Implementation

### Phase 1: Core Agent Provider (Days 1-3)

#### 1.1 Base Agent Provider

```python
# src/gleitzeit/providers/agent_provider.py
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import json
import uuid
from datetime import datetime
from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import ProviderError

@dataclass
class AgentStep:
    """Single step in agent execution"""
    action: str  # "search", "analyze", "code", "complete"
    method: str  # Provider method to call
    parameters: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None

class AgentProvider(ProtocolProvider):
    """
    Provider that implements agent capabilities.
    Agents can plan, execute multi-step tasks, and maintain memory.
    
    NOTE: This implementation requires core Gleitzeit modifications:
    - Registry needs to expose provider access methods
    - Or agents need to be passed provider instances at initialization
    """
    
    def __init__(self, config: Dict[str, Any], provider_instances: Optional[Dict[str, Any]] = None):
        super().__init__(
            provider_id=config.get("provider_id", "agent_provider"),
            protocol_id="agent/v1",
            name="Agent Provider",
            description="Agent orchestration provider"
        )
        self.provider_instances = provider_instances or {}  # Map of provider_id -> instance
        self.sessions = {}  # In-memory session storage
        self.default_model = config.get("default_model", "llama3.2")
        self.max_iterations = config.get("max_iterations", 10)
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle JSON-RPC request (required by ProtocolProvider)"""
        
        if not self.provider_instances:
            raise ProviderError("Agent provider requires access to other providers")
        
        # Route to appropriate agent type
        if method == "agent/research":
            return await self._research_agent(params)
        elif method == "agent/analyze":
            return await self._analysis_agent(params)
        elif method == "agent/code":
            return await self._code_agent(params)
        elif method == "agent/chat":
            return await self._chat_agent(params)
        else:
            raise ValueError(f"Unknown agent method: {method}")
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        # Could initialize connections to required providers here
        pass
    
    async def shutdown(self) -> None:
        """Shutdown the provider"""
        # Cleanup sessions and connections
        self.sessions.clear()
    
    async def health_check(self) -> bool:
        """Check provider health"""
        # Verify required providers are available
        return len(self.provider_instances) > 0
    
    async def _research_agent(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Research agent that gathers information on a topic.
        """
        topic = params["topic"]
        depth = params.get("depth", "medium")
        max_steps = params.get("max_steps", 5)
        session_id = params.get("session_id", str(uuid.uuid4()))
        
        # Initialize or get session
        session = self._get_or_create_session(session_id)
        session["topic"] = topic
        
        # Plan research steps
        plan = await self._plan_research(topic, depth)
        
        # Execute plan
        steps_executed = []
        for i, step in enumerate(plan[:max_steps]):
            try:
                result = await self._execute_step(step)
                step.result = result
                step.timestamp = datetime.now()
                steps_executed.append(step)
                
                # Update session context
                session["context"][f"step_{i}"] = result
                
            except Exception as e:
                step.error = str(e)
                steps_executed.append(step)
                # Continue with next step or abort based on criticality
                if self._is_critical_step(step):
                    break
        
        # Generate final report
        report = await self._synthesize_research(topic, steps_executed, session)
        
        return {
            "report": report,
            "topic": topic,
            "steps_executed": len(steps_executed),
            "session_id": session_id,
            "metadata": {
                "depth": depth,
                "success_rate": sum(1 for s in steps_executed if not s.error) / len(steps_executed)
            }
        }
    
    async def _plan_research(self, topic: str, depth: str) -> List[AgentStep]:
        """Generate research plan using LLM"""
        
        prompt = f"""Create a research plan for: {topic}
Depth level: {depth}

Generate 3-7 research steps. For each step specify:
- action: one of [search, analyze, verify, synthesize]
- query: what to search or analyze
- purpose: why this step is important

Output as JSON array."""
        
        response = await self._call_llm(prompt, temperature=0.7)
        
        # Parse LLM response into steps
        try:
            plan_data = json.loads(response)
            steps = []
            
            for item in plan_data:
                if item["action"] == "search":
                    step = AgentStep(
                        action="search",
                        method="mcp/tool.web_search",
                        parameters={"query": item["query"]}
                    )
                elif item["action"] == "analyze":
                    step = AgentStep(
                        action="analyze", 
                        method="llm/chat",
                        parameters={
                            "prompt": f"Analyze the following information about {topic}: {item['query']}"
                        }
                    )
                elif item["action"] == "synthesize":
                    step = AgentStep(
                        action="synthesize",
                        method="llm/chat",
                        parameters={
                            "prompt": f"Synthesize findings about {topic}"
                        }
                    )
                else:
                    continue
                    
                steps.append(step)
                
            return steps
            
        except json.JSONDecodeError:
            # Fallback to simple plan
            return [
                AgentStep("search", "mcp/tool.web_search", {"query": topic}),
                AgentStep("analyze", "llm/chat", {"prompt": f"Analyze information about {topic}"})
            ]
    
    async def _execute_step(self, step: AgentStep) -> Any:
        """Execute a single step by calling the appropriate provider
        
        NOTE: This method needs modification based on how providers are accessed.
        Current implementation assumes direct provider instance access.
        """
        
        # Determine which provider to use based on method prefix
        provider = None
        if step.method.startswith("llm/"):
            provider = self.provider_instances.get("ollama_provider")
        elif step.method.startswith("python/"):
            provider = self.provider_instances.get("python_provider")
        elif step.method.startswith("mcp/"):
            provider = self.provider_instances.get("mcp_provider")
        
        if not provider:
            raise ProviderError(f"No provider found for method: {step.method}")
        
        # Add model parameter for LLM calls
        if step.method.startswith("llm/"):
            step.parameters["model"] = self.default_model
            if "prompt" in step.parameters:
                step.parameters["messages"] = [
                    {"role": "user", "content": step.parameters.pop("prompt")}
                ]
        
        # Call provider's handle_request method (standard ProtocolProvider interface)
        result = await provider.handle_request(step.method, step.parameters)
        return result
    
    async def _synthesize_research(
        self, 
        topic: str, 
        steps: List[AgentStep], 
        session: Dict
    ) -> str:
        """Generate final research report"""
        
        # Gather successful results
        findings = []
        for i, step in enumerate(steps):
            if step.result and not step.error:
                findings.append(f"Step {i+1} ({step.action}): {step.result}")
        
        prompt = f"""Create a comprehensive research report on: {topic}

Based on the following findings:
{chr(10).join(findings)}

Structure the report with:
1. Executive Summary
2. Key Findings  
3. Detailed Analysis
4. Conclusions

Be concise but thorough."""
        
        report = await self._call_llm(prompt, temperature=0.5)
        return report
    
    async def _call_llm(self, prompt: str, temperature: float = 0.7) -> str:
        """Helper method to call LLM provider"""
        
        provider = self.provider_instances.get("ollama_provider")
        if not provider:
            raise ProviderError("LLM provider not available")
            
        result = await provider.handle_request("llm/chat", {
            "model": self.default_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature
        })
        
        return result.get("response", "")
    
    def _get_or_create_session(self, session_id: str) -> Dict:
        """Get or create agent session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "id": session_id,
                "created": datetime.now(),
                "context": {},
                "history": []
            }
        return self.sessions[session_id]
    
    def _is_critical_step(self, step: AgentStep) -> bool:
        """Determine if step failure should abort execution"""
        # Initial search/gather steps are critical
        return step.action in ["search", "gather"]
```

#### 1.2 Required Gleitzeit Core Modifications

**IMPORTANT**: The current Gleitzeit architecture does NOT support providers accessing other providers directly. To implement the Agent Provider pattern, one of these modifications would be needed:

**Option A: Registry Enhancement**
```python
# src/gleitzeit/registry.py (PROPOSED modification)
class ProtocolProviderRegistry:
    def get_provider_for_method(self, method: str) -> Optional[Any]:
        """NEW METHOD: Get provider instance that handles a specific method"""
        protocol_id = method.split('/')[0]  # Extract protocol from method
        provider_info = self.select_provider(protocol_id, method)
        if provider_info:
            return self.get_provider_instance(provider_info.provider_id)
        return None
    
    def register_provider(self, provider_id: str, protocol_id: str, 
                         provider_instance: Any, supported_methods: Optional[Set[str]] = None) -> None:
        """Modified to allow registry access"""
        # ... existing code ...
        
        # NEW: Give registry access to providers that need it
        if hasattr(provider_instance, 'set_registry'):
            provider_instance.set_registry(self)
        
        # ... rest of existing code ...
```

**Option B: Provider Factory Pattern**
```python
# src/gleitzeit/providers/agent_factory.py (NEW file)
class AgentProviderFactory:
    """Factory that creates agent providers with access to other providers"""
    
    @staticmethod
    def create_agent_provider(config: Dict[str, Any], registry: ProtocolProviderRegistry) -> AgentProvider:
        # Get instances of required providers
        provider_instances = {
            "ollama_provider": registry.get_provider_instance("ollama_provider"),
            "python_provider": registry.get_provider_instance("python_provider"),
            "mcp_provider": registry.get_provider_instance("mcp_provider")
        }
        
        return AgentProvider(config, provider_instances)
```

### Phase 2: Memory System (Days 4-5)

#### 2.1 Session Memory with Persistence

```python
# src/gleitzeit/providers/agent_memory.py
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json

class AgentMemory:
    """
    Memory management for agents.
    Handles short-term (session) and long-term (persistent) memory.
    """
    
    def __init__(self, persistence_adapter, session_id: str):
        self.persistence = persistence_adapter
        self.session_id = session_id
        self.short_term = []  # Current session
        self.context = {}  # Working memory
        
    async def remember(self, key: str, value: Any, memory_type: str = "short"):
        """Store information in memory"""
        
        memory_entry = {
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "type": memory_type
        }
        
        if memory_type == "short":
            self.short_term.append(memory_entry)
            self.context[key] = value
        else:
            # Store in persistence for long-term
            await self.persistence.store_task_result(
                f"agent_memory_{self.session_id}_{key}",
                memory_entry
            )
    
    async def recall(self, key: str) -> Optional[Any]:
        """Retrieve information from memory"""
        
        # Check working memory first
        if key in self.context:
            return self.context[key]
        
        # Check short-term memory
        for entry in reversed(self.short_term):
            if entry["key"] == key:
                return entry["value"]
        
        # Check long-term memory
        try:
            result = await self.persistence.retrieve_task_result(
                f"agent_memory_{self.session_id}_{key}"
            )
            if result:
                return result["value"]
        except:
            pass
        
        return None
    
    async def get_context_window(self, max_items: int = 10) -> List[Dict]:
        """Get recent context for LLM calls"""
        return self.short_term[-max_items:]
    
    def clear_session(self):
        """Clear short-term memory"""
        self.short_term.clear()
        self.context.clear()
```

### Phase 3: Advanced Agent Types (Days 6-8)

#### 3.1 Code Assistant Agent

```python
class AgentProvider(BaseProvider):
    # ... previous code ...
    
    async def _code_agent(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Code assistant agent for programming tasks.
        """
        task = params["task"]
        language = params.get("language", "python")
        context_code = params.get("context", "")
        session_id = params.get("session_id", str(uuid.uuid4()))
        
        steps = []
        
        # Step 1: Understand the task
        understanding = await self._call_llm(
            f"Analyze this coding task and identify key requirements:\n{task}\nLanguage: {language}"
        )
        steps.append({"step": "understand", "result": understanding})
        
        # Step 2: Generate solution
        solution_prompt = f"""Write {language} code to: {task}

Requirements identified: {understanding}

Context code:
{context_code}

Provide clean, well-commented code."""
        
        code = await self._call_llm(solution_prompt, temperature=0.3)
        steps.append({"step": "generate", "result": code})
        
        # Step 3: Test the code (if Python)
        if language == "python":
            test_result = await self._test_python_code(code)
            steps.append({"step": "test", "result": test_result})
            
            # Step 4: Fix if needed
            if test_result.get("error"):
                fix_prompt = f"""Fix this Python code error:
Code:
{code}

Error:
{test_result['error']}

Provide corrected code."""
                
                fixed_code = await self._call_llm(fix_prompt, temperature=0.2)
                code = fixed_code
                steps.append({"step": "fix", "result": fixed_code})
                
                # Re-test
                test_result = await self._test_python_code(fixed_code)
                steps.append({"step": "verify", "result": test_result})
        
        # Step 5: Generate explanation
        explanation = await self._call_llm(
            f"Explain how this code works:\n{code}\n\nBe concise and clear."
        )
        steps.append({"step": "explain", "result": explanation})
        
        return {
            "code": code,
            "explanation": explanation,
            "language": language,
            "test_result": test_result if language == "python" else None,
            "steps": steps,
            "session_id": session_id
        }
    
    async def _test_python_code(self, code: str) -> Dict[str, Any]:
        """Test Python code using PythonProvider"""
        
        provider = self.provider_instances.get("python_provider")
        if not provider:
            return {"success": False, "error": "Python provider not available"}
            
        try:
            result = await provider.handle_request("python/execute", {
                "code": code,
                "timeout": 10
            })
            return {"success": True, "output": result.get("response")}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

#### 3.2 Interactive Chat Agent

```python
class AgentProvider(BaseProvider):
    # ... previous code ...
    
    async def _chat_agent(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Interactive chat agent with memory.
        """
        message = params["message"]
        session_id = params.get("session_id", str(uuid.uuid4()))
        
        # Get session with history
        session = self._get_or_create_session(session_id)
        session["history"].append({"role": "user", "content": message, "timestamp": datetime.now()})
        
        # Determine if we need to use tools
        needs_tools = await self._check_needs_tools(message)
        
        if needs_tools:
            # Execute with tools
            tool_response = await self._execute_with_tools(message, session)
            response = tool_response["response"]
            metadata = tool_response.get("metadata", {})
        else:
            # Simple chat response
            history_context = self._format_history(session["history"][-5:])  # Last 5 messages
            
            prompt = f"""Previous conversation:
{history_context}

User: {message}

Provide a helpful response."""
            
            response = await self._call_llm(prompt, temperature=0.8)
            metadata = {"tool_used": False}
        
        # Store response in history
        session["history"].append({"role": "assistant", "content": response, "timestamp": datetime.now()})
        
        return {
            "response": response,
            "session_id": session_id,
            "metadata": metadata
        }
    
    async def _check_needs_tools(self, message: str) -> bool:
        """Determine if message requires tool use"""
        
        check_prompt = f"""Does this request require external tools or data?
Request: {message}

Answer 'yes' if it needs:
- Web search
- Code execution  
- File operations
- Current information

Answer 'no' for:
- General questions
- Explanations
- Opinions

Answer with just 'yes' or 'no'."""
        
        response = await self._call_llm(check_prompt, temperature=0.1)
        return "yes" in response.lower()
    
    async def _execute_with_tools(self, message: str, session: Dict) -> Dict[str, Any]:
        """Execute request using tools"""
        
        # Determine which tool to use
        tool_prompt = f"""What tool should I use for: {message}

Options:
- web_search: For current information
- code: For calculations or programming
- analyze: For data analysis

Respond with just the tool name."""
        
        tool = await self._call_llm(tool_prompt, temperature=0.1)
        tool = tool.strip().lower()
        
        # Execute based on tool selection
        if "search" in tool:
            # Perform search
            search_query = await self._call_llm(
                f"Extract search query from: {message}\nRespond with just the query."
            )
            
            provider = self.provider_instances.get("mcp_provider")
            if not provider:
                return {
                    "response": "I cannot perform web searches at this time (provider unavailable)",
                    "metadata": {"error": "MCP provider not available"}
                }
            
            search_result = await provider.handle_request("mcp/tool.web_search", {"query": search_query})
            
            # Generate response based on search
            response = await self._call_llm(
                f"Answer this question: {message}\n\nBased on search results: {search_result}"
            )
            
            return {
                "response": response,
                "metadata": {"tool_used": "web_search", "query": search_query}
            }
            
        elif "code" in tool:
            # Generate and execute code
            code = await self._call_llm(
                f"Write Python code to: {message}\nRespond with just the code."
            )
            
            test_result = await self._test_python_code(code)
            
            response = f"I executed the following code:\n```python\n{code}\n```\n\nResult: {test_result.get('output', test_result.get('error'))}"
            
            return {
                "response": response,
                "metadata": {"tool_used": "code", "code": code, "result": test_result}
            }
        
        else:
            # Default to analysis
            response = await self._call_llm(f"Analyze and respond to: {message}")
            return {
                "response": response,
                "metadata": {"tool_used": "analysis"}
            }
    
    def _format_history(self, history: List[Dict]) -> str:
        """Format conversation history for context"""
        formatted = []
        for entry in history:
            role = entry["role"].capitalize()
            content = entry["content"]
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
```

### Phase 4: Integration & Testing (Days 9-10)

#### 4.1 Workflow Integration

```yaml
# examples/agent_workflow.yaml
name: "Multi-Agent Research Pipeline"
tasks:
  # Research agent gathers information
  - id: "research"
    method: "agent/research"
    parameters:
      topic: "Impact of quantum computing on cryptography"
      depth: "comprehensive"
      max_steps: 8
  
  # Code agent creates demonstration
  - id: "demo"
    method: "agent/code"
    dependencies: ["research"]
    parameters:
      task: "Create a Python demonstration of quantum key distribution"
      context: "${research.report}"
      language: "python"
  
  # Analysis agent validates findings
  - id: "validate"
    method: "agent/analyze"
    dependencies: ["research", "demo"]
    parameters:
      content: "${research.report}"
      code: "${demo.code}"
      question: "Validate the accuracy and identify any gaps"
  
  # Final report generation
  - id: "report"
    method: "llm/chat"
    dependencies: ["research", "demo", "validate"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Create final report combining:
            Research: ${research.report}
            Demo: ${demo.explanation}
            Validation: ${validate.analysis}
```

#### 4.2 CLI Integration

```python
# src/gleitzeit/cli/commands/agent.py
import click
import asyncio
from gleitzeit.providers.agent_provider import AgentProvider

@click.group()
def agent():
    """Agent commands"""
    pass

@agent.command()
@click.argument('task')
@click.option('--type', default='research', help='Agent type: research, code, chat')
@click.option('--session', default=None, help='Session ID for continuity')
def execute(task, type, session):
    """Execute single agent task"""
    async def run():
        # Initialize agent provider
        agent = AgentProvider({
            "default_model": "llama3.2",
            "max_iterations": 10
        })
        
        # Set up registry (simplified for CLI)
        from gleitzeit.registry import ProtocolProviderRegistry
        registry = ProtocolProviderRegistry()
        # ... register providers ...
        agent.set_registry(registry)
        
        # Execute task
        result = await agent.execute(f"agent/{type}", {
            "task": task,
            "topic": task,
            "session_id": session
        })
        
        print(json.dumps(result, indent=2))
    
    asyncio.run(run())

@agent.command()
@click.option('--session', default=None, help='Session ID for continuity')
def chat(session):
    """Interactive chat with agent"""
    async def run():
        agent = AgentProvider({"default_model": "llama3.2"})
        # ... setup registry ...
        
        session_id = session or str(uuid.uuid4())
        print(f"Chat session: {session_id}")
        
        while True:
            try:
                message = input("\nYou: ")
                if message.lower() in ['exit', 'quit']:
                    break
                
                result = await agent.execute("agent/chat", {
                    "message": message,
                    "session_id": session_id
                })
                
                print(f"\nAgent: {result['response']}")
                
            except KeyboardInterrupt:
                break
    
    asyncio.run(run())
```

#### 4.3 Python API Usage

```python
# examples/agent_example.py
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    async with GleitzeitClient() as client:
        # Research agent
        research = await client.execute_provider("agent/research", {
            "topic": "renewable energy storage solutions",
            "depth": "comprehensive",
            "max_steps": 10
        })
        
        print(f"Research Report:\n{research['report']}")
        
        # Code agent using research context
        code_solution = await client.execute_provider("agent/code", {
            "task": "Create a battery capacity calculator",
            "context": research['report'],
            "language": "python"
        })
        
        print(f"\nGenerated Code:\n{code_solution['code']}")
        print(f"\nExplanation:\n{code_solution['explanation']}")
        
        # Interactive chat
        chat_session = str(uuid.uuid4())
        for question in ["What are the main findings?", "Can you elaborate on lithium batteries?"]:
            response = await client.execute_provider("agent/chat", {
                "message": question,
                "session_id": chat_session
            })
            print(f"\nQ: {question}")
            print(f"A: {response['response']}")

asyncio.run(main())
```

## Testing Strategy

### Unit Tests

```python
# tests/test_agent_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from gleitzeit.providers.agent_provider import AgentProvider

@pytest.mark.asyncio
async def test_research_agent():
    # Mock registry and providers
    mock_registry = MagicMock()
    mock_llm = AsyncMock()
    mock_llm.execute.return_value = {"response": "Test response"}
    mock_registry.get_provider_for_method.return_value = mock_llm
    
    # Create agent
    agent = AgentProvider({"default_model": "test-model"})
    agent.set_registry(mock_registry)
    
    # Execute research
    result = await agent.execute("agent/research", {
        "topic": "test topic",
        "max_steps": 2
    })
    
    assert "report" in result
    assert result["topic"] == "test topic"
    assert result["steps_executed"] > 0

@pytest.mark.asyncio
async def test_code_agent():
    # Similar test for code agent
    pass

@pytest.mark.asyncio
async def test_chat_agent_with_memory():
    # Test that chat agent maintains session history
    pass
```

### Integration Tests

```python
# tests/test_agent_integration.py
@pytest.mark.asyncio
async def test_agent_in_workflow():
    """Test agent provider within workflow execution"""
    
    workflow = Workflow(
        name="test_agent_workflow",
        tasks=[
            Task(
                id="agent_task",
                method="agent/research",
                parameters={"topic": "test", "max_steps": 2}
            )
        ]
    )
    
    engine = ExecutionEngine(...)
    result = await engine.execute_workflow(workflow)
    
    assert result.status == "completed"
    assert result.tasks[0].result["report"] is not None
```

## Deployment Considerations

### Configuration

```yaml
# ~/.gleitzeit/config.yaml
providers:
  agent:
    type: "AgentProvider"
    default_model: "llama3.2"
    max_iterations: 10
    memory:
      type: "persistence"  # or "in_memory"
      ttl: 3600
    tools:
      - "llm/chat"
      - "mcp/tool.web_search"
      - "python/execute"
```

### Performance Optimization

1. **Cache LLM Calls**: Cache planning results for similar requests
2. **Limit Iterations**: Set reasonable max_iterations to prevent runaway costs
3. **Memory Pruning**: Periodically clean old session data
4. **Concurrent Steps**: Execute independent steps in parallel

### Cost Management

```python
class AgentProvider(BaseProvider):
    def __init__(self, config):
        super().__init__(config)
        self.cost_tracker = CostTracker()
        self.cost_limit = config.get("cost_limit", 1.0)  # $1 default
    
    async def _call_llm(self, prompt: str, temperature: float = 0.7) -> str:
        # Track costs
        estimated_cost = self._estimate_cost(prompt)
        if self.cost_tracker.total + estimated_cost > self.cost_limit:
            raise ProviderError("Cost limit would be exceeded")
        
        result = await super()._call_llm(prompt, temperature)
        self.cost_tracker.add(estimated_cost)
        return result
```

## Implementation Requirements

This Agent Provider implementation **requires modifications to Gleitzeit's core architecture**:

1. **Current Limitation**: Providers cannot access other providers directly
2. **Required Change**: Either:
   - Add registry methods for provider-to-provider communication
   - Use factory pattern to inject provider dependencies
   - Create a new "orchestrator" layer above providers

Without these changes, the Agent Provider cannot orchestrate multiple tools as designed.

## Timeline

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 0: Core Modifications | Days 1-2 | Enable provider-to-provider communication |
| Phase 1: Core Agent Provider | Days 3-5 | Basic agent provider with research capability |
| Phase 2: Memory System | Days 6-7 | Session management and persistence |
| Phase 3: Advanced Agents | Days 8-10 | Code and chat agents |
| Phase 4: Integration | Days 11-12 | CLI, workflows, testing |
| **Total** | **12 Days** | **Production-ready agent system** |

## Success Metrics

1. **Functionality**: All agent types working (research, code, chat)
2. **Integration**: Seamless workflow integration
3. **Performance**: <2s response time for simple queries
4. **Cost**: <$0.10 per typical agent task
5. **Reliability**: 95% success rate for agent tasks

## Conclusion

This implementation plan provides a theoretical path to adding agent capabilities to Gleitzeit through the Agent Provider pattern. However, it requires **significant core modifications** to enable provider-to-provider communication.

### Key Considerations:

**Pros:**
- Agents integrate as standard providers
- Can be used in workflows like any other provider
- Progressive enhancement possible
- Clean separation of concerns

**Cons:**
- **Requires core architecture changes** (providers currently cannot access each other)
- Breaks current provider isolation model
- May introduce circular dependency risks
- Increases system complexity

### Alternative Approaches to Consider:

1. **Workflow-Based Agents**: Use the existing workflow engine for agent orchestration
   - No core changes needed
   - Higher overhead per agent "thought"
   - Already supported by current architecture

2. **External Agent Service**: Build agents as a separate service
   - Communicates with Gleitzeit via API
   - No core modifications needed
   - Can use any agent framework

3. **Enhanced Workflow Engine**: Add agent-specific features to workflows
   - Loop constructs for iterative thinking
   - Conditional branching for decision making
   - Memory management at workflow level

The 12-day timeline assumes core modifications are approved and feasible. Without core changes, consider the alternative approaches above.