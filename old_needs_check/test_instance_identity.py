#!/usr/bin/env python
"""Test the instance identity system"""

import sys
import os
sys.path.insert(0, 'src')

from gleitzeit.core.instance import InstanceIdentity, initialize_instance
from gleitzeit.core.config_loader import ConfigLoader
import json

def test_instance_identity():
    """Test instance identity creation and features"""

    print("=" * 60)
    print("Testing Instance Identity System")
    print("=" * 60)

    # Test 1: Create default instance
    print("\n1. Creating default instance...")
    instance = InstanceIdentity()
    print(f"   Instance ID: {instance.instance_id}")
    print(f"   Machine: {instance.machine_id}")
    print(f"   IP: {instance.machine_ip}")
    print(f"   Role: {instance.role}")

    # Test 2: Create named instance with port offset
    print("\n2. Creating named instance with port offset...")
    instance2 = InstanceIdentity(
        instance_name="worker-1",
        role="worker",
        port_offset=100
    )
    print(f"   Instance Name: {instance2.instance_name}")
    print(f"   Instance ID: {instance2.instance_id}")
    print(f"   API Port: {instance2.get_service_port('api')}")
    print(f"   UI Port: {instance2.get_service_port('ui')}")

    # Test 3: Check capabilities
    print("\n3. System capabilities:")
    caps = instance.capabilities
    print(f"   CPUs: {caps.cpu_count}")
    print(f"   Memory: {caps.memory_gb:.1f} GB")
    print(f"   Platform: {caps.platform}")
    print(f"   Python: {caps.python_version}")
    if caps.gpu_available:
        print(f"   GPUs: {caps.gpu_count} ({caps.gpu_memory_gb:.1f} GB)")
    else:
        print("   GPUs: Not available")
    print(f"   Features: {', '.join(caps.specialized_features) or 'None'}")

    # Test 4: Serialization
    print("\n4. Testing serialization...")
    data = instance.to_dict()
    print(f"   Serialized keys: {', '.join(data.keys())}")

    # Test 5: Redis namespace
    print("\n5. Testing Redis namespace...")
    print(f"   Namespace: {instance.get_redis_namespace()}")

    # Test 6: Fingerprint
    print("\n6. Testing instance fingerprint...")
    print(f"   Fingerprint: {instance.get_fingerprint()}")

    # Test 7: Configuration loader
    print("\n7. Testing configuration loader...")
    config_loader = ConfigLoader()
    config = config_loader.load()
    print(f"   Config loaded: {config.get('instance.name', 'default')}")
    print(f"   Redis URL: {config.get('redis.url')}")

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    test_instance_identity()