# Agent Hub Implementation

## Overview

This document presents an Agent Hub implementation that follows Gleitzeit's existing hub architecture. Unlike the Provider approach (which requires core modifications), the Agent Hub works **within the current architecture** by managing agent instances as resources, similar to how OllamaHub manages LLM instances and DockerHub manages containers.

## Key Advantages

1. **No Core Modifications Required** - Works with existing Gleitzeit architecture
2. **Follows Established Patterns** - Based on existing ResourceHub base class
3. **Provider Orchestration** - Hub can access providers through ResourceManager
4. **Resource Management** - Built-in health checks, metrics, and recovery
5. **Immediate Implementation** - Can be built without changing core code

## Architecture

```
┌──────────────────────────────────────────────┐
│                Workflows                      │
│         Can use agent/execute tasks           │
└────────────────┬─────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────┐
│            ResourceManager                    │
│    Orchestrates all hubs including AgentHub   │
└────────────────┬─────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────┐
│              AgentHub                         │
│  • Manages agent instances                    │
│  • Routes requests to agents                  │
│  • Handles agent lifecycle                    │
└────────────────┬─────────────────────────────┘
                 │ Uses
┌────────────────▼─────────────────────────────┐
│         Provider Instances                    │
│  • OllamaProvider (via OllamaHub)            │
│  • PythonProvider (via DockerHub)            │
│  • MCPProvider (direct)                       │
└───────────────────────────────────────────────┘
```

## Implementation

### Phase 1: Core Agent Hub (Days 1-2)

