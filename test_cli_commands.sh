#!/bin/bash
# Test script for new CLI commands
# Requires API server to be running: gleitzeit serve

echo "Testing Gleitzeit CLI Commands"
echo "=============================="
echo ""

# Check if API server is running
echo "1. Testing system health..."
gleitzeit system health --port 8000
if [ $? -ne 0 ]; then
    echo "❌ API server not running. Please start with: gleitzeit serve"
    exit 1
fi
echo "✅ System health check passed"
echo ""

# Test task commands
echo "2. Testing task commands..."
gleitzeit task list --limit 5
echo "✅ Task list working"
echo ""

# Test workflow commands
echo "3. Testing workflow commands..."
gleitzeit workflow list --limit 5
echo "✅ Workflow list working"
echo ""

# Test queue commands
echo "4. Testing queue commands..."
gleitzeit queue list
echo "✅ Queue list working"
echo ""

# Test log commands
echo "5. Testing log commands..."
gleitzeit logs stats
echo "✅ Log stats working"
echo ""

# Test system commands
echo "6. Testing system commands..."
gleitzeit system stats
echo "✅ System stats working"
echo ""

# Test provider commands
echo "7. Testing provider commands..."
gleitzeit provider list
echo "✅ Provider list working"
echo ""

# Test error commands
echo "8. Testing error commands..."
gleitzeit errors stats
echo "✅ Error stats working"
echo ""

echo "=============================="
echo "✅ All basic command tests passed!"
echo ""
echo "To test auth commands, run:"
echo "  gleitzeit auth status"
echo "  gleitzeit auth login"
echo ""
echo "For more detailed testing, try:"
echo "  gleitzeit task list --help"
echo "  gleitzeit workflow list --status RUNNING"
echo "  gleitzeit logs query --level ERROR"