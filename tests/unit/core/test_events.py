"""
Test module for event system

Tests cover:
- Event creation and serialization
- Event type hierarchy
- Event severity levels
- Event data classes
- Event filtering utilities
- Socket.IO formatting

Related components:
- EventType
- EventSeverity
- GleitzeitEvent
- Event data classes
"""

import pytest
from datetime import datetime
from typing import Dict, Any, List
from unittest.mock import Mock, patch

from gleitzeit.core.events import (
    EventType, EventSeverity, GleitzeitEvent,
    BaseEventData, TaskEventData, WorkflowEventData,
    ProviderEventData, QueueEventData, HealthEventData,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event, create_workflow_started_event,
    create_workflow_completed_event,
    get_events_by_severity, get_events_by_component,
    get_events_by_correlation_id
)
from gleitzeit.core.models import TaskStatus, WorkflowStatus


@pytest.mark.unit
class TestEventTypes:
    """Test event type definitions"""
    
    def test_event_type_naming_convention(self):
        """Test that event types follow naming convention"""
        for event_type in EventType:
            assert ":" in event_type.value, f"Event {event_type} should follow component:action format"
            parts = event_type.value.split(":")
            assert len(parts) == 2, f"Event {event_type} should have exactly one colon"
    
    def test_event_type_categories(self):
        """Test event type categorization"""
        engine_events = [e for e in EventType if e.value.startswith("engine:")]
        task_events = [e for e in EventType if e.value.startswith("task:")]
        workflow_events = [e for e in EventType if e.value.startswith("workflow:")]
        provider_events = [e for e in EventType if e.value.startswith("provider:")]
        
        assert len(engine_events) >= 4  # started, stopped, paused, resumed
        assert len(task_events) >= 8  # submitted, queued, started, completed, etc.
        assert len(workflow_events) >= 6  # submitted, validated, started, etc.
        assert len(provider_events) >= 6  # registered, started, stopped, etc.
    
    def test_event_severity_values(self):
        """Test event severity levels have correct string values"""
        assert EventSeverity.DEBUG.value == "debug"
        assert EventSeverity.INFO.value == "info"
        assert EventSeverity.WARNING.value == "warning"
        assert EventSeverity.ERROR.value == "error"
        assert EventSeverity.CRITICAL.value == "critical"
        
        # Verify all severity levels exist
        severities = [EventSeverity.DEBUG, EventSeverity.INFO, 
                     EventSeverity.WARNING, EventSeverity.ERROR, 
                     EventSeverity.CRITICAL]
        assert len(severities) == 5


@pytest.mark.unit
class TestEventDataClasses:
    """Test event data classes"""
    
    def test_base_event_data_timestamp(self):
        """Test BaseEventData auto-generates timestamp"""
        data = BaseEventData()
        assert data.timestamp is not None
        assert isinstance(data.timestamp, datetime)
    
    def test_base_event_data_to_dict(self):
        """Test BaseEventData serialization"""
        data = BaseEventData()
        data_dict = data.to_dict()
        
        assert "timestamp" in data_dict
        # Timestamp should be ISO format string
        assert isinstance(data_dict["timestamp"], str)
    
    def test_task_event_data(self):
        """Test TaskEventData creation and serialization"""
        data = TaskEventData(
            task_id="task_1",
            task_name="Test Task",
            protocol="llm/v1",
            method="chat",
            status=TaskStatus.EXECUTING,
            priority="normal",
            duration=1.5
        )
        
        assert data.task_id == "task_1"
        assert data.task_name == "Test Task"
        assert data.duration == 1.5
        
        data_dict = data.to_dict()
        assert data_dict["task_id"] == "task_1"
        assert "timestamp" in data_dict
    
    def test_workflow_event_data(self):
        """Test WorkflowEventData creation"""
        data = WorkflowEventData(
            workflow_id="workflow_1",
            workflow_name="Test Workflow",
            total_tasks=10,
            completed_tasks=5,
            failed_tasks=1,
            status=WorkflowStatus.RUNNING
        )
        
        assert data.workflow_id == "workflow_1"
        assert data.total_tasks == 10
        assert data.completed_tasks == 5
        assert data.failed_tasks == 1
    
    def test_provider_event_data(self):
        """Test ProviderEventData with metrics"""
        data = ProviderEventData(
            provider_id="ollama_provider",
            protocol_id="llm/v1",
            health_status="healthy",
            request_count=100,
            error_count=5,
            success_rate=0.95,
            response_time=0.250
        )
        
        assert data.provider_id == "ollama_provider"
        assert data.success_rate == 0.95
        assert data.response_time == 0.250
    
    def test_queue_event_data(self):
        """Test QueueEventData"""
        data = QueueEventData(
            queue_name="high_priority",
            task_id="task_1",
            queue_size=50,
            priority="high",
            wait_time=2.5
        )
        
        assert data.queue_name == "high_priority"
        assert data.queue_size == 50
        assert data.wait_time == 2.5
    
    def test_health_event_data(self):
        """Test HealthEventData"""
        data = HealthEventData(
            component="ollama_hub",
            status="healthy",
            details={"cpu": "5%", "memory": "200MB"},
            response_time=0.1
        )
        
        assert data.component == "ollama_hub"
        assert data.status == "healthy"
        assert data.details["cpu"] == "5%"


