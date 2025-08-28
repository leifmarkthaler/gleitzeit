#!/bin/bash
# Script to reorganize test files from root to appropriate test directories
# This is separate from cleanup.sh to allow careful review

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Test File Reorganization Script${NC}"
echo -e "${YELLOW}This will move test files from root to organized test directories${NC}"
echo ""

# Create directories if they don't exist
mkdir -p tests/integration
mkdir -p tests/scripts
mkdir -p tests/workflows

# Function to move file with confirmation
move_file() {
    local src=$1
    local dest=$2
    if [ -f "$src" ]; then
        mv "$src" "$dest"
        echo -e "${GREEN}✓${NC} Moved: $src → $dest"
    fi
}

echo -e "${YELLOW}Moving Python test files to tests/integration/${NC}"
# List of Python test files to move
PYTHON_TEST_FILES=(
    "test_admin_methods.py"
    "test_api_debug.py"
    "test_api_endpoints.py"
    "test_api_registration.py"
    "test_auth_backends.py"
    "test_auth_implementation.py"
    "test_auth_modes.py"
    "test_client_autostart.py"
    "test_complex_workflow_redis.py"
    "test_delete_all_backends.py"
    "test_delete_methods.py"
    "test_delete_with_example.py"
    "test_duplicate_fix.py"
    "test_event_driven.py"
    "test_fail.py"
    "test_log_output.py"
    "test_log_streaming.py"
    "test_minimal_api.py"
    "test_modular_client.py"
    "test_new_endpoints.py"
    "test_os_import.py"
    "test_persistence.py"
    "test_queue_endpoints.py"
    "test_redis_event_architecture.py"
    "test_redis_events.py"
    "test_sql_architecture.py"
    "test_sql_event_architecture.py"
    "test_sql_retry.py"
    "test_workflow.py"
)

for file in "${PYTHON_TEST_FILES[@]}"; do
    move_file "$file" "tests/integration/$file"
done

echo ""
echo -e "${YELLOW}Moving YAML workflow test files to tests/workflows/${NC}"
# List of YAML test files to move
YAML_TEST_FILES=(
    "test_complex_workflow.yaml"
    "test_dependency_workflow.yaml"
    "test_llm_only.yaml"
    "test_shared_engine.yaml"
    "test_ui_message.yaml"
)

for file in "${YAML_TEST_FILES[@]}"; do
    move_file "$file" "tests/workflows/$file"
done

echo ""
echo -e "${YELLOW}Moving shell test scripts to tests/scripts/${NC}"
# Shell script test files
if [ -f "test_cli_commands.sh" ]; then
    move_file "test_cli_commands.sh" "tests/scripts/test_cli_commands.sh"
fi

echo ""
echo -e "${YELLOW}Moving workflow files (not test-specific) to examples/workflows/${NC}"
# Non-test workflow files that should be in examples
mkdir -p examples/workflows
if [ -f "workflow1.yaml" ]; then
    move_file "workflow1.yaml" "examples/workflows/workflow1.yaml"
fi
if [ -f "workflow2.yaml" ]; then
    move_file "workflow2.yaml" "examples/workflows/workflow2.yaml"
fi

echo ""
echo -e "${YELLOW}Moving JSON test data to tests/${NC}"
if [ -f "test_workflow.json" ]; then
    move_file "test_workflow.json" "tests/test_workflow.json"
fi

echo ""
echo -e "${GREEN}Test file reorganization complete!${NC}"
echo ""

# Summary
echo -e "${BLUE}Summary:${NC}"
echo "  • Python test files moved to: tests/integration/"
echo "  • YAML test workflows moved to: tests/workflows/"
echo "  • Shell test scripts moved to: tests/scripts/"
echo "  • Example workflows moved to: examples/workflows/"
echo ""
echo -e "${YELLOW}Note:${NC} You may need to update import paths in moved files."