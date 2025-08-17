# Agent System Design for Gleitzeit

## Overview

This document outlines a design for building an agent system on top of Gleitzeit's existing workflow orchestration infrastructure. Agents are autonomous entities that can plan, use tools, maintain memory, and execute complex multi-step tasks.

## Core Concepts

### What is an Agent?

An agent in this system is:
- A **persistent workflow pattern** that maintains state across interactions
- A **decision-making entity** that can decompose complex tasks
- A **tool user** that leverages Gleitzeit providers
- A **learning system** that maintains memory and context

### Key Principles

1. **Build on Gleitzeit**: Agents use existing workflow engine, not replace it
2. **Modular Design**: Agents are compositions of providers and workflows
3. **Observable**: Every agent action is a tracked workflow task
4. **Stateful**: Agents maintain memory using persistence layer
5. **Extensible**: New capabilities added as providers/tools

## Architecture

### System Layers

```
┌─────────────────────────────────────┐
│         Agent Layer (New)            │
│  • Agent Definition & Lifecycle      │
│  • Memory/State Management           │
│  • Planning & Reasoning              │
│  • Tool Selection & Execution        │
└────────────┬────────────────────────┘
             │ Uses
┌────────────▼────────────────────────┐
│    Gleitzeit Core (Existing)        │
│  • Workflow Execution Engine         │
│  • Task Dependencies                 │
│  • Provider Management               │
│  • Unified Persistence               │
└─────────────────────────────────────┘
```

### Component Interactions

```
User Request → Agent → Planner → Workflow Generator → Execution Engine
                ↑                                            ↓
             Memory ← ← ← ← ← Results Processing ← ← ← Task Results
```

## Agent Definition Schema

### YAML Configuration

```yaml
# agents/research_assistant.yaml
agent:
  name: "ResearchAssistant"
  version: "1.0"
  description: "Autonomous research agent for gathering and analyzing information"
  
  # Agent capabilities and constraints
  capabilities:
    max_iterations: 10
    timeout: 600  # seconds
    allow_code_execution: true
    allow_web_access: true
  
  # Memory configuration
  memory:
    type: "hierarchical"  # short_term, long_term, hierarchical
    short_term:
      context_window: 10  # last N interactions
      ttl: 3600          # seconds
    long_term:
      storage: "persistence"  # use Gleitzeit persistence
      index_strategy: "semantic"  # keyword, semantic, hybrid
  
  # Available tools
  tools:
    - id: "web_search"
      method: "mcp/tool.web_search"
      description: "Search the web for information"
      cost: 0.001  # Optional cost tracking
      
    - id: "read_file"
      method: "mcp/tool.file_read"
      description: "Read content from a file"
      
    - id: "analyze_text"
      method: "llm/chat"
      description: "Analyze and summarize text content"
      parameters:
        model: "llama3.2"
        
    - id: "python_analysis"
      method: "python/execute"
      description: "Run Python code for data analysis"
      constraints:
        timeout: 30
        memory_limit: "256MB"
        
    - id: "write_report"
      method: "llm/chat"
      description: "Generate structured reports"
      parameters:
        model: "llama3.2"
        temperature: 0.7
  
  # Planning configuration
  planning:
    strategy: "react"  # react, chain_of_thought, tree_of_thought
    model: "llama3.2"
    system_prompt: |
      You are a research assistant that helps users gather and analyze information.
      Break down complex requests into actionable steps.
      Use available tools effectively to accomplish tasks.
      Always verify information from multiple sources when possible.
    
    # Planning examples for few-shot learning
    examples:
      - input: "Research the impact of AI on employment"
        plan: |
          1. Search for recent statistics on AI and employment
          2. Find expert opinions and research papers
          3. Analyze positive and negative impacts
          4. Synthesize findings into a balanced report
```

## Core Components

### 1. Agent Class

