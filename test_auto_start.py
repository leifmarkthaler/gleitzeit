#!/usr/bin/env python3
"""
Test client auto-start functionality.

This test verifies that the client can automatically start
the Gleitzeit server when it's not running.
"""

import asyncio
import aiohttp
import sys
import signal
import subprocess
from gleitzeit.client import GleitzeitClient


async def kill_existing_servers():
    """Kill any existing Gleitzeit servers on test ports."""
    for port in [8100, 8101]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{port}/health", timeout=aiohttp.ClientTimeout(total=1)) as resp:
                    if resp.status == 200:
                        # Server is running, find and kill it
                        result = subprocess.run(['lsof', '-t', f'-i:{port}'], capture_output=True, text=True)
                        if result.stdout:
                            pids = result.stdout.strip().split('\n')
                            for pid in pids:
                                try:
                                    subprocess.run(['kill', '-9', pid])
                                    print(f"Killed process {pid} on port {port}")
                                except:
                                    pass
        except:
            pass  # Server not running

    # Give time for processes to die
    await asyncio.sleep(2)


async def test_auto_start():
    """Test that client auto-starts server when not running."""

    # Test port that shouldn't have a server running
    test_port = 8100

    print(f"Testing auto-start on port {test_port}...")

    # Ensure no server is running on test port
    await kill_existing_servers()

    # Verify server is NOT running
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{test_port}/health",
                                 timeout=aiohttp.ClientTimeout(total=1)) as resp:
                if resp.status == 200:
                    print(f"❌ Server already running on port {test_port}, test invalid")
                    return False
    except:
        print(f"✅ Confirmed no server on port {test_port}")

    # Create client with auto_start enabled (default)
    print(f"Creating client with auto_start=True...")
    client = GleitzeitClient(
        api_host="localhost",
        api_port=test_port,
        auto_start_server=True  # This is default, but being explicit
    )

    # Initialize should trigger auto-start
    print("Initializing client (should auto-start server)...")
    await client.initialize()

    # Verify server is now running
    print("Verifying server started...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{test_port}/health",
                                 timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    print(f"✅ Server auto-started successfully on port {test_port}")

                    # Test that client can actually use the server
                    result = await client.submit_task({
                        "id": "test_task",
                        "protocol": "python/v1",
                        "method": "inline",
                        "params": {
                            "code": "return 'Hello from auto-started server'"
                        }
                    })

                    print(f"✅ Successfully submitted task to auto-started server")
                    return True
                else:
                    print(f"❌ Server responded but with status {resp.status}")
                    return False
    except Exception as e:
        print(f"❌ Failed to connect to auto-started server: {e}")
        return False
    finally:
        # Clean up
        await client.shutdown()
        await kill_existing_servers()


async def test_no_auto_start():
    """Test that client respects auto_start=False."""

    test_port = 8101

    print(f"\nTesting with auto_start=False on port {test_port}...")

    # Ensure no server is running
    await kill_existing_servers()

    # Create client with auto_start disabled
    print(f"Creating client with auto_start=False...")
    client = GleitzeitClient(
        api_host="localhost",
        api_port=test_port,
        auto_start_server=False  # Explicitly disable auto-start
    )

    # Initialize should NOT start server
    print("Initializing client (should NOT auto-start server)...")
    try:
        await client.initialize()

        # Try to use the client - should fail since no server
        result = await client.submit_task({
            "id": "test_task",
            "protocol": "python/v1",
            "method": "inline",
            "params": {
                "code": "return 'test'"
            }
        })

        print("❌ Client operation succeeded when it should have failed (no server)")
        return False
    except Exception as e:
        print(f"✅ Client correctly failed without server: {type(e).__name__}")
        return True
    finally:
        await client.shutdown()


async def main():
    """Run all auto-start tests."""
    print("=" * 60)
    print("TESTING CLIENT AUTO-START FUNCTIONALITY")
    print("=" * 60)

    # Test 1: Auto-start enabled
    test1 = await test_auto_start()

    # Test 2: Auto-start disabled
    test2 = await test_no_auto_start()

    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print(f"  Auto-start enabled:  {'✅ PASSED' if test1 else '❌ FAILED'}")
    print(f"  Auto-start disabled: {'✅ PASSED' if test2 else '❌ FAILED'}")

    if test1 and test2:
        print("\n✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())