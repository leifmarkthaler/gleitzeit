#!/usr/bin/env python3
"""
Debug script to check mixin initialization order.
"""

import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

# Check MRO
print("Method Resolution Order:")
for i, cls in enumerate(ModularStreamSystemManager.__mro__):
    print(f"{i}: {cls.__name__} from {cls.__module__}")

print("\n" + "="*60)

# Create instance and check attributes
config = SystemConfig()
config.deployment_mode = DeploymentMode.DEVELOPMENT

manager = ModularStreamSystemManager(
    config=config,
    stream_config={"total_shards": 42}
)

# Check what attributes exist
print("\nAttributes after initialization:")
for attr in ['instance_id', 'total_shards', 'stream_config', 'consumer_group']:
    if hasattr(manager, attr):
        value = getattr(manager, attr)
        print(f"✓ {attr}: {value}")
    else:
        print(f"✗ {attr}: NOT FOUND")

# Check if init methods were called
print("\n__init__ methods called:")
print(f"BaseSystemMixin.__init__ sets _initialized: {hasattr(manager, '_initialized')}")
print(f"StreamCoreMixin.__init__ sets total_shards: {hasattr(manager, 'total_shards')}")