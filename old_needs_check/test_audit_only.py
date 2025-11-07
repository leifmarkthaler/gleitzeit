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
            print(f'  Response: {logs}')
        except Exception as e:
            print(f'✗ Audit logs failed: {type(e).__name__}: {e}')

asyncio.run(test())
