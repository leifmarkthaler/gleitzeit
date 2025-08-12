"""
Protocol and Provider Registry Manager for Gleitzeit V5

Manages dynamic loading, validation, and registration of protocols and providers
from YAML files, ensuring they meet system requirements.
"""

import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from datetime import datetime

from .protocol import ProtocolRegistry, get_protocol_registry
from .yaml_loader import YAMLProtocolLoader, ProviderConfig, get_yaml_loader
from .errors import ValidationError

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Result of protocol/provider registration"""
    success: bool
    name: str
    type: str  # 'protocol' or 'provider'
    error: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class RegistryStatus:
    """Status of the registry system"""
    protocols_loaded: int
    providers_loaded: int
    protocols_failed: int
    providers_failed: int
    last_scan: Optional[datetime] = None
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class RegistryManager:
    """Manages protocol and provider registrations"""
    
    def __init__(self):
        self.protocol_registry = get_protocol_registry()
        self.yaml_loader = get_yaml_loader()
        self.registered_protocols: Set[str] = set()
        self.registered_providers: Set[str] = set()
        self.failed_registrations: Dict[str, str] = {}
        self.last_scan_time: Optional[datetime] = None
    
    async def scan_and_register_all(self, 
                                   protocol_dirs: List[Path], 
                                   provider_dirs: List[Path]) -> RegistryStatus:
        """Scan directories and register all valid protocols and providers"""
        
        logger.info("Starting protocol and provider registration scan")
        
        protocols_loaded = 0
        providers_loaded = 0
        protocols_failed = 0
        providers_failed = 0
        errors = []
        
        # Load and register protocols
        for protocol_dir in protocol_dirs:
            try:
                results = await self._scan_protocol_directory(protocol_dir)
                for result in results:
                    if result.success:
                        protocols_loaded += 1
                    else:
                        protocols_failed += 1
                        if result.error:
                            errors.append(f"Protocol {result.name}: {result.error}")
            except Exception as e:
                protocols_failed += 1
                errors.append(f"Protocol directory {protocol_dir}: {e}")
        
        # Load and register providers
        for provider_dir in provider_dirs:
            try:
                results = await self._scan_provider_directory(provider_dir)
                for result in results:
                    if result.success:
                        providers_loaded += 1
                    else:
                        providers_failed += 1
                        if result.error:
                            errors.append(f"Provider {result.name}: {result.error}")
            except Exception as e:
                providers_failed += 1
                errors.append(f"Provider directory {provider_dir}: {e}")
        
        self.last_scan_time = datetime.utcnow()
        
        status = RegistryStatus(
            protocols_loaded=protocols_loaded,
            providers_loaded=providers_loaded,
            protocols_failed=protocols_failed,
            providers_failed=providers_failed,
            last_scan=self.last_scan_time,
            errors=errors
        )
        
        logger.info(f"Registration scan complete: {protocols_loaded} protocols, "
                   f"{providers_loaded} providers loaded")
        
        return status
    
    async def _scan_protocol_directory(self, directory: Path) -> List[RegistrationResult]:
        """Scan a directory for protocol YAML files and register them"""
        
        results = []
        
        if not directory.exists():
            logger.warning(f"Protocol directory does not exist: {directory}")
            return results
        
        # Find YAML files
        yaml_files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
        
        for yaml_file in yaml_files:
            result = await self._register_protocol_from_file(yaml_file)
            results.append(result)
        
        return results
    
    async def _scan_provider_directory(self, directory: Path) -> List[RegistrationResult]:
        """Scan a directory for provider YAML files and register them"""
        
        results = []
        
        if not directory.exists():
            logger.warning(f"Provider directory does not exist: {directory}")
            return results
        
        # Find YAML files
        yaml_files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
        
        for yaml_file in yaml_files:
            result = await self._register_provider_from_file(yaml_file)
            results.append(result)
        
        return results
    
    async def _register_protocol_from_file(self, yaml_file: Path) -> RegistrationResult:
        """Register a single protocol from YAML file"""
        
        try:
            # Load protocol from YAML
            protocol = self.yaml_loader.load_protocol_from_yaml(yaml_file)
            
            # Validate protocol
            validation_result = self._validate_protocol(protocol)
            if not validation_result.success:
                return validation_result
            
            # Register with protocol registry
            self.protocol_registry.register(protocol)
            self.registered_protocols.add(protocol.protocol_id)
            
            logger.info(f"Successfully registered protocol: {protocol.protocol_id}")
            
            return RegistrationResult(
                success=True,
                name=protocol.protocol_id,
                type='protocol',
                warnings=validation_result.warnings
            )
            
        except Exception as e:
            logger.error(f"Failed to register protocol from {yaml_file}: {e}")
            return RegistrationResult(
                success=False,
                name=yaml_file.stem,
                type='protocol',
                error=str(e)
            )
    
    async def _register_provider_from_file(self, yaml_file: Path) -> RegistrationResult:
        """Register a single provider from YAML file"""
        
        try:
            # Load provider from YAML
            provider = self.yaml_loader.load_provider_from_yaml(yaml_file)
            
            # Validate provider
            validation_result = self._validate_provider(provider)
            if not validation_result.success:
                return validation_result
            
            # Store provider configuration (actual provider instantiation would be separate)
            self.registered_providers.add(provider.name)
            
            logger.info(f"Successfully registered provider: {provider.name}")
            
            return RegistrationResult(
                success=True,
                name=provider.name,
                type='provider',
                warnings=validation_result.warnings
            )
            
        except Exception as e:
            logger.error(f"Failed to register provider from {yaml_file}: {e}")
            return RegistrationResult(
                success=False,
                name=yaml_file.stem,
                type='provider',
                error=str(e)
            )
    
    def _validate_protocol(self, protocol) -> RegistrationResult:
        """Validate a protocol specification"""
        
        warnings = []
        
        try:
            # Check if protocol already exists
            if protocol.protocol_id in self.registered_protocols:
                return RegistrationResult(
                    success=False,
                    name=protocol.protocol_id,
                    type='protocol',
                    error=f"Protocol {protocol.protocol_id} is already registered"
                )
            
            # Validate methods exist
            if not protocol.methods:
                return RegistrationResult(
                    success=False,
                    name=protocol.protocol_id,
                    type='protocol',
                    error="Protocol must define at least one method"
                )
            
            # Validate method specifications
            for method_name, method_spec in protocol.methods.items():
                if not method_name.startswith(f"{protocol.name}/"):
                    warnings.append(f"Method {method_name} should start with protocol name {protocol.name}/")
                
                if not method_spec.description:
                    warnings.append(f"Method {method_name} missing description")
                
                # Validate parameter schemas
                if method_spec.params_schema:
                    for param_name, param_spec in method_spec.params_schema.items():
                        if not param_spec.description:
                            warnings.append(f"Parameter {param_name} in {method_name} missing description")
            
            return RegistrationResult(
                success=True,
                name=protocol.protocol_id,
                type='protocol',
                warnings=warnings
            )
            
        except Exception as e:
            return RegistrationResult(
                success=False,
                name=protocol.protocol_id,
                type='protocol',
                error=f"Validation error: {e}"
            )
    
    def _validate_provider(self, provider: ProviderConfig) -> RegistrationResult:
        """Validate a provider configuration"""
        
        warnings = []
        
        try:
            # Check if provider already exists
            if provider.name in self.registered_providers:
                return RegistrationResult(
                    success=False,
                    name=provider.name,
                    type='provider',
                    error=f"Provider {provider.name} is already registered"
                )
            
            # Check if protocol exists
            protocol_exists = False
            for protocol_id in self.protocol_registry.list_protocols():
                if protocol_id.startswith(f"{provider.protocol}/"):
                    protocol_exists = True
                    break
            
            if not protocol_exists:
                # Try to find if protocol is loaded in YAML loader
                loaded_protocols = self.yaml_loader.get_loaded_protocols()
                protocol_exists = any(p.name == provider.protocol for p in loaded_protocols.values())
            
            if not protocol_exists:
                warnings.append(f"Protocol {provider.protocol} not found - ensure it's loaded first")
            
            # Validate connection configuration
            if 'type' not in provider.connection:
                return RegistrationResult(
                    success=False,
                    name=provider.name,
                    type='provider',
                    error="Provider connection must specify 'type'"
                )
            
            # Validate capabilities
            if not provider.capabilities:
                warnings.append("Provider defines no capabilities")
            
            return RegistrationResult(
                success=True,
                name=provider.name,
                type='provider',
                warnings=warnings
            )
            
        except Exception as e:
            return RegistrationResult(
                success=False,
                name=provider.name,
                type='provider',
                error=f"Validation error: {e}"
            )
    
    def get_registry_status(self) -> RegistryStatus:
        """Get current registry status"""
        
        return RegistryStatus(
            protocols_loaded=len(self.registered_protocols),
            providers_loaded=len(self.registered_providers),
            protocols_failed=len([e for e in self.failed_registrations.values() if 'protocol' in e]),
            providers_failed=len([e for e in self.failed_registrations.values() if 'provider' in e]),
            last_scan=self.last_scan_time,
            errors=list(self.failed_registrations.values())
        )
    
    def get_registered_protocols(self) -> Set[str]:
        """Get list of registered protocol IDs"""
        return self.registered_protocols.copy()
    
    def get_registered_providers(self) -> Set[str]:
        """Get list of registered provider names"""
        return self.registered_providers.copy()
    
    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """Get configuration for a specific provider"""
        loaded_providers = self.yaml_loader.get_loaded_providers()
        return loaded_providers.get(provider_name)


# Global instance
_registry_manager = RegistryManager()


def get_registry_manager() -> RegistryManager:
    """Get the global registry manager instance"""
    return _registry_manager


async def scan_and_register_all(protocol_dirs: List[Path], 
                               provider_dirs: List[Path]) -> RegistryStatus:
    """Scan and register all protocols and providers (convenience function)"""
    return await _registry_manager.scan_and_register_all(protocol_dirs, provider_dirs)