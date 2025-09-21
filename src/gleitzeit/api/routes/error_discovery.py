"""
Error discovery API routes.

Provides endpoints for discovering errors from providers and protocols.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from gleitzeit.client import GleitzeitClient
from ..dependencies import get_client
from ..auth_dependencies import get_current_user_auto
from .base import APIRouteBase

router = APIRouter(prefix="/errors", tags=["error_discovery"])

# Create route handler instance (stateless)
error_routes = APIRouteBase()


@router.get("/provider/{provider_id}", response_model=List[Dict[str, Any]])
async def get_provider_errors(
    provider_id: str,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get all errors that a provider might raise.

    Returns:
        List of error information including:
        - name: Error class name
        - class: Error class type name
        - base_class: Parent error class name
        - module: Module containing the error
        - error_code: Numeric error code (if defined)
        - error_code_name: Error code enum name (if defined)
        - description: Error description/docstring
        - is_retryable: Whether the error is retryable
    """
    try:
        return await error_routes.handle_client_call(
            "get_provider_errors",
            provider_id=provider_id,
            client=client
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Provider not found: {provider_id}")
        raise


@router.get("/protocol/{protocol_id:path}", response_model=List[Dict[str, Any]])
async def get_protocol_errors(
    protocol_id: str,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get all errors associated with a protocol.

    The protocol_id should be in the format: name/version (e.g., "python/v1")

    Returns:
        List of error information for the protocol
    """
    try:
        return await error_routes.handle_client_call(
            "get_protocol_errors",
            protocol_id=protocol_id,
            client=client
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Protocol not found: {protocol_id}")
        raise


@router.get("/hierarchy", response_model=Dict[str, Any])
async def get_error_hierarchy(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get the complete error hierarchy from the system.

    Returns:
        Nested dictionary representing the error class hierarchy,
        starting from GleitzeitError and showing all subclasses
        with their error codes and descriptions.
    """
    return await error_routes.handle_client_call(
        "get_error_hierarchy",
        client=client
    )


@router.get("/all-providers", response_model=Dict[str, List[Dict[str, Any]]])
async def get_all_provider_errors(
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Get errors from all registered providers.

    Returns:
        Dictionary mapping provider IDs to their error lists
    """
    return await error_routes.handle_client_call(
        "get_all_provider_errors",
        client=client
    )


@router.get("/report", response_model=str)
async def get_error_report(
    provider_id: Optional[str] = Query(None, description="Optional provider ID for specific report"),
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Generate a formatted error report.

    Args:
        provider_id: Optional provider ID to generate report for.
                    If not provided, generates report for all providers.

    Returns:
        Markdown-formatted error report
    """
    return await error_routes.handle_client_call(
        "get_error_report",
        provider_id=provider_id,
        client=client
    )


@router.get("/retryable/{error_code}", response_model=bool)
async def check_error_retryability(
    error_code: int,
    client: GleitzeitClient = Depends(get_client),
    current_user: Dict[str, Any] = Depends(get_current_user_auto)
):
    """
    Check if an error code represents a retryable error.

    Args:
        error_code: The numeric error code to check

    Returns:
        True if the error is retryable, False otherwise
    """
    return await error_routes.handle_client_call(
        "check_error_retryability",
        error_code=error_code,
        client=client
    )