```python
# experimental/agentsystem/agent.py
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum
import uuid
from datetime import datetime

class AgentState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class AgentConfig:
    name: str
    version: str
    description: str
    capabilities: Dict[str, Any]
    memory_config: Dict[str, Any]
    tools: List[Dict[str, Any]]
    planning_config: Dict[str, Any]

class Agent:
    def __init__(
        self, 
        config: AgentConfig,
        execution_engine: ExecutionEngine,
        persistence: UnifiedPersistenceAdapter
    ):
        self.config = config
        self.engine = execution_engine
        self.persistence = persistence
        self.state = AgentState.IDLE
        self.session_id = str(uuid.uuid4())
        
        # Initialize components
        self.memory = AgentMemory(config.memory_config, persistence)
        self.planner = AgentPlanner(config.planning_config, execution_engine)
        self.tool_manager = ToolManager(config.tools)
        
        # Tracking
        self.current_objective = None
        self.execution_history = []
        self.iteration_count = 0
    
    async def process_request(self, request: str, context: Optional[Dict] = None) -> str:
        """Main entry point for agent requests"""
        try:
            self.state = AgentState.PLANNING
            self.current_objective = request
            self.iteration_count = 0
            
            # Add to memory
            await self.memory.add_interaction("user", request, context)
            
            # Generate and execute plan
            result = await self._execute_with_planning(request)
            
            # Store result in memory
            await self.memory.add_interaction("assistant", result)
            
            self.state = AgentState.COMPLETED
            return result
            
        except Exception as e:
            self.state = AgentState.FAILED
            error_msg = f"Agent execution failed: {str(e)}"
            await self.memory.add_interaction("error", error_msg)
            raise
    
    async def _execute_with_planning(self, objective: str) -> str:
        """Execute objective using planning strategy"""
        max_iterations = self.config.capabilities.get("max_iterations", 10)
        
        while self.iteration_count < max_iterations:
            self.iteration_count += 1
            
            # Get current context from memory
            context = await self.memory.get_relevant_context(objective)
            
            # Plan next action
            action = await self.planner.plan_next_action(
                objective=objective,
                context=context,
                tools=self.tool_manager.get_tool_descriptions(),
                history=self.execution_history
            )
            
            # Check if objective is complete
            if action.is_complete:
                return action.final_answer
            
            # Execute action
            self.state = AgentState.EXECUTING
            result = await self._execute_action(action)
            
            # Record execution
            self.execution_history.append({
                "iteration": self.iteration_count,
                "action": action.to_dict(),
                "result": result,
                "timestamp": datetime.now().isoformat()
            })
            
            # Check for completion
            if await self._is_objective_complete(objective, self.execution_history):
                return await self._generate_final_response(objective, self.execution_history)
        
        return f"Maximum iterations ({max_iterations}) reached. Partial results: {self._summarize_progress()}"
    
    async def _execute_action(self, action: AgentAction) -> Any:
        """Execute a planned action"""
        # Create workflow for action
        workflow = self._action_to_workflow(action)
        
        # Execute via Gleitzeit engine
        result = await self.engine.execute_workflow(workflow)
        
        # Extract and return result
        return self._extract_result(result)
    
    def _action_to_workflow(self, action: AgentAction) -> Workflow:
        """Convert agent action to Gleitzeit workflow"""
        task = Task(
            id=f"agent_action_{uuid.uuid4().hex[:8]}",
            method=action.tool.method,
            parameters=action.parameters,
            metadata={
                "agent": self.config.name,
                "session": self.session_id,
                "action_type": action.action_type
            }
        )
        
        return Workflow(
            name=f"agent_{self.config.name}_action",
            tasks=[task],
            metadata={
                "agent_session": self.session_id,
                "objective": self.current_objective
            }
        )
```

### 2. Agent Memory

