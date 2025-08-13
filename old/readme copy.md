# Gleitzeit

Event-driven distributed task execution built on JSON-RPC 2.0 and Socket.IO.

## Project Status
This project is in active development.

## Overview
- Central server assigns tasks and manages workflow dependencies
- Execution engines run assigned tasks and report results
- Persistent queue with SQLite or Redis backends
- No polling or background loops – all coordination happens through events

## Quick Start
```bash
# Install dependencies
uv pip install redis aiosqlite socketio fastapi uvicorn

# Start central server
python -m gleitzeit_v4.server.central_server

# Start execution engine
python -m gleitzeit_v4.client.socketio_engine
```

A Redis server is required for distributed deployments. Providers and additional engines connect over Socket.IO.

## Contributing
The architecture and APIs may change as the project evolves. Feedback and pull requests are welcome.
