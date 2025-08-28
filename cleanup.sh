#!/bin/bash
# Gleitzeit 0.0.6 Directory Cleanup Script
# Run from project root directory

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Gleitzeit 0.0.6 cleanup...${NC}"
echo ""

# Function to safely remove files
safe_remove() {
    if [ -f "$1" ]; then
        rm -f "$1"
        echo -e "${GREEN}✓${NC} Removed: $1"
    fi
}

# Function to safely remove directories
safe_remove_dir() {
    if [ -d "$1" ]; then
        rm -rf "$1"
        echo -e "${GREEN}✓${NC} Removed directory: $1"
    fi
}

# 1. Remove log files
echo -e "${YELLOW}Removing log files...${NC}"
for file in *.log; do
    [ -f "$file" ] && safe_remove "$file"
done

# 2. Remove database files
echo -e "${YELLOW}Removing database files...${NC}"
safe_remove "gleitzeit.db"
safe_remove "gleitzeit_test.db"

# 3. Remove test output files
echo -e "${YELLOW}Removing test output files...${NC}"
safe_remove "fail_test.txt"
safe_remove "test_batch_file.txt"
for file in hybrid_test_*.txt; do
    [ -f "$file" ] && safe_remove "$file"
done
for file in sql_test_*.txt; do
    [ -f "$file" ] && safe_remove "$file"
done
for file in test_file_*.txt; do
    [ -f "$file" ] && safe_remove "$file"
done

# 4. Remove backup files
echo -e "${YELLOW}Removing backup files...${NC}"
safe_remove "__init__.py.bak"

# 5. Remove build artifacts
echo -e "${YELLOW}Removing build artifacts...${NC}"
safe_remove_dir "src/gleitzeit.egg-info"

# 6. Remove Python cache directories
echo -e "${YELLOW}Removing Python cache directories...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo -e "${GREEN}✓${NC} Removed all __pycache__ directories"

# 7. Remove pytest cache
safe_remove_dir ".pytest_cache"

# 8. Create test organization directories if they don't exist
echo -e "${YELLOW}Creating test organization directories...${NC}"
mkdir -p tests/integration
mkdir -p tests/scripts  
mkdir -p tests/workflows
echo -e "${GREEN}✓${NC} Test directories ready"

echo ""
echo -e "${GREEN}Cleanup complete!${NC}"
echo ""

# Summary of what can be moved (but not done automatically)
echo -e "${YELLOW}Files that could be reorganized (manual review recommended):${NC}"
echo "  • Test Python files (test_*.py) in root → tests/integration/"
echo "  • Test YAML workflows (test_*.yaml) in root → tests/workflows/"
echo "  • Test shell scripts (test_*.sh) in root → tests/scripts/"
echo "  • Documentation files in root → docs/"
echo ""
echo "Run './move_tests.sh' to reorganize test files (will be created if you want)"