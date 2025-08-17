#!/bin/bash
# Universal installer for Redis with RediSearch module (Linux/Unix/macOS)

set -e  # Exit on error

# Colors for output (works on most terminals)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="${HOME}/.gleitzeit/redis-modules"
REDISEARCH_VERSION="v2.8.12"
REDIS_PORT=6379

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
DISTRO=""

# Detect Linux distribution if on Linux
if [ "$OS" = "linux" ]; then
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
    elif [ -f /etc/redhat-release ]; then
        DISTRO="rhel"
    elif [ -f /etc/debian_version ]; then
        DISTRO="debian"
    fi
fi

# Normalize architecture names
case "$ARCH" in
    x86_64|amd64)
        ARCH="x64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    armv7l|armhf)
        ARCH="arm"
        ;;
esac

PLATFORM="${OS}-${ARCH}"
echo -e "${GREEN}Detected platform: ${PLATFORM}${NC}"
[ -n "$DISTRO" ] && echo -e "${GREEN}Linux distribution: ${DISTRO}${NC}"

# Function to install dependencies based on OS
install_dependencies() {
    echo -e "${YELLOW}Installing dependencies...${NC}"
    
    case "$OS" in
        darwin)
            # macOS
            if command -v brew &> /dev/null; then
                brew install redis cmake make python3 || true
            else
                echo -e "${RED}Homebrew not found. Please install from https://brew.sh${NC}"
                exit 1
            fi
            ;;
        linux)
            # Linux - check distribution
            case "$DISTRO" in
                ubuntu|debian|raspbian)
                    sudo apt-get update
                    sudo apt-get install -y redis-server build-essential cmake python3 python3-pip git
                    ;;
                fedora|rhel|centos|rocky|almalinux)
                    sudo dnf install -y redis gcc gcc-c++ make cmake python3 python3-pip git
                    ;;
                arch|manjaro)
                    sudo pacman -Sy --noconfirm redis base-devel cmake python python-pip git
                    ;;
                alpine)
                    sudo apk add --no-cache redis build-base cmake python3 py3-pip git
                    ;;
                opensuse*)
                    sudo zypper install -y redis gcc gcc-c++ make cmake python3 python3-pip git
                    ;;
                *)
                    echo -e "${YELLOW}Unknown Linux distribution. Attempting generic install...${NC}"
                    # Try common package managers
                    if command -v apt-get &> /dev/null; then
                        sudo apt-get update && sudo apt-get install -y redis-server build-essential cmake python3
                    elif command -v yum &> /dev/null; then
                        sudo yum install -y redis gcc gcc-c++ make cmake python3
                    elif command -v dnf &> /dev/null; then
                        sudo dnf install -y redis gcc gcc-c++ make cmake python3
                    elif command -v pacman &> /dev/null; then
                        sudo pacman -Sy --noconfirm redis base-devel cmake python
                    else
                        echo -e "${RED}Could not determine package manager!${NC}"
                        echo "Please manually install: redis, gcc, make, cmake, python3"
                        exit 1
                    fi
                    ;;
            esac
            ;;
        freebsd)
            # FreeBSD
            sudo pkg install -y redis gcc cmake python3
            ;;
        openbsd)
            # OpenBSD
            doas pkg_add redis gcc cmake python3
            ;;
        *)
            echo -e "${RED}Unsupported OS: $OS${NC}"
            echo "Please manually install: redis, gcc, make, cmake, python3"
            exit 1
            ;;
    esac
    
    echo -e "${GREEN}✓ Dependencies installed${NC}"
}

# Function to check if Redis is running
check_redis() {
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &> /dev/null; then
            echo -e "${YELLOW}Redis is currently running on port 6379${NC}"
            echo -e "${YELLOW}It needs to be restarted to load the module${NC}"
            return 0
        fi
    fi
    return 1
}

