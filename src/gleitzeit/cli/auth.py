#!/usr/bin/env python3
"""
Authentication CLI commands for Gleitzeit
"""

import click
import asyncio
import getpass
from typing import Optional, Dict, Any
from tabulate import tabulate
from datetime import datetime

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.errors import SystemError, ErrorCode
from .error_handler import handle_cli_error, handle_auth_cli_error


@click.group()
def auth():
    """Authentication and user management commands"""
    pass


@auth.command()
@click.option('--username', '-u', prompt=True, help='Username')
@click.option('--password', '-p', prompt=True, hide_input=True, help='Password')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def login(username: str, password: str, host: str, port: int):
    """Login to Gleitzeit"""
    async def _login():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            result = await client.login(username, password)
            if result.get('success'):
                user = result.get('user', {})
                click.echo(f"✅ Logged in as {user.get('username', username)}")
                click.echo(f"   Role: {user.get('role', 'user')}")
                if result.get('token'):
                    click.echo(f"   Token: {result['token'][:20]}...")
            else:
                click.echo(f"❌ Login failed: {result.get('message', 'Invalid credentials')}", err=True)
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_login())


@auth.command()
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def logout(host: str, port: int):
    """Logout from Gleitzeit"""
    async def _logout():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            result = await client.logout()
            click.echo("✅ Logged out successfully")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_logout())


@auth.command()
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def whoami(host: str, port: int):
    """Show current user information"""
    async def _whoami():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            user = await client.get_current_user()
            if user:
                click.echo("Current User:")
                click.echo(f"  ID: {user.get('id', 'N/A')}")
                click.echo(f"  Username: {user.get('username', 'N/A')}")
                click.echo(f"  Email: {user.get('email', 'N/A')}")
                click.echo(f"  Role: {user.get('role', 'N/A')}")
                click.echo(f"  Active: {user.get('is_active', False)}")
                click.echo(f"  Verified: {user.get('email_verified', False)}")
            else:
                click.echo("Not authenticated")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_whoami())


# User management commands

@auth.command()
@click.option('--username', '-u', prompt=True, help='Username')
@click.option('--email', '-e', prompt=True, help='Email address')
@click.option('--password', '-p', prompt=True, hide_input=True, confirmation_prompt=True, help='Password')
@click.option('--role', default='user', type=click.Choice(['user', 'admin']), help='User role')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def create_user(username: str, email: str, password: str, role: str, host: str, port: int):
    """Create a new user"""
    async def _create():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            user = await client.create_user(username, email, password, role)
            click.echo(f"✅ User created successfully")
            click.echo(f"   ID: {user.get('id')}")
            click.echo(f"   Username: {user.get('username')}")
            click.echo(f"   Email: {user.get('email')}")
            click.echo(f"   Role: {user.get('role')}")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_create())


@auth.command()
@click.option('--limit', default=20, help='Number of users to show')
@click.option('--offset', default=0, help='Offset for pagination')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def list_users(limit: int, offset: int, host: str, port: int):
    """List all users"""
    async def _list():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            users = await client.list_users(limit, offset)
            if users:
                headers = ['ID', 'Username', 'Email', 'Role', 'Active', 'Verified']
                rows = []
                for user in users:
                    rows.append([
                        user.get('id', '')[:8] + '...' if user.get('id') else 'N/A',
                        user.get('username', 'N/A'),
                        user.get('email', 'N/A'),
                        user.get('role', 'N/A'),
                        '✅' if user.get('is_active') else '❌',
                        '✅' if user.get('email_verified') else '❌'
                    ])
                click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
            else:
                click.echo("No users found")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_list())


@auth.command()
@click.argument('user_id')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def get_user(user_id: str, host: str, port: int):
    """Get user details by ID"""
    async def _get():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            user = await client.get_user(user_id)
            if user:
                click.echo("User Details:")
                click.echo(f"  ID: {user.get('id')}")
                click.echo(f"  Username: {user.get('username')}")
                click.echo(f"  Email: {user.get('email')}")
                click.echo(f"  Role: {user.get('role')}")
                click.echo(f"  Active: {user.get('is_active')}")
                click.echo(f"  Email Verified: {user.get('email_verified')}")
                click.echo(f"  Created: {user.get('created_at')}")
                click.echo(f"  Last Login: {user.get('last_login')}")
                if user.get('metadata'):
                    click.echo(f"  Metadata: {user['metadata']}")
            else:
                click.echo(f"User {user_id} not found")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_get())


@auth.command()
@click.argument('user_id')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def activate_user(user_id: str, host: str, port: int):
    """Activate a user account"""
    async def _activate():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            user = await client.activate_user(user_id)
            click.echo(f"✅ User {user.get('username')} activated")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_activate())


@auth.command()
@click.argument('user_id')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def deactivate_user(user_id: str, host: str, port: int):
    """Deactivate a user account"""
    async def _deactivate():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            user = await client.deactivate_user(user_id)
            click.echo(f"✅ User {user.get('username')} deactivated")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_deactivate())


@auth.command()
@click.argument('user_id')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def delete_user(user_id: str, confirm: bool, host: str, port: int):
    """Delete a user (requires confirmation)"""
    if not confirm:
        if not click.confirm(f"Are you sure you want to delete user {user_id}?"):
            click.echo("Cancelled")
            return
    
    async def _delete():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            success = await client.delete_user(user_id)
            if success:
                click.echo(f"✅ User {user_id} deleted")
            else:
                click.echo(f"❌ Failed to delete user {user_id}")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_delete())


