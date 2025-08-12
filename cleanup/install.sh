#!/bin/bash
# Gleitzeit installer
# Usage: curl -sSL https://raw.githubusercontent.com/leifmarkthaler/gleitzeit/main/install.sh | bash

set -e

echo "Gleitzeit Quick Installer"
echo "========================"

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "Installing UV package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Source UV installation
    if [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

echo "UV package manager ready"

# Install Gleitzeit
echo "Installing Gleitzeit with monitoring..."
uv pip install "gleitzeit-cluster[monitor]"

# Run setup
echo "Setting up PATH..."
if [ -f "$HOME/.venv/bin/gleitzeit-setup" ]; then
    $HOME/.venv/bin/gleitzeit-setup
else
    echo "Setup script not found, adding PATH manually..."
    echo 'export PATH="$HOME/.venv/bin:$PATH"' >> ~/.zshrc
    echo "Added to ~/.zshrc"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "   1. Restart your terminal or run: source ~/.zshrc"
echo "   2. Test installation: gleitzeit --help"
echo "   3. Start development: gleitzeit dev"
echo "   4. Launch monitoring: gleitzeit pro"