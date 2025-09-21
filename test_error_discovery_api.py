#!/usr/bin/env python3
"""
Test error discovery functionality via Client and API
"""

import asyncio
import json
from gleitzeit.client import GleitzeitClient


async def test_client_methods():
    """Test error discovery through the client."""
    print("=" * 60)
    print("TESTING ERROR DISCOVERY CLIENT METHODS")
    print("=" * 60)

    # Initialize client
    client = GleitzeitClient(base_url="http://localhost:8000")

    try:
        # 1. Get provider errors
        print("\n1. Testing get_provider_errors('python-executor')...")
        try:
            errors = await client.get_provider_errors("python-executor")
            print(f"   Found {len(errors)} errors for python-executor")
            for error in errors[:3]:  # Show first 3
                print(f"   - {error['name']}: {error.get('error_code_name', 'N/A')}")
        except Exception as e:
            print(f"   Error: {e}")

        # 2. Get protocol errors
        print("\n2. Testing get_protocol_errors('python/v1')...")
        try:
            errors = await client.get_protocol_errors("python/v1")
            print(f"   Found {len(errors)} errors for python/v1 protocol")
            for error in errors[:3]:
                print(f"   - {error['name']}: {error.get('description', '')[:50]}")
        except Exception as e:
            print(f"   Error: {e}")

        # 3. Get error hierarchy
        print("\n3. Testing get_error_hierarchy()...")
        try:
            hierarchy = await client.get_error_hierarchy()
            print(f"   Root class: {hierarchy.get('class', 'Unknown')}")
            if 'subclasses' in hierarchy:
                print(f"   Found {len(hierarchy['subclasses'])} top-level error categories")
                for name in list(hierarchy['subclasses'].keys())[:5]:
                    print(f"   - {name}")
        except Exception as e:
            print(f"   Error: {e}")

        # 4. Check error retryability
        print("\n4. Testing check_error_retryability()...")
        try:
            # Check a timeout error (should be retryable)
            is_retryable = await client.check_error_retryability(-30006)  # PROVIDER_TIMEOUT
            print(f"   PROVIDER_TIMEOUT (-30006) is retryable: {is_retryable}")

            # Check an auth error (should not be retryable)
            is_retryable = await client.check_error_retryability(-25005)  # AUTHENTICATION_FAILED
            print(f"   AUTHENTICATION_FAILED (-25005) is retryable: {is_retryable}")
        except Exception as e:
            print(f"   Error: {e}")

        # 5. Get error report
        print("\n5. Testing get_error_report()...")
        try:
            report = await client.get_error_report(provider_id="python-executor")
            lines = report.split('\n')[:10]  # Show first 10 lines
            for line in lines:
                print(f"   {line}")
            print("   ...")
        except Exception as e:
            print(f"   Error: {e}")

    finally:
        await client.close()


async def test_api_endpoints():
    """Test error discovery through direct API calls."""
    print("\n" + "=" * 60)
    print("TESTING ERROR DISCOVERY API ENDPOINTS")
    print("=" * 60)

    import aiohttp

    async with aiohttp.ClientSession() as session:
        base_url = "http://localhost:8000"

        # 1. Test provider errors endpoint
        print("\n1. GET /errors/provider/python-executor")
        try:
            async with session.get(f"{base_url}/errors/provider/python-executor") as resp:
                if resp.status == 200:
                    errors = await resp.json()
                    print(f"   Status: {resp.status}")
                    print(f"   Found {len(errors)} errors")
                else:
                    print(f"   Status: {resp.status}")
                    print(f"   Error: {await resp.text()}")
        except Exception as e:
            print(f"   Request failed: {e}")

        # 2. Test protocol errors endpoint
        print("\n2. GET /errors/protocol/python/v1")
        try:
            async with session.get(f"{base_url}/errors/protocol/python/v1") as resp:
                if resp.status == 200:
                    errors = await resp.json()
                    print(f"   Status: {resp.status}")
                    print(f"   Found {len(errors)} errors")
                else:
                    print(f"   Status: {resp.status}")
                    print(f"   Error: {await resp.text()}")
        except Exception as e:
            print(f"   Request failed: {e}")

        # 3. Test hierarchy endpoint
        print("\n3. GET /errors/hierarchy")
        try:
            async with session.get(f"{base_url}/errors/hierarchy") as resp:
                if resp.status == 200:
                    hierarchy = await resp.json()
                    print(f"   Status: {resp.status}")
                    print(f"   Root class: {hierarchy.get('class', 'Unknown')}")
                else:
                    print(f"   Status: {resp.status}")
                    print(f"   Error: {await resp.text()}")
        except Exception as e:
            print(f"   Request failed: {e}")

        # 4. Test retryability endpoint
        print("\n4. GET /errors/retryable/-30006")
        try:
            async with session.get(f"{base_url}/errors/retryable/-30006") as resp:
                if resp.status == 200:
                    is_retryable = await resp.json()
                    print(f"   Status: {resp.status}")
                    print(f"   Is retryable: {is_retryable}")
                else:
                    print(f"   Status: {resp.status}")
                    print(f"   Error: {await resp.text()}")
        except Exception as e:
            print(f"   Request failed: {e}")

        # 5. Test report endpoint
        print("\n5. GET /errors/report?provider_id=python-executor")
        try:
            async with session.get(
                f"{base_url}/errors/report",
                params={"provider_id": "python-executor"}
            ) as resp:
                if resp.status == 200:
                    report = await resp.text()
                    print(f"   Status: {resp.status}")
                    print(f"   Report length: {len(report)} characters")
                    print("   First line:", report.split('\n')[0])
                else:
                    print(f"   Status: {resp.status}")
                    print(f"   Error: {await resp.text()}")
        except Exception as e:
            print(f"   Request failed: {e}")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ERROR DISCOVERY API TEST")
    print("=" * 60)
    print("\nThis test verifies that error discovery works through")
    print("both the client methods and direct API endpoints.\n")

    # Make sure server is running
    print("NOTE: Make sure the Gleitzeit server is running on port 8000")
    print("      Run: gleitzeit serve\n")

    await test_client_methods()
    await test_api_endpoints()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())