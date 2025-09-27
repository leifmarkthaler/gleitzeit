# Makefile for Docker-based Gleitzeit

.PHONY: help build up down restart logs scale clean test dev prod

# Default target
help:
	@echo "Gleitzeit Docker Management"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Start all services in development mode"
	@echo "  make up           - Start all services (basic)"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - View logs (all services)"
	@echo "  make logs-api     - View API logs"
	@echo "  make logs-worker  - View worker logs"
	@echo ""
	@echo "Production:"
	@echo "  make prod         - Start in production mode"
	@echo "  make scale-workers N=10 - Scale task workers"
	@echo ""
	@echo "Maintenance:"
	@echo "  make build        - Build all images"
	@echo "  make clean        - Remove containers and volumes"
	@echo "  make test         - Run tests in container"
	@echo "  make shell        - Open shell in debug container"
	@echo "  make redis-cli    - Connect to Redis"

# Build all images
build:
	docker-compose build

# Development mode with hot reload
dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
	@echo "Development environment started!"
	@echo "API: http://localhost:8000"
	@echo "UI:  http://localhost:8004"
	@echo "Redis: localhost:6379"

# Production mode
prod:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
	@echo "Production environment started!"

# Basic start
up:
	docker-compose up -d
	@echo "Services started!"
	@echo "API: http://localhost:8000"
	@echo "UI:  http://localhost:8004"

# Stop all services
down:
	docker-compose down
	@echo "Services stopped!"

# Restart all services
restart: down up

# View logs
logs:
	docker-compose logs -f

logs-api:
	docker-compose logs -f api

logs-ui:
	docker-compose logs -f ui

logs-worker:
	docker-compose logs -f worker-task worker-executor

logs-redis:
	docker-compose logs -f redis

# Scale workers
scale-workers:
	docker-compose up -d --scale worker-task=$(N)
	@echo "Scaled worker-task to $(N) instances"

# Clean everything
clean:
	docker-compose down -v
	docker system prune -f
	@echo "Cleaned up containers and volumes!"

# Run tests
test:
	docker-compose run --rm api python -m pytest tests/

# Open shell in debug container
shell:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml run --rm debug /bin/bash

# Connect to Redis
redis-cli:
	docker-compose exec redis redis-cli

# Check health
health:
	@echo "Checking service health..."
	@curl -f http://localhost:8000/health || echo "API unhealthy"
	@curl -f http://localhost:8004/health || echo "UI unhealthy"
	@docker-compose exec redis redis-cli ping || echo "Redis unhealthy"

# Quick status
status:
	docker-compose ps

# Build specific service
build-api:
	docker-compose build api

build-ui:
	docker-compose build ui

build-worker:
	docker-compose build worker-task

# Restart specific service
restart-api:
	docker-compose restart api

restart-ui:
	docker-compose restart ui

restart-workers:
	docker-compose restart worker-task worker-executor worker-workflow

# Quick development commands
dev-api:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d api redis

dev-ui:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d ui api redis

dev-workers:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d worker-task redis