#!/bin/bash

echo "Testing LLM workflow submission via curl"
echo "========================================="

# Submit LLM workflow
echo -e "\nSubmitting LLM workflow..."
RESPONSE=$(curl -s -X POST http://localhost:8000/workflows/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "llm_simple_test",
    "name": "Simple LLM Test",
    "tasks": [
      {
        "id": "llm_task_simple",
        "name": "Simple LLM Task",
        "method": "complete",
        "protocol": "llm",
        "config": {
          "model": "gpt-3.5-turbo",
          "messages": [
            {
              "role": "user",
              "content": "Say hello in exactly 3 words"
            }
          ],
          "max_tokens": 10
        }
      }
    ]
  }')

echo "Response: $RESPONSE"

# Extract workflow ID
WORKFLOW_ID=$(echo $RESPONSE | grep -o '"workflow_id":"[^"]*' | cut -d'"' -f4)
echo "Workflow ID: $WORKFLOW_ID"

# Wait for execution
echo -e "\nWaiting 5 seconds for LLM execution..."
sleep 5

# Get results
echo -e "\nGetting results..."
curl -s "http://localhost:8000/workflows/$WORKFLOW_ID/results" | python -m json.tool

echo -e "\n========================================="
echo "Test complete"