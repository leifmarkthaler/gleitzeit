# WebSocket Tests

This directory contains comprehensive tests for the Gleitzeit WebSocket implementation.

## Test Files

### `test_websocket_connection.py`
Tests basic WebSocket connection functionality:
- Connection establishment
- Auto-authentication with basic user
- Ping/pong keepalive
- Multiple concurrent connections
- Client ID and token parameters
- Reconnection behavior
- Invalid message handling

### `test_websocket_authentication.py`
Tests WebSocket authentication and authorization:
- Auto-login as basic user
- No authentication required (auto-login)
- Token parameter handling
- Consistency with HTTP API authentication
- Multiple connections using same user
- Stateless authentication
- Permission checking for basic user

### `test_websocket_events.py`
Tests event subscription and streaming:
- Event subscription with specific types
- Wildcard subscriptions (`task:*`, `*`)
- Multiple subscriptions
- Auto-subscribe parameter
- Event message format
- Concurrent connections with different subscriptions
- Event streaming readiness

### `test_websocket_scalability.py`
Tests scalability and performance:
- Multiple concurrent connections (10+)
- Connection establishment time
- Subscription performance
- Message throughput (ping/pong)
- Memory stability
- Concurrent operations
- Scaling with different connection counts

## Running the Tests

### Prerequisites
1. Start the Gleitzeit server:
```bash
gleitzeit serve --port 8080
```

2. Install test dependencies:
```bash
pip install pytest pytest-asyncio websockets aiohttp
```

### Run All WebSocket Tests
```bash
python -m pytest newtests/websockets/ -v
```

### Run Specific Test File
```bash
python -m pytest newtests/websockets/test_websocket_connection.py -v
```

### Run with Coverage
```bash
python -m pytest newtests/websockets/ --cov=gleitzeit.api.routes.events -v
```

## Test Status

### ✅ Working Features
- WebSocket connection establishment
- Authentication with basic user
- Ping/pong keepalive
- Event subscription
- Multiple concurrent connections
- Wildcard pattern subscriptions

### ⚠️ Partially Working
- Event streaming (subscription works, but events may not forward from Redis)

### 📋 Known Issues
- Event forwarding between Redis pub/sub and WebSocket needs verification
- Task submission endpoint validation prevents full end-to-end testing

## Architecture Notes

The WebSocket implementation uses:
- **Direct Event Bus Connection**: No client pool dependency for scalability
- **Pattern Subscriptions**: Redis `psubscribe` for wildcard support
- **Shared SystemManager**: Uses the same instance as the API
- **Stateless Operation**: No session persistence required

## Performance Targets

Based on the scalable architecture:
- **Connections per server**: 5,000-10,000
- **Connection time**: < 1 second average
- **Message throughput**: > 50 messages/second
- **Subscription time**: < 100ms average

## Future Improvements

1. Complete event forwarding implementation
2. Add event filtering by user permissions
3. Implement event replay functionality
4. Add connection pooling for Redis subscriptions
5. Implement WebSocket compression
6. Add metrics and monitoring