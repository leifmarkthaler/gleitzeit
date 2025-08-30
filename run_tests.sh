#!/bin/bash
# Run Gleitzeit test suite

echo "Running Gleitzeit Test Suite..."
echo "================================"

# Run registry tests
echo -e "\n📋 Registry Tests:"
python -m pytest newtests/core/test_registry.py -v --tb=short

# Run task queue tests  
echo -e "\n📋 Task Queue Tests:"
python -m pytest newtests/core/test_task_queue.py -v --tb=short

# Run execution engine tests
echo -e "\n📋 Execution Engine Tests:"
python -m pytest newtests/core/test_execution_engine.py -v --tb=short

# Summary
echo -e "\n📊 Overall Summary:"
python -m pytest newtests/core/ --co -q | tail -1
python -m pytest newtests/core/ -v --tb=no | tail -1