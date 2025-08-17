#!/bin/bash
# Start Redis Stack with vector support on alternate port (6380)

echo "🚀 Starting Redis Stack with vector support on port 6380..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "Please install Docker from: https://www.docker.com/get-started"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "❌ Docker is not running!"
    echo "Please start Docker Desktop"
    exit 1
fi

# Check if local Redis is running on 6379
if command -v redis-cli &> /dev/null; then
    if redis-cli -p 6379 ping &> /dev/null 2>&1; then
        echo "✓ Local Redis detected on port 6379 (keeping it running)"
    fi
fi

# Check if container already exists
if docker ps -a | grep -q redis-vector; then
    echo "Found existing redis-vector container"
    
    # Check if it's running
    if docker ps | grep -q redis-vector; then
        echo "✓ Redis Stack is already running"
    else
        echo "Starting stopped container..."
        docker start redis-vector
    fi
else
    # Start Redis Stack with docker-compose using alternate config
    echo "Starting Redis Stack on port 6380..."
    docker-compose -f docker-compose-alt-port.yml up -d
fi

# Wait for Redis to be ready
echo -n "Waiting for Redis Stack to be ready"
for i in {1..30}; do
    if docker exec redis-vector redis-cli ping &> /dev/null; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 1
done

# Verify RediSearch is loaded
echo "Checking RediSearch module..."
if docker exec redis-vector redis-cli MODULE LIST | grep -q search; then
    echo "✅ RediSearch module is loaded"
else
    echo "❌ RediSearch module not found"
    exit 1
fi

# Test vector functionality
echo "Testing vector functionality..."
docker exec redis-vector redis-cli --eval - << 'EOF'
-- Create a simple test index
local result = redis.call('FT.CREATE', 'test_idx', 'ON', 'HASH', 
    'SCHEMA', 'vec', 'VECTOR', 'FLAT', '6', 
    'TYPE', 'FLOAT32', 'DIM', '2', 'DISTANCE_METRIC', 'COSINE')
return "OK"
EOF

if [ $? -eq 0 ]; then
    echo "✅ Vector operations work!"
    docker exec redis-vector redis-cli FT.DROPINDEX test_idx DD &> /dev/null
else
    echo "⚠️  Vector test failed"
fi

echo ""
echo "=========================================="
echo "✅ Redis Stack is running with vector support!"
echo "=========================================="
echo ""
echo "📍 Connection details:"
echo "  Local Redis (no vectors):  localhost:6379"
echo "  Redis Stack (vectors):     localhost:6380"
echo "  RedisInsight Web UI:       http://localhost:8001"
echo ""
echo "📝 Usage examples:"
echo "  Connect to local Redis:    redis-cli -p 6379"
echo "  Connect to Redis Stack:    redis-cli -p 6380"
echo ""
echo "🐍 Python usage:"
echo "  local_redis = redis.Redis(port=6379)  # Your existing Redis"
echo "  vector_redis = redis.Redis(port=6380) # Redis with vectors"
echo ""
echo "To stop Redis Stack:  docker-compose -f docker-compose-alt-port.yml down"
echo "To view logs:         docker-compose -f docker-compose-alt-port.yml logs -f"
echo ""
echo "Test with: python test_redis_vectors.py --port 6380"