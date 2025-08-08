#!/usr/bin/env python3
"""
Setup script for Gleitzeit with post-install configuration
"""

import os
import sys
import subprocess
from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.install import install

class PostInstallCommand(install):
    """Custom install command that runs post-install setup"""
    
    def run(self):
        # Run the normal installation
        install.run(self)
        
        # Run post-install setup
        self.run_post_install()
    
    def run_post_install(self):
        """Run the post-installation setup"""
        try:
            print("\n" + "="*50)
            print("🔧 Running Gleitzeit post-install setup...")
            
            # Import and run the post-install script
            from gleitzeit_cluster.post_install import main as post_install_main
            post_install_main()
            
        except ImportError:
            # Fallback: run as subprocess
            try:
                subprocess.check_call([
                    sys.executable, '-m', 'gleitzeit_cluster.post_install'
                ])
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("⚠️  Could not run post-install setup automatically")
                print("   Run manually: gleitzeit-setup")
        except Exception as e:
            print(f"⚠️  Post-install setup failed: {e}")
            print("   Run manually: gleitzeit-setup")

class PostDevelopCommand(develop):
    """Custom develop command that runs post-install setup"""
    
    def run(self):
        # Run the normal development installation
        develop.run(self)
        
        # Run post-install setup
        self.run_post_install()
    
    def run_post_install(self):
        """Run the post-installation setup"""
        try:
            print("\n" + "="*50)
            print("🔧 Running Gleitzeit post-install setup...")
            
            # Import and run the post-install script
            from gleitzeit_cluster.post_install import main as post_install_main
            post_install_main()
            
        except ImportError:
            # Fallback for development mode
            try:
                subprocess.check_call([
                    sys.executable, '-c', 
                    'from gleitzeit_cluster.post_install import main; main()'
                ])
            except (subprocess.CalledProcessError, ImportError):
                print("⚠️  Could not run post-install setup automatically")
                print("   Run manually after installation: gleitzeit-setup")
        except Exception as e:
            print(f"⚠️  Post-install setup failed: {e}")
            print("   Run manually: gleitzeit-setup")

if __name__ == "__main__":
    setup(
        cmdclass={
            'install': PostInstallCommand,
            'develop': PostDevelopCommand,
        }
    )