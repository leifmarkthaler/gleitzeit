"""
YAML Protocol and Provider Loader for Gleitzeit V5

Enables dynamic loading of protocols and providers from YAML files,
making the system extensible without code changes.
"""

import yaml
import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass

from .protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType
from .errors import ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuration for a provider loaded from YAML"""
    name: str
    protocol: str
    version: str
    description: str
    capabilities: List[str]
    connection: Dict[str, Any]
    authentication: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    executor: Optional[str] = None  # Which executor to use for this provider


class YAMLProtocolLoader:
    """Loads protocol specifications from YAML files"""
    
    def __init__(self):
        self.loaded_protocols: Dict[str, ProtocolSpec] = {}
        self.loaded_providers: Dict[str, ProviderConfig] = {}
    
    def load_protocol_from_yaml(self, yaml_file: Union[str, Path]) -> ProtocolSpec:
        """Load a protocol specification from a YAML file"""
        
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)
            
            # Validate required fields
            self._validate_protocol_yaml(data)
            
            # Create ProtocolSpec from YAML data
            protocol = self._create_protocol_from_yaml(data)
            
            # Store the loaded protocol
            self.loaded_protocols[protocol.protocol_id] = protocol
            
            logger.info(f"Loaded protocol {protocol.protocol_id} from {yaml_file}")
            return protocol
            
        except Exception as e:
            logger.error(f"Failed to load protocol from {yaml_file}: {e}")
            raise ValidationError(f"Invalid protocol YAML: {e}")
    
    def load_provider_from_yaml(self, yaml_file: Union[str, Path]) -> ProviderConfig:
        """Load a provider configuration from a YAML file"""
        
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)
            
            # Validate required fields
            self._validate_provider_yaml(data)
            
            # Create ProviderConfig from YAML data
            provider = self._create_provider_from_yaml(data)
            
            # Store the loaded provider
            self.loaded_providers[provider.name] = provider
            
            logger.info(f"Loaded provider {provider.name} from {yaml_file}")
            return provider
            
        except Exception as e:
            logger.error(f"Failed to load provider from {yaml_file}: {e}")
            raise ValidationError(f"Invalid provider YAML: {e}")
    
    def load_protocols_from_directory(self, directory: Union[str, Path]) -> List[ProtocolSpec]:
        """Load all protocol YAML files from a directory"""
        
        protocols = []
        directory = Path(directory)
        
        if not directory.exists():
            logger.warning(f"Protocol directory does not exist: {directory}")
            return protocols
        
        for file_path in directory.glob("*.yaml"):
            try:
                protocol = self.load_protocol_from_yaml(file_path)
                protocols.append(protocol)
            except Exception as e:
                logger.error(f"Failed to load protocol from {file_path}: {e}")
        
        for file_path in directory.glob("*.yml"):
            try:
                protocol = self.load_protocol_from_yaml(file_path)
                protocols.append(protocol)
            except Exception as e:
                logger.error(f"Failed to load protocol from {file_path}: {e}")
        
        logger.info(f"Loaded {len(protocols)} protocols from {directory}")
        return protocols
    
    def load_providers_from_directory(self, directory: Union[str, Path]) -> List[ProviderConfig]:
        """Load all provider YAML files from a directory"""
        
        providers = []
        directory = Path(directory)
        
        if not directory.exists():
            logger.warning(f"Provider directory does not exist: {directory}")
            return providers
        
        for file_path in directory.glob("*.yaml"):
            try:
                provider = self.load_provider_from_yaml(file_path)
                providers.append(provider)
            except Exception as e:
                logger.error(f"Failed to load provider from {file_path}: {e}")
        
        for file_path in directory.glob("*.yml"):
            try:
                provider = self.load_provider_from_yaml(file_path)
                providers.append(provider)
            except Exception as e:
                logger.error(f"Failed to load provider from {file_path}: {e}")
        
        logger.info(f"Loaded {len(providers)} providers from {directory}")
        return providers
    
    def _validate_protocol_yaml(self, data: Dict[str, Any]) -> None:
        """Validate protocol YAML structure"""
        
        required_fields = ['name', 'version', 'description', 'methods']
        for field in required_fields:
            if field not in data:
                raise ValidationError(f"Missing required field: {field}")
        
        if not isinstance(data['methods'], dict):
            raise ValidationError("'methods' must be a dictionary")
        
        for method_name, method_data in data['methods'].items():
            self._validate_method_yaml(method_name, method_data)
    
    def _validate_provider_yaml(self, data: Dict[str, Any]) -> None:
        """Validate provider YAML structure"""
        
        required_fields = ['name', 'protocol', 'version', 'description', 'capabilities', 'connection']
        for field in required_fields:
            if field not in data:
                raise ValidationError(f"Missing required field: {field}")
        
        if not isinstance(data['capabilities'], list):
            raise ValidationError("'capabilities' must be a list")
        
        if not isinstance(data['connection'], dict):
            raise ValidationError("'connection' must be a dictionary")
    
    def _validate_method_yaml(self, method_name: str, method_data: Dict[str, Any]) -> None:
        """Validate method YAML structure"""
        
        required_fields = ['description']
        for field in required_fields:
            if field not in method_data:
                raise ValidationError(f"Method {method_name} missing required field: {field}")
        
        if 'parameters' in method_data and not isinstance(method_data['parameters'], dict):
            raise ValidationError(f"Method {method_name} 'parameters' must be a dictionary")
        
        if 'returns' in method_data and not isinstance(method_data['returns'], dict):
            raise ValidationError(f"Method {method_name} 'returns' must be a dictionary")
    
    def _create_protocol_from_yaml(self, data: Dict[str, Any]) -> ProtocolSpec:
        """Create a ProtocolSpec from YAML data"""
        
        # Create methods
        methods = {}
        for method_name, method_data in data['methods'].items():
            methods[method_name] = self._create_method_from_yaml(method_name, method_data)
        
        # Create protocol spec
        protocol = ProtocolSpec(
            name=data['name'],
            version=data['version'],
            description=data['description'],
            methods=methods,
            author=data.get('author', 'Unknown'),
            license=data.get('license', 'Unknown'),
            tags=data.get('tags', [])
        )
        
        return protocol
    
    def _create_method_from_yaml(self, method_name: str, method_data: Dict[str, Any]) -> MethodSpec:
        """Create a MethodSpec from YAML data"""
        
        # Create parameter schemas
        params_schema = {}
        if 'parameters' in method_data:
            for param_name, param_data in method_data['parameters'].items():
                params_schema[param_name] = self._create_parameter_from_yaml(param_name, param_data)
        
        # Create return schema
        returns_schema = None
        if 'returns' in method_data:
            returns_schema = self._create_parameter_from_yaml('return', method_data['returns'])
        
        # Create method spec
        method = MethodSpec(
            name=method_name,
            description=method_data['description'],
            params_schema=params_schema,
            returns_schema=returns_schema,
            examples=method_data.get('examples', [])
        )
        
        return method
    
    def _create_parameter_from_yaml(self, param_name: str, param_data: Dict[str, Any]) -> ParameterSpec:
        """Create a ParameterSpec from YAML data"""
        
        # Parse parameter type
        param_type_str = param_data.get('type', 'string')
        param_type = self._parse_parameter_type(param_type_str)
        
        # Create parameter spec
        param = ParameterSpec(
            type=param_type,
            description=param_data.get('description', ''),
            required=param_data.get('required', False),
            default=param_data.get('default'),
            enum=param_data.get('enum'),
            minimum=param_data.get('minimum'),
            maximum=param_data.get('maximum'),
            min_length=param_data.get('min_length'),
            max_length=param_data.get('max_length'),
            pattern=param_data.get('pattern')
        )
        
        # Handle object properties
        if param_type == ParameterType.OBJECT and 'properties' in param_data:
            properties = {}
            for prop_name, prop_data in param_data['properties'].items():
                properties[prop_name] = self._create_parameter_from_yaml(prop_name, prop_data)
            param.properties = properties
            param.additional_properties = param_data.get('additional_properties', True)
        
        # Handle array items
        if param_type == ParameterType.ARRAY and 'items' in param_data:
            param.items = self._create_parameter_from_yaml(f"{param_name}_item", param_data['items'])
            param.min_length = param_data.get('min_items')
            param.max_length = param_data.get('max_items')
        
        return param
    
    def _create_provider_from_yaml(self, data: Dict[str, Any]) -> ProviderConfig:
        """Create a ProviderConfig from YAML data"""
        
        provider = ProviderConfig(
            name=data['name'],
            protocol=data['protocol'],
            version=data['version'],
            description=data['description'],
            capabilities=data['capabilities'],
            connection=data['connection'],
            authentication=data.get('authentication'),
            metadata=data.get('metadata'),
            executor=data.get('executor')
        )
        
        return provider
    
    def _parse_parameter_type(self, type_str: str) -> ParameterType:
        """Parse parameter type from string"""
        
        type_mapping = {
            'string': ParameterType.STRING,
            'number': ParameterType.NUMBER,
            'integer': ParameterType.INTEGER,
            'boolean': ParameterType.BOOLEAN,
            'array': ParameterType.ARRAY,
            'object': ParameterType.OBJECT,
            'null': ParameterType.NULL
        }
        
        if type_str.lower() not in type_mapping:
            raise ValidationError(f"Unknown parameter type: {type_str}")
        
        return type_mapping[type_str.lower()]
    
    def get_loaded_protocols(self) -> Dict[str, ProtocolSpec]:
        """Get all loaded protocols"""
        return self.loaded_protocols.copy()
    
    def get_loaded_providers(self) -> Dict[str, ProviderConfig]:
        """Get all loaded providers"""
        return self.loaded_providers.copy()


# Global instance
_yaml_loader = YAMLProtocolLoader()


def get_yaml_loader() -> YAMLProtocolLoader:
    """Get the global YAML loader instance"""
    return _yaml_loader


def load_protocol_from_yaml(yaml_file: Union[str, Path]) -> ProtocolSpec:
    """Load a protocol from YAML file (convenience function)"""
    return _yaml_loader.load_protocol_from_yaml(yaml_file)


def load_provider_from_yaml(yaml_file: Union[str, Path]) -> ProviderConfig:
    """Load a provider from YAML file (convenience function)"""
    return _yaml_loader.load_provider_from_yaml(yaml_file)