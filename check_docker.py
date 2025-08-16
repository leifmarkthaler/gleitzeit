#!/usr/bin/env python
"""
Check Docker availability and provide setup instructions
"""
import subprocess
import sys
import platform
from pathlib import Path

def check_docker():
    """Check if Docker is installed and running"""
    
    print("🐳 Docker Status Check")
    print("=" * 50)
    
    # Check if Docker is installed
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Docker is installed: {result.stdout.strip()}")
        else:
            print("❌ Docker command found but returned an error")
            return False
    except FileNotFoundError:
        print("❌ Docker is not installed")
        print_installation_instructions()
        return False
    except subprocess.TimeoutExpired:
        print("⚠️  Docker command timed out - it may be starting up")
        return False
    
    # Check if Docker daemon is running
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print("✅ Docker daemon is running")
            
            # Check for Python images
            check_python_images()
            return True
        else:
            print("❌ Docker daemon is not running")
            print("\nTo start Docker:")
            if platform.system() == "Darwin":
                print("  1. Open Docker Desktop from Applications")
                print("  2. Wait for the whale icon to appear in the menu bar")
                print("  3. The icon should be steady (not animated)")
            elif platform.system() == "Linux":
                print("  Run: sudo systemctl start docker")
            return False
    except subprocess.TimeoutExpired:
        print("⚠️  Docker daemon is not responding")
        return False


def check_python_images():
    """Check for Python Docker images"""
    print("\n📦 Checking Python Docker images...")
    
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "--filter", "reference=python*"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        images = [img for img in result.stdout.strip().split('\n') if img]
        
        if images:
            print("Available Python images:")
            for img in images:
                print(f"  - {img}")
        else:
            print("No Python images found. They will be downloaded on first use.")
            print("\nTo pre-download Python images, run:")
            print("  docker pull python:3.11-slim")
            print("  docker pull python:3.11")
            
    except Exception as e:
        print(f"Could not check images: {e}")


def print_installation_instructions():
    """Print Docker installation instructions based on OS"""
    
    os_type = platform.system()
    
    print("\n📋 Docker Installation Instructions")
    print("-" * 40)
    
    if os_type == "Darwin":  # macOS
        print("\nFor macOS, you have several options:\n")
        
        print("Option 1: Docker Desktop (Recommended)")
        print("  1. Download from: https://www.docker.com/products/docker-desktop/")
        print("  2. Open the downloaded .dmg file")
        print("  3. Drag Docker to Applications")
        print("  4. Launch Docker Desktop from Applications")
        print("  5. Follow the setup wizard\n")
        
        print("Option 2: Using Homebrew")
        print("  brew install --cask docker\n")
        
        print("Option 3: Colima (Lightweight alternative)")
        print("  brew install colima docker")
        print("  colima start\n")
        
    elif os_type == "Linux":
        print("\nFor Linux:\n")
        print("  # Install Docker")
        print("  curl -fsSL https://get.docker.com -o get-docker.sh")
        print("  sudo sh get-docker.sh")
        print("  ")
        print("  # Add your user to docker group")
        print("  sudo usermod -aG docker $USER")
        print("  ")
        print("  # Start Docker")
        print("  sudo systemctl start docker")
        print("  sudo systemctl enable docker\n")
        
    elif os_type == "Windows":
        print("\nFor Windows:\n")
        print("  1. Download Docker Desktop from:")
        print("     https://www.docker.com/products/docker-desktop/")
        print("  2. Run the installer")
        print("  3. Follow the installation wizard")
        print("  4. Restart your computer if prompted\n")
    
    print("\n💡 After installing Docker:")
    print("  1. Verify installation: docker --version")
    print("  2. Test Docker: docker run hello-world")
    print("  3. Pull Python image: docker pull python:3.11-slim")


def test_docker_functionality():
    """Test basic Docker functionality"""
    print("\n🧪 Testing Docker functionality...")
    
    try:
        # Test running a simple container
        result = subprocess.run(
            ["docker", "run", "--rm", "hello-world"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and "Hello from Docker!" in result.stdout:
            print("✅ Docker can run containers successfully")
            return True
        else:
            print("❌ Docker test failed")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("⚠️  Docker test timed out")
        return False
    except Exception as e:
        print(f"❌ Docker test failed: {e}")
        return False


def check_docker_compose():
    """Check if Docker Compose is available"""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"\n✅ Docker Compose is available: {result.stdout.strip()}")
            return True
    except:
        pass
    
    # Try old docker-compose command
    try:
        result = subprocess.run(
            ["docker-compose", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"\n✅ Docker Compose (standalone) is available: {result.stdout.strip()}")
            return True
    except:
        print("\n⚠️  Docker Compose is not available")
        return False


def main():
    """Main function"""
    print("\n" + "=" * 50)
    print("🐳 Gleitzeit Docker Environment Check")
    print("=" * 50 + "\n")
    
    # Check Docker
    docker_ok = check_docker()
    
    if docker_ok:
        # Test functionality
        test_ok = test_docker_functionality()
        
        # Check Docker Compose
        compose_ok = check_docker_compose()
        
        print("\n" + "=" * 50)
        print("✅ Docker is ready for Gleitzeit!")
        print("=" * 50)
        
        print("\n📝 Next steps:")
        print("  1. The DockerExecutor will work with sandboxed execution")
        print("  2. Python code can be run in isolated containers")
        print("  3. Use 'sandboxed' mode for untrusted code")
        print("  4. Use 'local' mode for trusted code (no Docker needed)")
        
    else:
        print("\n" + "=" * 50)
        print("❌ Docker is not ready")
        print("=" * 50)
        
        print("\n📝 The PythonDockerProvider will still work in 'local' mode")
        print("   but 'sandboxed' mode requires Docker to be installed and running.")
    
    return 0 if docker_ok else 1


if __name__ == "__main__":
    sys.exit(main())