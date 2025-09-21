# Multi-stage build for Gleitzeit
# Stage 1: Builder
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /build

# Copy requirements first for better caching
COPY pyproject.toml setup.py README.md ./
COPY src ./src

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the package
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Stage 2: Runtime
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r gleitzeit && useradd -r -g gleitzeit -u 1000 gleitzeit

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --from=builder /build/src ./src

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GLEITZEIT_REDIS_URL="redis://redis:6379/0" \
    GLEITZEIT_API_HOST="0.0.0.0" \
    GLEITZEIT_API_PORT="8000" \
    GLEITZEIT_LOG_LEVEL="INFO"

# Create necessary directories and set permissions
RUN mkdir -p /app/logs /app/data && \
    chown -R gleitzeit:gleitzeit /app

# Switch to non-root user
USER gleitzeit

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/system/health || exit 1

# Default command
CMD ["gleitzeit", "serve", "--host", "0.0.0.0", "--port", "8000"]