```python
# src/gleitzeit/hub/agent_hub.py
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
import uuid
import json
import asyncio
from datetime import datetime
from enum import Enum

from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus, ResourceType, ResourceMetrics
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.core.errors import ProviderError
import logging

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """Types of agents"""
    RESEARCH = "research"
    CODE = "code"
    ANALYSIS = "analysis"
    CHAT = "chat"
    CUSTOM = "custom"


@dataclass
class AgentConfig:
    """Configuration for an agent instance"""
    agent_type: AgentType
    model: str = "llama3.2"
    max_iterations: int = 10
    temperature: float = 0.7
    tools: List[str] = field(default_factory=list)
    memory_enabled: bool = True
    session_ttl: int = 3600  # Session TTL in seconds
    custom_prompts: Dict[str, str] = field(default_factory=dict)


@dataclass
class AgentSession:
    """Agent conversation session"""
    session_id: str
    agent_id: str
    created_at: datetime
    last_activity: datetime
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class AgentStep:
    """Single step in agent execution"""
    action: str
    tool: str
    parameters: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None


class AgentInstance:
    """Represents a running agent instance"""
    
    def __init__(
        self,
        instance_id: str,
        config: AgentConfig,
        resource_manager: ResourceManager
    ):
        self.instance_id = instance_id
        self.config = config
        self.resource_manager = resource_manager
        self.sessions: Dict[str, AgentSession] = {}
        self.metrics = {
            "total_requests": 0,
            "total_steps": 0,
            "avg_steps_per_request": 0,
            "total_errors": 0
        }
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an agent method"""
        self.metrics["total_requests"] += 1
        
        try:
            if method == "research":
                return await self._research(params)
            elif method == "code":
                return await self._generate_code(params)
            elif method == "analyze":
                return await self._analyze(params)
            elif method == "chat":
                return await self._chat(params)
            else:
                raise ValueError(f"Unknown agent method: {method}")
        except Exception as e:
            self.metrics["total_errors"] += 1
            raise
    
    async def _research(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute research agent logic"""
        topic = params["topic"]
        max_steps = params.get("max_steps", 5)
        session_id = params.get("session_id", str(uuid.uuid4()))
        
        # Get or create session
        session = self._get_or_create_session(session_id)
        
        # Plan research steps
        plan = await self._plan_steps(topic, "research")
        
        # Execute plan
        results = []
        for i, step in enumerate(plan[:max_steps]):
            self.metrics["total_steps"] += 1
            
            try:
                # Execute step using appropriate provider
                result = await self._execute_tool(step.tool, step.parameters)
                step.result = result
                step.timestamp = datetime.now()
                results.append(step)
                
                # Update session context
                session.context[f"step_{i}"] = result
                
            except Exception as e:
                step.error = str(e)
                results.append(step)
                logger.error(f"Step {i} failed: {e}")
        
        # Synthesize findings
        report = await self._synthesize_results(topic, results, "research")
        
        # Update metrics
        self._update_avg_steps()
        
        return {
            "report": report,
            "steps_executed": len(results),
            "session_id": session_id,
            "success": True
        }
    
    async def _generate_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate code with testing"""
        task = params["task"]
        language = params.get("language", "python")
        context = params.get("context", "")
        
        # Generate code using LLM
        code = await self._call_llm(
            f"Write {language} code to: {task}\nContext: {context}",
            temperature=0.3
        )
        
        # Test if Python
        test_result = None
        if language == "python":
            test_result = await self._test_code(code)
            
            # Fix if needed
            if test_result.get("error"):
                fixed_code = await self._call_llm(
                    f"Fix this code error:\n{code}\nError: {test_result['error']}",
                    temperature=0.2
                )
                code = fixed_code
                test_result = await self._test_code(fixed_code)
        
        # Generate explanation
        explanation = await self._call_llm(
            f"Explain this {language} code concisely:\n{code}"
        )
        
        return {
            "code": code,
            "explanation": explanation,
            "test_result": test_result,
            "language": language
        }
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Interactive chat with memory"""
        message = params["message"]
        session_id = params.get("session_id", str(uuid.uuid4()))
        
        session = self._get_or_create_session(session_id)
        session.history.append({"role": "user", "content": message, "timestamp": datetime.now()})
        
        # Determine if tools needed
        needs_tools = await self._check_needs_tools(message)
        
        if needs_tools:
            # Execute with tools
            response = await self._execute_with_tools(message, session)
        else:
            # Simple LLM response with context
            context = self._format_history(session.history[-5:])
            response = await self._call_llm(
                f"Previous conversation:\n{context}\n\nUser: {message}",
                temperature=0.8
            )
        
        session.history.append({"role": "assistant", "content": response, "timestamp": datetime.now()})
        session.last_activity = datetime.now()
        
        return {
            "response": response,
            "session_id": session_id,
            "tools_used": needs_tools
        }
    
    async def _plan_steps(self, goal: str, agent_type: str) -> List[AgentStep]:
        """Plan execution steps using LLM"""
        prompt = f"""Plan steps to {agent_type}: {goal}
        
Available tools:
- llm: Language model queries
- python: Execute Python code  
- search: Web search (if MCP available)
- analyze: Deep analysis

Output JSON array with: action, tool, parameters"""
        
        response = await self._call_llm(prompt, temperature=0.7)
        
        try:
            steps_data = json.loads(response)
            steps = []
            for item in steps_data:
                steps.append(AgentStep(
                    action=item["action"],
                    tool=item["tool"],
                    parameters=item.get("parameters", {})
                ))
            return steps
        except:
            # Fallback plan
            return [
                AgentStep("analyze", "llm", {"prompt": f"Analyze {goal}"}),
                AgentStep("synthesize", "llm", {"prompt": f"Synthesize findings about {goal}"})
            ]
    
    async def _execute_tool(self, tool: str, parameters: Dict[str, Any]) -> Any:
        """Execute a tool using the appropriate provider via ResourceManager"""
        if tool == "llm":
            return await self._call_llm(parameters.get("prompt", ""))
        
        elif tool == "python":
            code = parameters.get("code", "")
            # Use DockerHub for Python execution
            docker_hub = self.resource_manager.get_hub("docker")
            if docker_hub:
                instance = await docker_hub.get_available_instance()
                if instance:
                    # Execute via Docker
                    result = await docker_hub.execute_code(code)
                    return result
            return {"error": "Python execution not available"}
        
        elif tool == "search":
            # Would use MCP provider if available
            return {"error": "Search not implemented", "query": parameters.get("query")}
        
        else:
            return await self._call_llm(f"Analyze: {parameters}")
    
    async def _call_llm(self, prompt: str, temperature: float = None) -> str:
        """Call LLM via OllamaHub"""
        ollama_hub = self.resource_manager.get_hub("ollama")
        if not ollama_hub:
            raise ProviderError("Ollama hub not available")
        
        result = await ollama_hub.chat_completion(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature or self.config.temperature
        )
        
        return result.get("response", "")
    
    async def _test_code(self, code: str) -> Dict[str, Any]:
        """Test Python code via DockerHub"""
        docker_hub = self.resource_manager.get_hub("docker")
        if docker_hub:
            try:
                result = await docker_hub.execute_code(code, timeout=10)
                return {"success": True, "output": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "Docker hub not available"}
    
    def _get_or_create_session(self, session_id: str) -> AgentSession:
        """Get or create session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = AgentSession(
                session_id=session_id,
                agent_id=self.instance_id,
                created_at=datetime.now(),
                last_activity=datetime.now()
            )
        return self.sessions[session_id]
    
    def _update_avg_steps(self):
        """Update average steps metric"""
        if self.metrics["total_requests"] > 0:
            self.metrics["avg_steps_per_request"] = (
                self.metrics["total_steps"] / self.metrics["total_requests"]
            )
    
    async def _check_needs_tools(self, message: str) -> bool:
        """Check if message requires tool use"""
        check = await self._call_llm(
            f"Does this need external tools or just conversation? '{message}'\nAnswer: yes/no",
            temperature=0.1
        )
        return "yes" in check.lower()
    
    async def _execute_with_tools(self, message: str, session: AgentSession) -> str:
        """Execute request using tools"""
        # Simplified tool execution
        plan = await self._plan_steps(message, "chat")
        
        results = []
        for step in plan[:3]:  # Limit steps in chat
            result = await self._execute_tool(step.tool, step.parameters)
            results.append(result)
        
        # Synthesize response
        return await self._call_llm(
            f"Answer '{message}' based on: {results}",
            temperature=0.7
        )
    
    def _format_history(self, history: List[Dict]) -> str:
        """Format conversation history"""
        formatted = []
        for entry in history:
            role = entry["role"].capitalize()
            content = entry["content"]
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    async def _synthesize_results(
        self, 
        goal: str, 
        results: List[AgentStep], 
        agent_type: str
    ) -> str:
        """Synthesize results into final output"""
        successful_results = [
            f"{r.action}: {r.result}" 
            for r in results 
            if r.result and not r.error
        ]
        
        prompt = f"""Create a {agent_type} report for: {goal}

Based on these findings:
{chr(10).join(successful_results)}

Be comprehensive but concise."""
        
        return await self._call_llm(prompt, temperature=0.5)


class AgentHub(ResourceHub[AgentConfig]):
    """
    Hub for managing agent instances
    
    Provides agent orchestration capabilities while working within
    Gleitzeit's existing architecture.
    """
    
    def __init__(
        self,
        hub_id: str = "agent_hub",
        resource_manager: Optional[ResourceManager] = None,
        max_agents: int = 10,
        **kwargs
    ):
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.CUSTOM,
            **kwargs
        )
        
        self.resource_manager = resource_manager
        self.max_agents = max_agents
        self.agent_instances: Dict[str, AgentInstance] = {}
        
        logger.info(f"Initialized AgentHub with max_agents={max_agents}")
    
    def set_resource_manager(self, resource_manager: ResourceManager):
        """Set the resource manager for accessing other hubs"""
        self.resource_manager = resource_manager
    
    async def check_health(self, instance: ResourceInstance[AgentConfig]) -> bool:
        """Check health of an agent instance"""
        agent = self.agent_instances.get(instance.id)
        if not agent:
            return False
        
        # Check if ResourceManager is available
        if not self.resource_manager:
            return False
        
        # Check if required hubs are available
        ollama_hub = self.resource_manager.get_hub("ollama")
        if not ollama_hub:
            return False
        
        # Simple health check - verify LLM is responsive
        try:
            response = await agent._call_llm("Hello", temperature=0.1)
            return len(response) > 0
        except:
            return False
    
    async def collect_metrics(self, instance: ResourceInstance[AgentConfig]) -> ResourceMetrics:
        """Collect metrics from agent instance"""
        agent = self.agent_instances.get(instance.id)
        if not agent:
            return ResourceMetrics()
        
        metrics = ResourceMetrics()
        metrics.request_count = agent.metrics["total_requests"]
        metrics.error_count = agent.metrics["total_errors"]
        metrics.custom_metrics = {
            "total_steps": agent.metrics["total_steps"],
            "avg_steps_per_request": agent.metrics["avg_steps_per_request"],
            "active_sessions": len(agent.sessions)
        }
        
        return metrics
    
    async def start_instance(self, config: AgentConfig) -> ResourceInstance[AgentConfig]:
        """Start a new agent instance"""
        if len(self.agent_instances) >= self.max_agents:
            raise Exception(f"Maximum number of agents ({self.max_agents}) reached")
        
        instance_id = f"agent_{uuid.uuid4().hex[:8]}"
        
        # Create agent instance
        agent = AgentInstance(instance_id, config, self.resource_manager)
        self.agent_instances[instance_id] = agent
        
        # Register as resource
        instance = await self.register_instance(
            instance_id=instance_id,
            name=f"Agent-{config.agent_type.value}",
            endpoint=f"agent://{instance_id}",
            metadata={
                "agent_type": config.agent_type.value,
                "model": config.model,
                "tools": config.tools
            },
            capabilities={config.agent_type.value, "llm", "orchestration"},
            config=config
        )
        
        logger.info(f"Started agent instance: {instance_id}")
        return instance
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop an agent instance"""
        if instance_id in self.agent_instances:
            # Clean up sessions
            agent = self.agent_instances[instance_id]
            agent.sessions.clear()
            
            del self.agent_instances[instance_id]
            await self.unregister_instance(instance_id)
            
            logger.info(f"Stopped agent instance: {instance_id}")
            return True
        return False
    
    async def restart_instance(self, instance_id: str) -> bool:
        """Restart an agent instance"""
        instance = await self.get_instance(instance_id)
        if not instance:
            return False
        
        # Stop and start
        await self.stop_instance(instance_id)
        new_instance = await self.start_instance(instance.config)
        
        # Copy the ID to maintain consistency
        self.agent_instances[instance_id] = self.agent_instances.pop(new_instance.id)
        new_instance.id = instance_id
        
        return True
    
    async def execute_agent_task(
        self,
        method: str,
        parameters: Dict[str, Any],
        agent_type: Optional[AgentType] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute an agent task
        
        This is the main entry point for using agents.
        """
        # Add session ID if not provided
        if session_id:
            parameters["session_id"] = session_id
        
        # Determine agent type from method if not specified
        if not agent_type:
            if method in ["research", "search", "investigate"]:
                agent_type = AgentType.RESEARCH
            elif method in ["code", "generate", "implement"]:
                agent_type = AgentType.CODE
            elif method in ["analyze", "evaluate"]:
                agent_type = AgentType.ANALYSIS
            elif method in ["chat", "converse"]:
                agent_type = AgentType.CHAT
            else:
                agent_type = AgentType.CUSTOM
        
        # Get or create appropriate agent
        agent = await self._get_or_create_agent(agent_type)
        
        # Execute task
        result = await agent.execute(method, parameters)
        
        # Update instance metrics
        instance = await self.get_instance(agent.instance_id)
        if instance:
            instance.metrics.request_count += 1
            instance.updated_at = datetime.now()
        
        return result
    
    async def _get_or_create_agent(self, agent_type: AgentType) -> AgentInstance:
        """Get existing agent or create new one"""
        # Look for existing agent of this type
        for agent_id, agent in self.agent_instances.items():
            if agent.config.agent_type == agent_type:
                return agent
        
        # Create new agent
        config = AgentConfig(
            agent_type=agent_type,
            model="llama3.2",
            tools=["llm", "python", "search"]
        )
        
        instance = await self.start_instance(config)
        return self.agent_instances[instance.id]
    
    async def cleanup_sessions(self, max_age_seconds: int = 3600):
        """Clean up old sessions"""
        now = datetime.now()
        
        for agent in self.agent_instances.values():
            expired = []
            for session_id, session in agent.sessions.items():
                age = (now - session.last_activity).total_seconds()
                if age > max_age_seconds:
                    expired.append(session_id)
            
            for session_id in expired:
                del agent.sessions[session_id]
                logger.debug(f"Cleaned up expired session: {session_id}")
```

