#!/bin/bash
# Startup script for Gleitzeit 0.0.7

# Set Python path
export PYTHONPATH="src:$PYTHONPATH"

# Default Redis URL
export REDIS_URL="${REDIS_URL:-redis://localhost:6379}"

# Function to start orchestrator
start_orchestrator() {
    echo "🚀 Starting Component Orchestrator..."
    python src/gleitzeit/cli/main.py orchestrator start
}

# Function to start workers individually
start_workers() {
    echo "🚀 Starting workers individually..."

    # Start task execution workers
    for i in {0..4}; do
        echo "Starting task_execution worker $i..."
        python src/gleitzeit/cli/main.py worker start --type task_execution --id "task-exec-$i" &
    done

    # Start dependency workers
    for i in {0..2}; do
        echo "Starting dependency worker $i..."
        python src/gleitzeit/cli/main.py worker start --type dependency --id "dep-$i" &
    done

    # Start workflow loader worker
    echo "Starting workflow_loader worker..."
    python src/gleitzeit/cli/main.py worker start --type workflow_loader --id "loader-0" &

    echo "All workers started. Press Ctrl+C to stop."
    wait
}

# Main menu
case "$1" in
    orchestrator)
        start_orchestrator
        ;;
    workers)
        start_workers
        ;;
    *)
        echo "Gleitzeit 0.0.7 - Worker-Based Architecture"
        echo ""
        echo "Usage: ./start.sh [orchestrator|workers]"
        echo ""
        echo "  orchestrator  - Start the Component Orchestrator (manages workers automatically)"
        echo "  workers       - Start workers manually"
        echo ""
        echo "Other commands:"
        echo "  python src/gleitzeit/cli/main.py workflow submit example_workflow.yaml"
        echo "  python src/gleitzeit/cli/main.py orchestrator status"
        echo "  python src/gleitzeit/cli/main.py worker list"
        ;;
esac