#!/usr/bin/env python
import asyncio
import sys
sys.path.insert(0, 'src')
from gleitzeit.client import GleitzeitClient

async def test():
    async with GleitzeitClient() as client:
        print('Testing error logs...')
        try:
            errors = await client.get_error_logs(limit=5, level='ERROR')
            print(f'✓ Got {len(errors)} error logs')
            print(f'  Response: {errors}')
        except Exception as e:
            print(f'✗ Error logs failed: {type(e).__name__}: {e}')

asyncio.run(test())
