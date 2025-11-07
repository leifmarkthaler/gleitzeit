"""
Test WebSocket Error Broadcasting

This script tests the end-to-end WebSocket error broadcasting implementation:
1. Subscribes to Redis Pub/Sub channel 'gleitzeit:events'
2. Connects to WebSocket endpoint at ws://localhost:8000/ws/events
3. Triggers errors and warnings via StatelessLogService
4. Verifies that events are published to Redis Pub/Sub
5. Verifies that WebSocket clients receive log_event messages
"""

import asyncio
import json
import sys
import redis.asyncio as redis
import websockets
from datetime import datetime

# Add src to path
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit 0.0.7/src')

from gleitzeit.core.stateless_log_service import StatelessLogService


class WebSocketErrorBroadcastingTest:
    def __init__(self):
        self.redis_url = "redis://localhost:6379"
        self.ws_url = "ws://localhost:8000/ws/events"
        self.redis_client = None
        self.pubsub = None
        self.ws_client = None

        # Track received events
        self.redis_events = []
        self.ws_events = []

    async def setup(self):
        """Set up Redis and WebSocket connections"""
        print("🔧 Setting up connections...")

        # Connect to Redis
        self.redis_client = await redis.from_url(self.redis_url, decode_responses=True)
        print(f"✅ Connected to Redis")

        # Subscribe to Pub/Sub
        self.pubsub = self.redis_client.pubsub()
        await self.pubsub.subscribe('gleitzeit:events')
        print(f"✅ Subscribed to Redis Pub/Sub channel 'gleitzeit:events'")

        # Connect to WebSocket
        self.ws_client = await websockets.connect(self.ws_url)
        print(f"✅ Connected to WebSocket {self.ws_url}")

        # Wait for connection confirmation
        msg = await self.ws_client.recv()
        data = json.loads(msg)
        if data.get('type') == 'connected':
            print(f"✅ WebSocket connection confirmed: {data.get('message')}")

    async def cleanup(self):
        """Clean up connections"""
        print("\n🧹 Cleaning up...")

        if self.pubsub:
            await self.pubsub.unsubscribe('gleitzeit:events')
            await self.pubsub.close()

        if self.redis_client:
            await self.redis_client.close()

        if self.ws_client:
            await self.ws_client.close()

        print("✅ Cleanup complete")

    async def listen_redis_pubsub(self):
        """Listen to Redis Pub/Sub in background"""
        print("👂 Starting Redis Pub/Sub listener...")

        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    self.redis_events.append(data)

                    event_type = data.get('type')
                    level = data.get('level')
                    msg_text = data.get('message', '')[:50]

                    print(f"  📡 Redis Pub/Sub: {event_type} | {level} | {msg_text}...")
        except asyncio.CancelledError:
            print("  ⏹️  Redis Pub/Sub listener stopped")

    async def listen_websocket(self):
        """Listen to WebSocket in background"""
        print("👂 Starting WebSocket listener...")

        try:
            while True:
                msg = await self.ws_client.recv()
                data = json.loads(msg)

                # Filter out ping/pong and connection messages
                if data.get('type') in ['log_event', 'workflow_event']:
                    self.ws_events.append(data)

                    event_type = data.get('type')
                    level = data.get('level', 'N/A')
                    msg_text = data.get('message', '')[:50]

                    print(f"  🌐 WebSocket: {event_type} | {level} | {msg_text}...")
        except asyncio.CancelledError:
            print("  ⏹️  WebSocket listener stopped")

    async def trigger_errors_and_warnings(self):
        """Trigger some errors and warnings via StatelessLogService"""
        print("\n🚨 Triggering errors and warnings...\n")

        await asyncio.sleep(1)  # Give listeners time to start

        # Trigger an error
        print("1️⃣  Triggering ERROR...")
        await StatelessLogService.log_error(
            redis=self.redis_client,
            message="Test error for WebSocket broadcasting",
            component="test_websocket_error_broadcasting",
            error_type="TestError",
            workflow_id="test-workflow-123",
            task_id="test-task-456",
            metadata={"test": "error_broadcast"}
        )

        await asyncio.sleep(0.5)

        # Trigger a warning
        print("2️⃣  Triggering WARNING...")
        await StatelessLogService.log_warning(
            redis=self.redis_client,
            message="Test warning for WebSocket broadcasting",
            component="test_websocket_error_broadcasting",
            warning_type="TestWarning",
            workflow_id="test-workflow-123",
            task_id="test-task-789",
            metadata={"test": "warning_broadcast"}
        )

        await asyncio.sleep(0.5)

        # Trigger another error
        print("3️⃣  Triggering another ERROR...")
        await StatelessLogService.log_error(
            redis=self.redis_client,
            message="Another test error with longer message to verify truncation in UI display",
            component="test_websocket_error_broadcasting",
            error_type="LongMessageError",
            workflow_id="test-workflow-456",
            metadata={"test": "long_message"}
        )

        await asyncio.sleep(1)  # Give time for events to propagate

    async def verify_results(self):
        """Verify that events were received"""
        print("\n📊 Verification Results:")
        print("=" * 70)

        # Verify Redis Pub/Sub
        print(f"\n✅ Redis Pub/Sub Events Received: {len(self.redis_events)}")
        for i, event in enumerate(self.redis_events, 1):
            print(f"  {i}. {event.get('level')}: {event.get('message')[:60]}...")

        # Verify WebSocket
        print(f"\n✅ WebSocket Events Received: {len(self.ws_events)}")
        for i, event in enumerate(self.ws_events, 1):
            print(f"  {i}. {event.get('level')}: {event.get('message')[:60]}...")

        print("\n" + "=" * 70)

        # Check if we got the expected events
        expected_errors = 2
        expected_warnings = 1

        redis_errors = [e for e in self.redis_events if e.get('level') == 'ERROR']
        redis_warnings = [e for e in self.redis_events if e.get('level') == 'WARNING']

        ws_errors = [e for e in self.ws_events if e.get('level') == 'ERROR']
        ws_warnings = [e for e in self.ws_events if e.get('level') == 'WARNING']

        print(f"\n🔍 Expected Events:")
        print(f"  - Errors: {expected_errors}")
        print(f"  - Warnings: {expected_warnings}")

        print(f"\n📡 Redis Pub/Sub Breakdown:")
        print(f"  - Errors: {len(redis_errors)} {'✅' if len(redis_errors) >= expected_errors else '❌'}")
        print(f"  - Warnings: {len(redis_warnings)} {'✅' if len(redis_warnings) >= expected_warnings else '❌'}")

        print(f"\n🌐 WebSocket Breakdown:")
        print(f"  - Errors: {len(ws_errors)} {'✅' if len(ws_errors) >= expected_errors else '❌'}")
        print(f"  - Warnings: {len(ws_warnings)} {'✅' if len(ws_warnings) >= expected_warnings else '❌'}")

        # Overall result
        redis_ok = len(redis_errors) >= expected_errors and len(redis_warnings) >= expected_warnings
        ws_ok = len(ws_errors) >= expected_errors and len(ws_warnings) >= expected_warnings

        print("\n" + "=" * 70)
        if redis_ok and ws_ok:
            print("✅ TEST PASSED: All events were successfully broadcast!")
        else:
            print("❌ TEST FAILED: Some events were not received")
            if not redis_ok:
                print("  - Redis Pub/Sub did not receive all expected events")
            if not ws_ok:
                print("  - WebSocket did not receive all expected events")
        print("=" * 70)

        return redis_ok and ws_ok

    async def run(self):
        """Run the test"""
        try:
            await self.setup()

            # Start listeners
            redis_task = asyncio.create_task(self.listen_redis_pubsub())
            ws_task = asyncio.create_task(self.listen_websocket())

            # Trigger events
            await self.trigger_errors_and_warnings()

            # Wait a bit more for events to arrive
            await asyncio.sleep(2)

            # Cancel listeners
            redis_task.cancel()
            ws_task.cancel()

            try:
                await redis_task
            except asyncio.CancelledError:
                pass

            try:
                await ws_task
            except asyncio.CancelledError:
                pass

            # Verify results
            success = await self.verify_results()

            await self.cleanup()

            return success

        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            await self.cleanup()
            return False


async def main():
    print("=" * 70)
    print("WebSocket Error Broadcasting Test")
    print("=" * 70)

    test = WebSocketErrorBroadcastingTest()
    success = await test.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
