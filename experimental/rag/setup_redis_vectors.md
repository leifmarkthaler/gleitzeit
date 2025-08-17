# Setting Up Redis with RediSearch Module (Manual Installation)

## 1. Download and Build RediSearch Module

### On macOS
```bash
# Install dependencies
brew install cmake

# Clone RediSearch repository
git clone --recursive https://github.com/RediSearch/RediSearch.git
cd RediSearch

# Checkout stable version
git checkout v2.8.12  # Latest stable as of 2024

# Build the module
make setup
make build

# The module will be at: bin/*/redisearch.so
# For macOS ARM64: bin/macos-arm64/redisearch.so
# For macOS x64: bin/macos-x64/redisearch.so
```

### On Linux
```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y build-essential cmake python3

# Clone and build
git clone --recursive https://github.com/RediSearch/RediSearch.git
cd RediSearch
make setup
make build

# Module location: bin/linux-x64-release/redisearch.so
```

## 2. Configure Redis to Load the Module

### Option A: Command Line
```bash
# Start Redis with the module
redis-server --loadmodule /path/to/redisearch.so

# Example for macOS ARM64
redis-server --loadmodule ./RediSearch/bin/macos-arm64-release/redisearch.so

# With additional options
redis-server \
  --loadmodule ./RediSearch/bin/macos-arm64-release/redisearch.so \
  --port 6379 \
  --dir /var/lib/redis \
  --save 60 1
```

### Option B: Redis Configuration File
Create or edit `redis.conf`:

```conf
# /usr/local/etc/redis.conf or ~/.redis/redis.conf

# Load RediSearch module
loadmodule /absolute/path/to/redisearch.so

# Optional RediSearch configuration
# loadmodule /path/to/redisearch.so MINPREFIX 2 MAXEXPANSIONS 100

# Standard Redis config
port 6379
dir /var/lib/redis
save 900 1
save 300 10
save 60 10000

# For development
protected-mode no
bind 0.0.0.0
```

Then start Redis:
```bash
redis-server /path/to/redis.conf
```

### Option C: SystemD Service (Linux)
Create `/etc/systemd/system/redis-vector.service`:

```ini
[Unit]
Description=Redis with RediSearch Vector Support
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/redis-server --supervised systemd \
  --loadmodule /opt/redis-modules/redisearch.so
ExecStop=/usr/bin/redis-cli shutdown
Restart=always
User=redis
Group=redis

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable redis-vector
sudo systemctl start redis-vector
```

## 3. Verify Installation

```bash
# Check if module is loaded
redis-cli MODULE LIST

# Should show:
# 1) 1) "name"
#    2) "search"
#    3) "ver"
#    4) (integer) 20812

# Test vector commands
redis-cli
> FT._LIST
(empty array)  # No indexes yet

> PING
PONG
```

## 4. Install Python Dependencies

```bash
# Using uv (recommended for Gleitzeit)
uv pip install redis redis-om numpy

# Or using pip
pip install redis redis-om numpy
```

## 5. Test Vector Functionality

Create `test_redis_vectors.py`:

```python
#!/usr/bin/env python3
import redis
import numpy as np
from redis.commands.search.field import VectorField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Check if RediSearch is loaded
modules = r.module_list()
if not any(m.get(b'name', b'').decode() == 'search' for m in modules):
    print("❌ RediSearch module not loaded!")
    print("Start Redis with: redis-server --loadmodule /path/to/redisearch.so")
    exit(1)

print("✅ RediSearch module loaded")

# Create a simple vector index
INDEX_NAME = "test_vectors"
DIM = 10  # Small dimension for testing

try:
    # Drop existing index if exists
    r.ft(INDEX_NAME).dropindex(delete_documents=True)
except:
    pass

# Create index
schema = [
    TextField("title"),
    VectorField("vector", "FLAT", {
        "TYPE": "FLOAT32",
        "DIM": DIM,
        "DISTANCE_METRIC": "COSINE"
    })
]

r.ft(INDEX_NAME).create_index(
    fields=schema,
    definition=IndexDefinition(prefix=["doc:"], index_type=IndexType.HASH)
)

print(f"✅ Created index: {INDEX_NAME}")

# Add documents with vectors
docs = [
    ("doc:1", "First document", [0.1] * DIM),
    ("doc:2", "Second document", [0.2] * DIM),
    ("doc:3", "Third document", [0.3] * DIM),
]

for doc_id, title, vector in docs:
    vector_bytes = np.array(vector, dtype=np.float32).tobytes()
    r.hset(doc_id, mapping={
        "title": title,
        "vector": vector_bytes
    })

print(f"✅ Added {len(docs)} documents")

# Search for similar vectors
query_vector = np.array([0.15] * DIM, dtype=np.float32).tobytes()
q = Query("*=>[KNN 2 @vector $vec AS score]").return_fields("title", "score").dialect(2)

results = r.ft(INDEX_NAME).search(q, query_params={"vec": query_vector})

print(f"\n📍 Vector search results (top 2):")
for doc in results.docs:
    print(f"  - {doc.title}: score={doc.score}")

# Get index info
info = r.ft(INDEX_NAME).info()
print(f"\n📊 Index stats:")
print(f"  - Documents: {info['num_docs']}")
print(f"  - Index size: {info.get('inverted_sz_mb', 0)} MB")

print("\n✅ Redis vector search is working!")
```

