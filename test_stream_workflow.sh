#!/bin/bash

echo "🚀 Testing Redis Streams workflow execution"
echo "==========================================="

# Kill any existing servers
pkill -f "gleitzeit serve" 2>/dev/null
sleep 2

# Start server with streams enabled
echo ""
echo "1️⃣ Starting server with Redis Streams enabled..."
export GLEITZEIT_STREAM_MODE=enabled
export GLEITZEIT_STREAM_PERCENTAGE=100

gleitzeit serve --port 8006 > server.log 2>&1 &
SERVER_PID=$!

# Wait for server
echo "   Waiting for server to start..."
sleep 5

# Check if server is running
if ! curl -s http://localhost:8006/health > /dev/null 2>&1; then
    echo "❌ Server failed to start. Checking logs:"
    tail -20 server.log
    kill $SERVER_PID 2>/dev/null
    exit 1
fi

echo "✅ Server started successfully"

# Submit a workflow
echo ""
echo "2️⃣ Submitting test workflow..."
WORKFLOW_RESULT=$(gleitzeit --host localhost --port 8006 run testworkflows/test_python_streams.yaml --wait 2>&1)
WORKFLOW_EXIT=$?

echo "$WORKFLOW_RESULT"

# Check if workflow completed
if [ $WORKFLOW_EXIT -eq 0 ]; then
    echo ""
    echo "✅ Workflow completed successfully!"
    
    # Check if streams were used
    echo ""
    echo "3️⃣ Checking if Redis Streams were used..."
    grep -i "stream" server.log | grep -v "StreamOrchestrator\|initialized" | head -10
else
    echo ""
    echo "❌ Workflow failed"
    echo "Server logs:"
    tail -30 server.log
fi

# Cleanup
echo ""
echo "4️⃣ Cleaning up..."
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

echo "✅ Test complete"