@pytest.mark.unit
class TestGleitzeitEvent:
    """Test main event class"""
    
    def test_event_creation(self):
        """Test creating a GleitzeitEvent"""
        event = GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            severity=EventSeverity.INFO,
            data={"task_id": "task_1"},
            source="execution_engine",
            correlation_id="workflow_1"
        )
        
        assert event.event_type == EventType.TASK_STARTED
        assert event.severity == EventSeverity.INFO
        assert event.data["task_id"] == "task_1"
        assert event.source == "execution_engine"
        assert event.correlation_id == "workflow_1"
    
    def test_event_to_dict(self):
        """Test event serialization to dictionary"""
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={"task_id": "task_1", "duration": 1.5}
        )
        
        event_dict = event.to_dict()
        assert event_dict["event_type"] == "task:completed"
        assert event_dict["severity"] == "info"
        assert event_dict["data"]["task_id"] == "task_1"
    
    def test_event_to_socket_io(self):
        """Test event conversion to Socket.IO format"""
        event = GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={"task_id": "task_1"}
        )
        
        event_name, event_data = event.to_socket_io()
        assert event_name == "task:started"
        assert isinstance(event_data, dict)
        assert event_data["data"]["task_id"] == "task_1"
    
    def test_create_task_event(self):
        """Test factory method for task events"""
        task_data = TaskEventData(
            task_id="task_1",
            task_name="Test Task",
            workflow_id="workflow_1",
            status=TaskStatus.EXECUTING
        )
        
        event = GleitzeitEvent.create_task_event(
            EventType.TASK_STARTED,
            task_data,
            source="test"
        )
        
        assert event.event_type == EventType.TASK_STARTED
        assert event.correlation_id == "workflow_1"
        assert event.tags["component"] == "task"
        assert event.tags["task_id"] == "task_1"
    
    def test_create_workflow_event(self):
        """Test factory method for workflow events"""
        workflow_data = WorkflowEventData(
            workflow_id="workflow_1",
            workflow_name="Test Workflow",
            total_tasks=5
        )
        
        event = GleitzeitEvent.create_workflow_event(
            EventType.WORKFLOW_STARTED,
            workflow_data,
            source="test"
        )
        
        assert event.event_type == EventType.WORKFLOW_STARTED
        assert event.correlation_id == "workflow_1"
        assert event.tags["component"] == "workflow"
        assert event.tags["workflow_id"] == "workflow_1"
    
    def test_create_provider_event(self):
        """Test factory method for provider events"""
        provider_data = ProviderEventData(
            provider_id="ollama_1",
            protocol_id="llm/v1",
            health_status="healthy"
        )
        
        event = GleitzeitEvent.create_provider_event(
            EventType.PROVIDER_STARTED,
            provider_data,
            source="test"
        )
        
        assert event.event_type == EventType.PROVIDER_STARTED
        assert event.tags["component"] == "provider"
        assert event.tags["provider_id"] == "ollama_1"


@pytest.mark.unit
class TestEventUtilityFunctions:
    """Test event utility functions"""
    
    def test_create_task_started_event(self):
        """Test creating a task started event"""
        event = create_task_started_event(
            task_id="task_1",
            task_name="Test Task",
            protocol="llm/v1",
            method="chat",
            workflow_id="workflow_1"
        )
        
        assert event.event_type == EventType.TASK_STARTED
        assert event.data["task_id"] == "task_1"
        assert event.data["task_name"] == "Test Task"
        assert event.correlation_id == "workflow_1"
    
    def test_create_task_completed_event(self):
        """Test creating a task completed event"""
        event = create_task_completed_event(
            task_id="task_1",
            workflow_id="workflow_1",
            duration=2.5,
            result_size=1024
        )
        
        assert event.event_type == EventType.TASK_COMPLETED
        assert event.data["duration"] == 2.5
        assert event.data["result_size"] == 1024
    
    def test_create_task_failed_event(self):
        """Test creating a task failed event"""
        event = create_task_failed_event(
            task_id="task_1",
            error_message="Connection timeout",
            workflow_id="workflow_1",
            error_type="TimeoutError",
            is_retryable=True
        )
        
        assert event.event_type == EventType.TASK_FAILED
        assert event.severity == EventSeverity.ERROR
        assert event.data["error_message"] == "Connection timeout"
        assert event.tags.get("error_type") == "TimeoutError"
        assert event.tags.get("is_retryable") == "True"
    
    def test_create_workflow_started_event(self):
        """Test creating a workflow started event"""
        event = create_workflow_started_event(
            workflow_id="workflow_1",
            workflow_name="Test Workflow",
            total_tasks=10,
            execution_levels=3
        )
        
        assert event.event_type == EventType.WORKFLOW_STARTED
        assert event.data["total_tasks"] == 10
        assert event.data["execution_levels"] == 3
    
    def test_create_workflow_completed_event(self):
        """Test creating a workflow completed event"""
        event = create_workflow_completed_event(
            workflow_id="workflow_1",
            duration=30.5,
            tasks_completed=10
        )
        
        assert event.event_type == EventType.WORKFLOW_COMPLETED
        assert event.data["duration"] == 30.5
        assert event.data["completed_tasks"] == 10


