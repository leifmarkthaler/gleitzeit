#!/usr/bin/env python3
"""
Post-installation script for Gleitzeit
Automatically configures PATH and provides installation feedback
"""

import os
import sys
import subprocess
from pathlib import Path
import shutil

def get_shell_config_file():
    """Detect the user's shell and return appropriate config file"""
    shell = os.environ.get('SHELL', '/bin/bash')
    
    if 'zsh' in shell:
        return Path.home() / '.zshrc'
    elif 'bash' in shell:
        # Check for .bash_profile first (macOS), then .bashrc (Linux)
        bash_profile = Path.home() / '.bash_profile'
        bashrc = Path.home() / '.bashrc'
        return bash_profile if bash_profile.exists() else bashrc
    elif 'fish' in shell:
        config_dir = Path.home() / '.config' / 'fish'
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / 'config.fish'
    else:
        # Default to .profile for unknown shells
        return Path.home() / '.profile'

def get_uv_bin_path():
    """Find the UV virtual environment bin directory"""
    # Try common UV locations
    possible_paths = [
        Path.home() / '.venv' / 'bin',
        Path('.venv') / 'bin',
        Path(os.environ.get('VIRTUAL_ENV', '')) / 'bin',
    ]
    
    for path in possible_paths:
        if path.exists() and (path / 'gleitzeit').exists():
            return path
    
    return None

def is_path_in_shell_config(shell_config, bin_path):
    """Check if the bin path is already in the shell config"""
    if not shell_config.exists():
        return False
    
    content = shell_config.read_text()
    return str(bin_path) in content

def add_to_path(shell_config, bin_path):
    """Add the bin path to shell configuration"""
    shell_name = shell_config.name
    
    if shell_name == 'config.fish':
        # Fish shell syntax
        path_line = f'set -gx PATH "{bin_path}" $PATH\n'
    else:
        # Bash/Zsh syntax
        path_line = f'export PATH="{bin_path}:$PATH"\n'
    
    # Add a comment and the PATH line
    addition = f'\n# Added by Gleitzeit installation\n{path_line}'
    
    try:
        with shell_config.open('a') as f:
            f.write(addition)
        return True
    except Exception as e:
        print(f"⚠️  Could not write to {shell_config}: {e}")
        return False

def test_command_available():
    """Test if the gleitzeit command is available"""
    try:
        result = subprocess.run(['gleitzeit', '--version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def main():
    """Main post-installation setup"""
    print("Gleitzeit Post-Installation Setup")
    print("=" * 40)
    
    # Find UV bin directory
    bin_path = get_uv_bin_path()
    if not bin_path:
        print("Error: Could not find UV virtual environment")
        print("Manual setup required:")
        print("   export PATH=\"$HOME/.venv/bin:$PATH\"")
        return False
    
    print(f"Found Gleitzeit at: {bin_path / 'gleitzeit'}")
    
    # Check if command is already available
    if test_command_available():
        print("Command 'gleitzeit' is already available")
        print_completion_message()
        return True
    
    # Detect shell and config file
    shell_config = get_shell_config_file()
    print(f"Detected shell config: {shell_config}")
    
    # Check if already configured
    if is_path_in_shell_config(shell_config, bin_path):
        print("PATH already configured in shell")
        print("Please restart your terminal or run:")
        print(f"   source {shell_config}")
        return True
    
    # Ask user for permission to modify shell config
    print(f"\nTo make 'gleitzeit' command available, we need to add:")
    print(f"   {bin_path}")
    print(f"   to your PATH in {shell_config}")
    
    if not sys.stdin.isatty():
        # Non-interactive mode - add automatically
        print("Non-interactive mode: Adding PATH automatically")
        modify_config = True
    else:
        # Interactive mode - ask user
        response = input("\nAdd to PATH automatically? [Y/n]: ").strip().lower()
        modify_config = response in ('', 'y', 'yes')
    
    if modify_config:
        if add_to_path(shell_config, bin_path):
            print(f"Added to PATH in {shell_config}")
            print("\nPlease restart your terminal or run:")
            print(f"   source {shell_config}")
        else:
            print("Failed to modify shell config")
            print_manual_setup(bin_path)
    else:
        print("Skipped automatic PATH setup")
        print_manual_setup(bin_path)
    
    print_completion_message()
    return True

def print_manual_setup(bin_path):
    """Print manual setup instructions"""
    print("\nManual setup (copy and paste):")
    print(f"   echo 'export PATH=\"{bin_path}:$PATH\"' >> ~/.zshrc")
    print("   source ~/.zshrc")

def print_completion_message():
    """Print completion message with next steps"""
    print("\n" + "=" * 40)
    print("Installation Complete!")
    print("\nNext steps:")
    print("   1. Restart terminal or source your shell config")
    print("   2. Test: gleitzeit --help")
    print("   3. Start development: gleitzeit dev")
    print("   4. Launch monitoring: gleitzeit pro")
    print("\nDocumentation:")
    print("   • README.md - Getting started")
    print("   • UV_INSTALL.md - UV-specific instructions") 
    print("   • INSTALL.md - All installation methods")

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        sys.exit(1)