```python
# experimental/agentsystem/memory.py
from collections import deque
from typing import List, Dict, Any, Optional
import json
import hashlib

class MemoryType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    WORKING = "working"

class AgentMemory:
    def __init__(self, config: Dict[str, Any], persistence: UnifiedPersistenceAdapter):
        self.config = config
        self.persistence = persistence
        
        # Memory stores
        self.short_term = deque(maxlen=config.get("short_term", {}).get("context_window", 10))
        self.long_term = {}  # Key-value store for important information
        self.working_memory = {}  # Current task context
        
        # Memory index for retrieval
        self.memory_index = MemoryIndex()
    
    async def add_interaction(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add interaction to memory"""
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "metadata": metadata or {}
        }
        
        # Add to short-term memory
        self.short_term.append(interaction)
        
        # Determine if should be stored long-term
        if await self._should_store_long_term(interaction):
            await self._store_long_term(interaction)
        
        # Update working memory if relevant
        self._update_working_memory(interaction)
    
    async def get_relevant_context(self, query: str, max_items: int = 5) -> str:
        """Retrieve relevant context for query"""
        relevant_items = []
        
        # Get recent interactions from short-term
        recent = list(self.short_term)[-max_items:]
        relevant_items.extend(recent)
        
        # Search long-term memory
        if self.long_term:
            long_term_results = await self._search_long_term(query, max_items)
            relevant_items.extend(long_term_results)
        
        # Include working memory
        if self.working_memory:
            relevant_items.append({
                "type": "working_memory",
                "content": self.working_memory
            })
        
        return self._format_context(relevant_items)
    
    async def _should_store_long_term(self, interaction: Dict) -> bool:
        """Determine if interaction should be stored long-term"""
        # Store if contains important information
        importance_keywords = ["result", "conclusion", "summary", "important", "remember"]
        content = interaction.get("content", "").lower()
        
        return any(keyword in content for keyword in importance_keywords)
    
    async def _store_long_term(self, interaction: Dict):
        """Store interaction in long-term memory"""
        # Generate key based on content
        key = self._generate_memory_key(interaction["content"])
        
        # Create memory entry
        memory_entry = {
            "key": key,
            "interaction": interaction,
            "embeddings": None,  # Future: Add semantic embeddings
            "tags": self._extract_tags(interaction["content"])
        }
        
        # Store in persistence
        await self.persistence.store_task_result(
            f"agent_memory_{key}",
            memory_entry
        )
        
        # Update local index
        self.long_term[key] = memory_entry
        self.memory_index.add(key, memory_entry)
    
    def _generate_memory_key(self, content: str) -> str:
        """Generate unique key for memory entry"""
        hash_obj = hashlib.md5(content.encode())
        return f"mem_{hash_obj.hexdigest()[:8]}"
    
    def _extract_tags(self, content: str) -> List[str]:
        """Extract tags from content for indexing"""
        # Simple keyword extraction (could be enhanced with NLP)
        words = content.lower().split()
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for"}
        tags = [w for w in words if w not in stopwords and len(w) > 3]
        return tags[:10]  # Limit to top 10 tags
```

### 3. Agent Planner

