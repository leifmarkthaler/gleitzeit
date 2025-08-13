"""
CLI authentication commands

Provides command-line interface for managing users, API keys, and authentication.
"""

import argparse
import getpass
import sys
from datetime import datetime
from typing import Optional

from .auth_manager import AuthManager, get_auth_manager, initialize_auth
from .models import Role, Permission


class CLIAuthenticator:
    """CLI authentication interface"""
    
    def __init__(self, auth_manager: Optional[AuthManager] = None):
        """Initialize CLI authenticator"""
        self.auth_manager = auth_manager or get_auth_manager()
    
    def setup_auth_commands(self, parser: argparse.ArgumentParser):
        """Add auth commands to argument parser"""
        auth_subparsers = parser.add_subparsers(dest='auth_command', help='Auth commands')
        
        # Initialize command
        init_parser = auth_subparsers.add_parser('init', help='Initialize authentication system')
        
        # Login command  
        login_parser = auth_subparsers.add_parser('login', help='Login with API key')
        login_parser.add_argument('--api-key', help='API key (will prompt if not provided)')
        login_parser.add_argument('--save', action='store_true', help='Save credentials for future use')
        
        # Logout command
        logout_parser = auth_subparsers.add_parser('logout', help='Clear saved credentials')
        
        # Status command
        status_parser = auth_subparsers.add_parser('status', help='Show authentication status')
        
        # User management commands
        user_parser = auth_subparsers.add_parser('user', help='User management')
        user_subparsers = user_parser.add_subparsers(dest='user_command', help='User commands')
        
        # Create user
        create_user_parser = user_subparsers.add_parser('create', help='Create new user')
        create_user_parser.add_argument('username', help='Username')
        create_user_parser.add_argument('--email', help='Email address')
        create_user_parser.add_argument('--full-name', help='Full name')
        create_user_parser.add_argument('--role', choices=[r.value for r in Role], 
                                       action='append', help='User roles (can specify multiple)')
        
        # List users
        list_users_parser = user_subparsers.add_parser('list', help='List users')
        list_users_parser.add_argument('--format', choices=['table', 'json'], default='table',
                                      help='Output format')
        
        # Show user
        show_user_parser = user_subparsers.add_parser('show', help='Show user details')
        show_user_parser.add_argument('username', help='Username')
        
        # Delete user
        delete_user_parser = user_subparsers.add_parser('delete', help='Delete user')
        delete_user_parser.add_argument('username', help='Username')
        delete_user_parser.add_argument('--confirm', action='store_true',
                                       help='Skip confirmation prompt')
        
        # API key management commands
        key_parser = auth_subparsers.add_parser('key', help='API key management')
        key_subparsers = key_parser.add_subparsers(dest='key_command', help='Key commands')
        
        # Create API key
        create_key_parser = key_subparsers.add_parser('create', help='Create API key')
        create_key_parser.add_argument('name', help='Key name/description')
        create_key_parser.add_argument('--user', help='Username (default: current user)')
        create_key_parser.add_argument('--expires', type=int, help='Expiration in days')
        
        # List API keys
        list_keys_parser = key_subparsers.add_parser('list', help='List API keys')
        list_keys_parser.add_argument('--user', help='Username (default: current user)')
        list_keys_parser.add_argument('--format', choices=['table', 'json'], default='table',
                                     help='Output format')
        
        # Revoke API key
        revoke_key_parser = key_subparsers.add_parser('revoke', help='Revoke API key')
        revoke_key_parser.add_argument('key_id', help='Key ID to revoke')
        revoke_key_parser.add_argument('--user', help='Username (default: current user)')
        
        # System commands
        system_parser = auth_subparsers.add_parser('system', help='System management')
        system_subparsers = system_parser.add_subparsers(dest='system_command', help='System commands')
        
        # Cleanup
        cleanup_parser = system_subparsers.add_parser('cleanup', help='Clean up expired keys')
        
        # Stats
        stats_parser = system_subparsers.add_parser('stats', help='Show system statistics')
    
    async def handle_auth_command(self, args):
        """Handle auth command execution"""
        if not hasattr(args, 'auth_command') or not args.auth_command:
            print("Use 'gleitzeit auth --help' for usage information")
            return
        
        try:
            if args.auth_command == 'init':
                await self.handle_init()
            elif args.auth_command == 'login':
                await self.handle_login(args)
            elif args.auth_command == 'logout':
                await self.handle_logout()
            elif args.auth_command == 'status':
                await self.handle_status()
            elif args.auth_command == 'user':
                await self.handle_user_command(args)
            elif args.auth_command == 'key':
                await self.handle_key_command(args)
            elif args.auth_command == 'system':
                await self.handle_system_command(args)
            else:
                print(f"Unknown auth command: {args.auth_command}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        
        return True
    
    async def handle_init(self):
        """Initialize authentication system"""
        print("🔧 Initializing Gleitzeit authentication...")
        
        initialized = initialize_auth()
        if initialized:
            print("✅ Authentication system initialized")
            print("💡 Use 'gleitzeit auth login' to authenticate")
        else:
            print("ℹ️  Authentication system already initialized")
    
    async def handle_login(self, args):
        """Handle login command"""
        api_key = args.api_key
        
        if not api_key:
            api_key = getpass.getpass("🔑 Enter API key: ")
        
        if not api_key:
            print("❌ API key required")
            return
        
        try:
            context = self.auth_manager.authenticate_api_key(api_key)
            print(f"✅ Logged in as: {context.user.username}")
            print(f"📋 Roles: {', '.join(role.value for role in context.user.roles)}")
            
            if args.save:
                self.auth_manager.storage.set_current_context(api_key)
                print("💾 Credentials saved for future use")
        
        except Exception as e:
            print(f"❌ Login failed: {e}")
    
    async def handle_logout(self):
        """Handle logout command"""
        self.auth_manager.clear_current_context()
        print("✅ Logged out")
    
    async def handle_status(self):
        """Show authentication status"""
        context = self.auth_manager.get_current_context()
        
        if context:
            print(f"✅ Authenticated as: {context.user.username}")
            print(f"📋 User ID: {context.user.user_id}")
            print(f"📧 Email: {context.user.email or 'Not set'}")
            print(f"👤 Full Name: {context.user.full_name or 'Not set'}")
            print(f"🎭 Roles: {', '.join(role.value for role in context.user.roles)}")
            
            if context.api_key:
                print(f"🔑 API Key: ...{context.api_key.key_id}")
                print(f"📅 Key Created: {context.api_key.created_at.strftime('%Y-%m-%d %H:%M')}")
                if context.api_key.expires_at:
                    print(f"⏰ Key Expires: {context.api_key.expires_at.strftime('%Y-%m-%d %H:%M')}")
                else:
                    print("⏰ Key Expires: Never")
        else:
            print("❌ Not authenticated")
            print("💡 Use 'gleitzeit auth login' to authenticate")
    
    async def handle_user_command(self, args):
        """Handle user management commands"""
        if not hasattr(args, 'user_command') or not args.user_command:
            print("Use 'gleitzeit auth user --help' for usage")
            return
        
        if args.user_command == 'create':
            await self.create_user(args)
        elif args.user_command == 'list':
            await self.list_users(args)
        elif args.user_command == 'show':
            await self.show_user(args)
        elif args.user_command == 'delete':
            await self.delete_user(args)
    
    async def create_user(self, args):
        """Create new user"""
        roles = set()
        if args.role:
            roles = {Role(r) for r in args.role}
        else:
            roles = {Role.USER}  # Default role
        
        try:
            user = self.auth_manager.create_user(
                username=args.username,
                email=args.email,
                full_name=args.full_name,
                roles=roles
            )
            
            print(f"✅ Created user: {user.username}")
            print(f"📋 User ID: {user.user_id}")
            print(f"🎭 Roles: {', '.join(role.value for role in user.roles)}")
            print("💡 Use 'gleitzeit auth key create' to create an API key for this user")
        
        except Exception as e:
            print(f"❌ Failed to create user: {e}")
    
    async def list_users(self, args):
        """List users"""
        try:
            users = self.auth_manager.list_users()
            
            if args.format == 'json':
                import json
                user_data = self.auth_manager.export_users()
                print(json.dumps(user_data, indent=2))
            else:
                # Table format
                if not users:
                    print("No users found")
                    return
                
                print(f"{'Username':<20} {'Roles':<20} {'Email':<30} {'Status':<10}")
                print("-" * 80)
                
                for user in users:
                    roles = ', '.join(role.value for role in user.roles)
                    email = user.email or ''
                    status = 'Active' if user.is_active else 'Inactive'
                    
                    print(f"{user.username:<20} {roles:<20} {email:<30} {status:<10}")
        
        except Exception as e:
            print(f"❌ Failed to list users: {e}")
    
    async def show_user(self, args):
        """Show user details"""
        try:
            user = self.auth_manager.get_user_by_username(args.username)
            if not user:
                print(f"❌ User not found: {args.username}")
                return
            
            print(f"👤 User: {user.username}")
            print(f"📋 User ID: {user.user_id}")
            print(f"📧 Email: {user.email or 'Not set'}")
            print(f"👤 Full Name: {user.full_name or 'Not set'}")
            print(f"🎭 Roles: {', '.join(role.value for role in user.roles)}")
            print(f"📅 Created: {user.created_at.strftime('%Y-%m-%d %H:%M')}")
            if user.last_login_at:
                print(f"🕐 Last Login: {user.last_login_at.strftime('%Y-%m-%d %H:%M')}")
            print(f"✅ Status: {'Active' if user.is_active else 'Inactive'}")
            
            # Show API keys
            active_keys = user.get_active_api_keys()
            print(f"🔑 Active API Keys: {len(active_keys)}")
            for key in active_keys:
                print(f"   • {key.name} (...{key.key_id})")
        
        except Exception as e:
            print(f"❌ Failed to show user: {e}")
    
    async def delete_user(self, args):
        """Delete user"""
        try:
            user = self.auth_manager.get_user_by_username(args.username)
            if not user:
                print(f"❌ User not found: {args.username}")
                return
            
            if not args.confirm:
                confirm = input(f"⚠️  Are you sure you want to delete user '{args.username}'? (y/N): ")
                if confirm.lower() != 'y':
                    print("Cancelled")
                    return
            
            success = self.auth_manager.delete_user(user.user_id)
            if success:
                print(f"✅ Deleted user: {args.username}")
            else:
                print(f"❌ Failed to delete user: {args.username}")
        
        except Exception as e:
            print(f"❌ Failed to delete user: {e}")
    
    async def handle_key_command(self, args):
        """Handle API key management commands"""
        if not hasattr(args, 'key_command') or not args.key_command:
            print("Use 'gleitzeit auth key --help' for usage")
            return
        
        if args.key_command == 'create':
            await self.create_api_key(args)
        elif args.key_command == 'list':
            await self.list_api_keys(args)
        elif args.key_command == 'revoke':
            await self.revoke_api_key(args)
    
    async def create_api_key(self, args):
        """Create API key"""
        try:
            # Determine target user
            if args.user:
                user = self.auth_manager.get_user_by_username(args.user)
                if not user:
                    print(f"❌ User not found: {args.user}")
                    return
                user_id = user.user_id
            else:
                # Use current user
                context = self.auth_manager.require_authentication()
                user_id = context.user.user_id
            
            api_key, raw_key = self.auth_manager.create_api_key(
                user_id=user_id,
                name=args.name,
                expires_in_days=args.expires
            )
            
            print(f"✅ Created API key: {args.name}")
            print(f"🔑 Key: {raw_key}")
            print(f"📋 Key ID: {api_key.key_id}")
            if api_key.expires_at:
                print(f"⏰ Expires: {api_key.expires_at.strftime('%Y-%m-%d')}")
            else:
                print("⏰ Expires: Never")
            print("⚠️  Store this key securely - it won't be shown again!")
        
        except Exception as e:
            print(f"❌ Failed to create API key: {e}")
    
    async def list_api_keys(self, args):
        """List API keys"""
        try:
            # Determine target user
            if args.user:
                user = self.auth_manager.get_user_by_username(args.user)
                if not user:
                    print(f"❌ User not found: {args.user}")
                    return
                user_id = user.user_id
                username = user.username
            else:
                # Use current user
                context = self.auth_manager.require_authentication()
                user_id = context.user.user_id
                username = context.user.username
            
            keys = self.auth_manager.list_user_api_keys(user_id)
            
            if args.format == 'json':
                import json
                key_data = [
                    {
                        'key_id': key.key_id,
                        'name': key.name,
                        'created_at': key.created_at.isoformat(),
                        'expires_at': key.expires_at.isoformat() if key.expires_at else None,
                        'last_used_at': key.last_used_at.isoformat() if key.last_used_at else None,
                        'is_active': key.is_active
                    }
                    for key in keys
                ]
                print(json.dumps(key_data, indent=2))
            else:
                # Table format
                if not keys:
                    print(f"No API keys found for user: {username}")
                    return
                
                print(f"API keys for user: {username}")
                print(f"{'Name':<20} {'Key ID':<10} {'Created':<12} {'Expires':<12} {'Last Used':<12}")
                print("-" * 80)
                
                for key in keys:
                    created = key.created_at.strftime('%Y-%m-%d')
                    expires = key.expires_at.strftime('%Y-%m-%d') if key.expires_at else 'Never'
                    last_used = key.last_used_at.strftime('%Y-%m-%d') if key.last_used_at else 'Never'
                    
                    print(f"{key.name:<20} {key.key_id:<10} {created:<12} {expires:<12} {last_used:<12}")
        
        except Exception as e:
            print(f"❌ Failed to list API keys: {e}")
    
    async def revoke_api_key(self, args):
        """Revoke API key"""
        try:
            # Determine target user
            if args.user:
                user = self.auth_manager.get_user_by_username(args.user)
                if not user:
                    print(f"❌ User not found: {args.user}")
                    return
                user_id = user.user_id
            else:
                # Use current user
                context = self.auth_manager.require_authentication()
                user_id = context.user.user_id
            
            success = self.auth_manager.revoke_api_key(user_id, args.key_id)
            if success:
                print(f"✅ Revoked API key: {args.key_id}")
            else:
                print(f"❌ API key not found: {args.key_id}")
        
        except Exception as e:
            print(f"❌ Failed to revoke API key: {e}")
    
    async def handle_system_command(self, args):
        """Handle system management commands"""
        if not hasattr(args, 'system_command') or not args.system_command:
            print("Use 'gleitzeit auth system --help' for usage")
            return
        
        if args.system_command == 'cleanup':
            await self.cleanup_expired_keys()
        elif args.system_command == 'stats':
            await self.show_stats()
    
    async def cleanup_expired_keys(self):
        """Clean up expired API keys"""
        try:
            removed_count = self.auth_manager.cleanup_expired_keys()
            print(f"✅ Removed {removed_count} expired API keys")
        except Exception as e:
            print(f"❌ Failed to cleanup keys: {e}")
    
    async def show_stats(self):
        """Show system statistics"""
        try:
            stats = self.auth_manager.get_stats()
            
            print("📊 Authentication System Statistics")
            print("=" * 40)
            print(f"👥 Total Users: {stats['total_users']}")
            print(f"✅ Active Users: {stats['active_users']}")
            print(f"🔑 Total API Keys: {stats['total_api_keys']}")
            print(f"✅ Active API Keys: {stats['active_api_keys']}")
            print(f"⏰ Expired API Keys: {stats['expired_api_keys']}")
            print(f"📁 Config Directory: {stats['config_dir']}")
        
        except Exception as e:
            print(f"❌ Failed to get stats: {e}")


# Convenience function for CLI usage
def setup_auth_cli(parser: argparse.ArgumentParser):
    """Set up authentication CLI commands"""
    cli = CLIAuthenticator()
    cli.setup_auth_commands(parser)