#!/bin/bash

echo "🚀 Starting batch workflow submission test..."
START_TIME=$(date +%s)

# Use PYTHONPATH to ensure we use 0.0.7
export PYTHONPATH="/Users/leifmarkthaler/github/gleitzeit 0.0.7/src:$PYTHONPATH"

# Submit 20 workflows
echo "Submitting 20 workflows..."
for i in {1..20}; do
    echo -n "Submitting workflow $i/20... "
    cd "/Users/leifmarkthaler/github/gleitzeit 0.0.7" && python -c "
import sys
sys.path.insert(0, 'src')
from gleitzeit.cli import main
sys.argv = ['gleitzeit', 'submit', 'perf_test_workflow.yaml']
main()
"
done

SUBMIT_END=$(date +%s)
SUBMIT_TIME=$((SUBMIT_END - START_TIME))

echo ""
echo "✅ Submitted 20 workflows in ${SUBMIT_TIME}s"
echo ""
echo "Waiting for workflows to complete..."

# Wait a bit for execution
sleep 5

# Check results in Redis
echo ""
echo "Checking workflow results..."
redis-cli --raw eval "
local workflows = redis.call('keys', 'workflow:*')
local completed = 0
local failed = 0
for i, key in ipairs(workflows) do
    if string.match(key, ':result$') then
        local result = redis.call('get', key)
        if result then
            if string.match(result, '\"status\"%s*:%s*\"completed\"') then
                completed = completed + 1
            elseif string.match(result, '\"status\"%s*:%s*\"failed\"') then
                failed = failed + 1
            end
        end
    end
end
return 'Completed: ' .. completed .. ', Failed: ' .. failed
" 0

END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

echo ""
echo "📊 Performance Summary:"
echo "  - Submission time: ${SUBMIT_TIME}s"
echo "  - Total time: ${TOTAL_TIME}s"
echo "  - Average per workflow: $((TOTAL_TIME / 20))s"
