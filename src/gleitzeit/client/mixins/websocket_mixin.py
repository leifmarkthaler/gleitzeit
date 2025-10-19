"""
WebSocket mixin for Gleitzeit client.

Provides real-time event streaming and callback-based workflow monitoring.
"""

import logging
import asyncio
import json
import websockets
from typing import Optional, Callable, Dict, Any, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class WebSocketMixin:
    """
    WebSocket operations mixin for real-time event streaming.

    Provides methods for:
    - Subscribing to workflow events
    - Callback-based workflow monitoring
    - Real-time task updates
    """

    async def wait_for_workflow_async(
        self,
        workflow_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_failure: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_task_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout: Optional[int] = None
    ):
        """
        Wait for workflow completion using WebSocket events (non-blocking with callbacks).

        This creates a background task that listens to WebSocket events and triggers
        callbacks when events occur. Your code continues immediately.

        Args:
            workflow_id: Workflow ID to monitor
            on_event: Called for every workflow event
            on_complete: Called when workflow completes successfully
            on_failure: Called when workflow fails
            on_task_complete: Called when any task completes
            timeout: Optional timeout in seconds

        Returns:
            AsyncTask that can be awaited or run in background

        Example:
            ```python
            async with GleitzeitClient() as client:
                # Submit workflow
                response = await client.submit_workflow(workflow)

                # Set up event-driven monitoring (non-blocking)
                await client.wait_for_workflow_async(
                    response.workflow_id,
                    on_task_complete=lambda event: print(f"Task done: {event}"),
                    on_complete=lambda event: print("Workflow completed!"),
                    on_failure=lambda event: print(f"Failed: {event}")
                )

                # Continue with other work - callbacks fire as events arrive
                await do_other_work()
            ```
        """
        # Convert HTTP URL to WebSocket URL
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        async def event_listener():
            """Background task that listens to WebSocket events."""
            try:
                async with websockets.connect(ws_url) as websocket:
                    # Wait for connection confirmation
                    conn_msg = await websocket.recv()
                    logger.info(f"WebSocket connected: {conn_msg}")

                    # Subscribe to workflow events FIRST
                    await websocket.send(json.dumps({
                        "action": "subscribe",
                        "workflow_ids": [workflow_id]
                    }))

                    # Wait for subscription confirmation
                    sub_msg = await websocket.recv()
                    logger.info(f"Subscribed: {sub_msg}")

                    # Check if workflow already completed (before we subscribed)
                    try:
                        workflow_status = await self.get_workflow_status(workflow_id)
                        status = workflow_status.status

                        if status == 'completed':
                            # Workflow already done - create synthetic event and fire callback
                            synthetic_event = {
                                "type": "workflow_event",
                                "workflow_id": workflow_id,
                                "event_type": "workflow:completed",
                                "timestamp": workflow_status.completed_at,
                                "data": {
                                    "status": status,
                                    "already_completed": True
                                }
                            }
                            if on_complete:
                                on_complete(synthetic_event)
                            return

                        elif status == 'failed':
                            # Workflow already failed - create synthetic event and fire callback
                            synthetic_event = {
                                "type": "workflow_event",
                                "workflow_id": workflow_id,
                                "event_type": "workflow:failed",
                                "timestamp": workflow_status.completed_at,
                                "data": {
                                    "error": workflow_status.error,
                                    "status": status,
                                    "already_completed": True
                                }
                            }
                            if on_failure:
                                on_failure(synthetic_event)
                            return

                    except Exception as e:
                        logger.warning(f"Could not check workflow state: {e}")
                        # Continue to WebSocket listening

                    # Workflow not completed yet, listen for events
                    start_time = asyncio.get_event_loop().time()
                    last_ping_time = asyncio.get_event_loop().time()
                    ping_interval = 30  # Send ping every 30 seconds

                    while True:
                        # Check timeout
                        if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                            logger.warning(f"Workflow {workflow_id} monitoring timeout after {timeout}s")
                            break

                        # Send periodic ping to keep connection alive
                        current_time = asyncio.get_event_loop().time()
                        if current_time - last_ping_time > ping_interval:
                            try:
                                await websocket.send(json.dumps({"action": "ping"}))
                                last_ping_time = current_time
                                logger.debug("Sent keepalive ping")
                            except Exception as e:
                                logger.warning(f"Failed to send ping: {e}")

                        try:
                            # Receive event
                            event_data = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=5.0  # 5 second receive timeout
                            )

                            event = json.loads(event_data) if isinstance(event_data, str) else event_data

                            event_type = event.get("event_type", "")
                            msg_type = event.get("type", "")

                            # Skip pong responses
                            if msg_type == "pong":
                                logger.debug("Received pong")
                                continue

                            # Call generic event callback
                            if on_event:
                                on_event(event)

                            # Call specific callbacks
                            if "task:completed" in event_type and on_task_complete:
                                on_task_complete(event)

                            if "workflow:completed" in event_type:
                                if on_complete:
                                    on_complete(event)
                                break  # Workflow done

                            if "workflow:failed" in event_type:
                                if on_failure:
                                    on_failure(event)
                                break  # Workflow done

                        except asyncio.TimeoutError:
                            # No event received, keep listening
                            continue

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if on_failure:
                    on_failure({"error": str(e)})

        # Create and return background task
        task = asyncio.create_task(event_listener())
        return task

    async def stream_workflow_events(
        self,
        workflow_ids: Optional[List[str]] = None,
        task_ids: Optional[List[str]] = None
    ):
        """
        Stream events for multiple workflows/tasks (async generator).

        Args:
            workflow_ids: Optional list of workflow IDs to monitor
            task_ids: Optional list of task IDs to monitor

        Yields:
            Event dictionaries as they arrive

        Example:
            ```python
            async for event in client.stream_workflow_events([workflow_id]):
                print(f"Event: {event['event_type']}")
                if event['event_type'] == 'workflow.completed':
                    break
            ```
        """
        # Convert HTTP URL to WebSocket URL
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        async with websockets.connect(ws_url) as websocket:
            # Wait for connection
            await websocket.recv()

            # Subscribe to events
            subscribe_msg = {
                "action": "subscribe"
            }
            if workflow_ids:
                subscribe_msg["workflow_ids"] = workflow_ids
            if task_ids:
                subscribe_msg["task_ids"] = task_ids

            await websocket.send(json.dumps(subscribe_msg))

            # Wait for subscription confirmation
            await websocket.recv()

            # Stream events
            while True:
                try:
                    event_data = await websocket.recv()
                    event = json.loads(event_data) if isinstance(event_data, str) else event_data
                    yield event
                except websockets.exceptions.ConnectionClosed:
                    break

    async def watch_multiple_workflows(
        self,
        workflow_ids: List[str],
        on_workflow_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_all_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_workflow_failed: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        timeout: Optional[int] = None
    ):
        """
        Monitor multiple workflows simultaneously.

        Args:
            workflow_ids: List of workflow IDs to monitor
            on_workflow_complete: Called when each workflow completes (workflow_id, event)
            on_all_complete: Called when all workflows complete (summary dict)
            on_workflow_failed: Called when any workflow fails (workflow_id, event)
            timeout: Optional timeout in seconds

        Returns:
            Summary dict with completion status for each workflow

        Example:
            ```python
            async with GleitzeitClient() as client:
                # Submit multiple workflows
                ids = []
                for i in range(5):
                    resp = await client.submit_workflow(workflow)
                    ids.append(resp.workflow_id)

                # Monitor all at once
                summary = await client.watch_multiple_workflows(
                    ids,
                    on_workflow_complete=lambda wid, e: print(f"{wid} done!"),
                    on_all_complete=lambda s: print(f"All done! {s}")
                )
            ```
        """
        # Convert HTTP URL to WebSocket URL
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        # Track completion
        completed = {}
        failed = {}
        remaining = set(workflow_ids)

        async with websockets.connect(ws_url) as websocket:
            # Connect and subscribe
            await websocket.recv()  # connection message
            await websocket.send(json.dumps({
                "action": "subscribe",
                "workflow_ids": workflow_ids
            }))
            await websocket.recv()  # subscription confirmation

            start_time = asyncio.get_event_loop().time()
            last_ping_time = asyncio.get_event_loop().time()

            while remaining:
                # Check timeout
                if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                    logger.warning(f"Timeout after {timeout}s. Remaining: {remaining}")
                    break

                # Send periodic ping
                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping_time > 30:
                    await websocket.send(json.dumps({"action": "ping"}))
                    last_ping_time = current_time

                try:
                    event_data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    event = json.loads(event_data) if isinstance(event_data, str) else event_data

                    if event.get("type") == "pong":
                        continue

                    event_type = event.get("event_type", "")
                    workflow_id = event.get("workflow_id")

                    if "workflow:completed" in event_type and workflow_id in remaining:
                        completed[workflow_id] = event
                        remaining.remove(workflow_id)
                        if on_workflow_complete:
                            on_workflow_complete(workflow_id, event)

                    if "workflow:failed" in event_type and workflow_id in remaining:
                        failed[workflow_id] = event
                        remaining.remove(workflow_id)
                        if on_workflow_failed:
                            on_workflow_failed(workflow_id, event)

                except asyncio.TimeoutError:
                    continue

        # Create summary
        summary = {
            "total": len(workflow_ids),
            "completed": len(completed),
            "failed": len(failed),
            "timeout": len(remaining),
            "workflow_ids": {
                "completed": list(completed.keys()),
                "failed": list(failed.keys()),
                "timeout": list(remaining)
            }
        }

        if on_all_complete and not remaining:
            on_all_complete(summary)

        return summary

    async def wait_for_task_ws(
        self,
        task_id: str,
        workflow_id: str,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_failure: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Wait for a specific task to complete using WebSocket events.

        If the task has already completed before subscribing, the callback
        will be fired immediately with the current task state.

        Args:
            task_id: Task ID to monitor
            workflow_id: Workflow ID containing the task
            on_complete: Called when task completes
            on_failure: Called when task fails
            timeout: Optional timeout in seconds

        Returns:
            Final task event

        Example:
            ```python
            async with GleitzeitClient() as client:
                response = await client.submit_workflow(workflow)

                # Wait for specific task via WebSocket
                task_event = await client.wait_for_task_ws(
                    "task-123",
                    response.workflow_id,
                    on_complete=lambda e: print("Task done!")
                )
            ```
        """
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        final_event = None

        async with websockets.connect(ws_url) as websocket:
            # Connect and subscribe FIRST (so we don't miss any events)
            await websocket.recv()
            await websocket.send(json.dumps({
                "action": "subscribe",
                "task_ids": [task_id],
                "workflow_ids": [workflow_id]
            }))
            await websocket.recv()

            # Now check if task already completed
            try:
                tasks = await self.get_workflow_tasks(workflow_id)
                for task in tasks:
                    if task.get('task_id') == task_id:
                        status = task.get('status')

                        if status == 'completed':
                            # Task already done - create synthetic event and fire callback
                            final_event = {
                                "type": "workflow_event",
                                "workflow_id": workflow_id,
                                "task_id": task_id,
                                "event_type": "task:completed",
                                "timestamp": task.get('completed_at'),
                                "data": {
                                    "result": task.get('result'),
                                    "status": status,
                                    "already_completed": True
                                }
                            }
                            if on_complete:
                                on_complete(final_event)
                            return final_event

                        elif status == 'failed':
                            # Task already failed - create synthetic event and fire callback
                            final_event = {
                                "type": "workflow_event",
                                "workflow_id": workflow_id,
                                "task_id": task_id,
                                "event_type": "task:failed",
                                "timestamp": task.get('completed_at') or task.get('failed_at'),
                                "data": {
                                    "error": task.get('error'),
                                    "status": status,
                                    "already_completed": True
                                }
                            }
                            if on_failure:
                                on_failure(final_event)
                            return final_event

            except Exception as e:
                logger.warning(f"Could not check task state: {e}")
                # Continue to WebSocket listening

            # Task not completed yet, listen for events
            start_time = asyncio.get_event_loop().time()
            last_ping_time = asyncio.get_event_loop().time()

            while True:
                if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                    raise TimeoutError(f"Task {task_id} timeout after {timeout}s")

                # Send periodic ping
                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping_time > 30:
                    await websocket.send(json.dumps({"action": "ping"}))
                    last_ping_time = current_time

                try:
                    event_data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    event = json.loads(event_data) if isinstance(event_data, str) else event_data

                    if event.get("type") == "pong":
                        continue

                    event_type = event.get("event_type", "")
                    event_task_id = event.get("task_id")

                    if event_task_id == task_id:
                        if "task:completed" in event_type:
                            final_event = event
                            if on_complete:
                                on_complete(event)
                            break

                        if "task:failed" in event_type:
                            final_event = event
                            if on_failure:
                                on_failure(event)
                            break

                except asyncio.TimeoutError:
                    continue

        return final_event

    async def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get WebSocket connection health statistics.

        Returns:
            Dict with connection stats (latency, status, etc.)

        Example:
            ```python
            async with GleitzeitClient() as client:
                stats = await client.get_connection_stats()
                print(f"Latency: {stats['latency_ms']}ms")
            ```
        """
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        stats = {
            "url": ws_url,
            "status": "unknown",
            "latency_ms": None,
            "connected": False
        }

        try:
            start = asyncio.get_event_loop().time()

            async with websockets.connect(ws_url) as websocket:
                # Measure connection time
                await websocket.recv()  # connection message
                connect_time = (asyncio.get_event_loop().time() - start) * 1000

                # Measure ping/pong latency
                ping_start = asyncio.get_event_loop().time()
                await websocket.send(json.dumps({"action": "ping"}))

                pong_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                ping_time = (asyncio.get_event_loop().time() - ping_start) * 1000

                stats.update({
                    "status": "healthy",
                    "latency_ms": round(ping_time, 2),
                    "connect_time_ms": round(connect_time, 2),
                    "connected": True
                })

        except asyncio.TimeoutError:
            stats["status"] = "timeout"
        except Exception as e:
            stats["status"] = "error"
            stats["error"] = str(e)

        return stats

    async def unsubscribe(
        self,
        websocket,
        workflow_ids: Optional[List[str]] = None,
        task_ids: Optional[List[str]] = None
    ):
        """
        Update subscription filters (add or remove specific workflows/tasks).

        Args:
            websocket: Active WebSocket connection
            workflow_ids: Workflow IDs to subscribe to (replaces current)
            task_ids: Task IDs to subscribe to (replaces current)

        Example:
            ```python
            # Subscribe to new set of workflows
            await client.unsubscribe(
                websocket,
                workflow_ids=["new-workflow-1", "new-workflow-2"]
            )
            ```
        """
        subscribe_msg = {"action": "subscribe"}

        if workflow_ids is not None:
            subscribe_msg["workflow_ids"] = workflow_ids
        if task_ids is not None:
            subscribe_msg["task_ids"] = task_ids

        await websocket.send(json.dumps(subscribe_msg))
        response = await websocket.recv()
        return json.loads(response) if isinstance(response, str) else response

    async def monitor_all_workflows(
        self,
        on_workflow_start: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_workflow_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_task_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        duration: Optional[int] = None
    ):
        """
        Monitor all workflow activity (global event stream).

        Args:
            on_workflow_start: Called when any workflow starts
            on_workflow_complete: Called when any workflow completes
            on_task_event: Called for any task event
            duration: How long to monitor (seconds), None = infinite

        Returns:
            Summary dict with event counts

        Example:
            ```python
            async with GleitzeitClient() as client:
                # Monitor everything for 60 seconds
                summary = await client.monitor_all_workflows(
                    on_workflow_start=lambda e: print(f"Started: {e['workflow_id']}"),
                    on_task_event=lambda e: print(f"Task: {e.get('event_type')}"),
                    duration=60
                )
            ```
        """
        parsed = urlparse(self.api_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/ws/events"

        event_counts = {
            "workflows_started": 0,
            "workflows_completed": 0,
            "workflows_failed": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_events": 0
        }

        async with websockets.connect(ws_url) as websocket:
            # Connect with no filters (receive all events)
            await websocket.recv()
            await websocket.send(json.dumps({"action": "subscribe"}))
            await websocket.recv()

            start_time = asyncio.get_event_loop().time()
            last_ping_time = asyncio.get_event_loop().time()

            while True:
                # Check duration
                if duration and (asyncio.get_event_loop().time() - start_time) > duration:
                    break

                # Send periodic ping
                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping_time > 30:
                    await websocket.send(json.dumps({"action": "ping"}))
                    last_ping_time = current_time

                try:
                    event_data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    event = json.loads(event_data) if isinstance(event_data, str) else event_data

                    if event.get("type") == "pong":
                        continue

                    event_type = event.get("event_type", "")
                    event_counts["total_events"] += 1

                    # Track event types
                    if "workflow:started" in event_type:
                        event_counts["workflows_started"] += 1
                        if on_workflow_start:
                            on_workflow_start(event)

                    if "workflow:completed" in event_type:
                        event_counts["workflows_completed"] += 1
                        if on_workflow_complete:
                            on_workflow_complete(event)

                    if "workflow:failed" in event_type:
                        event_counts["workflows_failed"] += 1

                    if "task:completed" in event_type:
                        event_counts["tasks_completed"] += 1

                    if "task:failed" in event_type:
                        event_counts["tasks_failed"] += 1

                    # Call generic task event callback
                    if "task:" in event_type and on_task_event:
                        on_task_event(event)

                except asyncio.TimeoutError:
                    continue

        return event_counts

    async def get_workflow_events_history(
        self,
        workflow_id: str,
        event_types: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get historical events for a workflow from event store.

        Args:
            workflow_id: Workflow ID
            event_types: Optional filter for specific event types
            limit: Maximum number of events to retrieve

        Returns:
            List of event dictionaries

        Example:
            ```python
            async with GleitzeitClient() as client:
                # Get last 50 events for a workflow
                events = await client.get_workflow_events_history(
                    "workflow-123",
                    event_types=["task:completed", "task:failed"],
                    limit=50
                )
            ```
        """
        # Use the REST API to get workflow events from event store
        try:
            response = await self._request(
                "GET",
                f"/workflows/{workflow_id}/events",
                params={
                    "limit": limit,
                    "event_types": ",".join(event_types) if event_types else None
                }
            )
            return response.get("events", [])
        except Exception as e:
            logger.warning(f"Failed to get event history: {e}")
            return []
