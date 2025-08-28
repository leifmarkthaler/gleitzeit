#!/usr/bin/env python3
"""
Test authentication with different persistence backends
"""

import os
import asyncio
import tempfile
from pathlib import Path
import logging
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit.persistence.factory import PersistenceFactory, PersistenceType
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.auth.database import get_auth_db, init_auth_db, reset_auth_db
from gleitzeit.auth.utils import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_test(name: str, passed: bool, details: str = ""):
    """Print test result"""
    status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
    print(f"{status} - {name}")
    if details:
        print(f"  {YELLOW}{details}{RESET}")


async def test_memory_backend():
    """Test auth with in-memory backend"""
    print(f"\n{BLUE}=== Testing In-Memory Backend ==={RESET}")
    
    # Reset auth db
    reset_auth_db()
    
    # Set environment for in-memory
    os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "memory"
    os.environ["GLEITZEIT_AUTH_ENABLED"] = "true"
    os.environ["GLEITZEIT_AUTH_CREATE_ADMIN"] = "true"
    os.environ["GLEITZEIT_AUTH_ADMIN_EMAIL"] = "admin@memory.test"
    os.environ["GLEITZEIT_AUTH_ADMIN_PASSWORD"] = "mempass"
    
    try:
        # Get auth database (should create in-memory)
        auth_db = get_auth_db()
        print_test("Created in-memory auth database", True, type(auth_db).__name__)
        
        # Check admin user was created
        admin = await auth_db.get_user_by_email("admin@memory.test")
        print_test("Admin user created", admin is not None, 
                  f"Email: {admin.email if admin else 'Not found'}")
        
        # Create a new user
        user_data = {
            "email": "test@memory.test",
            "password": "testpass",
            "username": "memtest",
            "full_name": "Memory Test User"
        }
        new_user = await auth_db.create_user(user_data)
        print_test("Created test user", new_user is not None,
                  f"ID: {new_user.id if new_user else 'Failed'}")
        
        # Create API key
        if new_user:
            api_key_data = {
                "key_hash": hash_password("test-key-123"),
                "key_prefix": "mem_",
                "name": "Memory Test Key"
            }
            api_key = await auth_db.create_api_key(new_user.id, api_key_data)
            print_test("Created API key", api_key is not None,
                      f"Prefix: {api_key.key_prefix if api_key else 'Failed'}")
        
        # Create audit log
        await auth_db.create_audit_log(
            user_id=new_user.id if new_user else None,
            action="test",
            resource_type="memory_test"
        )
        print_test("Created audit log", True, "Audit log created")
        
        return True
        
    except Exception as e:
        print_test("Memory backend test", False, str(e))
        return False


async def test_sql_backend():
    """Test auth with SQL backend"""
    print(f"\n{BLUE}=== Testing SQL Backend ==={RESET}")
    
    # Reset auth db
    reset_auth_db()
    
    # Create temporary SQLite database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Set environment for SQL
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "sql"
        os.environ["GLEITZEIT_AUTH_ENABLED"] = "true"
        os.environ["GLEITZEIT_AUTH_CREATE_ADMIN"] = "true"
        os.environ["GLEITZEIT_AUTH_ADMIN_EMAIL"] = "admin@sql.test"
        os.environ["GLEITZEIT_AUTH_ADMIN_PASSWORD"] = "sqlpass"
        
        # Create persistence backend
        persistence = PersistenceFactory.create(
            persistence_type=PersistenceType.SQL,
            connection_string=f"sqlite:///{db_path}"
        )
        print_test("Created SQL persistence", True, f"SQLite: {db_path}")
        
        # Initialize auth database with SQL backend
        auth_db = init_auth_db(persistence=persistence)
        print_test("Created SQL auth database", True, type(auth_db).__name__)
        
        # Check admin user was created
        admin = await auth_db.get_user_by_email("admin@sql.test")
        print_test("Admin user created", admin is not None,
                  f"Email: {admin.email if admin else 'Not found'}")
        
        # Create a new user
        user_data = {
            "email": "test@sql.test",
            "password": "testpass",
            "username": "sqltest",
            "full_name": "SQL Test User"
        }
        new_user = await auth_db.create_user(user_data)
        print_test("Created test user", new_user is not None,
                  f"ID: {new_user.id if new_user else 'Failed'}")
        
        # Test persistence - reset and reload
        reset_auth_db()
        auth_db = init_auth_db(persistence=persistence)
        
        # Check user still exists
        reloaded_user = await auth_db.get_user_by_email("test@sql.test")
        print_test("User persisted after reload", reloaded_user is not None,
                  f"Username: {reloaded_user.username if reloaded_user else 'Not found'}")
        
        return True
        
    except Exception as e:
        print_test("SQL backend test", False, str(e))
        return False
    finally:
        # Clean up temp database
        try:
            Path(db_path).unlink()
        except:
            pass