Run the test:
```bash
python test_redis_vectors.py
```

## 6. Gleitzeit Integration Script

Create a startup script for Gleitzeit with Redis vectors:

```bash
#!/bin/bash
# start_gleitzeit_with_vectors.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REDIS_MODULE_PATH="${SCRIPT_DIR}/RediSearch/bin/macos-arm64-release/redisearch.so"

# Check if module exists
if [ ! -f "$REDIS_MODULE_PATH" ]; then
    echo "❌ RediSearch module not found at: $REDIS_MODULE_PATH"
    echo "Please build it first:"
    echo "  git clone --recursive https://github.com/RediSearch/RediSearch.git"
    echo "  cd RediSearch && make setup && make build"
    exit 1
fi

# Check if Redis is already running
if pgrep -x "redis-server" > /dev/null; then
    echo "⚠️  Redis is already running. Stopping it first..."
    redis-cli shutdown
    sleep 2
fi

# Start Redis with RediSearch module
echo "🚀 Starting Redis with RediSearch module..."
redis-server --loadmodule "$REDIS_MODULE_PATH" \
  --port 6379 \
  --daemonize yes \
  --dir /tmp \
  --pidfile /tmp/redis-vector.pid \
  --logfile /tmp/redis-vector.log

# Wait for Redis to start
sleep 2

# Verify module is loaded
if redis-cli MODULE LIST | grep -q "search"; then
    echo "✅ Redis started with vector search support"
    echo "📍 PID file: /tmp/redis-vector.pid"
    echo "📍 Log file: /tmp/redis-vector.log"
else
    echo "❌ Failed to load RediSearch module"
    exit 1
fi

# Now start Gleitzeit
echo "🚀 Starting Gleitzeit..."
gleitzeit serve
```

Make it executable:
```bash
chmod +x start_gleitzeit_with_vectors.sh
```

## 7. Docker Compose Alternative

If building from source is problematic, create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis-vector:
    image: redis/redis-stack-server:latest
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    environment:
      - REDIS_ARGS=--save 60 1000 --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis-data:
```

Start with:
```bash
docker-compose up -d
```

## 8. Troubleshooting

### Module Loading Issues

```bash
# Check Redis version (needs >= 4.0)
redis-server --version

# Check module compatibility
redis-cli
> MODULE LOAD /path/to/redisearch.so
# If error, check the error message

# Common issues:
# 1. Wrong architecture (ARM vs x64)
# 2. Missing dependencies
# 3. Permission issues
```

### Build Issues on macOS

```bash
# If cmake issues
brew reinstall cmake

# If compiler issues
xcode-select --install

# For M1/M2 Macs, ensure using ARM64 build
file bin/macos-arm64-release/redisearch.so
# Should show: Mach-O 64-bit bundle arm64
```

### Build Issues on Linux

```bash
# Install all dependencies
sudo apt-get install -y \
  build-essential \
  cmake \
  python3 \
  python3-pip \
  git

# For CentOS/RHEL
sudo yum groupinstall "Development Tools"
sudo yum install cmake3 python3
```

## 9. Production Deployment

### Systemd Service with Module

```ini
# /etc/systemd/system/redis-vector.service
[Unit]
Description=Redis with Vector Search
After=network.target

[Service]
Type=notify
ExecStart=/usr/bin/redis-server --supervised systemd \
  --loadmodule /opt/redis-modules/redisearch.so \
  --dir /var/lib/redis \
  --save 900 1 \
  --save 300 10 \
  --save 60 10000 \
  --maxmemory 4gb \
  --maxmemory-policy allkeys-lru
ExecStop=/usr/bin/redis-cli shutdown
TimeoutStopSec=0
Restart=always
User=redis
Group=redis
RuntimeDirectory=redis
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

### Redis Sentinel for HA

```conf
# sentinel.conf
port 26379
sentinel monitor mymaster 127.0.0.1 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000

# Load module on all Redis instances
loadmodule /opt/redis-modules/redisearch.so
```

## 10. Performance Tuning

### Redis Configuration for Vectors

```conf
# Optimize for vector workloads
maxmemory 8gb
maxmemory-policy noeviction  # Don't evict vector data

# RediSearch specific
# FT.CONFIG SET MINPREFIX 2
# FT.CONFIG SET MAXEXPANSIONS 100
# FT.CONFIG SET TIMEOUT 500

# For large vectors
proto-max-bulk-len 512mb
client-output-buffer-limit normal 0 0 0
```

### Index Creation Options

```python
# Optimized HNSW parameters for production
VectorField("vector", "HNSW", {
    "TYPE": "FLOAT32",
    "DIM": 768,
    "DISTANCE_METRIC": "COSINE",
    "INITIAL_CAP": 1000000,     # Expected number of vectors
    "M": 32,                     # Higher = better recall, more memory
    "EF_CONSTRUCTION": 400,      # Higher = better index quality
    "EF_RUNTIME": 20,           # Higher = better search quality
    "EPSILON": 0.01,            # For quantization
})
```

## Summary

With Option 2 (manual module loading), you get:
- ✅ Full control over Redis configuration
- ✅ No Docker dependency
- ✅ Can use existing Redis installation
- ✅ Production-ready setup
- ✅ Works with Redis clustering

The RediSearch module provides enterprise-grade vector search capabilities that integrate perfectly with Gleitzeit's existing Redis-based persistence layer.