```python
# experimental/agentsystem/planner.py
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum

class PlanningStrategy(Enum):
    REACT = "react"  # Reasoning + Acting
    CHAIN_OF_THOUGHT = "chain_of_thought"
    TREE_OF_THOUGHT = "tree_of_thought"
    REFLEXION = "reflexion"

@dataclass
class AgentAction:
    action_type: str  # "think", "act", "observe", "complete"
    tool: Optional[Tool] = None
    parameters: Optional[Dict[str, Any]] = None
    reasoning: str = ""
    is_complete: bool = False
    final_answer: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type,
            "tool": self.tool.id if self.tool else None,
            "parameters": self.parameters,
            "reasoning": self.reasoning,
            "is_complete": self.is_complete
        }

class AgentPlanner:
    def __init__(self, config: Dict[str, Any], execution_engine: ExecutionEngine):
        self.config = config
        self.engine = execution_engine
        self.strategy = PlanningStrategy(config.get("strategy", "react"))
        self.model = config.get("model", "llama3.2")
        self.system_prompt = config.get("system_prompt", "")
    
    async def plan_next_action(
        self,
        objective: str,
        context: str,
        tools: List[Dict],
        history: List[Dict]
    ) -> AgentAction:
        """Plan next action based on current state"""
        
        if self.strategy == PlanningStrategy.REACT:
            return await self._plan_react(objective, context, tools, history)
        elif self.strategy == PlanningStrategy.CHAIN_OF_THOUGHT:
            return await self._plan_cot(objective, context, tools, history)
        else:
            raise ValueError(f"Unknown planning strategy: {self.strategy}")
    
    async def _plan_react(
        self,
        objective: str,
        context: str,
        tools: List[Dict],
        history: List[Dict]
    ) -> AgentAction:
        """ReAct planning: Reason then Act"""
        
        # Format prompt for reasoning
        prompt = self._build_react_prompt(objective, context, tools, history)
        
        # Get reasoning from LLM
        reasoning_task = Task(
            id="reasoning",
            method="llm/chat",
            parameters={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            }
        )
        
        workflow = Workflow(name="agent_reasoning", tasks=[reasoning_task])
        result = await self.engine.execute_workflow(workflow)
        
        # Parse LLM response into action
        return self._parse_reasoning_to_action(result.tasks[0].result)
    
    def _build_react_prompt(
        self,
        objective: str,
        context: str,
        tools: List[Dict],
        history: List[Dict]
    ) -> str:
        """Build ReAct prompt"""
        
        # Format history
        history_str = ""
        for h in history[-5:]:  # Last 5 actions
            history_str += f"\nThought: {h['action']['reasoning']}\n"
            if h['action'].get('tool'):
                history_str += f"Action: {h['action']['tool']} with {h['action'].get('parameters', {})}\n"
                history_str += f"Observation: {h.get('result', 'No result')}\n"
        
        # Format tools
        tools_str = "\n".join([f"- {t['id']}: {t['description']}" for t in tools])
        
        prompt = f"""
Objective: {objective}

Context:
{context}

Available Tools:
{tools_str}

History:
{history_str if history_str else "No previous actions"}

Now, think about what to do next. Follow this format:

Thought: [Your reasoning about what to do next]
Action: [Either use a tool or provide final answer]
Tool: [If using a tool, which one?]
Parameters: [If using a tool, what parameters?]
Is Complete: [true/false - is the objective complete?]
Final Answer: [If complete, what is the final answer?]

Think step by step.
"""
        return prompt
    
    def _parse_reasoning_to_action(self, llm_response: str) -> AgentAction:
        """Parse LLM response into AgentAction"""
        # Simple parsing logic (could be enhanced with structured output)
        lines = llm_response.strip().split('\n')
        
        action = AgentAction(
            action_type="think",
            reasoning="",
            is_complete=False
        )
        
        for line in lines:
            line = line.strip()
            if line.startswith("Thought:"):
                action.reasoning = line[8:].strip()
            elif line.startswith("Tool:"):
                tool_id = line[5:].strip()
                if tool_id and tool_id != "None":
                    action.action_type = "act"
                    action.tool = Tool(id=tool_id, method="", description="")
            elif line.startswith("Parameters:"):
                params_str = line[11:].strip()
                try:
                    action.parameters = json.loads(params_str)
                except:
                    action.parameters = {"input": params_str}
            elif line.startswith("Is Complete:"):
                action.is_complete = "true" in line.lower()
            elif line.startswith("Final Answer:"):
                action.final_answer = line[13:].strip()
        
        return action
```

### 4. Tool Manager

