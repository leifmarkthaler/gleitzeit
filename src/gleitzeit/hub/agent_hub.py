"""
Agent Hub for Gleitzeit

Manages agent instances that can orchestrate multiple tools and maintain conversation state.
Works within the existing ResourceHub architecture.
"""

from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
import uuid
import json
import asyncio
from datetime import datetime
from enum import Enum

from gleitzeit.hub.base import ResourceHub, ResourceInstance, ResourceStatus, ResourceType, ResourceMetrics
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
    tools: List[str] = field(default_factory=lambda: ["llm", "python"])
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
        resource_manager: Optional[Any] = None
    ) -> None:
        self.instance_id = instance_id
        self.config = config
        self.resource_manager = resource_manager
        self.sessions: Dict[str, AgentSession] = {}
        self.metrics = {
            "total_requests": 0,
            "total_steps": 0,
            "avg_steps_per_request": 0.0,
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
        session.context["topic"] = topic
        
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
        code_prompt = f"""Write {language} code to: {task}

Context: {context}

Provide clean, well-commented code."""
        
        code = await self._call_llm(code_prompt, temperature=0.3)
        
        # Test if Python
        test_result = None
        if language == "python" and "python" in self.config.tools:
            test_result = await self._test_code(code)
            
            # Fix if needed
            if test_result and test_result.get("error"):
                fix_prompt = f"""Fix this Python code error:

Code:
{code}

Error:
{test_result['error']}

Provide corrected code."""
                
                fixed_code = await self._call_llm(fix_prompt, temperature=0.2)
                code = fixed_code
                test_result = await self._test_code(fixed_code)
        
        # Generate explanation
        explanation = await self._call_llm(
            f"Explain this {language} code concisely:\n{code}",
            temperature=0.5
        )
        
        return {
            "code": code,
            "explanation": explanation,
            "test_result": test_result,
            "language": language
        }
    
    async def _analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze content"""
        content = params.get("content", "")
        question = params.get("question", "Provide a detailed analysis")
        
        analysis_prompt = f"""Analyze the following content:

{content}

Question: {question}

Provide a thorough analysis."""
        
        analysis = await self._call_llm(analysis_prompt, temperature=0.6)
        
        return {
            "analysis": analysis,
            "question": question,
            "success": True
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
            prompt = f"""Previous conversation:
{context}

User: {message}

Provide a helpful response."""
            
            response = await self._call_llm(prompt, temperature=0.8)
        
        session.history.append({"role": "assistant", "content": response, "timestamp": datetime.now()})
        session.last_activity = datetime.now()
        
        return {
            "response": response,
            "session_id": session_id,
            "tools_used": needs_tools
        }
    
    async def _plan_steps(self, goal: str, agent_type: str) -> List[AgentStep]:
        """Plan execution steps using LLM"""
        prompt = f"""Create a plan to {agent_type}: {goal}
        
Available tools:
- llm: Language model queries
- python: Execute Python code (if available)
- analyze: Deep analysis

Generate 3-5 steps. For each step specify:
- action: what to do
- tool: which tool to use
- parameters: any specific parameters

Output as JSON array."""
        
        response = await self._call_llm(prompt, temperature=0.7)
        
        # Try to parse JSON response
        try:
            # Extract JSON from response if wrapped in text
            import re
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                steps_data = json.loads(json_match.group())
            else:
                steps_data = json.loads(response)
            
            steps = []
            for item in steps_data:
                steps.append(AgentStep(
                    action=item.get("action", "analyze"),
                    tool=item.get("tool", "llm"),
                    parameters=item.get("parameters", {})
                ))
            return steps
        except Exception as e:
            logger.warning(f"Failed to parse plan JSON: {e}")
            # Fallback plan
            return [
                AgentStep("analyze", "llm", {"prompt": f"Analyze {goal}"}),
                AgentStep("synthesize", "llm", {"prompt": f"Synthesize findings about {goal}"})
            ]
    
    async def _execute_tool(self, tool: str, parameters: Dict[str, Any]) -> Any:
        """Execute a tool using the appropriate provider via ResourceManager"""
        if tool == "llm":
            prompt = parameters.get("prompt", "")
            return await self._call_llm(prompt)
        
        elif tool == "python" and "python" in self.config.tools:
            code = parameters.get("code", "")
            if self.resource_manager:
                # Try to use DockerHub for Python execution
                docker_hub = self.resource_manager.get_hub("docker")
                if docker_hub:
                    try:
                        instance = await docker_hub.get_available_instance()
                        if instance:
                            # Execute via Docker
                            result = await docker_hub.execute_code(code)
                            return {"output": result, "success": True}
                    except Exception as e:
                        logger.warning(f"Docker execution failed: {e}")
            return {"error": "Python execution not available", "code": code}
        
        elif tool == "analyze":
            # Use LLM for analysis
            prompt = parameters.get("prompt", f"Analyze: {parameters}")
            return await self._call_llm(prompt)
        
        else:
            # Default to LLM
            return await self._call_llm(f"Process this with {tool}: {parameters}")
    
    async def _call_llm(self, prompt: str, temperature: Optional[float] = None) -> str:
        """Call LLM via OllamaHub"""
        if not self.resource_manager:
            return "Error: No resource manager available"
        
        ollama_hub = self.resource_manager.get_hub("ollama")
        if not ollama_hub:
            return "Error: Ollama hub not available"
        
        try:
            result = await ollama_hub.chat_completion(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature or self.config.temperature
            )
            
            return result.get("response", "")
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return f"Error calling LLM: {str(e)}"
    
    async def _test_code(self, code: str) -> Dict[str, Any]:
        """Test Python code via DockerHub"""
        if not self.resource_manager:
            return {"success": False, "error": "No resource manager"}
        
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
    
    def _update_avg_steps(self) -> None:
        """Update average steps metric"""
        if self.metrics["total_requests"] > 0:
            self.metrics["avg_steps_per_request"] = (
                self.metrics["total_steps"] / self.metrics["total_requests"]
            )
    
    async def _check_needs_tools(self, message: str) -> bool:
        """Check if message requires tool use"""
        check_prompt = f"""Does this request need external tools or data, or can it be answered with general knowledge?
Request: {message}

Answer 'yes' if it needs tools (web search, code execution, file operations).
Answer 'no' for general questions, explanations, or conversations.

Answer with just 'yes' or 'no'."""
        
        check = await self._call_llm(check_prompt, temperature=0.1)
        return "yes" in check.lower()
    
    async def _execute_with_tools(self, message: str, session: AgentSession) -> str:
        """Execute request using tools"""
        # Simplified tool execution
        plan = await self._plan_steps(message, "chat")
        
        results = []
        for step in plan[:3]:  # Limit steps in chat
            result = await self._execute_tool(step.tool, step.parameters)
            results.append(f"{step.action}: {result}")
        
        # Synthesize response
        synthesis_prompt = f"""Answer this question: {message}

Based on these results:
{chr(10).join(results)}

Provide a helpful, conversational response."""
        
        return await self._call_llm(synthesis_prompt, temperature=0.7)
    
    def _format_history(self, history: List[Dict]) -> str:
        """Format conversation history"""
        formatted = []
        for entry in history:
            role = entry["role"].capitalize()
            content = entry["content"][:500]  # Truncate long messages
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    async def _synthesize_results(
        self, 
        goal: str, 
        results: List[AgentStep], 
        agent_type: str
    ) -> str:
        """Synthesize results into final output"""
        successful_results = []
        for r in results:
            if r.result and not r.error:
                result_str = str(r.result)[:500]  # Truncate long results
                successful_results.append(f"{r.action}: {result_str}")
        
        if not successful_results:
            return f"Unable to complete {agent_type} for: {goal}. All steps failed."
        
        prompt = f"""Create a comprehensive {agent_type} report for: {goal}

Based on these findings:
{chr(10).join(successful_results)}

Structure the report with:
1. Summary
2. Key Findings
3. Details
4. Conclusions

Be thorough but concise."""
        
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
        resource_manager: Optional[Any] = None,
        max_agents: int = 10,
        **kwargs
    ) -> None:
        super().__init__(
            hub_id=hub_id,
            resource_type=ResourceType.CUSTOM,
            **kwargs
        )
        
        self.resource_manager = resource_manager
        self.max_agents = max_agents
        self.agent_instances: Dict[str, AgentInstance] = {}
        
        logger.info(f"Initialized AgentHub with max_agents={max_agents}")
    
    def set_resource_manager(self, resource_manager: Any) -> None:
        """Set the resource manager for accessing other hubs"""
        self.resource_manager = resource_manager
        # Update existing agents with resource manager
        for agent in self.agent_instances.values():
            agent.resource_manager = resource_manager
    
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
            response = await agent._call_llm("Respond with 'ok'", temperature=0.1)
            return "ok" in response.lower() or len(response) > 0
        except Exception as e:
            logger.error(f"Health check failed for agent {instance.id}: {e}")
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
        if not instance or not instance.config:
            return False
        
        config = instance.config
        
        # Stop and start
        await self.stop_instance(instance_id)
        new_instance = await self.start_instance(config)
        
        # Swap to maintain ID
        if new_instance.id in self.agent_instances:
            agent = self.agent_instances.pop(new_instance.id)
            agent.instance_id = instance_id
            self.agent_instances[instance_id] = agent
            
            # Update registration
            await self.unregister_instance(new_instance.id)
            new_instance.id = instance_id
            self.instances[instance_id] = new_instance
        
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
        # Add session ID if provided
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
            tools=["llm", "python"] if agent_type == AgentType.CODE else ["llm"]
        )
        
        instance = await self.start_instance(config)
        return self.agent_instances[instance.id]
    
    async def cleanup_sessions(self, max_age_seconds: int = 3600) -> int:
        """Clean up old sessions"""
        now = datetime.now()
        total_cleaned = 0
        
        for agent in self.agent_instances.values():
            expired = []
            for session_id, session in agent.sessions.items():
                age = (now - session.last_activity).total_seconds()
                if age > max_age_seconds:
                    expired.append(session_id)
            
            for session_id in expired:
                del agent.sessions[session_id]
                total_cleaned += 1
                logger.debug(f"Cleaned up expired session: {session_id}")
        
        return total_cleaned
    
    async def get_agent_status(self) -> Dict[str, Any]:
        """Get detailed status of all agents"""
        status = {
            "total_agents": len(self.agent_instances),
            "max_agents": self.max_agents,
            "agents": []
        }
        
        for agent_id, agent in self.agent_instances.items():
            instance = await self.get_instance(agent_id)
            if instance:
                agent_info = {
                    "id": agent_id,
                    "type": agent.config.agent_type.value,
                    "model": agent.config.model,
                    "status": instance.status.value,
                    "metrics": agent.metrics,
                    "sessions": len(agent.sessions),
                    "tools": agent.config.tools
                }
                status["agents"].append(agent_info)
        
        return status