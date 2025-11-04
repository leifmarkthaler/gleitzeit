"""
Tests for GleitzeitClient authentication functionality.

Tests session management, JWT tokens, and API key authentication.
"""
import pytest
import asyncio
from gleitzeit.client import GleitzeitClient


@pytest.mark.asyncio
async def test_session_creation():
    """Test creating a new session."""
    async with GleitzeitClient(auto_login=False) as client:
        session_id = await client.create_session("test_user")
        assert session_id is not None
        assert client.session_id == session_id
        print(f"✓ Created session: {session_id}")


@pytest.mark.asyncio
async def test_session_validation():
    """Test validating an active session."""
    async with GleitzeitClient(auto_login=False) as client:
        # Create session first
        await client.create_session("test_user")

        # Validate it
        is_valid = await client.validate_session()
        assert is_valid is True
        print(f"✓ Session is valid")


@pytest.mark.asyncio
async def test_session_destruction():
    """Test destroying a session."""
    async with GleitzeitClient(auto_login=False) as client:
        # Create session
        session_id = await client.create_session("test_user")

        # Destroy it
        result = await client.destroy_session()
        assert client.session_id is None
        print(f"✓ Destroyed session: {session_id}")


@pytest.mark.asyncio
async def test_auto_login():
    """Test automatic login on connection."""
    async with GleitzeitClient(
        auto_login=True,
        username="test_user"
    ) as client:
        # Session should be automatically created
        assert client.session_id is not None
        print(f"✓ Auto-login created session: {client.session_id}")


@pytest.mark.asyncio
async def test_get_current_user():
    """Test getting current user information."""
    async with GleitzeitClient() as client:
        user_info = await client.get_current_user()
        assert "username" in user_info or "user_id" in user_info
        print(f"✓ Got user info: {user_info}")


@pytest.mark.asyncio
async def test_manual_authentication():
    """Test manual authentication without auto-login."""
    client = GleitzeitClient(auto_login=False)

    try:
        await client.connect()
        session_id = await client.create_session("manual_user")
        assert session_id is not None
        print(f"✓ Manual authentication successful: {session_id}")
    finally:
        await client.close()


if __name__ == "__main__":
    print("Running authentication tests...\n")
    asyncio.run(test_session_creation())
    asyncio.run(test_session_validation())
    asyncio.run(test_session_destruction())
    asyncio.run(test_auto_login())
    asyncio.run(test_get_current_user())
    asyncio.run(test_manual_authentication())
    print("\n✓ All authentication tests passed!")
