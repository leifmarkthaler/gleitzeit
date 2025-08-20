"""
JSON-RPC 2.0 implementation for Gleitzeit V4

Provides standard JSON-RPC 2.0 request/response handling
with full spec compliance and error handling.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from enum import IntEnum
import json
import uuid

from gleitzeit.core.errors import (
    ErrorCode, GleitzeitError, error_to_jsonrpc,
    ProtocolError, InvalidParameterError
)


# JSON-RPC error codes are now defined in centralized ErrorCode enum
# This maintains backward compatibility while using the centralized system


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object"""
    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Optional[Any] = Field(None, description="Additional error data")
    
    @field_validator('code')
    @classmethod
    def validate_error_code(cls, v):
        """Validate error code follows JSON-RPC 2.0 spec"""
        # Accept any ErrorCode value (they're designed to be JSON-RPC compliant)
        if isinstance(v, ErrorCode):
            return v.value
        
        # Accept integer codes in valid ranges
        if isinstance(v, int):
            # JSON-RPC reserved range (-32768 to -32000)
            if -32768 <= v <= -32000:
                return v
            # Application-specific codes (positive or -32099 to -25000)
            if v > 0 or -32099 <= v <= -25000:
                return v
        
        raise ProtocolError(f"Invalid JSON-RPC error code: {v}")
    
    def __str__(self) -> str:
        return f"JSONRPCError({self.code}): {self.message}"


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request object"""
    jsonrpc: str = Field("2.0", pattern="^2\\.0$", description="JSON-RPC version")
    method: str = Field(..., min_length=1, description="Method name to call")
    params: Optional[Union[List[Any], Dict[str, Any]]] = Field(None, description="Method parameters")
    id: Optional[Union[str, int, None]] = Field(None, description="Request identifier")
    
    model_config = ConfigDict(extra="forbid")  # Strict JSON-RPC compliance
    
    @field_validator('method')
    @classmethod
    def validate_method_name(cls, v):
        """Validate method name follows JSON-RPC conventions"""
        if v.startswith('rpc.'):
            raise ProtocolError("Method names starting with 'rpc.' are reserved")
        return v
    
    def is_notification(self) -> bool:
        """Check if this is a notification (no response expected)"""
        return self.id is None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {"jsonrpc": self.jsonrpc, "method": self.method}
        
        if self.params is not None:
            result["params"] = self.params
        
        if self.id is not None:
            result["id"] = self.id
        
        return result
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def create(
        cls, 
        method: str, 
        params: Optional[Union[List[Any], Dict[str, Any]]] = None,
        request_id: Optional[Union[str, int]] = None,
        is_notification: bool = False
    ) -> "JSONRPCRequest":
        """Create a new JSON-RPC request"""
        if is_notification:
            request_id = None
        elif request_id is None:
            request_id = str(uuid.uuid4())
        
        return cls(
            method=method,
            params=params,
            id=request_id
        )


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response object"""
    jsonrpc: str = Field("2.0", pattern="^2\\.0$", description="JSON-RPC version")
    id: Union[str, int, None] = Field(..., description="Request identifier")
    result: Optional[Any] = Field(None, description="Method result")
    error: Optional[JSONRPCError] = Field(None, description="Error object")
    
    model_config = ConfigDict(extra="forbid")  # Strict JSON-RPC compliance
    
    @model_validator(mode='after')
    def validate_result_or_error(self):
        """Ensure exactly one of result or error is present"""
        # Now that we renamed the classmethod, we can safely access the field
        if self.result is not None and self.error is not None:
            raise ProtocolError("Response cannot have both result and error")
        
        if self.result is None and self.error is None:
            raise ProtocolError("Response must have either result or error")
        
        return self
    
    def is_success(self) -> bool:
        """Check if response indicates success"""
        return self.error is None
    
    def is_error(self) -> bool:
        """Check if response indicates an error"""
        return self.error is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {"jsonrpc": self.jsonrpc, "id": self.id}
        
        if self.error is not None:
            result["error"] = self.error.model_dump()
        else:
            result["result"] = self.result
        
        return result
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def success(
        cls, 
        request_id: Union[str, int, None], 
        result: Any
    ) -> "JSONRPCResponse":
        """Create a success response"""
        return cls(id=request_id, result=result)
    
    @classmethod
    def create_error(
        cls, 
        request_id: Union[str, int, None], 
        error_code: Union[int, ErrorCode],
        error_message: str,
        error_data: Optional[Any] = None
    ) -> "JSONRPCResponse":
        """Create an error response"""
        if isinstance(error_code, ErrorCode):
            error_code = error_code.value
        
        return cls(
            id=request_id,
            error=JSONRPCError(
                code=error_code,
                message=error_message,
                data=error_data
            )
        )
    
    @classmethod
    def from_gleitzeit_error(
        cls,
        request_id: Union[str, int, None],
        error: GleitzeitError
    ) -> "JSONRPCResponse":
        """Create error response from GleitzeitError"""
        jsonrpc_error = error_to_jsonrpc(error)
        return cls(
            id=request_id,
            error=JSONRPCError(
                code=jsonrpc_error["code"],
                message=jsonrpc_error["message"],
                data=jsonrpc_error.get("data")
            )
        )


