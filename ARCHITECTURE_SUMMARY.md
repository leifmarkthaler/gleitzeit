# Gleitzeit Architecture Summary

## Overview
Gleitzeit is a workflow orchestration system that stores all state in Redis and supports running multiple instances.

## Core Components

### 1. Persistence Layer
- Uses Redis for all state storage
- Lua scripts for atomic operations
- No in-memory state between requests

### 2. System Manager
- Coordinates components through Redis
- Maintains registry of available services
- Handles leader election when needed

### 3. Provider System
- Executes tasks using JSON-RPC 2.0 protocol
- Pools provider connections
- Manages LLM/Docker resources through hubs
- Providers register with TTL values

### 4. Event Architecture
- Redis PubSub for messaging between instances
- Event handlers stored in Redis
- Events saved for replay capabilities

### 5. API Layer
- Uses dependency injection
- Client connections pooled and shared
- Supports native (direct) and API (HTTP/WebSocket) modes

### 6. Workflow Engine
- Orchestrates task execution with dependencies
- Implements retry logic with backoff
- Supports streaming output

## Design Principles

1. No local state - everything in Redis
2. Idempotent operations for safe retries
3. Supports multiple instances
4. Protocol-based task execution
5. Event-driven communication

## Scalability Features

- Multiple instances can run simultaneously
- Instances discover each other through Redis
- Resources pooled across instances
- State recoverable from Redis after failures
- Atomic task claiming prevents duplicate work

## Current Capabilities

- Redis for persistence
- Error handling with retries
- TTL-based cleanup of stale data
- Authentication with session management
- WebSocket for real-time updates