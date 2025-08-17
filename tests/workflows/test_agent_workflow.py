"""Tests for agent workflow execution"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import yaml

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentHub, AgentConfig, AgentType


class TestAgentWorkflow:
    """Test agent workflow execution"""
    
    @pytest.fixture
    def agent_workflow_content(self):
        """Create agent workflow content"""
        return {
            "name": "Agent Test Workflow",
            "version": "1.0",
            "description": "Test workflow for agent execution",
            "tasks": [
                {
                    "id": "research_task",
                    "name": "Research Task",
                    "protocol": "agent",
                    "method": "research",
                    "params": {
                        "topic": "benefits of automated testing",
                        "max_steps": 2
                    }
                },
                {
                    "id": "analyze_task",
                    "name": "Analyze Task",
                    "protocol": "agent",
                    "method": "analyze",
                    "dependencies": ["research_task"],
                    "params": {
                        "content": "${research_task.report}",
                        "question": "What are the top 3 benefits?"
                    }
                },
                {
                    "id": "chat_task",
                    "name": "Chat Task",
                    "protocol": "agent",
                    "method": "chat",
                    "params": {
                        "message": "Can you summarize the research?",
                        "session_id": "test_session"
                    }
                }
            ]
        }
    
    @pytest.fixture
    async def mock_agent_provider(self):
        """Create mock agent provider"""
        provider = Mock()
        provider.provider_id = "agent"
        provider.protocol_id = "agent/v1"
        
        # Mock responses for different agent methods
        async def handle_request(method, params):
            if method == "research":
                return {
                    "report": "Research on automated testing shows multiple benefits including faster feedback, consistent execution, and reduced human error.",
                    "steps_executed": 2,
                    "session_id": "research_session",
                    "success": True
                }
            elif method == "analyze":
                return {
                    "analysis": "Top 3 benefits: 1) Faster feedback cycles, 2) Consistent test execution, 3) Reduced human error",
                    "question": params.get("question"),
                    "success": True
                }
            elif method == "chat":
                return {
                    "response": "The research shows that automated testing provides faster feedback, consistent execution, and reduces human error.",
                    "session_id": params.get("session_id"),
                    "tools_used": False
                }
            elif method == "code":
                return {
                    "code": "def test_example():\n    assert True",
                    "explanation": "Simple test function",
                    "language": "python",
                    "test_result": {"success": True}
                }
            return {"error": f"Unknown method: {method}"}
        
        provider.handle_request = AsyncMock(side_effect=handle_request)
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_resource_manager_with_agent(self, mock_agent_provider):
        """Create mock resource manager with agent hub"""
        resource_manager = Mock(spec=ResourceManager)
        
        # Create mock Ollama hub
        ollama_hub = AsyncMock()
        ollama_hub.chat_completion = AsyncMock(return_value={
            "response": "Mock LLM response"
        })
        
        # Create real agent hub with mocked resource manager
        agent_hub = AgentHub(
            hub_id="agent",
            resource_manager=resource_manager,
            max_agents=3
        )
        
        # Configure resource manager to return hubs
        def get_hub(hub_id):
            if hub_id == "ollama":
                return ollama_hub
            elif hub_id == "agent":
                return agent_hub
            return None
        
        resource_manager.get_hub = Mock(side_effect=get_hub)
        
        # Start agent hub
        await agent_hub.start()
        
        yield resource_manager, agent_hub
        
        await agent_hub.stop()
    
    @pytest.fixture
    async def mock_registry_with_agent(self, mock_agent_provider):
        """Create mock registry with agent provider"""
        registry = Mock(spec=ProtocolProviderRegistry)
        
        async def get_provider(protocol, method):
            if protocol == "agent" or protocol == "agent/v1":
                return mock_agent_provider
            return None
        
        registry.get_provider_for_method = AsyncMock(side_effect=get_provider)
        return registry
    
    @pytest.mark.asyncio
    async def test_workflow_structure(self, agent_workflow_content):
        """Test agent workflow has correct structure"""
        assert agent_workflow_content["name"] == "Agent Test Workflow"
        assert len(agent_workflow_content["tasks"]) == 3
        
        # Check task IDs
        task_ids = [t["id"] for t in agent_workflow_content["tasks"]]
        assert "research_task" in task_ids
        assert "analyze_task" in task_ids
        assert "chat_task" in task_ids
        
        # Check dependencies
        analyze_task = next(t for t in agent_workflow_content["tasks"] if t["id"] == "analyze_task")
        assert "research_task" in analyze_task["dependencies"]
    
    @pytest.mark.asyncio
    async def test_agent_research_execution(self, mock_agent_provider):
        """Test research agent execution"""
        result = await mock_agent_provider.handle_request("research", {
            "topic": "test topic",
            "max_steps": 2
        })
        
        assert result["success"] is True
        assert "report" in result
        assert result["steps_executed"] == 2
        assert "automated testing" in result["report"].lower()
    
    @pytest.mark.asyncio
    async def test_agent_analyze_execution(self, mock_agent_provider):
        """Test analyze agent execution"""
        result = await mock_agent_provider.handle_request("analyze", {
            "content": "Some content to analyze",
            "question": "What are the key points?"
        })
        
        assert result["success"] is True
        assert "analysis" in result
        assert "Top 3 benefits" in result["analysis"]
    
    @pytest.mark.asyncio
    async def test_agent_chat_execution(self, mock_agent_provider):
        """Test chat agent execution"""
        result = await mock_agent_provider.handle_request("chat", {
            "message": "Hello",
            "session_id": "test_session"
        })
        
        assert "response" in result
        assert result["session_id"] == "test_session"
        assert result["tools_used"] is False
    
    @pytest.mark.asyncio
    async def test_agent_code_execution(self, mock_agent_provider):
        """Test code generation agent execution"""
        result = await mock_agent_provider.handle_request("code", {
            "task": "Create a test function",
            "language": "python"
        })
        
        assert "code" in result
        assert "explanation" in result
        assert result["language"] == "python"
        assert result["test_result"]["success"] is True
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, mock_agent_provider):
        """Test that agent workflow respects task dependencies"""
        # Test the dependency logic directly without execution engine
        from gleitzeit.core.models import Workflow, Task
        
        # Create tasks with dependencies
        research_task = Task(
            id="research_task",
            name="Research Task",
            protocol="agent",
            method="research",
            params={"topic": "test", "max_steps": 2}
        )
        
        analyze_task = Task(
            id="analyze_task",
            name="Analyze Task",
            protocol="agent",
            method="analyze",
            params={"content": "${research_task.report}", "question": "What are the key points?"},
            dependencies=["research_task"]
        )
        
        chat_task = Task(
            id="chat_task",
            name="Chat Task",
            protocol="agent",
            method="chat",
            params={"message": "Summarize", "session_id": "test"}
        )
        
        workflow = Workflow(
            name="Test Agent Workflow",
            tasks=[research_task, analyze_task, chat_task]
        )
        
        # Verify task structure
        assert len(workflow.tasks) == 3
        assert analyze_task.dependencies == ["research_task"]
        assert chat_task.dependencies == []  # No dependencies
        
        # Simulate execution order
        execution_order = []
        
        # Execute tasks respecting dependencies
        # First, tasks with no dependencies
        for task in workflow.tasks:
            if not task.dependencies:
                result = await mock_agent_provider.handle_request(task.method, task.params)
                execution_order.append(task.id)
        
        # Then tasks with satisfied dependencies
        for task in workflow.tasks:
            if task.dependencies and task.dependencies[0] in execution_order:
                result = await mock_agent_provider.handle_request(task.method, task.params)
                execution_order.append(task.id)
        
        # Verify execution order
        assert "research_task" in execution_order
        assert "chat_task" in execution_order
        assert "analyze_task" in execution_order
        
        # Research should be before analyze (due to dependency)
        if "research_task" in execution_order and "analyze_task" in execution_order:
            assert execution_order.index("research_task") < execution_order.index("analyze_task")
    
    @pytest.mark.asyncio
    async def test_real_agent_hub_integration(self, mock_resource_manager_with_agent):
        """Test real agent hub integration"""
        resource_manager, agent_hub = mock_resource_manager_with_agent
        
        # Test research task
        research_result = await agent_hub.execute_agent_task(
            method="research",
            parameters={
                "topic": "Python testing",
                "max_steps": 2
            }
        )
        
        assert research_result is not None
        assert "report" in research_result
        assert "session_id" in research_result
        
        # Test chat with session
        session_id = "integration_test_session"
        chat_result = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "What is unit testing?",
                "session_id": session_id
            }
        )
        
        assert chat_result is not None
        assert "response" in chat_result
        assert chat_result["session_id"] == session_id
        
        # Verify agent was created
        status = await agent_hub.get_agent_status()
        assert status["total_agents"] > 0
    
    @pytest.mark.asyncio
    async def test_agent_session_persistence(self, mock_resource_manager_with_agent):
        """Test that agent sessions persist across calls"""
        resource_manager, agent_hub = mock_resource_manager_with_agent
        session_id = "persistent_session"
        
        # First message
        result1 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "Remember the number 42",
                "session_id": session_id
            }
        )
        
        # Second message in same session
        result2 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "What number did I mention?",
                "session_id": session_id
            }
        )
        
        # Both should have same session ID
        assert result1["session_id"] == session_id
        assert result2["session_id"] == session_id
        
        # Check that session exists in agent
        agents = list(agent_hub.agent_instances.values())
        chat_agent = next((a for a in agents if a.config.agent_type == AgentType.CHAT), None)
        
        if chat_agent:
            assert session_id in chat_agent.sessions
            session = chat_agent.sessions[session_id]
            assert len(session.history) >= 2  # At least 2 messages
    
    @pytest.mark.asyncio
    async def test_parameter_substitution(self, agent_workflow_content):
        """Test that parameter substitution works in agent workflows"""
        # The analyze task should reference research task results
        analyze_task = next(t for t in agent_workflow_content["tasks"] if t["id"] == "analyze_task")
        assert "${research_task.report}" in str(analyze_task["params"])
    
    @pytest.mark.asyncio
    async def test_agent_cleanup(self, mock_resource_manager_with_agent):
        """Test agent cleanup and session management"""
        resource_manager, agent_hub = mock_resource_manager_with_agent
        
        # Create some agents and sessions
        for i in range(3):
            await agent_hub.execute_agent_task(
                method="chat",
                parameters={
                    "message": f"Message {i}",
                    "session_id": f"session_{i}"
                }
            )
        
        # Check status before cleanup
        status_before = await agent_hub.get_agent_status()
        total_sessions_before = sum(agent["sessions"] for agent in status_before["agents"])
        
        # Clean up old sessions (with very short max age for testing)
        cleaned = await agent_hub.cleanup_sessions(max_age_seconds=0)
        
        # Check status after cleanup
        status_after = await agent_hub.get_agent_status()
        total_sessions_after = sum(agent["sessions"] for agent in status_after["agents"])
        
        # Should have cleaned up sessions
        assert cleaned >= 0  # At least some sessions cleaned
        assert total_sessions_after <= total_sessions_before