### Phase 2: Integration with Gleitzeit (Days 3-4)

```python
# src/gleitzeit/hub/resource_manager.py (addition)
class ResourceManager:
    async def initialize_agent_hub(self):
        """Initialize the agent hub"""
        agent_hub = AgentHub(
            hub_id="agent_hub",
            resource_manager=self,
            max_agents=10
        )
        
        await self.register_hub("agent", agent_hub)
        await agent_hub.start()
        
        logger.info("Agent hub initialized and started")
```

### Phase 3: Workflow Integration (Day 5)

```yaml
# examples/agent_workflow.yaml
name: "Agent-Powered Research"
tasks:
  - id: "research"
    method: "hub/agent/execute"
    parameters:
      method: "research"
      agent_type: "research"
      params:
        topic: "quantum computing applications"
        max_steps: 10
  
  - id: "code_example"
    method: "hub/agent/execute"
    dependencies: ["research"]
    parameters:
      method: "code"
      agent_type: "code"
      params:
        task: "Create a quantum circuit simulator"
        context: "${research.report}"
        language: "python"
  
  - id: "analysis"
    method: "hub/agent/execute"
    dependencies: ["research", "code_example"]
    parameters:
      method: "analyze"
      agent_type: "analysis"
      params:
        content: "${research.report}"
        code: "${code_example.code}"
        question: "Evaluate the feasibility and accuracy"
```