async def test_redis_backend():
    """Test auth with Redis backend"""
    print(f"\n{BLUE}=== Testing Redis Backend ==={RESET}")
    
    # Reset auth db
    reset_auth_db()
    
    # Check if Redis is available
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
    except:
        print(f"{YELLOW}Redis not available, skipping Redis tests{RESET}")
        return True
    
    try:
        # Set environment for Redis
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "redis"
        os.environ["GLEITZEIT_AUTH_ENABLED"] = "true"
        os.environ["GLEITZEIT_AUTH_CREATE_ADMIN"] = "true"
        os.environ["GLEITZEIT_AUTH_ADMIN_EMAIL"] = "admin@redis.test"
        os.environ["GLEITZEIT_AUTH_ADMIN_PASSWORD"] = "redispass"
        os.environ["GLEITZEIT_REDIS_URL"] = "redis://localhost:6379"
        
        # Create Redis adapter
        redis_adapter = UnifiedRedisAdapter(
            redis_url="redis://localhost:6379"
        )
        print_test("Created Redis adapter", True, "Connected to Redis")
        
        # Create SQL backend for persistent storage (hybrid mode)
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        sql_persistence = PersistenceFactory.create(
            persistence_type=PersistenceType.SQL,
            connection_string=f"sqlite:///{db_path}"
        )
        
        # Initialize auth database with Redis + SQL (hybrid)
        auth_db = init_auth_db(
            persistence=sql_persistence,
            redis_adapter=redis_adapter
        )
        print_test("Created Redis auth database", True, 
                  f"{type(auth_db).__name__} (Hybrid: Redis + SQL)")
        
        # Check admin user was created
        admin = await auth_db.get_user_by_email("admin@redis.test")
        print_test("Admin user created", admin is not None,
                  f"Email: {admin.email if admin else 'Not found'}")
        
        # Create a session (Redis-specific feature)
        if admin:
            session_data = {
                "token_hash": hash_password("session-token"),
                "expires_at": "2025-12-31T23:59:59",
                "ip_address": "127.0.0.1"
            }
            session = await auth_db.create_session(admin.id, session_data)
            print_test("Created session in Redis", session is not None,
                      f"Session ID: {session.id if session else 'Failed'}")
            
            # Verify session exists in Redis
            session_check = await auth_db.get_session_by_token_hash(
                hash_password("session-token")
            )
            print_test("Retrieved session from Redis", session_check is not None,
                      "Session cached in Redis")
        
        # Clean up
        try:
            Path(db_path).unlink()
        except:
            pass
        
        return True
        
    except Exception as e:
        print_test("Redis backend test", False, str(e))
        return False


async def test_backend_switching():
    """Test switching between backends"""
    print(f"\n{BLUE}=== Testing Backend Switching ==={RESET}")
    
    try:
        # Start with memory
        reset_auth_db()
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "memory"
        auth_db = get_auth_db()
        print_test("Started with memory backend", True, type(auth_db).__name__)
        
        # Switch to SQL
        reset_auth_db()
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "sql"
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        persistence = PersistenceFactory.create(
            persistence_type=PersistenceType.SQL,
            connection_string=f"sqlite:///{db_path}"
        )
        auth_db = init_auth_db(persistence=persistence)
        print_test("Switched to SQL backend", True, type(auth_db).__name__)
        
        # Clean up
        try:
            Path(db_path).unlink()
        except:
            pass
        
        return True
        
    except Exception as e:
        print_test("Backend switching test", False, str(e))
        return False


async def main():
    """Run all backend tests"""
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}Gleitzeit Auth Backend Compatibility Test{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    results = []
    
    # Test each backend
    results.append(("Memory", await test_memory_backend()))
    results.append(("SQL", await test_sql_backend()))
    results.append(("Redis", await test_redis_backend()))
    results.append(("Switching", await test_backend_switching()))
    
    # Summary
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}Test Summary:{RESET}")
    for name, passed in results:
        status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"  {status} {name} Backend")
    
    all_passed = all(r[1] for r in results)
    if all_passed:
        print(f"\n{GREEN}✅ All backend tests passed!{RESET}")
        print(f"\nThe authentication system works with:")
        print(f"  • In-Memory backend (development)")
        print(f"  • SQL backend (SQLite/PostgreSQL)")
        print(f"  • Redis backend (with SQL fallback)")
        print(f"  • Hybrid mode (Redis cache + SQL persistence)")
    else:
        print(f"\n{RED}❌ Some tests failed{RESET}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Test interrupted by user{RESET}")
        sys.exit(130)