```python
# experimental/agentsystem/tools.py
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class Tool:
    id: str
    method: str  # Gleitzeit provider method
    description: str
    parameters: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    cost: Optional[float] = None

class ToolManager:
    def __init__(self, tool_configs: List[Dict[str, Any]]):
        self.tools = {}
        for config in tool_configs:
            tool = Tool(**config)
            self.tools[tool.id] = tool
    
    def get_tool(self, tool_id: str) -> Optional[Tool]:
        """Get tool by ID"""
        return self.tools.get(tool_id)
    
    def get_tool_descriptions(self) -> List[Dict]:
        """Get tool descriptions for planning"""
        return [
            {
                "id": tool.id,
                "description": tool.description,
                "parameters": tool.parameters
            }
            for tool in self.tools.values()
        ]
    
    def validate_tool_use(self, tool_id: str, parameters: Dict) -> bool:
        """Validate if tool can be used with given parameters"""
        tool = self.get_tool(tool_id)
        if not tool:
            return False
        
        # Check constraints
        if tool.constraints:
            # Validate against constraints
            pass
        
        return True
```

## Example Agent Implementations

### 1. Research Agent

```python
# experimental/agentsystem/agents/research_agent.py

class ResearchAgent(Agent):
    """Specialized agent for research tasks"""
    
    async def research_topic(self, topic: str, depth: str = "medium") -> Dict:
        """Research a topic with specified depth"""
        
        research_plan = f"""
        Research the topic: {topic}
        Depth: {depth}
        
        Steps:
        1. Search for general information
        2. Find authoritative sources
        3. Gather statistics and data
        4. Identify different perspectives
        5. Synthesize findings
        """
        
        result = await self.process_request(research_plan)
        
        # Structure the research output
        return {
            "topic": topic,
            "summary": result,
            "sources": self._extract_sources(self.execution_history),
            "key_findings": self._extract_findings(result),
            "timestamp": datetime.now().isoformat()
        }
```

### 2. Code Assistant Agent

```python
# experimental/agentsystem/agents/code_agent.py

class CodeAssistant(Agent):
    """Agent specialized in code analysis and generation"""
    
    async def debug_code(self, code: str, language: str = "python") -> Dict:
        """Debug code and provide fixes"""
        
        debug_request = f"""
        Debug this {language} code and fix any issues:
        
        ```{language}
        {code}
        ```
        
        Provide:
        1. Issue identification
        2. Fixed code
        3. Explanation of changes
        4. Test cases if applicable
        """
        
        result = await self.process_request(debug_request)
        
        return {
            "original_code": code,
            "analysis": result,
            "fixed_code": self._extract_code_blocks(result),
            "test_results": await self._run_tests(self._extract_code_blocks(result))
        }
    
    async def _run_tests(self, code: str) -> Dict:
        """Run code tests"""
        test_task = Task(
            id="test_code",
            method="python/execute",
            parameters={"code": code}
        )
        
        workflow = Workflow(name="code_test", tasks=[test_task])
        result = await self.engine.execute_workflow(workflow)
        
        return {
            "success": result.status == "completed",
            "output": result.tasks[0].result if result.status == "completed" else None,
            "error": result.tasks[0].error if result.status == "failed" else None
        }
```

### 3. Multi-Agent Coordinator