## Advantages Over Provider Approach

1. **No Core Changes Required**
   - Works with existing ResourceHub base class
   - Uses established hub patterns
   - Integrates with ResourceManager

2. **Access to Other Hubs**
   - Can use OllamaHub for LLM calls
   - Can use DockerHub for Python execution
   - Can access any registered hub

3. **Built-in Resource Management**
   - Health monitoring
   - Metrics collection
   - Auto-recovery
   - Instance lifecycle

4. **Simpler Integration**
   - Workflows use standard hub invocation
   - No new provider protocol needed
   - Follows existing patterns

## Timeline

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 1: Core Agent Hub | Days 1-2 | Basic AgentHub with research agent |
| Phase 2: Integration | Days 3-4 | ResourceManager integration, health checks |
| Phase 3: Workflow Support | Day 5 | Workflow examples and testing |
| Phase 4: Advanced Agents | Days 6-7 | Code, analysis, and chat agents |
| Phase 5: Testing & Docs | Days 8 | Tests and documentation |
| **Total** | **8 Days** | **Production-ready agent system** |

## Usage Examples

### Python API

```python
from gleitzeit.client import GleitzeitClient

async with GleitzeitClient() as client:
    # Get resource manager
    resource_manager = client.resource_manager
    
    # Get agent hub
    agent_hub = resource_manager.get_hub("agent")
    
    # Execute research
    result = await agent_hub.execute_agent_task(
        method="research",
        parameters={
            "topic": "machine learning optimization techniques",
            "max_steps": 10
        }
    )
    
    print(result["report"])
    
    # Interactive chat with session
    session_id = str(uuid.uuid4())
    
    response1 = await agent_hub.execute_agent_task(
        method="chat",
        parameters={"message": "What are gradient descent variants?"},
        session_id=session_id
    )
    
    response2 = await agent_hub.execute_agent_task(
        method="chat",
        parameters={"message": "Which one is best for large datasets?"},
        session_id=session_id  # Maintains context
    )
```

### CLI Integration

```bash
# Execute agent task
gleitzeit agent research --topic "blockchain consensus mechanisms"

# Interactive chat
gleitzeit agent chat --session

# Generate code
gleitzeit agent code --task "implement binary search tree"

# Check agent hub status
gleitzeit hub status agent
```

## Conclusion

The Agent Hub approach provides a clean, immediately implementable solution that:

- **Works within existing architecture** without core modifications
- **Leverages existing hub infrastructure** for resource management
- **Provides full agent capabilities** including planning, tool use, and memory
- **Integrates seamlessly** with workflows and other hubs
- **Can be implemented in 8 days** with current codebase

This is the recommended approach for adding agent capabilities to Gleitzeit.