@pytest.mark.unit
class TestEventFiltering:
    """Test event filtering utilities"""
    
    @pytest.fixture
    def sample_events(self):
        """Create sample events for filtering tests"""
        return [
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                severity=EventSeverity.INFO,
                data={"task_id": "task_1"},
                correlation_id="workflow_1",
                tags={"component": "task"}
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                data={"task_id": "task_2"},
                correlation_id="workflow_1",
                tags={"component": "task"}
            ),
            GleitzeitEvent(
                event_type=EventType.PROVIDER_ERROR,
                severity=EventSeverity.WARNING,
                data={"provider_id": "provider_1"},
                correlation_id="workflow_2",
                tags={"component": "provider"}
            ),
            GleitzeitEvent(
                event_type=EventType.SYSTEM_SHUTDOWN,
                severity=EventSeverity.CRITICAL,
                data={},
                tags={"component": "system"}
            )
        ]
    
    def test_filter_by_severity(self, sample_events):
        """Test filtering events by severity"""
        # Get only ERROR and above
        filtered = get_events_by_severity(sample_events, EventSeverity.ERROR)
        assert len(filtered) == 2  # ERROR and CRITICAL events
        
        # Get only CRITICAL
        filtered = get_events_by_severity(sample_events, EventSeverity.CRITICAL)
        assert len(filtered) == 1
        assert filtered[0].event_type == EventType.SYSTEM_SHUTDOWN
        
        # Get all (DEBUG and above)
        filtered = get_events_by_severity(sample_events, EventSeverity.DEBUG)
        assert len(filtered) == len(sample_events)
    
    def test_filter_by_component(self, sample_events):
        """Test filtering events by component"""
        # Get task events
        task_events = get_events_by_component(sample_events, "task")
        assert len(task_events) == 2
        
        # Get provider events
        provider_events = get_events_by_component(sample_events, "provider")
        assert len(provider_events) == 1
        
        # Get system events
        system_events = get_events_by_component(sample_events, "system")
        assert len(system_events) == 1
        
        # Get non-existent component
        none_events = get_events_by_component(sample_events, "nonexistent")
        assert len(none_events) == 0
    
    def test_filter_by_correlation_id(self, sample_events):
        """Test filtering events by correlation ID"""
        # Get workflow_1 events
        workflow1_events = get_events_by_correlation_id(sample_events, "workflow_1")
        assert len(workflow1_events) == 2
        
        # Get workflow_2 events
        workflow2_events = get_events_by_correlation_id(sample_events, "workflow_2")
        assert len(workflow2_events) == 1
        
        # Get events with no correlation
        no_correlation = get_events_by_correlation_id(sample_events, None)
        assert len(no_correlation) == 1  # SYSTEM_SHUTDOWN has no correlation


@pytest.mark.unit
class TestEventTypeHints:
    """Test type hints for event system"""
    
    @pytest.fixture
    def sample_events(self):
        """Create sample events for type hint tests"""
        return [
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                severity=EventSeverity.INFO,
                data={"task_id": "task_1"},
                correlation_id="workflow_1",
                tags={"component": "task"}
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                data={"task_id": "task_2"},
                correlation_id="workflow_1",
                tags={"component": "task"}
            )
        ]
    
    def test_event_data_post_init_returns_none(self):
        """Test that __post_init__ methods return None"""
        data_classes = [
            BaseEventData(),
            TaskEventData(task_id="test"),
            WorkflowEventData(workflow_id="test"),
            ProviderEventData(provider_id="test"),
            QueueEventData(),
            HealthEventData(component="test", status="healthy")
        ]
        
        for data in data_classes:
            # __post_init__ is called during __init__, returns None
            assert data.timestamp is not None  # Verifies __post_init__ ran
    
    def test_filtering_functions_return_lists(self, sample_events):
        """Test that filtering functions return lists"""
        result = get_events_by_severity(sample_events, EventSeverity.INFO)
        assert isinstance(result, list)
        
        result = get_events_by_component(sample_events, "task")
        assert isinstance(result, list)
        
        result = get_events_by_correlation_id(sample_events, "workflow_1")
        assert isinstance(result, list)