```python
# experimental/agentsystem/coordinator.py

class MultiAgentCoordinator:
    """Coordinates multiple agents for complex tasks"""
    
    def __init__(self, execution_engine: ExecutionEngine):
        self.engine = execution_engine
        self.agents = {}
        self.agent_registry = AgentRegistry()
    
    async def register_agent(self, agent_config_path: str) -> str:
        """Register a new agent"""
        config = self._load_agent_config(agent_config_path)
        agent = Agent(config, self.engine, self.engine.persistence)
        
        self.agents[config.name] = agent
        self.agent_registry.register(config.name, config.capabilities)
        
        return config.name
    
    async def delegate_task(self, task: str) -> Dict:
        """Delegate task to most appropriate agent"""
        
        # Select best agent for task
        agent_name = await self._select_agent(task)
        
        if not agent_name:
            raise ValueError("No suitable agent found for task")
        
        agent = self.agents[agent_name]
        result = await agent.process_request(task)
        
        return {
            "agent": agent_name,
            "result": result,
            "execution_time": agent.execution_history[-1]["timestamp"]
        }
    
    async def collaborate(self, objective: str, agents: List[str]) -> Dict:
        """Multiple agents collaborate on objective"""
        
        # Create collaboration plan
        collaboration_plan = await self._create_collaboration_plan(objective, agents)
        
        results = {}
        for step in collaboration_plan.steps:
            agent = self.agents[step.agent]
            
            # Include results from previous steps in context
            context = {
                "previous_results": results,
                "collaboration_objective": objective
            }
            
            result = await agent.process_request(step.task, context)
            results[step.id] = {
                "agent": step.agent,
                "task": step.task,
                "result": result
            }
        
        # Synthesize final result
        final_result = await self._synthesize_results(objective, results)
        
        return {
            "objective": objective,
            "collaboration_plan": collaboration_plan.to_dict(),
            "agent_results": results,
            "final_result": final_result
        }
```

## Integration with Gleitzeit

### New CLI Commands

```bash
# Initialize agent
gleitzeit agent init research_agent.yaml

# Run agent interactively
gleitzeit agent chat research_agent

# Execute single request
gleitzeit agent run research_agent "Research quantum computing applications"

# List available agents
gleitzeit agent list

# Multi-agent collaboration
gleitzeit agent collaborate --agents research,code "Build a quantum computing simulator"
```

### Configuration Extension

```yaml
# ~/.gleitzeit/config.yaml
agents:
  enabled: true
  registry_path: ~/.gleitzeit/agents
  
  defaults:
    max_iterations: 10
    timeout: 600
    memory_type: "hierarchical"
  
  available_agents:
    - research_agent.yaml
    - code_agent.yaml
    - data_analyst.yaml
```

## Next Steps

### Phase 1: Foundation (Week 1-2)
1. Implement basic Agent class
2. Create simple memory system
3. Build ReAct planner
4. Integrate with Gleitzeit engine

### Phase 2: Core Features (Week 3-4)
1. Implement tool manager
2. Add planning strategies
3. Build agent registry
4. Create CLI interface

### Phase 3: Advanced Features (Week 5-6)
1. Multi-agent coordination
2. Advanced memory (semantic search)
3. Learning from feedback
4. Cost tracking and optimization

### Phase 4: Testing & Polish (Week 7-8)
1. Comprehensive testing
2. Documentation
3. Example agents
4. Performance optimization

## Challenges & Considerations

### Technical Challenges
1. **Dynamic Workflow Generation**: Creating workflows on-the-fly
2. **Context Management**: Handling LLM context windows
3. **State Persistence**: Maintaining agent state across sessions
4. **Error Recovery**: Graceful handling of failures

### Design Decisions
1. **Memory Architecture**: Hierarchical vs flat storage
2. **Planning Strategies**: Which to implement first
3. **Tool Integration**: How to expose Gleitzeit providers
4. **Cost Management**: Tracking and limiting LLM usage

### Performance Considerations
1. **Caching**: Cache LLM responses for similar queries
2. **Parallel Execution**: Run independent actions in parallel
3. **Resource Limits**: Prevent runaway agent execution
4. **Monitoring**: Track agent performance metrics

## Conclusion

This agent system design leverages Gleitzeit's existing infrastructure while adding autonomous capabilities. The modular design allows for incremental development and testing, with clear integration points into the existing system.

The key innovation is treating agents as intelligent workflow generators that can:
- Plan and execute complex multi-step tasks
- Maintain memory and learn from interactions
- Coordinate with other agents
- Use any Gleitzeit provider as a tool

This approach maintains Gleitzeit's core strengths while extending it into the realm of autonomous agents.