# Function to build RediSearch
build_redisearch() {
    echo -e "${YELLOW}Building RediSearch module...${NC}"
    
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    
    # Clone or update RediSearch
    if [ -d "RediSearch" ]; then
        echo "Updating existing RediSearch repository..."
        cd RediSearch
        git fetch --tags
        git checkout "$REDISEARCH_VERSION"
        git pull origin "$REDISEARCH_VERSION" 2>/dev/null || true
    else
        echo "Cloning RediSearch repository..."
        git clone --recursive https://github.com/RediSearch/RediSearch.git
        cd RediSearch
        git checkout "$REDISEARCH_VERSION"
    fi
    
    # Build the module
    echo "Building RediSearch (this may take a few minutes)..."
    make setup
    make build
    
    # Find the built module
    MODULE_PATH=$(find bin -name "redisearch.so" -type f 2>/dev/null | head -1)
    
    if [ -z "$MODULE_PATH" ]; then
        echo -e "${RED}Failed to build RediSearch module!${NC}"
        echo "Build output directory contents:"
        ls -la bin/*/
        exit 1
    fi
    
    FULL_MODULE_PATH="${INSTALL_DIR}/RediSearch/${MODULE_PATH}"
    echo -e "${GREEN}✓ RediSearch module built: ${FULL_MODULE_PATH}${NC}"
    
    # Make module accessible
    MODULE_LINK="${HOME}/.gleitzeit/redisearch.so"
    mkdir -p "$(dirname "$MODULE_LINK")"
    ln -sf "$FULL_MODULE_PATH" "$MODULE_LINK"
    echo -e "${GREEN}✓ Module linked to: ${MODULE_LINK}${NC}"
}

# Function to create start/stop scripts
create_scripts() {
    echo -e "${YELLOW}Creating helper scripts...${NC}"
    
    BIN_DIR="${HOME}/.gleitzeit/bin"
    mkdir -p "$BIN_DIR"
    
    # Start script
    cat > "$BIN_DIR/redis-with-vectors" << EOF
#!/bin/bash
# Start Redis with RediSearch vector support

MODULE_PATH="${HOME}/.gleitzeit/redisearch.so"

if [ ! -f "\$MODULE_PATH" ]; then
    echo "RediSearch module not found at: \$MODULE_PATH"
    echo "Please run: install_redis_vectors.sh"
    exit 1
fi

# Stop existing Redis if running
redis-cli shutdown 2>/dev/null || true
sleep 1

echo "Starting Redis with RediSearch module..."
redis-server --loadmodule "\$MODULE_PATH" \\
    --port 6379 \\
    --dir /tmp \\
    --daemonize yes \\
    --pidfile /tmp/redis-vector.pid \\
    --logfile /tmp/redis-vector.log

sleep 2

# Verify module loaded
if redis-cli MODULE LIST | grep -q search; then
    echo "✓ Redis started with vector search support"
    echo "  PID file: /tmp/redis-vector.pid"
    echo "  Log file: /tmp/redis-vector.log"
    echo ""
    echo "To stop: redis-cli shutdown"
else
    echo "✗ Failed to load RediSearch module"
    exit 1
fi
EOF

    chmod +x "$BIN_DIR/redis-with-vectors"
    
    echo -e "${GREEN}✓ Created start script: $BIN_DIR/redis-with-vectors${NC}"
    
    # Add to PATH if not already there
    if ! echo "$PATH" | grep -q "/.gleitzeit/bin"; then
        echo -e "${YELLOW}Add to your PATH: export PATH=\"\$PATH:$BIN_DIR\"${NC}"
    fi
}

# Main installation
main() {
    echo -e "${GREEN}===================================${NC}"
    echo -e "${GREEN}Redis Vector Search Installation${NC}"
    echo -e "${GREEN}===================================${NC}"
    echo
    
    # Check for Redis
    if ! command -v redis-server &> /dev/null; then
        echo -e "${YELLOW}Redis not found. Installing...${NC}"
        install_dependencies
    else
        echo -e "${GREEN}✓ Redis is installed${NC}"
    fi
    
    # Check if Redis is running
    check_redis
    
    # Build RediSearch
    build_redisearch
    
    # Create helper scripts
    create_scripts
    
    echo
    echo -e "${GREEN}===================================${NC}"
    echo -e "${GREEN}Installation Complete!${NC}"
    echo -e "${GREEN}===================================${NC}"
    echo
    echo "To use Redis with vector search:"
    echo
    echo "1. Start Redis with the module:"
    echo "   ${HOME}/.gleitzeit/bin/redis-with-vectors"
    echo
    echo "2. Or manually:"
    echo "   redis-server --loadmodule ${HOME}/.gleitzeit/redisearch.so"
    echo
    echo "3. Test it works:"
    echo "   python test_redis_vectors.py"
    echo
    echo -e "${GREEN}Module location: ${HOME}/.gleitzeit/redisearch.so${NC}"
    echo
    
    # Offer to start Redis now
    echo -n "Start Redis with vector support now? [Y/n] "
    read -r response
    if [ -z "$response" ] || [ "$response" = "y" ] || [ "$response" = "Y" ]; then
        ${HOME}/.gleitzeit/bin/redis-with-vectors
    fi
}

# Run main function
main