@auth.command()
@click.argument('query')
@click.option('--field', type=click.Choice(['username', 'email', 'role']), default='username', help='Field to search')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def search_users(query: str, field: str, host: str, port: int):
    """Search for users"""
    async def _search():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            users = await client.search_users(query, field)
            if users:
                click.echo(f"Found {len(users)} user(s) matching '{query}' in {field}:")
                headers = ['ID', 'Username', 'Email', 'Role', 'Active']
                rows = []
                for user in users:
                    rows.append([
                        user.get('id', '')[:8] + '...' if user.get('id') else 'N/A',
                        user.get('username', 'N/A'),
                        user.get('email', 'N/A'),
                        user.get('role', 'N/A'),
                        '✅' if user.get('is_active') else '❌'
                    ])
                click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
            else:
                click.echo(f"No users found matching '{query}' in {field}")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_search())


# Password management commands

@auth.command()
@click.option('--user-id', help='User ID (admin only)')
@click.option('--old-password', prompt=True, hide_input=True, help='Current password')
@click.option('--new-password', prompt=True, hide_input=True, confirmation_prompt=True, help='New password')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def change_password(user_id: Optional[str], old_password: str, new_password: str, host: str, port: int):
    """Change password"""
    async def _change():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            # If no user_id, get current user
            if not user_id:
                current = await client.get_current_user()
                user_id = current.get('id')
                if not user_id:
                    click.echo("❌ Not authenticated", err=True)
                    return
            
            success = await client.change_password(user_id, old_password, new_password)
            if success:
                click.echo("✅ Password changed successfully")
            else:
                click.echo("❌ Failed to change password")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_change())


@auth.command()
@click.option('--email', '-e', prompt=True, help='Email address')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def reset_password(email: str, host: str, port: int):
    """Request password reset"""
    async def _reset():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            result = await client.request_password_reset(email)
            click.echo(f"✅ Password reset requested")
            click.echo(f"   Token: {result.get('token', 'Check email')}")
            click.echo("   Check your email for reset instructions")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_reset())


# Session management commands

@auth.command()
@click.option('--user-id', help='User ID (admin only, default: current user)')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def sessions(user_id: Optional[str], host: str, port: int):
    """List active sessions"""
    async def _sessions():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            sessions = await client.get_sessions(user_id)
            if sessions:
                click.echo(f"Active Sessions ({len(sessions)}):")
                headers = ['Session ID', 'Created', 'Last Activity', 'IP', 'User Agent']
                rows = []
                for session in sessions:
                    rows.append([
                        session.get('id', '')[:12] + '...' if session.get('id') else 'N/A',
                        session.get('created_at', 'N/A'),
                        session.get('last_activity', 'N/A'),
                        session.get('ip_address', 'N/A'),
                        (session.get('user_agent', 'N/A')[:30] + '...') if len(session.get('user_agent', '')) > 30 else session.get('user_agent', 'N/A')
                    ])
                click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
            else:
                click.echo("No active sessions")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_sessions())


@auth.command()
@click.argument('session_id')
@click.option('--user-id', help='User ID (admin only)')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def revoke_session(session_id: str, user_id: Optional[str], host: str, port: int):
    """Revoke a specific session"""
    async def _revoke():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            success = await client.revoke_session(session_id, user_id)
            if success:
                click.echo(f"✅ Session {session_id} revoked")
            else:
                click.echo(f"❌ Failed to revoke session")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_revoke())


@auth.command()
@click.option('--user-id', help='User ID (admin only, default: current user)')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompt')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def revoke_all(user_id: Optional[str], confirm: bool, host: str, port: int):
    """Revoke all sessions (logout everywhere)"""
    if not confirm:
        if not click.confirm("Are you sure you want to revoke all sessions?"):
            click.echo("Cancelled")
            return
    
    async def _revoke_all():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            count = await client.revoke_all_sessions(user_id)
            click.echo(f"✅ Revoked {count} session(s)")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_revoke_all())


@auth.command()
@click.option('--limit', default=20, help='Number of entries to show')
@click.option('--user-id', help='User ID (admin only, default: current user)')
@click.option('--host', default='localhost', help='API host')
@click.option('--port', default=8000, help='API port')
def history(limit: int, user_id: Optional[str], host: str, port: int):
    """Show authentication history"""
    async def _history():
        client = GleitzeitClient(mode=ClientMode.API, api_host=host, api_port=port)
        try:
            history = await client.get_auth_history(limit, user_id)
            if history:
                click.echo(f"Authentication History (last {limit} events):")
                headers = ['Time', 'Event', 'IP', 'Success', 'Details']
                rows = []
                for event in history:
                    rows.append([
                        event.get('timestamp', 'N/A'),
                        event.get('event_type', 'N/A'),
                        event.get('ip_address', 'N/A'),
                        '✅' if event.get('success') else '❌',
                        event.get('details', '')[:40]
                    ])
                click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
            else:
                click.echo("No authentication history")
        except Exception as e:
            handle_auth_cli_error(e)
        finally:
            await client.shutdown()
    
    asyncio.run(_history())


if __name__ == '__main__':
    auth()