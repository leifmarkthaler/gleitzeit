#!/bin/bash
# Backup Script - Run this BEFORE cleanup.sh to create a safety backup
# Creates a tarball of files that will be deleted

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Create backup directory with timestamp
BACKUP_DIR="cleanup_backup_$(date +%Y%m%d_%H%M%S)"
BACKUP_TARBALL="${BACKUP_DIR}.tar.gz"

echo -e "${YELLOW}Creating backup of files that will be deleted...${NC}"
echo ""

# Create temporary list of files to backup
FILES_TO_BACKUP=""

# Add log files
for file in *.log; do
    [ -f "$file" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP $file"
done

# Add database files
[ -f "gleitzeit.db" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP gleitzeit.db"
[ -f "gleitzeit_test.db" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP gleitzeit_test.db"

# Add test output files
[ -f "fail_test.txt" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP fail_test.txt"
[ -f "test_batch_file.txt" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP test_batch_file.txt"
for file in hybrid_test_*.txt sql_test_*.txt test_file_*.txt; do
    [ -f "$file" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP $file"
done

# Add backup files
[ -f "__init__.py.bak" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP __init__.py.bak"

# Add build artifacts
[ -d "src/gleitzeit.egg-info" ] && FILES_TO_BACKUP="$FILES_TO_BACKUP src/gleitzeit.egg-info"

if [ -z "$FILES_TO_BACKUP" ]; then
    echo -e "${GREEN}No files need backing up. Directory is already clean!${NC}"
    exit 0
fi

# Create the backup
echo -e "${YELLOW}Creating backup tarball: ${BACKUP_TARBALL}${NC}"
tar -czf "$BACKUP_TARBALL" $FILES_TO_BACKUP 2>/dev/null || {
    echo -e "${RED}Error creating backup. Aborting.${NC}"
    exit 1
}

# Show backup contents
echo ""
echo -e "${GREEN}Backup created successfully!${NC}"
echo -e "Backup file: ${GREEN}${BACKUP_TARBALL}${NC}"
echo ""
echo "Contents backed up:"
tar -tzf "$BACKUP_TARBALL" | head -20
TOTAL_FILES=$(tar -tzf "$BACKUP_TARBALL" | wc -l)
echo "... (${TOTAL_FILES} items total)"
echo ""
echo -e "${YELLOW}To restore from backup later:${NC}"
echo "  tar -xzf $BACKUP_TARBALL"
echo ""
echo -e "${GREEN}You can now safely run ./cleanup.sh${NC}"