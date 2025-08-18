"""
Models for Instructor integration
"""

from typing import Dict, Any, Optional, List, Type, Union
from dataclasses import dataclass
from pydantic import BaseModel, create_model, Field
import json


@dataclass
class StructuredOutput:
    """Result from structured LLM generation"""
    data: Dict[str, Any]
    model: str
    provider: str
    validation_attempts: int = 1
    raw_response: Optional[str] = None


@dataclass 
class SchemaDefinition:
    """Schema definition for structured output"""
    name: str
    properties: Dict[str, Any]
    required: Optional[List[str]] = None
    description: Optional[str] = None
    
    def to_pydantic_model(self) -> Type[BaseModel]:
        """Convert schema definition to Pydantic model"""
        fields = {}
        
        for field_name, field_def in self.properties.items():
            field_type = self._get_python_type(field_def)
            is_required = self.required and field_name in self.required
            
            if is_required:
                fields[field_name] = (field_type, Field(..., description=field_def.get('description', '')))
            else:
                fields[field_name] = (Optional[field_type], Field(None, description=field_def.get('description', '')))
        
        return create_model(
            self.name,
            __doc__=self.description or f"Generated model for {self.name}",
            **fields
        )
    
    def _get_python_type(self, field_def: Dict[str, Any]) -> type:
        """Convert JSON schema type to Python type"""
        type_map = {
            'string': str,
            'integer': int,
            'number': float,
            'boolean': bool,
            'array': list,
            'object': dict,
        }
        
        field_type = field_def.get('type', 'string')
        
        if field_type == 'array':
            items = field_def.get('items', {})
            item_type = self._get_python_type(items)
            return List[item_type]
        
        return type_map.get(field_type, str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SchemaDefinition':
        """Create from dictionary"""
        return cls(
            name=data.get('name', 'GeneratedModel'),
            properties=data.get('properties', {}),
            required=data.get('required'),
            description=data.get('description')
        )
    
    @classmethod
    def from_pydantic_model(cls, model: Type[BaseModel]) -> 'SchemaDefinition':
        """Create from existing Pydantic model"""
        schema = model.model_json_schema()
        return cls(
            name=model.__name__,
            properties=schema.get('properties', {}),
            required=schema.get('required', []),
            description=model.__doc__
        )