"""
Protocol specification and validation for Gleitzeit V4

Defines protocol schemas, method specifications, and validation
for JSON-RPC 2.0 compliant protocols.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import jsonschema
from jsonschema import validate, ValidationError


class ParameterType(str, Enum):
    """Supported parameter types for protocol methods"""
    STRING = "string"
    INTEGER = "integer" 
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"


class ParameterSpec(BaseModel):
    """Specification for a method parameter"""
    type: Union[ParameterType, List[ParameterType]] = Field(..., description="Parameter type(s)")
    description: Optional[str] = Field(None, description="Parameter description")
    required: bool = Field(True, description="Whether parameter is required")
    default: Optional[Any] = Field(None, description="Default value if not required")
    enum: Optional[List[Any]] = Field(None, description="Allowed values (enumeration)")
    minimum: Optional[Union[int, float]] = Field(None, description="Minimum value for numbers")
    maximum: Optional[Union[int, float]] = Field(None, description="Maximum value for numbers")
    min_length: Optional[int] = Field(None, ge=0, description="Minimum length for strings/arrays")
    max_length: Optional[int] = Field(None, ge=0, description="Maximum length for strings/arrays")
    pattern: Optional[str] = Field(None, description="Regex pattern for strings")
    items: Optional["ParameterSpec"] = Field(None, description="Item specification for arrays")
    properties: Optional[Dict[str, "ParameterSpec"]] = Field(None, description="Object properties")
    additional_properties: bool = Field(True, description="Allow additional object properties")
    
    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema format"""
        schema = {}
        
        # Handle type
        if isinstance(self.type, list):
            schema["type"] = [t.value for t in self.type]
        else:
            schema["type"] = self.type.value
        
        # Add constraints
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = self.enum
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.pattern:
            schema["pattern"] = self.pattern
        
        # Handle array items
        if self.items:
            schema["items"] = self.items.to_json_schema()
        
        # Handle object properties
        if self.properties:
            schema["properties"] = {
                key: prop.to_json_schema() 
                for key, prop in self.properties.items()
            }
            schema["additionalProperties"] = self.additional_properties
            
            # Add required fields
            required_fields = [
                key for key, prop in self.properties.items() 
                if prop.required
            ]
            if required_fields:
                schema["required"] = required_fields
        
        return schema


# Forward reference resolution
ParameterSpec.model_rebuild()


class MethodSpec(BaseModel):
    """Specification for a protocol method"""
    name: str = Field(..., description="Method name")
    description: Optional[str] = Field(None, description="Method description")
    params_schema: Dict[str, ParameterSpec] = Field(default_factory=dict, description="Parameter specifications")
    returns_schema: Optional[ParameterSpec] = Field(None, description="Return value specification") 
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="Usage examples")
    deprecated: bool = Field(False, description="Whether method is deprecated")
    
    @field_validator('name')
    @classmethod
    def validate_method_name(cls, v: str) -> str:
        """
        Validate method name with support for different protocol conventions:
        - Standard JSON-RPC: alphanumeric with underscores and slashes
        - MCP (Model Context Protocol): supports dotted notation like 'tool.echo'
        - URI-style: supports colons for resource URIs like 'resource.file://path'
        """
        if not v:
            raise ValueError("Method name cannot be empty")
        
        # Must start with a letter
        if not v[0].isalpha():
            raise ValueError("Method name must start with a letter")
        
        # Check for valid characters: letters, numbers, dots, underscores, slashes, colons, hyphens
        import re
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_./:/-]*$', v):
            raise ValueError(f"Method name '{v}' contains invalid characters. Allowed: letters, numbers, dots, underscores, slashes, colons, hyphens")
        
        # Additional checks for common patterns
        if '..' in v:
            raise ValueError("Method name cannot contain consecutive dots")
        
        if v.endswith('.'):
            raise ValueError("Method name cannot end with a dot")
            
        return v
    
    def validate_params(self, params: Union[Dict[str, Any], List[Any]]) -> None:
        """
        Validate method parameters against schema
        
        Args:
            params: Parameters to validate
            
        Raises:
            ValidationError: If parameters are invalid
        """
        if not self.params_schema:
            return  # No validation needed
        
        # Convert named parameters to positional if needed
        if isinstance(params, list):
            # For positional parameters, need to map to parameter names
            param_names = list(self.params_schema.keys())
            if len(params) > len(param_names):
                raise ValidationError("Too many positional parameters")
            
            params_dict = {}
            for i, value in enumerate(params):
                if i < len(param_names):
                    params_dict[param_names[i]] = value
            params = params_dict
        
        # Build JSON schema for validation
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
        
        for param_name, param_spec in self.params_schema.items():
            schema["properties"][param_name] = param_spec.to_json_schema()
            if param_spec.required:
                schema["required"].append(param_name)
        
        # Validate against schema
        validate(instance=params, schema=schema)
    
    def get_param_schema(self, param_name: str) -> Optional[ParameterSpec]:
        """Get schema for a specific parameter"""
        return self.params_schema.get(param_name)


