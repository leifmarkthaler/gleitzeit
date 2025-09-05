"""
Deployment configuration validation for Gleitzeit.

Ensures that deployment configurations are valid and that
required backends are available for specific deployment modes.
"""

import logging
from typing import Optional, List, Tuple

from .models import DeploymentMode, SystemConfig
from ..persistence.base import PersistenceBackend
from ..core.errors import ConfigurationError

logger = logging.getLogger(__name__)


class DeploymentValidator:
    """
    Validates deployment configurations and enforces requirements.
    
    Ensures that:
    - Production deployments use proper persistence
    - Distributed features have required backends
    - Configuration is consistent
    """
    
    @staticmethod
    def validate_configuration(
        config: SystemConfig,
        persistence: Optional[PersistenceBackend] = None
    ) -> Tuple[bool, List[str]]:
        """
        Validate a system configuration.
        
        Args:
            config: System configuration to validate
            persistence: Persistence backend being used
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check deployment mode requirements
        if config.deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
            # Production modes require proper persistence
            if persistence:
                backend_type = type(persistence).__name__
                
                # Check for in-memory backend
                if "InMemory" in backend_type:
                    errors.append(
                        f"Deployment mode '{config.deployment_mode}' requires a distributed "
                        f"persistence backend (Redis, PostgreSQL, etc.). "
                        f"In-memory persistence is not supported for production deployments "
                        f"as it cannot provide atomic operations needed for distributed coordination."
                    )
                
                # Check if it supports atomic operations (Redis does)
                if hasattr(persistence, 'supports_atomic_operations'):
                    if not persistence.supports_atomic_operations():
                        errors.append(
                            f"Persistence backend '{backend_type}' does not support atomic operations "
                            f"required for {config.deployment_mode} mode"
                        )
                # For backwards compatibility, assume Redis-like backends are okay
                elif "Redis" not in backend_type:
                    # If it's not Redis and doesn't have the method, be cautious
                    errors.append(
                        f"Persistence backend '{backend_type}' may not support atomic operations "
                        f"required for {config.deployment_mode} mode"
                    )
            else:
                errors.append(
                    f"Deployment mode '{config.deployment_mode}' requires a persistence backend"
                )
        
        # Check worker configuration
        if config.deployment_mode == DeploymentMode.KUBERNETES:
            if config.max_workers > 0:
                errors.append(
                    "Kubernetes deployment should not specify max_workers "
                    "(workers are managed by Kubernetes)"
                )
        
        # Check resource limits (only enforce for production)
        if config.enable_resource_limits:
            if config.deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
                if not persistence or "InMemory" in type(persistence).__name__:
                    errors.append(
                        "Resource limits in production require a distributed persistence backend "
                        "for quota coordination across instances"
                    )
        
        # Check metrics configuration
        if config.metrics_enabled:
            if config.metrics_port < 1024:
                errors.append(
                    f"Metrics port {config.metrics_port} requires root privileges. "
                    f"Use a port >= 1024 for non-root deployments"
                )
        
        # Check service discovery
        if config.deployment_mode == DeploymentMode.PRODUCTION:
            # Check if using in-memory service registry in production
            if hasattr(config, 'service_registry_backend') and config.service_registry_backend == "memory":
                logger.warning(
                    "Production deployment with in-memory service registry. "
                    "Consider using Redis or etcd for distributed coordination."
                )
        
        # Validate environment
        valid_environments = ["dev", "development", "staging", "production", "test"]
        if config.environment not in valid_environments:
            errors.append(
                f"Invalid environment '{config.environment}'. "
                f"Must be one of: {', '.join(valid_environments)}"
            )
        
        # Check for inconsistencies
        if config.environment == "production" and config.deployment_mode == DeploymentMode.DEVELOPMENT:
            errors.append(
                "Inconsistent configuration: production environment with development deployment mode"
            )
        
        if config.environment in ["dev", "development"] and config.deployment_mode == DeploymentMode.PRODUCTION:
            logger.warning(
                "Development environment with production deployment mode. "
                "Consider using development mode for local development."
            )
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    @staticmethod
    def get_required_backend(deployment_mode: DeploymentMode) -> str:
        """
        Get the required persistence backend for a deployment mode.
        
        Args:
            deployment_mode: The deployment mode
            
        Returns:
            Required backend type or "any" if no specific requirement
        """
        if deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
            return "redis"  # Or could be "distributed" to allow PostgreSQL, etc.
        return "any"
    
    @staticmethod
    def validate_for_distributed(
        persistence: PersistenceBackend
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that persistence backend supports distributed operations.
        
        Args:
            persistence: Persistence backend to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        backend_type = type(persistence).__name__
        
        # Check for in-memory backend
        if "InMemory" in backend_type:
            return False, (
                "Distributed operations require a persistence backend with atomic operations. "
                "In-memory persistence cannot provide distributed coordination. "
                "Please use Redis or another distributed backend."
            )
        
        # Check for atomic operations support
        # In a real implementation, we'd check for specific atomic operations
        atomic_ops = ['set_nx', 'compare_and_swap', 'atomic_increment']
        has_atomic = any(hasattr(persistence, op) for op in atomic_ops)
        
        if not has_atomic:
            # Check if it's Redis (which has atomic ops even if not exposed directly)
            if hasattr(persistence, 'redis') or 'Redis' in backend_type:
                return True, None
            
            return False, (
                f"Backend '{backend_type}' does not appear to support atomic operations "
                "required for distributed coordination"
            )
        
        return True, None
    
    @staticmethod
    def enforce_requirements(
        config: SystemConfig,
        persistence: Optional[PersistenceBackend] = None
    ) -> None:
        """
        Enforce deployment requirements, raising errors if invalid.
        
        Args:
            config: System configuration
            persistence: Persistence backend
            
        Raises:
            ConfigurationError: If configuration is invalid
        """
        is_valid, errors = DeploymentValidator.validate_configuration(config, persistence)
        
        if not is_valid:
            error_msg = "Invalid deployment configuration:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            raise ConfigurationError(error_msg)
        
        # Additional distributed validation if needed
        if config.deployment_mode in [DeploymentMode.PRODUCTION, DeploymentMode.KUBERNETES]:
            if persistence:
                is_distributed, error = DeploymentValidator.validate_for_distributed(persistence)
                if not is_distributed:
                    raise ConfigurationError(f"Distributed deployment error: {error}")
        
        logger.info(f"Deployment configuration validated for {config.deployment_mode} mode")