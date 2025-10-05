"""
WebSocket Routes for Real-Time Updates
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..services.event_broadcaster import get_broadcaster

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time workflow/task events

    Client can send subscription filters:
    {
        "action": "subscribe",
        "workflow_ids": ["workflow-123", "workflow-456"],
        "task_ids": ["task-789"]
    }

    Server sends events in format:
    {
        "type": "workflow_event",
        "workflow_id": "workflow-uuid",
        "task_id": "task-uuid",
        "event_type": "workflow.started|task.completed|...",
        "timestamp": "2025-10-02T10:30:00Z",
        "data": {...}
    }
    """
    broadcaster = get_broadcaster()

    try:
        # Accept WebSocket connection
        await websocket.accept()

        # Add client to broadcaster with no initial filters
        await broadcaster.add_client(websocket, [])

        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected successfully"
        })

        # Listen for client messages
        while True:
            try:
                data = await websocket.receive_json()

                if data.get("action") == "subscribe":
                    # Update client filters
                    filters = data.get("workflow_ids", []) + data.get("task_ids", [])
                    await broadcaster.update_filters(websocket, filters)

                    # Confirm subscription
                    await websocket.send_json({
                        "type": "subscription_updated",
                        "filters": filters
                    })

                elif data.get("action") == "ping":
                    # Respond to ping
                    await websocket.send_json({"type": "pong"})

            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Remove client from broadcaster
        await broadcaster.remove_client(websocket)