class ProtocolSpec(BaseModel):
    """Complete specification for a protocol"""
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$", description="Protocol name")
    version: str = Field(..., pattern=r"^v\d+(\.\d+)*$", description="Protocol version")
    description: Optional[str] = Field(None, description="Protocol description")
    
    # Protocol inheritance
    extends: Optional[str] = Field(None, description="Parent protocol this extends")
    
    # Method definitions
    methods: Dict[str, MethodSpec] = Field(default_factory=dict, description="Method specifications")
    
    # Metadata
    author: Optional[str] = Field(None, description="Protocol author")
    license: Optional[str] = Field(None, description="Protocol license")
    documentation_url: Optional[str] = Field(None, description="Documentation URL")
    tags: List[str] = Field(default_factory=list, description="Protocol tags")
    
    @property
    def protocol_id(self) -> str:
        """Get full protocol identifier"""
        return f"{self.name}/{self.version}"
    
    def get_method(self, method_name: str) -> Optional[MethodSpec]:
        """Get method specification by name"""
        return self.methods.get(method_name)
    
    def validate_method_call(self, method_name: str, params: Union[Dict[str, Any], List[Any]]) -> None:
        """
        Validate a method call against protocol specification
        
        Args:
            method_name: Name of method being called
            params: Parameters for the method call
            
        Raises:
            ValueError: If method not found
            ValidationError: If parameters are invalid
        """
        method_spec = self.get_method(method_name)
        if not method_spec:
            raise ValueError(f"Method '{method_name}' not found in protocol '{self.protocol_id}'")
        
        method_spec.validate_params(params)
    
    def list_methods(self) -> List[str]:
        """Get list of all method names"""
        return list(self.methods.keys())
    
    def to_openapi_spec(self) -> Dict[str, Any]:
        """Convert to OpenAPI 3.0 specification for documentation"""
        spec = {
            "openapi": "3.0.0",
            "info": {
                "title": f"{self.name} Protocol",
                "version": self.version.lstrip("v"),
                "description": self.description or f"JSON-RPC 2.0 protocol: {self.name}"
            },
            "paths": {},
            "components": {
                "schemas": {}
            }
        }
        
        # Add methods as paths
        for method_name, method_spec in self.methods.items():
            path = f"/{method_name}"
            spec["paths"][path] = {
                "post": {
                    "summary": method_spec.description or f"Call {method_name} method",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "jsonrpc": {"type": "string", "enum": ["2.0"]},
                                        "method": {"type": "string", "enum": [method_name]},
                                        "params": self._params_to_schema(method_spec),
                                        "id": {"oneOf": [{"type": "string"}, {"type": "integer"}]}
                                    },
                                    "required": ["jsonrpc", "method", "id"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "JSON-RPC response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "jsonrpc": {"type": "string", "enum": ["2.0"]},
                                            "result": method_spec.returns_schema.to_json_schema() if method_spec.returns_schema else {},
                                            "id": {"oneOf": [{"type": "string"}, {"type": "integer"}]}
                                        },
                                        "required": ["jsonrpc", "id"]
                                    }
                                }
                            }
                        }
                    }
                }
            }
        
        return spec
    
    def _params_to_schema(self, method_spec: MethodSpec) -> Dict[str, Any]:
        """Convert method parameters to JSON schema"""
        if not method_spec.params_schema:
            return {"type": "object"}
        
        schema = {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
        
        required = []
        for param_name, param_spec in method_spec.params_schema.items():
            schema["properties"][param_name] = param_spec.to_json_schema()
            if param_spec.required:
                required.append(param_name)
        
        if required:
            schema["required"] = required
        
        return schema


class ProtocolRegistry:
    """Registry for managing protocol specifications"""
    
    def __init__(self):
        self._protocols: Dict[str, ProtocolSpec] = {}
    
    def register(self, protocol: ProtocolSpec) -> None:
        """Register a protocol specification"""
        self._protocols[protocol.protocol_id] = protocol
    
    def unregister(self, protocol_id: str) -> None:
        """Unregister a protocol"""
        self._protocols.pop(protocol_id, None)
    
    def get(self, protocol_id: str) -> Optional[ProtocolSpec]:
        """Get protocol specification by ID"""
        return self._protocols.get(protocol_id)
    
    def list_protocols(self) -> List[str]:
        """Get list of all registered protocol IDs"""
        return list(self._protocols.keys())
    
    def find_by_method(self, method_name: str) -> List[ProtocolSpec]:
        """Find all protocols that support a given method"""
        matching = []
        for protocol in self._protocols.values():
            if method_name in protocol.methods:
                matching.append(protocol)
        return matching
    
    def validate_task(self, protocol_id: str, method: str, params: Union[Dict[str, Any], List[Any]]) -> None:
        """
        Validate a task against protocol specification
        
        Args:
            protocol_id: Protocol identifier
            method: Method name
            params: Method parameters
            
        Raises:
            ValueError: If protocol or method not found
            ValidationError: If parameters are invalid
        """
        protocol = self.get(protocol_id)
        if not protocol:
            raise ValueError(f"Protocol not found: {protocol_id}")
        
        protocol.validate_method_call(method, params)


# Global protocol registry instance
_registry = ProtocolRegistry()


def get_protocol_registry() -> ProtocolRegistry:
    """Get the global protocol registry"""
    return _registry


def register_protocol(protocol: ProtocolSpec) -> None:
    """Register a protocol with the global registry"""
    _registry.register(protocol)


def get_protocol(protocol_id: str) -> Optional[ProtocolSpec]:
    """Get protocol from global registry"""
    return _registry.get(protocol_id)