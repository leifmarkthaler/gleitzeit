#!/usr/bin/env python3
"""
Error handling utilities for Gleitzeit CLI.

Provides user-friendly error messages for common errors.
"""

import click
from gleitzeit.core.errors import (
    SystemError, 
    ErrorCode, 
    GleitzeitError,
    AuthenticationError,
    AuthorizationError
)


def handle_cli_error(error: Exception) -> None:
    """
    Handle an error in the CLI with appropriate user-friendly message.
    
    Args:
        error: The exception to handle
    """
    # Handle specific error types first
    if isinstance(error, AuthorizationError):
        click.echo("❌ Authorization failed: You don't have permission to perform this action", err=True)
        if str(error):
            click.echo(f"   Details: {error}", err=True)
    
    elif isinstance(error, AuthenticationError):
        click.echo("❌ Authentication failed: Please login or check your credentials", err=True)
        if str(error):
            click.echo(f"   Details: {error}", err=True)
    
    elif isinstance(error, SystemError) and error.code == ErrorCode.RESOURCE_NOT_FOUND:
        resource_type = getattr(error, 'resource_type', 'Resource')
        resource_id = getattr(error, 'resource_id', 'unknown')
        click.echo(f"❌ {resource_type.capitalize()} not found: {resource_id}", err=True)
        if error.message:
            click.echo(f"   Details: {error.message}", err=True)
    
    elif isinstance(error, SystemError) and error.code == ErrorCode.RATE_LIMIT_EXCEEDED:
        click.echo("❌ Rate limit exceeded: Please slow down your requests", err=True)
        if str(error):
            click.echo(f"   Details: {error}", err=True)
    
    elif isinstance(error, SystemError):
        # Authentication errors
        if error.code == ErrorCode.AUTHENTICATION_FAILED:
            click.echo("❌ Authentication failed: Invalid credentials", err=True)
        elif error.code == ErrorCode.AUTHORIZATION_FAILED:
            click.echo("❌ Authorization failed: Insufficient permissions", err=True)
        elif error.code == ErrorCode.ACCOUNT_LOCKED:
            click.echo("❌ Account is locked due to too many failed attempts", err=True)
            if error.data and "retry_after" in error.data:
                click.echo(f"   Please try again after {error.data['retry_after']} seconds", err=True)
        elif error.code == ErrorCode.EMAIL_NOT_VERIFIED:
            click.echo("❌ Email verification required", err=True)
            click.echo("   Please check your email for verification link", err=True)
        
        # Resource errors
        elif error.code == ErrorCode.NOT_FOUND:
            click.echo(f"❌ Not found: {error.message}", err=True)
        elif error.code == ErrorCode.ALREADY_EXISTS:
            click.echo(f"❌ Already exists: {error.message}", err=True)
        elif error.code == ErrorCode.RATE_LIMIT_EXCEEDED:
            click.echo("❌ Rate limit exceeded. Please slow down.", err=True)
        
        # System errors
        elif error.code == ErrorCode.SYSTEM_NOT_INITIALIZED:
            click.echo("❌ System not initialized. Please ensure the server is running.", err=True)
        elif error.code == ErrorCode.METHOD_NOT_SUPPORTED:
            click.echo(f"❌ Operation not supported: {error.message}", err=True)
        
        # Validation errors
        elif error.code == ErrorCode.INVALID_PARAMS:
            click.echo(f"❌ Invalid parameters: {error.message}", err=True)
        
        # Generic error with message
        else:
            click.echo(f"❌ Error: {error.message}", err=True)
            if error.data:
                for key, value in error.data.items():
                    click.echo(f"   {key}: {value}", err=True)
    
    elif isinstance(error, GleitzeitError):
        # Other Gleitzeit errors
        click.echo(f"❌ {error.code.name}: {error.message}", err=True)
    
    else:
        # Unknown errors
        click.echo(f"❌ Unexpected error: {error}", err=True)
        

def handle_auth_cli_error(error: Exception) -> None:
    """
    Special handling for authentication-related CLI errors.
    
    Args:
        error: The exception to handle
    """
    if isinstance(error, SystemError):
        if error.code == ErrorCode.AUTHENTICATION_FAILED:
            click.echo("❌ Login failed: Invalid username or password", err=True)
            click.echo("   Please check your credentials and try again", err=True)
        elif error.code == ErrorCode.ACCOUNT_LOCKED:
            click.echo("❌ Account locked: Too many failed login attempts", err=True)
            click.echo("   Please wait a few minutes before trying again", err=True)
        elif error.code == ErrorCode.EMAIL_NOT_VERIFIED:
            click.echo("❌ Email not verified", err=True)
            click.echo("   Please check your email and click the verification link", err=True)
        elif error.code == ErrorCode.AUTHORIZATION_FAILED:
            if "deactivated" in error.message.lower():
                click.echo("❌ Account deactivated", err=True)
                click.echo("   Please contact an administrator to reactivate your account", err=True)
            else:
                click.echo("❌ Access denied: You don't have permission for this operation", err=True)
        else:
            handle_cli_error(error)
    else:
        handle_cli_error(error)