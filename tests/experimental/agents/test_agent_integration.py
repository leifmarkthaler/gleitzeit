"""
Integration tests for AgentHub with Gleitzeit workflow system

These tests verify that agents work correctly within the workflow execution engine.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from datetime import datetime

from gleitzeit.core.models import Workflow, Task
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentHub, AgentConfig, AgentType
from gleitzeit.registry import ProtocolProviderRegistry


@pytest.fixture
async def mock_execution_environment():
    """Create a mock execution environment with agent support"""
    
    # Create resource manager
    resource_manager = ResourceManager("test-manager")
    
    # Mock Ollama hub
    ollama_hub = AsyncMock()
    ollama_hub.chat_completion = AsyncMock(return_value={
        "response": "Mock LLM response for testing"
    })
    ollama_hub.running = True
    
    # Add Ollama hub to resource manager
    await resource_manager.add_hub("ollama", ollama_hub)
    
    # Create and add Agent hub
    agent_hub = AgentHub(
        hub_id="agent",
        resource_manager=resource_manager,
        max_agents=3
    )
    await resource_manager.add_hub("agent", agent_hub)
    await agent_hub.start()
    
    # Create registry (mock)
    registry = MagicMock(spec=ProtocolProviderRegistry)
    
    # Create execution engine (simplified mock)
    engine = MagicMock(spec=ExecutionEngine)
    engine.resource_manager = resource_manager
    engine.registry = registry
    
    yield {
        "resource_manager": resource_manager,
        "agent_hub": agent_hub,
        "ollama_hub": ollama_hub,
        "registry": registry,
        "engine": engine
    }
    
    # Cleanup
    await agent_hub.stop()
    await resource_manager.stop()


class TestAgentWorkflowIntegration:
    """Test agent integration with workflow system"""
    
    @pytest.mark.asyncio
    async def test_simple_agent_workflow(self, mock_execution_environment):
        """Test a simple workflow using agents"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        # Create a simple workflow
        workflow = Workflow(
            name="test_agent_workflow",
            tasks=[
                Task(
                    id="research_task",
                    method="agent/research",
                    parameters={
                        "topic": "artificial intelligence",
                        "max_steps": 2
                    }
                ),
                Task(
                    id="analyze_task",
                    method="agent/analyze",
                    dependencies=["research_task"],
                    parameters={
                        "content": "${research_task.report}",
                        "question": "What are the key points?"
                    }
                )
            ]
        )
        
        # Execute tasks manually (simulating engine execution)
        results = {}
        
        # Execute research task
        research_result = await agent_hub.execute_agent_task(
            method="research",
            parameters=workflow.tasks[0].parameters
        )
        results["research_task"] = research_result
        
        # Simulate parameter substitution
        analyze_params = workflow.tasks[1].parameters.copy()
        analyze_params["content"] = research_result.get("report", "")
        
        # Execute analyze task
        analyze_result = await agent_hub.execute_agent_task(
            method="analyze",
            parameters=analyze_params
        )
        results["analyze_task"] = analyze_result
        
        # Verify results
        assert "research_task" in results
        assert "analyze_task" in results
        assert results["research_task"]["success"] is True
        assert "analysis" in results["analyze_task"]
    
    @pytest.mark.asyncio
    async def test_agent_session_across_tasks(self, mock_execution_environment):
        """Test maintaining agent session across workflow tasks"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        session_id = str(uuid.uuid4())
        
        # Create workflow with multiple chat tasks using same session
        workflow = Workflow(
            name="chat_workflow",
            tasks=[
                Task(
                    id="chat1",
                    method="agent/chat",
                    parameters={
                        "message": "Hello, I'm learning about Python",
                        "session_id": session_id
                    }
                ),
                Task(
                    id="chat2",
                    method="agent/chat",
                    dependencies=["chat1"],
                    parameters={
                        "message": "What are the main data types?",
                        "session_id": session_id
                    }
                ),
                Task(
                    id="chat3",
                    method="agent/chat",
                    dependencies=["chat2"],
                    parameters={
                        "message": "Can you show me an example?",
                        "session_id": session_id
                    }
                )
            ]
        )
        
        # Execute tasks in sequence
        for task in workflow.tasks:
            result = await agent_hub.execute_agent_task(
                method="chat",
                parameters=task.parameters
            )
            assert "response" in result
            assert result["session_id"] == session_id
        
        # Verify session was maintained
        agents = list(agent_hub.agent_instances.values())
        assert len(agents) > 0
        
        chat_agent = None
        for agent in agents:
            if agent.config.agent_type == AgentType.CHAT:
                chat_agent = agent
                break
        
        assert chat_agent is not None
        assert session_id in chat_agent.sessions
        session = chat_agent.sessions[session_id]
        assert len(session.history) == 6  # 3 user + 3 assistant messages
    
    @pytest.mark.asyncio
    async def test_agent_code_generation_workflow(self, mock_execution_environment):
        """Test code generation and testing workflow"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        # Mock Docker hub for code testing
        docker_hub = AsyncMock()
        docker_hub.execute_code = AsyncMock(return_value={
            "output": "Test passed"
        })
        docker_hub.get_available_instance = AsyncMock(return_value=MagicMock())
        await env["resource_manager"].add_hub("docker", docker_hub)
        
        # Workflow: Generate code, then test it
        workflow = Workflow(
            name="code_gen_workflow",
            tasks=[
                Task(
                    id="generate",
                    method="agent/code",
                    parameters={
                        "task": "Create a function to calculate factorial",
                        "language": "python"
                    }
                ),
                Task(
                    id="improve",
                    method="agent/code",
                    dependencies=["generate"],
                    parameters={
                        "task": "Optimize this code: ${generate.code}",
                        "language": "python"
                    }
                )
            ]
        )
        
        # Execute generation task
        gen_result = await agent_hub.execute_agent_task(
            method="code",
            parameters=workflow.tasks[0].parameters
        )
        
        assert "code" in gen_result
        assert "explanation" in gen_result
        assert gen_result["language"] == "python"
        
        # Execute improvement task
        improve_params = workflow.tasks[1].parameters.copy()
        improve_params["task"] = f"Optimize this code: {gen_result['code']}"
        
        improve_result = await agent_hub.execute_agent_task(
            method="code",
            parameters=improve_params
        )
        
        assert "code" in improve_result
        assert improve_result["language"] == "python"
    
    @pytest.mark.asyncio
    async def test_agent_resource_limits(self, mock_execution_environment):
        """Test that agent resource limits are enforced"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        # Agent hub was created with max_agents=3
        agent_types = [AgentType.RESEARCH, AgentType.CODE, AgentType.CHAT]
        
        # Create maximum number of agents
        for agent_type in agent_types:
            config = AgentConfig(agent_type=agent_type)
            await agent_hub.start_instance(config)
        
        # Verify we have 3 agents
        assert len(agent_hub.agent_instances) == 3
        
        # Try to create one more (should fail)
        with pytest.raises(Exception) as exc_info:
            config = AgentConfig(agent_type=AgentType.ANALYSIS)
            await agent_hub.start_instance(config)
        
        assert "Maximum number of agents" in str(exc_info.value)
        
        # But we should be able to reuse existing agents
        result = await agent_hub.execute_agent_task(
            method="research",
            parameters={"topic": "test", "max_steps": 1}
        )
        assert result is not None  # Should reuse existing research agent
    
    @pytest.mark.asyncio
    async def test_agent_error_recovery(self, mock_execution_environment):
        """Test agent error handling and recovery"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        # Temporarily break Ollama hub
        env["ollama_hub"].chat_completion.side_effect = Exception("LLM service unavailable")
        
        # Try to execute task (should handle error gracefully)
        result = await agent_hub.execute_agent_task(
            method="chat",
            parameters={"message": "Hello"}
        )
        
        # Agent should handle the error
        assert "response" in result
        assert "Error" in result["response"] or result["response"] == ""
        
        # Restore Ollama hub
        env["ollama_hub"].chat_completion.side_effect = None
        env["ollama_hub"].chat_completion.return_value = {"response": "Recovered"}
        
        # Try again (should work now)
        result = await agent_hub.execute_agent_task(
            method="chat",
            parameters={"message": "Hello again"}
        )
        
        assert "response" in result
        assert result["response"] == "Recovered"
    
    @pytest.mark.asyncio
    async def test_agent_metrics_collection(self, mock_execution_environment):
        """Test that agent metrics are properly collected"""
        env = mock_execution_environment
        agent_hub = env["agent_hub"]
        
        # Execute several tasks
        for i in range(3):
            await agent_hub.execute_agent_task(
                method="chat",
                parameters={"message": f"Message {i}"}
            )
        
        # Get agent status
        status = await agent_hub.get_agent_status()
        
        assert status["total_agents"] > 0
        
        # Find chat agent
        chat_agent_info = None
        for agent_info in status["agents"]:
            if agent_info["type"] == "chat":
                chat_agent_info = agent_info
                break
        
        assert chat_agent_info is not None
        assert chat_agent_info["metrics"]["total_requests"] == 3
        
        # Check hub-level metrics
        for agent_id, agent_instance in agent_hub.agent_instances.items():
            if agent_instance.config.agent_type == AgentType.CHAT:
                instance = await agent_hub.get_instance(agent_id)
                if instance:
                    metrics = await agent_hub.collect_metrics(instance)
                    assert metrics.request_count == 3
                    break


if __name__ == "__main__":
    pytest.main([__file__, "-v"])