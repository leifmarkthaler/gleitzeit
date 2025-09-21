"""
Trigger endpoints for stateless event processing and reconciliation.

These endpoints allow external systems (cron, K8s, Lambda, etc.) to trigger
processing without persistent loops.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse

from ..shared_dependencies import (
    get_system_manager,
    get_current_user_optional,
    require_admin
)
from ...core.errors import SystemError, ErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.post("/process-events")
async def trigger_event_processing(
    duration_seconds: int = Query(default=60, description="Maximum duration to process events"),
    max_messages: int = Query(default=1000, description="Maximum messages to process"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    system_manager=Depends(get_system_manager),
    current_user=Depends(get_current_user_optional)
) -> Dict[str, Any]:
    """
    Trigger event processing for a specified duration.

    This endpoint allows external schedulers to trigger event processing
    without requiring persistent loops in the system.

    Args:
        duration_seconds: Maximum time to spend processing (1-300 seconds)
        max_messages: Maximum number of messages to process
        background_tasks: FastAPI background tasks
        system_manager: System manager instance
        current_user: Optional authenticated user

    Returns:
        Processing statistics
    """
    # Validate parameters
    if duration_seconds < 1 or duration_seconds > 300:
        raise HTTPException(
            status_code=400,
            detail="Duration must be between 1 and 300 seconds"
        )

    if max_messages < 1 or max_messages > 10000:
        raise HTTPException(
            status_code=400,
            detail="Max messages must be between 1 and 10000"
        )

    try:
        # Get the event bus
        if not system_manager.event_bus:
            raise SystemError(
                message="Event bus not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        # Check if it's our stateless adapter
        if hasattr(system_manager.event_bus, 'process_once'):
            # Process events once
            processed = await system_manager.event_bus.process_once()

            return {
                "status": "success",
                "processed_messages": processed,
                "instance_id": system_manager.instance_id,
                "trigger_type": "manual",
                "duration_requested": duration_seconds,
                "max_messages_requested": max_messages
            }
        else:
            # Legacy event bus - no stateless processing available
            return {
                "status": "unsupported",
                "message": "Event bus does not support stateless processing",
                "instance_id": system_manager.instance_id
            }

    except SystemError as e:
        logger.error(f"System error during event processing: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during event processing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reconcile")
async def trigger_reconciliation(
    reason: str = Query(default="manual", description="Reason for reconciliation"),
    system_manager=Depends(get_system_manager),
    current_user=Depends(require_admin)  # Admin only
) -> Dict[str, Any]:
    """
    Trigger workflow/task reconciliation.

    This endpoint allows administrators to manually trigger reconciliation
    to recover stuck workflows and tasks.

    Args:
        reason: Reason for triggering reconciliation
        system_manager: System manager instance
        current_user: Authenticated admin user

    Returns:
        Reconciliation result
    """
    try:
        # Get reconciliation service
        if not hasattr(system_manager, 'reconciliation_service'):
            raise SystemError(
                message="Reconciliation service not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        reconciliation_service = system_manager.reconciliation_service

        # Check if it's our stateless reconciliation manager
        if hasattr(reconciliation_service, 'reconcile_once'):
            # Perform reconciliation
            result = await reconciliation_service.reconcile_once(reason)

            return {
                "status": "success",
                "result": result,
                "triggered_by": current_user.get('username', 'unknown')
            }
        else:
            # Legacy reconciliation - may have loops
            return {
                "status": "unsupported",
                "message": "Reconciliation service does not support manual triggers",
                "instance_id": system_manager.instance_id
            }

    except SystemError as e:
        logger.error(f"System error during reconciliation: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during reconciliation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reconcile-check")
async def check_and_reconcile(
    system_manager=Depends(get_system_manager),
    current_user=Depends(get_current_user_optional)
) -> Dict[str, Any]:
    """
    Check if reconciliation is needed and trigger if so.

    This endpoint can be called frequently by external schedulers
    to check system health and trigger reconciliation only when needed.

    Args:
        system_manager: System manager instance
        current_user: Optional authenticated user

    Returns:
        Check result and optional reconciliation result
    """
    try:
        # Get reconciliation service
        if not hasattr(system_manager, 'reconciliation_service'):
            raise SystemError(
                message="Reconciliation service not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        reconciliation_service = system_manager.reconciliation_service

        # Check if it's our stateless reconciliation manager
        if hasattr(reconciliation_service, 'trigger_if_needed'):
            # Check and reconcile if needed
            result = await reconciliation_service.trigger_if_needed()

            return {
                "status": "success",
                "result": result,
                "instance_id": system_manager.instance_id
            }
        else:
            # Legacy reconciliation
            return {
                "status": "unsupported",
                "message": "Reconciliation service does not support conditional triggers",
                "instance_id": system_manager.instance_id
            }

    except SystemError as e:
        logger.error(f"System error during reconciliation check: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during reconciliation check: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status")
async def get_trigger_status(
    system_manager=Depends(get_system_manager),
    current_user=Depends(get_current_user_optional)
) -> Dict[str, Any]:
    """
    Get status of trigger-based systems.

    Returns information about the stateless event processing and
    reconciliation systems.

    Args:
        system_manager: System manager instance
        current_user: Optional authenticated user

    Returns:
        Status information
    """
    try:
        status = {
            "instance_id": system_manager.instance_id,
            "event_processing": {},
            "reconciliation": {}
        }

        # Check event bus status
        if system_manager.event_bus:
            if hasattr(system_manager.event_bus, 'get_consumer_stats'):
                status["event_processing"] = await system_manager.event_bus.get_consumer_stats()
            else:
                status["event_processing"] = {
                    "type": "legacy",
                    "stateless": False
                }

        # Check reconciliation status
        if hasattr(system_manager, 'reconciliation_service'):
            reconciliation_service = system_manager.reconciliation_service
            if hasattr(reconciliation_service, 'get_status'):
                status["reconciliation"] = await reconciliation_service.get_status()
            else:
                status["reconciliation"] = {
                    "type": "legacy",
                    "stateless": False
                }

        return status

    except Exception as e:
        logger.error(f"Error getting trigger status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/heartbeat")
async def trigger_heartbeat(
    system_manager=Depends(get_system_manager)
) -> Dict[str, Any]:
    """
    Heartbeat endpoint for external monitoring.

    This endpoint can be called by external systems to verify
    the trigger system is responsive.

    Args:
        system_manager: System manager instance

    Returns:
        Heartbeat response
    """
    return {
        "status": "alive",
        "instance_id": system_manager.instance_id,
        "timestamp": datetime.utcnow().isoformat()
    }


# Lambda handler wrapper
async def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for trigger endpoints.

    This function can be deployed as a Lambda function to trigger
    event processing and reconciliation.

    Args:
        event: Lambda event
        context: Lambda context

    Returns:
        Processing result
    """
    action = event.get("action", "process-events")

    if action == "process-events":
        # Calculate remaining time
        remaining_time = context.get_remaining_time_in_millis() / 1000
        duration = min(int(remaining_time - 5), 300)  # Leave 5 seconds buffer

        # Trigger processing
        from ...system.modular_stream_system_manager import ModularStreamSystemManager
        from ...system.models import SystemConfig, DeploymentMode
        from ...persistence.factory import PersistenceFactory

        persistence = await PersistenceFactory.create()
        config = SystemConfig()
        config.deployment_mode = DeploymentMode.PRODUCTION

        system_manager = await ModularStreamSystemManager.create(
            config=config,
            persistence=persistence,
            create_if_missing=False,
            start_system=False
        )

        if system_manager and system_manager.event_bus:
            if hasattr(system_manager.event_bus, 'process_once'):
                processed = await system_manager.event_bus.process_once()
                return {
                    "statusCode": 200,
                    "body": {
                        "processed_messages": processed,
                        "duration": duration
                    }
                }

    elif action == "reconcile":
        # Trigger reconciliation
        from ...system.modular_stream_system_manager import ModularStreamSystemManager
        from ...system.models import SystemConfig, DeploymentMode
        from ...persistence.factory import PersistenceFactory

        persistence = await PersistenceFactory.create()
        config = SystemConfig()
        config.deployment_mode = DeploymentMode.PRODUCTION

        system_manager = await ModularStreamSystemManager.create(
            config=config,
            persistence=persistence,
            create_if_missing=False,
            start_system=False
        )

        if system_manager and hasattr(system_manager, 'reconciliation_service'):
            if hasattr(system_manager.reconciliation_service, 'reconcile_once'):
                result = await system_manager.reconciliation_service.reconcile_once("lambda_trigger")
                return {
                    "statusCode": 200,
                    "body": result
                }

    return {
        "statusCode": 400,
        "body": {"error": f"Unknown action: {action}"}
    }