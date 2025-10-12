#!/bin/bash
# Test Worker Management API

API_URL="${API_URL:-http://localhost:8000}"

echo "=== Worker Management API Test ==="
echo ""

# 1. List all workers
echo "1. Listing all workers..."
curl -s "$API_URL/system/workers" | jq '.workers[] | {worker_id, worker_type, status}'
echo ""

# 2. Get timer worker ID
TIMER_WORKER=$(curl -s "$API_URL/system/workers" | jq -r '.workers[] | select(.worker_type == "timer") | .worker_id' | head -1)

if [ -z "$TIMER_WORKER" ]; then
    echo "❌ No timer worker found"
    exit 1
fi

echo "2. Found timer worker: $TIMER_WORKER"
echo ""

# 3. Test restart command
echo "3. Sending restart command to $TIMER_WORKER..."
curl -X POST "$API_URL/system/workers/$TIMER_WORKER/restart?reason=Testing+API" | jq '.'
echo ""

# 4. Wait for command to be processed
echo "4. Waiting 3 seconds for worker to process command..."
sleep 3
echo ""

# 5. Check worker status
echo "5. Checking worker status..."
curl -s "$API_URL/system/workers" | jq --arg id "$TIMER_WORKER" '.workers[] | select(.worker_id == $id)'
echo ""

echo "=== Test Complete ==="
echo ""
echo "To manually restart the timer worker:"
echo "  curl -X POST '$API_URL/system/workers/$TIMER_WORKER/restart?reason=Apply+timer+fixes'"
