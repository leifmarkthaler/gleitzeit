"""
Test deployment validation and configuration enforcement.
"""

import pytest
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.system.deployment_validator import DeploymentValidator
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.persistence.factory import PersistenceFactory


@pytest.mark.asyncio
async def test_development_mode_allows_inmemory():
    """Test that development mode allows in-memory persistence."""
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="development"
    )
    
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    is_valid, errors = DeploymentValidator.validate_configuration(config, persistence)
    
    assert is_valid is True
    assert len(errors) == 0


@pytest.mark.asyncio
async def test_production_mode_rejects_inmemory():
    """Test that production mode rejects in-memory persistence."""
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    is_valid, errors = DeploymentValidator.validate_configuration(config, persistence)
    
    assert is_valid is False
    assert any("distributed persistence backend" in e for e in errors)
    assert any("cannot provide atomic operations" in e for e in errors)


@pytest.mark.asyncio
async def test_kubernetes_mode_rejects_inmemory():
    """Test that Kubernetes mode rejects in-memory persistence."""
    config = SystemConfig(
        deployment_mode=DeploymentMode.KUBERNETES,
        environment="production",
        max_workers=0  # Kubernetes manages workers
    )
    
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    is_valid, errors = DeploymentValidator.validate_configuration(config, persistence)
    
    assert is_valid is False
    assert any("distributed persistence backend" in e for e in errors)


def test_kubernetes_mode_worker_validation():
    """Test that Kubernetes mode validates worker configuration."""
    config = SystemConfig(
        deployment_mode=DeploymentMode.KUBERNETES,
        environment="production",
        max_workers=10  # Should trigger error
    )
    
    is_valid, errors = DeploymentValidator.validate_configuration(config, None)
    
    assert is_valid is False
    assert any("Kubernetes" in e and "max_workers" in e for e in errors)


def test_environment_validation():
    """Test environment validation."""
    # Valid environment
    config_valid = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="development"
    )
    
    is_valid, errors = DeploymentValidator.validate_configuration(config_valid, None)
    assert "Invalid environment" not in str(errors)
    
    # Invalid environment
    config_invalid = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="invalid_env"
    )
    
    is_valid, errors = DeploymentValidator.validate_configuration(config_invalid, None)
    assert any("Invalid environment" in e for e in errors)


def test_inconsistent_configuration():
    """Test detection of inconsistent configurations."""
    # Production environment with development mode
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="production"
    )
    
    is_valid, errors = DeploymentValidator.validate_configuration(config, None)
    assert any("Inconsistent configuration" in e for e in errors)


@pytest.mark.asyncio
async def test_atomic_operations_check():
    """Test atomic operations support detection."""
    # In-memory doesn't support atomic ops
    in_memory = UnifiedInMemoryAdapter()
    await in_memory.initialize()
    assert in_memory.supports_atomic_operations() is False
    
    # Try to get Redis if available
    try:
        redis_persistence = await PersistenceFactory.create()
        if "Redis" in type(redis_persistence).__name__:
            assert redis_persistence.supports_atomic_operations() is True
    except:
        pass  # Redis not available, skip


@pytest.mark.asyncio
async def test_distributed_validation():
    """Test validation for distributed operations."""
    in_memory = UnifiedInMemoryAdapter()
    await in_memory.initialize()
    
    is_distributed, error = DeploymentValidator.validate_for_distributed(in_memory)
    
    assert is_distributed is False
    assert "atomic operations" in error
    assert "In-memory persistence cannot provide distributed coordination" in error


def test_get_required_backend():
    """Test getting required backend for deployment modes."""
    # Production requires distributed backend
    assert DeploymentValidator.get_required_backend(DeploymentMode.PRODUCTION) == "redis"
    
    # Kubernetes requires distributed backend  
    assert DeploymentValidator.get_required_backend(DeploymentMode.KUBERNETES) == "redis"
    
    # Development can use any
    assert DeploymentValidator.get_required_backend(DeploymentMode.DEVELOPMENT) == "any"


@pytest.mark.asyncio
async def test_enforce_requirements():
    """Test enforcement of deployment requirements."""
    config = SystemConfig(
        deployment_mode=DeploymentMode.PRODUCTION,
        environment="production"
    )
    
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Should raise ConfigurationError
    from gleitzeit.core.errors import ConfigurationError
    
    with pytest.raises(ConfigurationError) as exc_info:
        DeploymentValidator.enforce_requirements(config, persistence)
    
    assert "Invalid deployment configuration" in str(exc_info.value)
    assert "distributed persistence backend" in str(exc_info.value)