class JSONRPCBatch(BaseModel):
    """JSON-RPC 2.0 batch request/response handler"""
    items: List[Union[JSONRPCRequest, JSONRPCResponse]] = Field(..., min_length=1)
    
    def is_batch_request(self) -> bool:
        """Check if this is a batch of requests"""
        return all(isinstance(item, JSONRPCRequest) for item in self.items)
    
    def is_batch_response(self) -> bool:
        """Check if this is a batch of responses"""
        return all(isinstance(item, JSONRPCResponse) for item in self.items)
    
    def get_requests(self) -> List[JSONRPCRequest]:
        """Get all requests in the batch"""
        return [item for item in self.items if isinstance(item, JSONRPCRequest)]
    
    def get_responses(self) -> List[JSONRPCResponse]:
        """Get all responses in the batch"""
        return [item for item in self.items if isinstance(item, JSONRPCResponse)]
    
    def to_dict(self) -> List[Dict[str, Any]]:
        """Convert to list of dictionaries for JSON serialization"""
        return [item.to_dict() for item in self.items]
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())


def parse_jsonrpc_request(data: Union[str, bytes, Dict[str, Any]]) -> Union[JSONRPCRequest, JSONRPCBatch]:
    """
    Parse JSON-RPC request from various input formats
    
    Args:
        data: JSON string, bytes, or dictionary
        
    Returns:
        JSONRPCRequest for single requests or JSONRPCBatch for batch requests
        
    Raises:
        ValueError: For invalid JSON-RPC format
        json.JSONDecodeError: For invalid JSON
    """
    # Parse JSON if needed
    if isinstance(data, (str, bytes)):
        parsed = json.loads(data)
    elif isinstance(data, dict):
        parsed = data
    else:
        raise InvalidParameterError(
            "data",
            f"Unsupported input type: {type(data)}"
        )
    
    # Handle batch requests
    if isinstance(parsed, list):
        if not parsed:
            raise ProtocolError("Empty batch request")
        
        requests = []
        for item in parsed:
            requests.append(JSONRPCRequest(**item))
        
        return JSONRPCBatch(items=requests)
    
    # Handle single request
    elif isinstance(parsed, dict):
        return JSONRPCRequest(**parsed)
    
    else:
        raise ProtocolError("Invalid JSON-RPC format")


