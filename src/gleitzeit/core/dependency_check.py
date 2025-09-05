"""
Dependency checking utilities for Gleitzeit.

Ensures required packages are installed before enabling features.
"""

import sys
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def check_auth_dependencies() -> Tuple[bool, Optional[str]]:
    """
    Check if authentication dependencies are installed.
    
    Returns:
        Tuple of (success, error_message)
    """
    missing = []
    
    try:
        import jwt
    except ImportError:
        missing.append("PyJWT")
    
    try:
        import bcrypt
    except ImportError:
        missing.append("bcrypt")
    
    try:
        import passlib
    except ImportError:
        missing.append("passlib")
    
    if missing:
        error_msg = (
            f"Authentication is enabled but required packages are missing: {', '.join(missing)}\n"
            f"Please install them with: pip install {' '.join(missing)}\n"
            f"Or install all auth dependencies with: pip install gleitzeit[auth]"
        )
        return False, error_msg
    
    return True, None


def check_redis_dependencies() -> Tuple[bool, Optional[str]]:
    """
    Check if Redis dependencies are installed.
    
    Returns:
        Tuple of (success, error_message)
    """
    try:
        import redis.asyncio
    except ImportError:
        error_msg = (
            "Redis persistence is configured but redis package is not installed.\n"
            "Please install it with: pip install redis\n"
            "Or install all dependencies with: pip install gleitzeit[redis]"
        )
        return False, error_msg
    
    return True, None


def check_ui_dependencies() -> Tuple[bool, Optional[str]]:
    """
    Check if UI dependencies are installed.
    
    Returns:
        Tuple of (success, error_message)
    """
    missing = []
    
    try:
        import aiofiles
    except ImportError:
        missing.append("aiofiles")
    
    try:
        import websockets
    except ImportError:
        missing.append("websockets")
    
    if missing:
        error_msg = (
            f"UI server requires packages that are missing: {', '.join(missing)}\n"
            f"Please install them with: pip install {' '.join(missing)}\n"
            f"Or install all UI dependencies with: pip install gleitzeit[ui]"
        )
        return False, error_msg
    
    return True, None


def check_dependencies(features: List[str]) -> Dict[str, Tuple[bool, Optional[str]]]:
    """
    Check dependencies for specified features.
    
    Args:
        features: List of features to check ('auth', 'redis', 'ui')
        
    Returns:
        Dictionary mapping feature to (success, error_message)
    """
    checkers = {
        'auth': check_auth_dependencies,
        'redis': check_redis_dependencies,
        'ui': check_ui_dependencies
    }
    
    results = {}
    for feature in features:
        if feature in checkers:
            results[feature] = checkers[feature]()
        else:
            results[feature] = (False, f"Unknown feature: {feature}")
    
    return results


def verify_and_report_dependencies(features: List[str], exit_on_error: bool = False) -> bool:
    """
    Verify dependencies and report any issues.
    
    Args:
        features: List of features to check
        exit_on_error: Whether to exit the program if dependencies are missing
        
    Returns:
        True if all dependencies are satisfied, False otherwise
    """
    results = check_dependencies(features)
    
    all_ok = True
    for feature, (success, error_msg) in results.items():
        if not success:
            all_ok = False
            logger.error(f"Dependency check failed for {feature}: {error_msg}")
            if exit_on_error:
                logger.error(f"ERROR: {error_msg}")
                sys.exit(1)
        else:
            logger.debug(f"Dependencies for {feature} are satisfied")
    
    return all_ok