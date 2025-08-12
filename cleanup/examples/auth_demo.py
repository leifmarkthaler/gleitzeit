#!/usr/bin/env python3
"""
CLI Authentication System Demo

Demonstrates the file-based, CLI-first authentication system with
API keys, role-based access control, and permission checking.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.auth.auth_manager import AuthManager, initialize_auth
from gleitzeit_cluster.auth.models import Role, Permission, AuthContext
from gleitzeit_cluster.auth.decorators import require_auth, require_permission, require_role
from gleitzeit_cluster.auth.storage import AuthStorage


async def demo_auth_initialization():
    """Demo: Initialize authentication system"""
    print("🔧 Authentication System Initialization")
    print("=" * 50)
    
    # Create temp directory for demo
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Initialize auth manager with temp directory
        auth_manager = AuthManager(config_dir=temp_path)
        
        # Initialize system (creates default admin)
        initialized = auth_manager.initialize()
        
        if initialized:
            print("✅ System initialized with default admin user")
            
            # Show what was created
            users = auth_manager.storage.list_users()
            print(f"👥 Created {len(users)} user(s):")
            for user in users:
                print(f"   • {user.username} ({', '.join(r.value for r in user.roles)})")
                
                # Show API keys
                active_keys = user.get_active_api_keys()
                print(f"     🔑 API Keys: {len(active_keys)}")
                for key in active_keys:
                    print(f"        - {key.name} (...{key.key_id})")
        
        # Show file structure
        print(f"\n📁 Config Directory: {temp_path}")
        for file in temp_path.glob("*"):
            print(f"   📄 {file.name} ({file.stat().st_size} bytes)")
    
    print()


async def demo_user_management():
    """Demo: User and API key management"""
    print("👥 User and API Key Management")
    print("=" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        auth_manager = AuthManager(config_dir=temp_path)
        
        # Initialize and get admin key
        auth_manager.initialize()
        admin_user = auth_manager.storage.list_users()[0]
        admin_api_key = admin_user.get_active_api_keys()[0]
        
        # Create a new admin key for demo (simulate user having the raw key)
        _, raw_admin_key = admin_user.create_api_key("Demo Admin Key")
        auth_manager.storage.update_user(admin_user)
        
        # Authenticate as admin
        admin_context = auth_manager.authenticate_api_key(raw_admin_key)
        auth_manager.set_current_context(admin_context)
        
        print(f"✅ Authenticated as: {admin_context.user.username}")
        
        # Create users with different roles
        print("\n👤 Creating users with different roles...")
        
        regular_user = auth_manager.create_user(
            username="john_doe",
            email="john@example.com",
            full_name="John Doe",
            roles={Role.USER}
        )
        print(f"   ✅ Created user: {regular_user.username} (role: USER)")
        
        operator_user = auth_manager.create_user(
            username="jane_admin",
            email="jane@example.com", 
            full_name="Jane Smith",
            roles={Role.OPERATOR}
        )
        print(f"   ✅ Created user: {operator_user.username} (role: OPERATOR)")
        
        service_user = auth_manager.create_user(
            username="api_service",
            roles={Role.SERVICE}
        )
        print(f"   ✅ Created user: {service_user.username} (role: SERVICE)")
        
        # Create API keys for users
        print(f"\n🔑 Creating API keys...")
        
        _, john_key = auth_manager.create_api_key(
            user_id=regular_user.user_id,
            name="John's Personal Key",
            expires_in_days=30
        )
        print(f"   🔑 Created key for {regular_user.username}: ...{john_key[-8:]}")
        
        _, jane_key = auth_manager.create_api_key(
            user_id=operator_user.user_id,
            name="Jane's Admin Key"
        )
        print(f"   🔑 Created key for {operator_user.username}: ...{jane_key[-8:]}")
        
        _, service_key = auth_manager.create_api_key(
            user_id=service_user.user_id,
            name="Service API Key",
            expires_in_days=365
        )
        print(f"   🔑 Created key for {service_user.username}: ...{service_key[-8:]}")
        
        # List all users
        print(f"\n📋 User Summary:")
        users = auth_manager.list_users()
        for user in users:
            permissions = user.get_permissions()
            print(f"   👤 {user.username}:")
            print(f"      🎭 Roles: {', '.join(r.value for r in user.roles)}")
            print(f"      ✅ Permissions: {len(permissions)}")
            print(f"      🔑 API Keys: {len(user.get_active_api_keys())}")
    
    print()


async def demo_permission_checking():
    """Demo: Permission and role-based access control"""
    print("🛡️  Permission and Role-Based Access Control")
    print("=" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        auth_manager = AuthManager(config_dir=temp_path)
        
        # Setup users
        auth_manager.initialize()
        
        # Create test users
        admin_user = auth_manager.storage.list_users()[0]  # Default admin
        _, admin_key = admin_user.create_api_key("Admin Test Key")
        auth_manager.storage.update_user(admin_user)
        
        # Authenticate as admin to create other users
        admin_context = auth_manager.authenticate_api_key(admin_key)
        auth_manager.set_current_context(admin_context)
        
        regular_user = auth_manager.create_user("regular_user", roles={Role.USER})
        _, regular_key = auth_manager.create_api_key(regular_user.user_id, "Regular Key")
        
        readonly_user = auth_manager.create_user("readonly_user", roles={Role.READONLY})
        _, readonly_key = auth_manager.create_api_key(readonly_user.user_id, "Readonly Key")
        
        # Test permission checking
        print("🧪 Testing permission checks...")
        
        test_cases = [
            (admin_key, "Admin", Permission.CLUSTER_ADMIN),
            (regular_key, "Regular User", Permission.WORKFLOW_CREATE),
            (regular_key, "Regular User", Permission.CLUSTER_ADMIN),  # Should fail
            (readonly_key, "Readonly User", Permission.WORKFLOW_READ),
            (readonly_key, "Readonly User", Permission.WORKFLOW_CREATE),  # Should fail
        ]
        
        for api_key, user_name, permission in test_cases:
            try:
                context = auth_manager.authenticate_api_key(api_key)
                has_permission = context.has_permission(permission)
                
                status = "✅ ALLOWED" if has_permission else "❌ DENIED"
                print(f"   {status}: {user_name} → {permission.value}")
                
            except Exception as e:
                print(f"   ❌ ERROR: {user_name} → {permission.value} ({e})")
    
    print()


@require_auth
async def protected_workflow_function(message: str, auth_context: AuthContext = None):
    """Example of a protected function that requires authentication"""
    return f"Hello {auth_context.user.username}! Message: {message}"


@require_permission(Permission.CLUSTER_ADMIN)
async def admin_only_function(action: str, auth_context: AuthContext = None):
    """Example of a function that requires admin permissions"""
    return f"Admin {auth_context.user.username} performed: {action}"


@require_role(Role.OPERATOR)
async def operator_function(operation: str, auth_context: AuthContext = None):
    """Example of a function that requires operator role"""
    return f"Operator {auth_context.user.username} executed: {operation}"


async def demo_decorators():
    """Demo: Authentication decorators in action"""
    print("🎭 Authentication Decorators")
    print("=" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        auth_manager = AuthManager(config_dir=temp_path)
        
        # Setup
        auth_manager.initialize()
        admin_user = auth_manager.storage.list_users()[0]
        _, admin_key = admin_user.create_api_key("Decorator Test Key")
        auth_manager.storage.update_user(admin_user)
        
        # Create regular user
        admin_context = auth_manager.authenticate_api_key(admin_key)
        auth_manager.set_current_context(admin_context)
        
        regular_user = auth_manager.create_user("test_user", roles={Role.USER})
        _, regular_key = auth_manager.create_api_key(regular_user.user_id, "Test Key")
        
        print("🧪 Testing decorated functions...")
        
        # Test with admin key
        print(f"\n👑 Testing with admin credentials:")
        auth_manager.set_current_context(auth_manager.authenticate_api_key(admin_key))
        
        try:
            result = await protected_workflow_function("Hello from admin")
            print(f"   ✅ @require_auth: {result}")
        except Exception as e:
            print(f"   ❌ @require_auth failed: {e}")
        
        try:
            result = await admin_only_function("system restart")
            print(f"   ✅ @require_permission(ADMIN): {result}")
        except Exception as e:
            print(f"   ❌ @require_permission(ADMIN) failed: {e}")
        
        try:
            result = await operator_function("endpoint maintenance")
            print(f"   ✅ @require_role(OPERATOR): {result}")
        except Exception as e:
            print(f"   ❌ @require_role(OPERATOR) failed: {e}")
        
        # Test with regular user
        print(f"\n👤 Testing with regular user credentials:")
        auth_manager.set_current_context(auth_manager.authenticate_api_key(regular_key))
        
        try:
            result = await protected_workflow_function("Hello from user")
            print(f"   ✅ @require_auth: {result}")
        except Exception as e:
            print(f"   ❌ @require_auth failed: {e}")
        
        try:
            result = await admin_only_function("system restart")
            print(f"   ✅ @require_permission(ADMIN): {result}")
        except Exception as e:
            print(f"   ❌ @require_permission(ADMIN) failed: {e}")
        
        try:
            result = await operator_function("endpoint maintenance") 
            print(f"   ✅ @require_role(OPERATOR): {result}")
        except Exception as e:
            print(f"   ❌ @require_role(OPERATOR) failed: {e}")
        
        # Test with no authentication
        print(f"\n🚫 Testing with no authentication:")
        auth_manager.clear_current_context()
        
        try:
            result = await protected_workflow_function("Hello anonymous")
            print(f"   ✅ @require_auth: {result}")
        except Exception as e:
            print(f"   ❌ @require_auth failed: {e}")
    
    print()


async def demo_cli_workflow():
    """Demo: Typical CLI authentication workflow"""
    print("💻 CLI Authentication Workflow")
    print("=" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        print(f"📁 Using config directory: {temp_path}")
        print()
        
        # Step 1: Initialize system
        print("1️⃣  Initialize authentication system")
        auth_manager = AuthManager(config_dir=temp_path)
        initialized = auth_manager.initialize()
        
        if initialized:
            print("   ✅ System initialized")
            admin_user = auth_manager.storage.list_users()[0]
            admin_key = admin_user.get_active_api_keys()[0]
            print(f"   🔑 Admin key created: gzt_...{admin_key.key_id}")
        
        print()
        
        # Step 2: Login with API key (simulated)
        print("2️⃣  Login with API key")
        
        # Simulate getting the actual raw key (in CLI, user would have this)
        _, raw_key = admin_user.create_api_key("CLI Demo Key")
        auth_manager.storage.update_user(admin_user)
        
        try:
            context = auth_manager.authenticate_api_key(raw_key)
            print(f"   ✅ Authenticated as: {context.user.username}")
            print(f"   🎭 Roles: {', '.join(r.value for r in context.user.roles)}")
            
            # Save context (simulates CLI saving credentials)
            auth_manager.set_current_context(context)
            print("   💾 Credentials saved")
        except Exception as e:
            print(f"   ❌ Login failed: {e}")
        
        print()
        
        # Step 3: Perform authenticated operations
        print("3️⃣  Perform authenticated operations")
        
        try:
            # Check current auth status
            current = auth_manager.get_current_context()
            if current:
                print(f"   ✅ Currently authenticated as: {current.user.username}")
                
                # Create another user (admin operation)
                new_user = auth_manager.create_user(
                    "demo_user",
                    email="demo@example.com",
                    roles={Role.USER}
                )
                print(f"   ✅ Created user: {new_user.username}")
                
                # Create API key for new user
                _, user_key = auth_manager.create_api_key(
                    new_user.user_id,
                    "Demo User Key"
                )
                print(f"   🔑 Created API key: gzt_...{user_key[-8:]}")
                
                # List all users
                users = auth_manager.list_users()
                print(f"   📋 Total users: {len(users)}")
                
            else:
                print("   ❌ Not authenticated")
        
        except Exception as e:
            print(f"   ❌ Operation failed: {e}")
        
        print()
        
        # Step 4: Logout
        print("4️⃣  Logout")
        auth_manager.clear_current_context()
        
        current = auth_manager.get_current_context()
        if current is None:
            print("   ✅ Logged out successfully")
        else:
            print("   ❌ Logout failed")
    
    print()


async def demo_environment_auth():
    """Demo: Environment variable authentication"""
    print("🌍 Environment Variable Authentication")
    print("=" * 50)
    
    import os
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        auth_manager = AuthManager(config_dir=temp_path)
        
        # Setup
        auth_manager.initialize()
        admin_user = auth_manager.storage.list_users()[0]
        _, api_key = admin_user.create_api_key("Env Test Key")
        auth_manager.storage.update_user(admin_user)
        
        # Test environment variable authentication
        print("🧪 Testing GLEITZEIT_API_KEY environment variable...")
        
        # Set environment variable
        os.environ['GLEITZEIT_API_KEY'] = api_key
        
        try:
            # Create new auth manager (simulates new CLI invocation)
            new_auth_manager = AuthManager(config_dir=temp_path)
            context = new_auth_manager.authenticate_from_environment()
            
            if context:
                print(f"   ✅ Authenticated from environment: {context.user.username}")
                print(f"   🔑 Using API key: ...{context.api_key.key_id}")
            else:
                print("   ❌ Environment authentication failed")
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        finally:
            # Clean up environment
            os.environ.pop('GLEITZEIT_API_KEY', None)
        
        print("   🧹 Environment cleaned up")
    
    print()


async def main():
    """Run all authentication demos"""
    
    print("🔐 Gleitzeit CLI Authentication System Demo")
    print("=" * 60)
    print()
    
    demos = [
        demo_auth_initialization,
        demo_user_management, 
        demo_permission_checking,
        demo_decorators,
        demo_cli_workflow,
        demo_environment_auth
    ]
    
    for demo in demos:
        try:
            await demo()
        except Exception as e:
            print(f"💥 Demo {demo.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    print("🎯 CLI Authentication Features Summary:")
    print("✅ File-based credential storage (~/.gleitzeit/)")
    print("✅ API key authentication with expiration")
    print("✅ Role-based access control (USER, OPERATOR, ADMIN, etc.)")
    print("✅ Permission-based authorization")
    print("✅ Authentication decorators for functions")
    print("✅ Environment variable support (GLEITZEIT_API_KEY)")
    print("✅ CLI commands for user and key management")
    print("✅ Automatic admin user initialization")
    print("✅ Secure file permissions (600)")
    print("✅ Future-proof design for web UI integration")
    print()
    print("💡 Ready for production CLI usage and future web UI integration!")


if __name__ == "__main__":
    asyncio.run(main())