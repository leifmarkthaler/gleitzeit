#!/usr/bin/env python
import asyncio
import sys
sys.path.insert(0, 'src')
from gleitzeit.client import GleitzeitClient

async def test():
    async with GleitzeitClient() as client:
        print('Testing audit logs...')
        try:
            logs = await client.get_audit_logs(limit=10)
            print(f'✓ Got {len(logs)} audit logs')
        except Exception as e:
            print(f'✗ Audit logs failed: {e}')

        print('\nTesting error logs...')
        try:
            errors = await client.get_error_logs(limit=5, level='ERROR')
            print(f'✓ Got {len(errors)} error logs')
        except Exception as e:
            print(f'✗ Error logs failed: {e}')

asyncio.run(test())
