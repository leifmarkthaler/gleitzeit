#!/bin/bash
# Secure PyPI upload script

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Gleitzeit Package Upload Script${NC}"
echo ""

# Check if dist files exist
if [ ! -d "dist" ] || [ -z "$(ls -A dist/)" ]; then
    echo -e "${RED}❌ No dist/ files found. Run 'python -m build' first${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 Found package files:${NC}"
ls -la dist/

# Check if .pypirc exists
if [ ! -f "$HOME/.pypirc" ]; then
    echo -e "${RED}❌ No ~/.pypirc found. Set up your API tokens first${NC}"
    echo "Create ~/.pypirc with your PyPI tokens"
    exit 1
fi

echo ""
echo "Select upload target:"
echo "1) TestPyPI (recommended for testing)"
echo "2) PyPI (production)"
read -p "Enter choice (1 or 2): " choice

case $choice in
    1)
        echo -e "${YELLOW}🧪 Uploading to TestPyPI...${NC}"
        twine upload --repository testpypi dist/*
        echo ""
        echo -e "${GREEN}✅ Upload complete!${NC}"
        echo -e "${YELLOW}Test installation with:${NC}"
        echo "pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ gleitzeit-cluster"
        ;;
    2)
        echo -e "${YELLOW}🚀 Uploading to PyPI...${NC}"
        read -p "Are you sure? This will publish to production PyPI (y/N): " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            twine upload dist/*
            echo ""
            echo -e "${GREEN}✅ Upload complete!${NC}"
            echo -e "${YELLOW}Install with:${NC}"
            echo "pip install gleitzeit-cluster"
            echo ""
            echo -e "${GREEN}🎉 Package is now live on PyPI!${NC}"
            echo "View at: https://pypi.org/project/gleitzeit-cluster/"
        else
            echo "Upload cancelled"
        fi
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac