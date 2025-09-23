"""Test signal send handler functionality"""

import pytest
import asyncio
from datetime import datetime

from gleitzeit.handlers.signal import SignalHandler
from gleitzeit.core.models import Task, TaskStatus, TaskResult


@pytest.fixture
def signal_handler():
    """Create a signal handler instance"""
    return SignalHandler()


@pytest.mark.asyncio
async def test_signal_send_validation(signal_handler):
    """Test validation of signal/send parameters"""

    # Valid send task
    valid_task = Task(
        id="test-send-1",
        name="Test Send Signal",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "test-signal"
        }
    )
    await signal_handler.validate(valid_task)  # Should not raise

    # Missing signal_name
    invalid_task = Task(
        id="test-send-2",
        name="Test Invalid Send",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={}
    )
    with pytest.raises(Exception) as exc_info:
        await signal_handler.validate(invalid_task)
    assert "signal_name" in str(exc_info.value)

    # Invalid signal_name type
    invalid_task = Task(
        id="test-send-3",
        name="Test Invalid Type",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": 123  # Should be string
        }
    )
    with pytest.raises(Exception) as exc_info:
        await signal_handler.validate(invalid_task)
    assert "string" in str(exc_info.value).lower()

    # Invalid payload type
    invalid_task = Task(
        id="test-send-4",
        name="Test Invalid Payload",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "test-signal",
            "payload": "not a dict"  # Should be dict
        }
    )
    with pytest.raises(Exception) as exc_info:
        await signal_handler.validate(invalid_task)
    assert "dictionary" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_signal_send_execution(signal_handler):
    """Test execution of signal/send task"""

    # Test basic send (defaults to current workflow)
    task = Task(
        id="test-send-exec-1",
        name="Test Send Execution",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "test-signal",
            "payload": {"key": "value"}
        }
    )

    result = await signal_handler.execute(task)

    # Check result structure
    assert isinstance(result, TaskResult)
    assert result.status == TaskStatus.COMPLETED
    assert result.result["signal_sent"] == "test-signal"
    assert result.result["target_workflows"] == ["workflow-1"]  # Defaults to current workflow
    assert result.result["payload"] == {"key": "value"}

    # Check metadata for emission flag
    assert result.metadata["emit_signal"] is True
    assert result.metadata["signal_name"] == "test-signal"
    assert result.metadata["signal_action"] == "send"
    assert result.metadata["target_workflows"] == ["workflow-1"]


@pytest.mark.asyncio
async def test_signal_send_with_targets(signal_handler):
    """Test signal send with multiple target workflows"""

    task = Task(
        id="test-send-target",
        name="Test Send With Target",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "targeted-signal",
            "payload": {"data": "test"},
            "target_workflows": ["workflow-2", "workflow-3"]
        }
    )

    result = await signal_handler.execute(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["signal_sent"] == "targeted-signal"
    assert result.result["target_workflows"] == ["workflow-2", "workflow-3"]
    assert result.metadata["target_workflows"] == ["workflow-2", "workflow-3"]


@pytest.mark.asyncio
async def test_signal_send_without_payload(signal_handler):
    """Test signal send without payload (should use empty dict)"""

    task = Task(
        id="test-send-no-payload",
        name="Test Send No Payload",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/send",
        params={
            "signal_name": "simple-signal"
        }
    )

    result = await signal_handler.execute(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["payload"] == {}
    assert result.metadata["payload"] == {}


@pytest.mark.asyncio
async def test_signal_broadcast(signal_handler):
    """Test signal broadcast (system-wide)"""

    task = Task(
        id="test-broadcast",
        name="Test Broadcast",
        workflow_id="workflow-1",
        protocol="signal/v1",
        method="signal/broadcast",
        params={
            "signal_name": "system-signal",
            "payload": {"broadcast": True}
        }
    )

    result = await signal_handler.execute(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["signal_broadcast"] == "system-signal"
    assert result.result["payload"] == {"broadcast": True}
    assert result.metadata["signal_action"] == "broadcast"
    assert result.metadata["emit_signal"] is True


@pytest.mark.asyncio
async def test_signal_handler_capabilities(signal_handler):
    """Test that signal handler reports send and broadcast capabilities"""

    capabilities = signal_handler.get_capabilities()

    # Check that signal/send is in the methods
    assert "signal/send" in capabilities["methods"]
    send_method = capabilities["methods"]["signal/send"]
    assert "signal_name" in send_method["required"]
    assert "payload" in send_method["optional"]
    assert "target_workflows" in send_method["optional"]

    # Check that signal/broadcast is in the methods
    assert "signal/broadcast" in capabilities["methods"]
    broadcast_method = capabilities["methods"]["signal/broadcast"]
    assert "signal_name" in broadcast_method["required"]
    assert "payload" in broadcast_method["optional"]