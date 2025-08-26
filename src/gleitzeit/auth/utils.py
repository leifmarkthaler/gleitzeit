"""
Authentication utility functions
"""

import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
import bcrypt


# Configuration defaults
API_KEY_PREFIX = "glzt"
API_KEY_LENGTH = 32
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY = None  # Will be set from environment


def generate_api_key(environment: str = "prod") -> str:
    """
    Generate a new API key with prefix
    
    Args:
        environment: Environment identifier (prod, dev, test)
    
    Returns:
        API key string like 'glzt_prod_abc123...'
    """
    # Generate random key
    alphabet = string.ascii_letters + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(API_KEY_LENGTH))
    
    # Create key with prefix
    api_key = f"{API_KEY_PREFIX}_{environment}_{random_part}"
    return api_key


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA256
    
    Args:
        api_key: Plain text API key
    
    Returns:
        SHA256 hash of the API key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """
    Verify an API key against stored hash
    
    Args:
        api_key: Plain text API key
        stored_hash: Stored SHA256 hash
    
    Returns:
        True if key matches, False otherwise
    """
    return hash_api_key(api_key) == stored_hash


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt
    
    Args:
        password: Plain text password
    
    Returns:
        Bcrypt hash of the password
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against bcrypt hash
    
    Args:
        password: Plain text password
        hashed: Bcrypt hash
    
    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def create_jwt_token(
    user_data: Dict[str, Any],
    secret_key: str,
    expires_in: Optional[timedelta] = None,
    algorithm: str = JWT_ALGORITHM
) -> str:
    """
    Create a JWT token
    
    Args:
        user_data: User data to encode in token
        secret_key: Secret key for signing
        expires_in: Token expiration time
        algorithm: JWT algorithm (default HS256)
    
    Returns:
        Encoded JWT token
    """
    payload = user_data.copy()
    
    # Add expiration
    if expires_in:
        expire = datetime.utcnow() + expires_in
        payload['exp'] = expire
    
    # Add issued at time
    payload['iat'] = datetime.utcnow()
    
    # Encode token
    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    return token


def decode_jwt_token(
    token: str,
    secret_key: str,
    algorithms: list = None,
    verify_exp: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Decode and verify a JWT token
    
    Args:
        token: JWT token to decode
        secret_key: Secret key for verification
        algorithms: List of allowed algorithms
        verify_exp: Whether to verify expiration
    
    Returns:
        Decoded token payload or None if invalid
    """
    if algorithms is None:
        algorithms = [JWT_ALGORITHM]
    
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=algorithms,
            options={"verify_exp": verify_exp}
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_access_token(user: Dict, secret_key: str, expires_minutes: int = 60) -> str:
    """
    Create an access token for a user
    
    Args:
        user: User data dictionary
        secret_key: Secret key for signing
        expires_minutes: Token expiration in minutes
    
    Returns:
        JWT access token
    """
    token_data = {
        "sub": str(user.get("id")),
        "email": user.get("email"),
        "username": user.get("username"),
        "roles": user.get("roles", []),
        "is_superuser": user.get("is_superuser", False),
        "type": "access"
    }
    
    return create_jwt_token(
        token_data,
        secret_key,
        expires_in=timedelta(minutes=expires_minutes)
    )


def create_refresh_token(user: Dict, secret_key: str, expires_days: int = 30) -> str:
    """
    Create a refresh token for a user
    
    Args:
        user: User data dictionary
        secret_key: Secret key for signing
        expires_days: Token expiration in days
    
    Returns:
        JWT refresh token
    """
    token_data = {
        "sub": str(user.get("id")),
        "type": "refresh"
    }
    
    return create_jwt_token(
        token_data,
        secret_key,
        expires_in=timedelta(days=expires_days)
    )


def extract_api_key_prefix(api_key: str) -> str:
    """
    Extract the prefix from an API key
    
    Args:
        api_key: Full API key
    
    Returns:
        Key prefix for identification
    """
    parts = api_key.split('_')
    if len(parts) >= 3:
        return f"{parts[0]}_{parts[1]}_"
    return ""


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets strength requirements
    
    Args:
        password: Password to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    
    return True, ""


def generate_session_token() -> str:
    """
    Generate a secure session token
    
    Returns:
        Random session token
    """
    return secrets.token_urlsafe(32)


def parse_bearer_token(auth_header: str) -> Optional[str]:
    """
    Parse bearer token from Authorization header
    
    Args:
        auth_header: Authorization header value
    
    Returns:
        Token or None if invalid format
    """
    if not auth_header:
        return None
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    return parts[1]


def parse_basic_auth(auth_header: str) -> Optional[tuple[str, str]]:
    """
    Parse basic authentication from Authorization header
    
    Args:
        auth_header: Authorization header value
    
    Returns:
        Tuple of (username, password) or None if invalid
    """
    if not auth_header:
        return None
    
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    
    try:
        import base64
        decoded = base64.b64decode(parts[1]).decode('utf-8')
        username, password = decoded.split(':', 1)
        return username, password
    except Exception:
        return None