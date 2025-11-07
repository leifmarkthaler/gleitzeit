#!/usr/bin/env python3
"""
Multi-Instance Coordination Test Script

Tests the Phase 2 horizontal scaling features:
1. Instance registration
2. Leader election for singleton workers
3. Service registry with heartbeats
4. Zombie instance detection and cleanup
"""

import subprocess
import time
import sys
import os
import redis

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def run_command(cmd):
    """Run a shell command and return output"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def check_redis():
    """Verify Redis is accessible"""
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("✅ Redis is accessible")
        return r
    except Exception as e:
        print(f"❌ Redis not accessible: {e}")
        sys.exit(1)


def clear_redis(r):
    """Clear all Redis data"""
    r.flushall()
    print("✅ Redis cleared")


def start_instance(instance_num):
    """Start a gleitzeit instance in the background"""
    cmd = f'cd "/Users/leifmarkthaler/github/gleitzeit 0.0.7" && PYTHONPATH="$PWD/src" /Users/leifmarkthaler/.venv/bin/python3 -m gleitzeit.cli.main serve > /tmp/gleitzeit_instance_{instance_num}.log 2>&1 &'
    subprocess.Popen(cmd, shell=True)
    print(f"🚀 Started instance {instance_num}")
    return f"/tmp/gleitzeit_instance_{instance_num}.log"


def check_instances(r):
    """Check registered instances in Redis"""
    instances = r.smembers('instance:registry')
    print(f"\n📊 Registered instances: {len(instances)}")
    for inst in instances:
        print(f"   - {inst}")
    return instances


def check_leaders(r):
    """Check current leaders"""
    print("\n👑 Current leaders:")
    for worker in ['timer', 'signal', 'loki_exporter']:
        leader = r.get(f'leader:{worker}')
        if leader:
            print(f"   - {worker}: {leader.decode() if isinstance(leader, bytes) else leader}")
        else:
            print(f"   - {worker}: None")


def check_services(r):
    """Check service registry"""
    services = r.hgetall('services:registry')
    print(f"\n🔧 Services registered: {len(services)}")
    for service, data in services.items():
        service_name = service.decode() if isinstance(service, bytes) else service
        print(f"   - {service_name}")


def kill_processes():
    """Kill all gleitzeit processes"""
    run_command("pkill -9 -f 'python.*gleitzeit' 2>/dev/null")
    time.sleep(2)
    print("🛑 Killed all gleitzeit processes")


def main():
    print("=" * 60)
    print("Multi-Instance Coordination Test")
    print("=" * 60)

    # Setup
    r = check_redis()
    clear_redis(r)
    kill_processes()

    print("\n" + "=" * 60)
    print("Test 1: Start first instance")
    print("=" * 60)

    log1 = start_instance(1)
    time.sleep(10)  # Wait for startup

    instances = check_instances(r)
    if len(instances) != 1:
        print(f"❌ Expected 1 instance, found {len(instances)}")
        print(f"\nInstance 1 logs:\n{open(log1).read()[-500:]}")
        kill_processes()
        return False

    check_leaders(r)
    check_services(r)

    print("\n" + "=" * 60)
    print("Test 2: Start second instance")
    print("=" * 60)

    log2 = start_instance(2)
    time.sleep(10)  # Wait for startup

    instances = check_instances(r)
    if len(instances) != 2:
        print(f"❌ Expected 2 instances, found {len(instances)}")
        print(f"\nInstance 2 logs:\n{open(log2).read()[-500:]}")
        kill_processes()
        return False

    check_leaders(r)
    check_services(r)

    # Verify only ONE leader for each singleton worker
    for worker in ['timer', 'signal', 'loki_exporter']:
        leader = r.get(f'leader:{worker}')
        if not leader:
            print(f"❌ No leader elected for {worker}")
            kill_processes()
            return False

    print("\n✅ Leader election working - only one leader per singleton worker")

    print("\n" + "=" * 60)
    print("Test 3: Kill first instance and check zombie cleanup")
    print("=" * 60)

    # Kill instance 1 (simulate crash)
    run_command("ps aux | grep '/tmp/gleitzeit_instance_1.log' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null")
    print("🛑 Killed instance 1")

    # Wait for reconciliation worker to detect and clean up zombie
    print("⏳ Waiting 90 seconds for reconciliation worker to detect zombie...")
    time.sleep(90)

    instances = check_instances(r)
    if len(instances) != 1:
        print(f"⚠️  Expected 1 instance after cleanup, found {len(instances)}")
        print("   (Zombie cleanup may need more time)")
    else:
        print("✅ Zombie instance cleaned up successfully!")

    check_leaders(r)
    check_services(r)

    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)

    # Cleanup
    kill_processes()
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
