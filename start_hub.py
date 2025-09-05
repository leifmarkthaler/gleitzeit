#!/usr/bin/env python3
"""Start the provider hub server."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    from gleitzeit.hub.provider_hub_simple import start_simple_hub_server
    print("Starting SimpleProviderHub server on http://127.0.0.1:8090")
    await start_simple_hub_server(host="127.0.0.1", port=8090)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nHub server stopped")