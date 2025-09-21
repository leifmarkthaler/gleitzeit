"""
Stream auth mixin providing authentication management.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StreamAuthMixin:
    """
    Mixin providing authentication management for stream-based system.

    This mixin handles:
    - AuthManager initialization
    - User authentication and authorization
    - Session management
    """

    def __init__(self, **kwargs):
        """Initialize auth components."""
        self.auth_manager = None
        super().__init__(**kwargs)

    async def initialize_stream_auth(self):
        """Initialize authentication manager."""
        try:
            from ...auth.auth_manager import AuthManager

            self.auth_manager = AuthManager(
                persistence=self.persistence,
                event_bus=self.event_bus
            )

            # Ensure basic user exists for immediate use
            await self.auth_manager.ensure_basic_user_exists()

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="auth_manager",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stateless": True,
                        "token_expiry_hours": self.auth_manager.token_expiry_hours,
                        "has_basic_user": True
                    }
                )

            logger.info("AuthManager initialized with authentication enabled (stateless)")

        except Exception as e:
            logger.error(f"Failed to initialize AuthManager: {e}")
            # AuthManager failure shouldn't prevent system startup in basic mode
            self.auth_manager = None

    async def shutdown_stream_auth(self):
        """Shutdown authentication manager."""
        if self.auth_manager:
            try:
                await self.auth_manager.shutdown()
                logger.info("AuthManager shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down auth manager: {e}")

    def get_auth_manager(self) -> Optional['AuthManager']:
        """Get the auth manager instance."""
        return self.auth_manager

    # Authentication interface
    async def authenticate_user(self, username: str, password: str) -> Optional[str]:
        """Authenticate user and return session token."""
        if not self.auth_manager:
            logger.warning("Auth manager not available")
            return None

        try:
            return await self.auth_manager.authenticate_user(username, password)
        except Exception as e:
            logger.error(f"Error authenticating user {username}: {e}")
            return None

    async def get_current_user(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current user from session."""
        if not self.auth_manager:
            logger.warning("Auth manager not available")
            return None

        try:
            return await self.auth_manager.get_current_user(session_id)
        except Exception as e:
            logger.error(f"Error getting current user for session {session_id}: {e}")
            return None

    async def logout_user(self, session_id: str) -> bool:
        """Logout user session."""
        if not self.auth_manager:
            logger.warning("Auth manager not available")
            return False

        try:
            return await self.auth_manager.logout_user(session_id)
        except Exception as e:
            logger.error(f"Error logging out session {session_id}: {e}")
            return False

    async def create_user(self, username: str, password: str, **metadata) -> Optional[str]:
        """Create a new user."""
        if not self.auth_manager:
            logger.warning("Auth manager not available")
            return None

        try:
            return await self.auth_manager.create_user(username, password, **metadata)
        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return None

    async def submit_workflow_authenticated(self, workflow, session_id: str) -> str:
        """Submit a workflow with authentication."""
        from ...core.errors import AuthenticationError, AuthorizationError, WorkflowValidationError, SystemError, ErrorCode

        # Get user from session
        if not self.auth_manager:
            raise SystemError(
                message="AuthManager not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        user = await self.auth_manager.get_current_user(session_id)
        if not user:
            raise AuthenticationError("Invalid session")

        # Process workflow through WorkflowLoader for validation
        if not hasattr(self, 'workflow_loader') or not self.workflow_loader:
            raise SystemError(
                message="WorkflowLoader not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        # Convert to dict if it's a Workflow object
        from ...core.models import Workflow as WorkflowModel
        if isinstance(workflow, WorkflowModel):
            workflow_dict = workflow.model_dump() if hasattr(workflow, 'model_dump') else workflow.dict()
        else:
            workflow_dict = workflow

        # Load through WorkflowLoader for ID generation and validation
        try:
            validated_workflow = self.workflow_loader.load_workflow_from_dict(workflow_dict)
        except Exception as e:
            raise WorkflowValidationError(
                workflow_id=workflow_dict.get('id', 'unknown'),
                validation_errors=[str(e)]
            )

        # Validate the workflow
        validation_errors = self.workflow_loader.validate_workflow_enhanced(validated_workflow)
        if validation_errors:
            raise WorkflowValidationError(
                workflow_id=validated_workflow.id,
                validation_errors=validation_errors
            )

        # Set ownership on validated workflow
        from datetime import datetime
        validated_workflow.user_id = user.get('id', 'unknown')
        if not validated_workflow.metadata:
            validated_workflow.metadata = {}
        validated_workflow.metadata['user_id'] = validated_workflow.user_id
        validated_workflow.metadata['submitted_by'] = user.get('username', 'unknown')
        validated_workflow.metadata['submission_time'] = datetime.utcnow().isoformat()

        # Submit through WorkflowManager
        if not hasattr(self, 'workflow_manager') or not self.workflow_manager:
            raise SystemError(
                message="WorkflowManager not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        return await self.workflow_manager.submit_workflow(validated_workflow)

    async def get_workflow_authenticated(self, workflow_id: str, session_id: str):
        """Get a workflow with authorization check."""
        from ...core.errors import AuthenticationError, AuthorizationError, SystemError, ErrorCode

        # Get user from session
        if not self.auth_manager:
            raise SystemError(
                message="AuthManager not initialized",
                code=ErrorCode.SYSTEM_NOT_INITIALIZED
            )

        user = await self.auth_manager.get_current_user(session_id)
        if not user:
            raise AuthenticationError("Invalid session")

        # Get workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return None

        # Check authorization
        # Admin/superuser can access all
        if user.get('is_superuser') or user.get('role') == 'admin':
            return workflow

        # Check ownership
        workflow_user_id = getattr(workflow, 'user_id', None)
        if hasattr(workflow, 'user_id'):
            workflow_user_id = workflow.user_id
        elif hasattr(workflow, 'metadata') and workflow.metadata:
            workflow_user_id = workflow.metadata.get('user_id')

        user_id = user.get('id')

        # Owner can access
        if workflow_user_id == user_id:
            return workflow

        # Check if workflow is public
        is_public = getattr(workflow, 'is_public', False)
        if hasattr(workflow, 'is_public'):
            is_public = workflow.is_public
        elif hasattr(workflow, 'metadata') and workflow.metadata:
            is_public = workflow.metadata.get('is_public', False)

        if is_public:
            return workflow

        # No access
        raise AuthorizationError(
            resource=f"workflow/{workflow_id}",
            action="read",
            reason="You don't have permission to access this workflow"
        )