def parse_jsonrpc_response(data: Union[str, bytes, Dict[str, Any]]) -> Union[JSONRPCResponse, JSONRPCBatch]:
    """
    Parse JSON-RPC response from various input formats
    
    Args:
        data: JSON string, bytes, or dictionary
        
    Returns:
        JSONRPCResponse for single responses or JSONRPCBatch for batch responses
        
    Raises:
        ValueError: For invalid JSON-RPC format
        json.JSONDecodeError: For invalid JSON
    """
    # Parse JSON if needed
    if isinstance(data, (str, bytes)):
        parsed = json.loads(data)
    elif isinstance(data, dict):
        parsed = data
    else:
        raise InvalidParameterError(
            "data",
            f"Unsupported input type: {type(data)}"
        )
    
    # Handle batch responses
    if isinstance(parsed, list):
        if not parsed:
            raise ProtocolError("Empty batch response")
        
        responses = []
        for item in parsed:
            responses.append(JSONRPCResponse(**item))
        
        return JSONRPCBatch(items=responses)
    
    # Handle single response
    elif isinstance(parsed, dict):
        return JSONRPCResponse(**parsed)
    
    else:
        raise ProtocolError("Invalid JSON-RPC format")


# Exception classes for JSON-RPC errors
class JSONRPCException(Exception):
    """Base exception for JSON-RPC errors"""
    def __init__(self, error: JSONRPCError):
        self.error = error
        super().__init__(str(error))


class ParseError(JSONRPCException):
    """JSON-RPC parse error"""
    def __init__(self, message: str = "Parse error", data: Any = None):
        error = JSONRPCError(
            code=ErrorCode.PARSE_ERROR,
            message=message,
            data=data
        )
        super().__init__(error)


class InvalidRequest(JSONRPCException):
    """JSON-RPC invalid request error"""
    def __init__(self, message: str = "Invalid Request", data: Any = None):
        error = JSONRPCError(
            code=ErrorCode.INVALID_REQUEST,
            message=message,
            data=data
        )
        super().__init__(error)


class MethodNotFound(JSONRPCException):
    """JSON-RPC method not found error"""
    def __init__(self, method: str, data: Any = None):
        error = JSONRPCError(
            code=ErrorCode.METHOD_NOT_FOUND,
            message=f"Method not found: {method}",
            data=data
        )
        super().__init__(error)


class InvalidParams(JSONRPCException):
    """JSON-RPC invalid parameters error"""
    def __init__(self, message: str = "Invalid params", data: Any = None):
        error = JSONRPCError(
            code=ErrorCode.INVALID_PARAMS,
            message=message,
            data=data
        )
        super().__init__(error)


class InternalError(JSONRPCException):
    """JSON-RPC internal error"""
    def __init__(self, message: str = "Internal error", data: Any = None):
        error = JSONRPCError(
            code=ErrorCode.INTERNAL_ERROR,
            message=message,
            data=data
        )
        super().__init__(error)


# Utility functions for error conversion
def gleitzeit_error_to_jsonrpc_response(
    request_id: Union[str, int, None], 
    error: Union[GleitzeitError, Exception]
) -> JSONRPCResponse:
    """
    Convert any error to a JSON-RPC error response
    
    Args:
        request_id: The JSON-RPC request ID
        error: GleitzeitError or standard exception
        
    Returns:
        JSONRPCResponse with appropriate error
    """
    if isinstance(error, GleitzeitError):
        return JSONRPCResponse.from_gleitzeit_error(request_id, error)
    else:
        # Convert standard exceptions using centralized mapping
        jsonrpc_error = error_to_jsonrpc(error)
        return JSONRPCResponse(
            id=request_id,
            error=JSONRPCError(
                code=jsonrpc_error["code"],
                message=jsonrpc_error["message"],
                data=jsonrpc_error.get("data")
            )
        )


def create_jsonrpc_error_from_code(
    code: ErrorCode,
    message: Optional[str] = None,
    data: Optional[Any] = None
) -> JSONRPCError:
    """
    Create JSONRPCError from ErrorCode
    
    Args:
        code: ErrorCode enum value
        message: Optional custom message (uses default if None)
        data: Optional additional error data
        
    Returns:
        JSONRPCError object
    """
    if message is None:
        # Generate default message based on code
        message = code.name.replace('_', ' ').lower().capitalize()
    
    return JSONRPCError(
        code=code.value,
        message=message,
        data=data
    )