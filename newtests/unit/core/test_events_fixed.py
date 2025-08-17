"""
Fixed test module for event system

Tests cover:
- Event creation and serialization
- Event type hierarchy
- Event severity levels
- Event data classes
- Event filtering utilities

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
class TestEventTypesFixed:
    """Fixed tests for event type definitions"""
    
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
        """Test event severity levels have correct values"""
        # Just check they exist and are strings
        assert EventSeverity.DEBUG.value == "debug"
        assert EventSeverity.INFO.value == "info"
        assert EventSeverity.WARNING.value == "warning"
        assert EventSeverity.ERROR.value == "error"
        assert EventSeverity.CRITICAL.value == "critical"


@pytest.mark.unit
class TestEventDataClassesFixed:
    """Fixed tests for event data classes"""
    
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


@pytest.mark.unit
class TestGleitzeitEventFixed:
    """Fixed tests for main event class"""
    
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


@pytest.mark.unit
class TestEventUtilityFunctionsFixed:
    """Fixed tests for event utility functions"""
    
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


@pytest.mark.unit
class TestEventFilteringFixed:
    """Fixed tests for event filtering utilities"""
    
    def test_filter_by_severity(self):
        """Test filtering events by severity"""
        events = [
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                severity=EventSeverity.INFO,
                data={"task_id": "task_1"}
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                data={"task_id": "task_2"}
            ),
            GleitzeitEvent(
                event_type=EventType.SYSTEM_SHUTDOWN,
                severity=EventSeverity.CRITICAL,
                data={}
            )
        ]
        
        # Get only ERROR and above
        filtered = get_events_by_severity(events, EventSeverity.ERROR)
        assert len(filtered) == 2  # ERROR and CRITICAL events
        
        # Get only CRITICAL
        filtered = get_events_by_severity(events, EventSeverity.CRITICAL)
        assert len(filtered) == 1
        assert filtered[0].event_type == EventType.SYSTEM_SHUTDOWN
    
    def test_filter_by_component(self):
        """Test filtering events by component"""
        events = [
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                data={},
                tags={"component": "task"}
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={},
                tags={"component": "task"}
            ),
            GleitzeitEvent(
                event_type=EventType.PROVIDER_ERROR,
                data={},
                tags={"component": "provider"}
            )
        ]
        
        # Get task events
        task_events = get_events_by_component(events, "task")
        assert len(task_events) == 2
        
        # Get provider events
        provider_events = get_events_by_component(events, "provider")
        assert len(provider_events) == 1
    
    def test_filter_by_correlation_id(self):
        """Test filtering events by correlation ID"""
        events = [
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                data={},
                correlation_id="workflow_1"
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={},
                correlation_id="workflow_1"
            ),
            GleitzeitEvent(
                event_type=EventType.TASK_STARTED,
                data={},
                correlation_id="workflow_2"
            )
        ]
        
        # Get workflow_1 events
        workflow1_events = get_events_by_correlation_id(events, "workflow_1")
        assert len(workflow1_events) == 2
        
        # Get workflow_2 events
        workflow2_events = get_events_by_correlation_id(events, "workflow_2")
        assert len(workflow2_events) == 1