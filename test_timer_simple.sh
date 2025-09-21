#!/bin/bash

# Test timer workflow via API

echo "Testing Timer Provider..."

# 1. Login to get token
echo "1. Logging in..."
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "basic", "password": "basic123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

echo "   Token: ${TOKEN:0:20}..."

# 2. Submit workflow
echo "2. Submitting workflow..."
WORKFLOW_ID=$(curl -s -X POST http://localhost:8000/workflows/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @<(cat <<EOF
{
  "workflow_file": "test_timer_workflow.yaml",
  "params": {}
}
EOF
) | python3 -c "import sys, json; print(json.load(sys.stdin)['workflow_id'])")

echo "   Workflow ID: $WORKFLOW_ID"

# 3. Monitor workflow
echo "3. Monitoring workflow status..."
for i in {1..20}; do
  STATUS=$(curl -s -X GET "http://localhost:8000/workflows/$WORKFLOW_ID/status" \
    -H "Authorization: Bearer $TOKEN" | python3 -c "import sys, json; data=json.load(sys.stdin); print(f\"Status: {data['status']} | Tasks: {[t['name'] + ':' + t['status'] for t in data.get('tasks', [])]}\")") 
  
  echo "   $STATUS"
  
  if [[ $STATUS == *"COMPLETED"* ]] || [[ $STATUS == *"FAILED"* ]]; then
    break
  fi
  
  sleep 1
done

echo "4. Done!"