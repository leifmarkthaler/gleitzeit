"""
Tests for AgentHub implementation
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import uuid

from gleitzeit.hub.agent_hub import (
    AgentHub, AgentInstance, AgentConfig, AgentType,
    AgentSession, AgentStep
)
from gleitzeit.hub.base import ResourceStatus, ResourceType
# ResourceManager removed - using stateless coordination


@pytest.fixture
async def mock_resource_manager():
    """Create a mock resource manager with mock hubs"""
    manager = MagicMock()  # Mock for legacy compatibility
    
    # Mock Ollama hub
    ollama_hub = AsyncMock()
    ollama_hub.chat_completion = AsyncMock(return_value={
        "response": "Test LLM response"
    })
    
    # Mock Docker hub
    docker_hub = AsyncMock()
    docker_hub.execute_code = AsyncMock(return_value={
        "output": "Code executed successfully"
    })
    docker_hub.get_available_instance = AsyncMock(return_value=MagicMock())
    
    # Configure get_hub to return appropriate mocks
    def get_hub(hub_id):
        if hub_id == "ollama":
            return ollama_hub
        elif hub_id == "docker":
            return docker_hub
        return None
    
    manager.get_hub = MagicMock(side_effect=get_hub)
    
    return manager


@pytest.fixture
async def agent_hub(mock_resource_manager):
    """Create an AgentHub instance with mock resource manager"""
    hub = AgentHub(
        hub_id="test_agent_hub",
        resource_manager=mock_resource_manager,
        max_agents=5
    )
    await hub.start()
    yield hub
    await hub.stop()


class TestAgentHub:
    """Test AgentHub functionality"""
    
    @pytest.mark.asyncio
    async def test_hub_initialization(self, agent_hub):
        """Test that AgentHub initializes correctly"""
        assert agent_hub.hub_id == "test_agent_hub"
        assert agent_hub.max_agents == 5
        assert agent_hub.resource_type == ResourceType.CUSTOM
        assert len(agent_hub.agent_instances) == 0
        assert agent_hub.running is True
    
    @pytest.mark.asyncio
    async def test_start_agent_instance(self, agent_hub):
        """Test starting a new agent instance"""
        config = AgentConfig(
            agent_type=AgentType.RESEARCH,
            model="llama3.2",
            max_iterations=5
        )
        
        instance = await agent_hub.start_instance(config)
        
        assert instance is not None
        assert instance.id.startswith("agent_")
        assert instance.name == "Agent-research"
        assert instance.type == ResourceType.CUSTOM
        assert instance.config == config
        assert instance.id in agent_hub.agent_instances
        
        # Verify agent instance was created
        agent = agent_hub.agent_instances[instance.id]
        assert agent.config == config
        assert agent.instance_id == instance.id
    
    @pytest.mark.asyncio
    async def test_max_agents_limit(self, agent_hub):
        """Test that max agents limit is enforced"""
        # Create max number of agents
        for i in range(agent_hub.max_agents):
            config = AgentConfig(agent_type=AgentType.CHAT)
            await agent_hub.start_instance(config)
        
        # Try to create one more
        with pytest.raises(Exception) as exc_info:
            config = AgentConfig(agent_type=AgentType.CHAT)
            await agent_hub.start_instance(config)
        
        assert "Maximum number of agents" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_stop_agent_instance(self, agent_hub):
        """Test stopping an agent instance"""
        config = AgentConfig(agent_type=AgentType.CODE)
        instance = await agent_hub.start_instance(config)
        instance_id = instance.id
        
        # Add a session to verify cleanup
        agent = agent_hub.agent_instances[instance_id]
        agent.sessions["test_session"] = AgentSession(
            session_id="test_session",
            agent_id=instance_id,
            created_at=datetime.now(),
            last_activity=datetime.now()
        )
        
        # Stop the instance
        success = await agent_hub.stop_instance(instance_id)
        
        assert success is True
        assert instance_id not in agent_hub.agent_instances
        assert await agent_hub.get_instance(instance_id) is None
    
    @pytest.mark.asyncio
    async def test_execute_agent_task_research(self, agent_hub):
        """Test executing a research task"""
        result = await agent_hub.execute_agent_task(
            method="research",
            parameters={
                "topic": "test topic",
                "max_steps": 2
            }
        )
        
        assert result is not None
        assert "report" in result
        assert "steps_executed" in result
        assert "session_id" in result
        assert result["success"] is True
        
        # Verify agent was created
        assert len(agent_hub.agent_instances) == 1
        agent = list(agent_hub.agent_instances.values())[0]
        assert agent.config.agent_type == AgentType.RESEARCH
    
    @pytest.mark.asyncio
    async def test_execute_agent_task_code(self, agent_hub):
        """Test executing a code generation task"""
        result = await agent_hub.execute_agent_task(
            method="code",
            parameters={
                "task": "write a hello world function",
                "language": "python"
            }
        )
        
        assert result is not None
        assert "code" in result
        assert "explanation" in result
        assert "language" in result
        assert result["language"] == "python"
    
    @pytest.mark.asyncio
    async def test_execute_agent_task_chat(self, agent_hub):
        """Test executing a chat task with session"""
        session_id = str(uuid.uuid4())
        
        # First message
        result1 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={"message": "Hello, how are you?"},
            session_id=session_id
        )
        
        assert result1 is not None
        assert "response" in result1
        assert "session_id" in result1
        assert result1["session_id"] == session_id
        
        # Second message in same session
        result2 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={"message": "What did I just ask you?"},
            session_id=session_id
        )
        
        assert result2["session_id"] == session_id
        
        # Verify session was maintained
        agent = list(agent_hub.agent_instances.values())[0]
        assert session_id in agent.sessions
        assert len(agent.sessions[session_id].history) == 4  # 2 user + 2 assistant
    
    @pytest.mark.asyncio
    async def test_agent_health_check(self, agent_hub):
        """Test agent health check"""
        config = AgentConfig(agent_type=AgentType.ANALYSIS)
        instance = await agent_hub.start_instance(config)
        
        # Health check should succeed with mock
        is_healthy = await agent_hub.check_health(instance)
        assert is_healthy is True
        
        # Remove resource manager to simulate failure
        agent_hub.resource_manager = None
        is_healthy = await agent_hub.check_health(instance)
        assert is_healthy is False
    
    @pytest.mark.asyncio
    async def test_collect_metrics(self, agent_hub):
        """Test collecting metrics from agent"""
        config = AgentConfig(agent_type=AgentType.CHAT)
        instance = await agent_hub.start_instance(config)
        agent = agent_hub.agent_instances[instance.id]
        
        # Simulate some activity
        agent.metrics["total_requests"] = 10
        agent.metrics["total_steps"] = 25
        agent.metrics["total_errors"] = 2
        agent.metrics["avg_steps_per_request"] = 2.5
        
        # Collect metrics
        metrics = await agent_hub.collect_metrics(instance)
        
        assert metrics.request_count == 10
        assert metrics.error_count == 2
        assert metrics.custom_metrics["total_steps"] == 25
        assert metrics.custom_metrics["avg_steps_per_request"] == 2.5
        assert metrics.custom_metrics["active_sessions"] == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_sessions(self, agent_hub):
        """Test cleaning up expired sessions"""
        config = AgentConfig(agent_type=AgentType.CHAT)
        instance = await agent_hub.start_instance(config)
        agent = agent_hub.agent_instances[instance.id]
        
        # Create sessions with different ages
        now = datetime.now()
        
        # Active session
        agent.sessions["active"] = AgentSession(
            session_id="active",
            agent_id=instance.id,
            created_at=now,
            last_activity=now
        )
        
        # Expired session
        from datetime import timedelta
        expired_time = now - timedelta(seconds=7200)  # 2 hours old
        agent.sessions["expired"] = AgentSession(
            session_id="expired",
            agent_id=instance.id,
            created_at=expired_time,
            last_activity=expired_time
        )
        
        # Clean up sessions older than 1 hour
        cleaned = await agent_hub.cleanup_sessions(max_age_seconds=3600)
        
        assert cleaned == 1
        assert "active" in agent.sessions
        assert "expired" not in agent.sessions
    
    @pytest.mark.asyncio
    async def test_get_agent_status(self, agent_hub):
        """Test getting detailed agent status"""
        # Create a couple of agents
        config1 = AgentConfig(agent_type=AgentType.RESEARCH)
        await agent_hub.start_instance(config1)
        
        config2 = AgentConfig(agent_type=AgentType.CODE)
        await agent_hub.start_instance(config2)
        
        status = await agent_hub.get_agent_status()
        
        assert status["total_agents"] == 2
        assert status["max_agents"] == 5
        assert len(status["agents"]) == 2
        
        # Check agent info
        for agent_info in status["agents"]:
            assert "id" in agent_info
            assert "type" in agent_info
            assert "model" in agent_info
            assert "metrics" in agent_info
            assert "sessions" in agent_info
            assert "tools" in agent_info


class TestAgentInstance:
    """Test AgentInstance functionality"""
    
    @pytest.mark.asyncio
    async def test_agent_instance_creation(self, mock_resource_manager):
        """Test creating an agent instance"""
        config = AgentConfig(
            agent_type=AgentType.RESEARCH,
            model="test-model",
            max_iterations=3
        )
        
        agent = AgentInstance(
            instance_id="test_agent_001",
            config=config,
            resource_manager=mock_resource_manager
        )
        
        assert agent.instance_id == "test_agent_001"
        assert agent.config == config
        assert agent.resource_manager == mock_resource_manager
        assert len(agent.sessions) == 0
        assert agent.metrics["total_requests"] == 0
    
    @pytest.mark.asyncio
    async def test_agent_research_execution(self, mock_resource_manager):
        """Test research agent execution"""
        config = AgentConfig(agent_type=AgentType.RESEARCH)
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        result = await agent.execute("research", {
            "topic": "artificial intelligence",
            "max_steps": 2
        })
        
        assert result is not None
        assert "report" in result
        assert "steps_executed" in result
        assert "session_id" in result
        assert result["success"] is True
        assert agent.metrics["total_requests"] == 1
        assert agent.metrics["total_steps"] >= 2
    
    @pytest.mark.asyncio
    async def test_agent_code_generation(self, mock_resource_manager):
        """Test code generation"""
        config = AgentConfig(
            agent_type=AgentType.CODE,
            tools=["llm", "python"]
        )
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        result = await agent.execute("code", {
            "task": "create a function to add two numbers",
            "language": "python"
        })
        
        assert result is not None
        assert "code" in result
        assert "explanation" in result
        assert "language" in result
        assert result["language"] == "python"
    
    @pytest.mark.asyncio
    async def test_agent_chat_with_session(self, mock_resource_manager):
        """Test chat agent with session management"""
        config = AgentConfig(agent_type=AgentType.CHAT)
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        session_id = "test_session_123"
        
        # First message
        result1 = await agent.execute("chat", {
            "message": "Hello!",
            "session_id": session_id
        })
        
        assert "response" in result1
        assert result1["session_id"] == session_id
        assert session_id in agent.sessions
        
        # Check session history
        session = agent.sessions[session_id]
        assert len(session.history) == 2  # user + assistant
        assert session.history[0]["role"] == "user"
        assert session.history[0]["content"] == "Hello!"
        assert session.history[1]["role"] == "assistant"
    
    @pytest.mark.asyncio
    async def test_agent_error_handling(self, mock_resource_manager):
        """Test error handling in agent execution"""
        config = AgentConfig(agent_type=AgentType.CUSTOM)
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        # Try unknown method
        with pytest.raises(ValueError) as exc_info:
            await agent.execute("unknown_method", {})
        
        assert "Unknown agent method" in str(exc_info.value)
        assert agent.metrics["total_errors"] == 1
    
    @pytest.mark.asyncio
    async def test_agent_plan_steps(self, mock_resource_manager):
        """Test planning steps for execution"""
        config = AgentConfig(agent_type=AgentType.RESEARCH)
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        # Mock LLM to return valid JSON plan
        mock_resource_manager.get_hub("ollama").chat_completion.return_value = {
            "response": '[{"action": "search", "tool": "llm", "parameters": {"prompt": "search for AI"}}, {"action": "analyze", "tool": "llm", "parameters": {"prompt": "analyze findings"}}]'
        }
        
        steps = await agent._plan_steps("test artificial intelligence", "research")
        
        assert len(steps) == 2
        assert steps[0].action == "search"
        assert steps[0].tool == "llm"
        assert steps[1].action == "analyze"
    
    @pytest.mark.asyncio
    async def test_agent_session_management(self, mock_resource_manager):
        """Test session creation and management"""
        config = AgentConfig(agent_type=AgentType.CHAT)
        agent = AgentInstance("test_agent", config, mock_resource_manager)
        
        # Get or create new session
        session1 = agent._get_or_create_session("session_001")
        assert session1.session_id == "session_001"
        assert session1.agent_id == "test_agent"
        
        # Get existing session
        session2 = agent._get_or_create_session("session_001")
        assert session1 is session2  # Same object
        
        # Create different session
        session3 = agent._get_or_create_session("session_002")
        assert session3.session_id == "session_002"
        assert session3 is not session1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])