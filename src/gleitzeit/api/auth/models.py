"""
Authentication models
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class UserRole(str, Enum):
    """User roles"""
    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"  # For service accounts/API keys


class User(BaseModel):
    """User model"""
    id: str
    username: str
    email: Optional[str] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


class TokenType(str, Enum):
    """Token types"""
    BEARER = "bearer"
    API_KEY = "api_key"


class Token(BaseModel):
    """Token response model"""
    access_token: str
    token_type: TokenType = TokenType.BEARER
    expires_in: Optional[int] = None  # Seconds until expiration


class LoginRequest(BaseModel):
    """Login request model"""
    username: str
    password: Optional[str] = None  # Optional for development auto-login


class Session(BaseModel):
    """Session model"""
    session_id: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    last_activity: datetime


class ApiKey(BaseModel):
    """API Key model"""
    key_id: str
    key_hash: str  # Store hashed version
    user_id: str
    name: str
    created_at: datetime
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True