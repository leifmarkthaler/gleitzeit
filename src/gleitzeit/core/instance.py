"""
Instance Identity and Management for Gleitzeit

Provides core instance identification, capability detection,
and metadata management for multi-instance deployments.
"""

import os
import socket
import uuid
import platform
import psutil
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
from dataclasses import dataclass, field, asdict
import json
import hashlib


@dataclass
class InstanceCapabilities:
    """Hardware and software capabilities of an instance"""
    cpu_count: int
    memory_gb: float
    gpu_available: bool = False
    gpu_count: int = 0
    gpu_memory_gb: float = 0.0
    platform: str = ""
    python_version: str = ""
    specialized_features: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['specialized_features'] = list(self.specialized_features)
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstanceCapabilities":
        """Create from dictionary"""
        if 'specialized_features' in data:
            data['specialized_features'] = set(data['specialized_features'])
        return cls(**data)


@dataclass
class MachineInfo:
    """Machine-level information for multi-machine deployments"""
    machine_id: str  # Unique machine identifier
    machine_fingerprint: str  # Hardware fingerprint for machine identity
    hostname: str  # Network hostname
    fqdn: str  # Fully qualified domain name
    primary_ip: str  # Primary IP address
    all_ips: List[str] = field(default_factory=list)  # All network interfaces
    datacenter: str = "default"  # Datacenter/location identifier
    rack: str = "default"  # Rack/physical location
    network_zone: str = "default"  # Network security zone

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MachineInfo":
        """Create from dictionary"""
        return cls(**data)


@dataclass
class InstanceMetadata:
    """Additional metadata about the instance"""
    environment: str = "development"  # development, staging, production
    region: str = "default"
    zone: str = "default"
    cluster: str = "default"  # Cluster identifier for grouped deployments
    tags: Dict[str, str] = field(default_factory=dict)
    labels: Set[str] = field(default_factory=set)
    network_tags: Set[str] = field(default_factory=set)  # Network accessibility tags

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        result = asdict(self)
        result['labels'] = list(self.labels)
        result['network_tags'] = list(self.network_tags)
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstanceMetadata":
        """Create from dictionary"""
        if 'labels' in data:
            data['labels'] = set(data['labels'])
        if 'network_tags' in data:
            data['network_tags'] = set(data['network_tags'])
        return cls(**data)


class InstanceIdentity:
    """Core identity for each Gleitzeit instance"""

    def __init__(self,
                 instance_name: Optional[str] = None,
                 role: str = "standalone",
                 port_offset: int = 0):
        """
        Initialize instance identity.

        Args:
            instance_name: Optional custom name for the instance
            role: Instance role (standalone, worker, coordinator, etc.)
            port_offset: Port offset for this instance
        """
        # Generate unique instance ID
        self.instance_id = self._generate_instance_id(instance_name)
        self.instance_name = instance_name or self.instance_id[:8]

        # Machine identification
        self.machine_info = self._get_machine_info()
        self.machine_id = self.machine_info.machine_id
        self.machine_ip = self.machine_info.primary_ip

        # Deployment identification
        self.deployment_id = f"{self.machine_id}:{self.instance_id}"
        self.role = role
        self.port_offset = port_offset

        # Timestamps
        self.started_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()

        # Capabilities
        self.capabilities = self._detect_capabilities()

        # Metadata
        self.metadata = InstanceMetadata(
            environment=os.getenv("GLEITZEIT_ENVIRONMENT", "development"),
            region=os.getenv("GLEITZEIT_REGION", "default"),
            zone=os.getenv("GLEITZEIT_ZONE", "default"),
            cluster=os.getenv("GLEITZEIT_CLUSTER", "default")
        )

        # Set network tags based on environment
        if self.metadata.environment == "production":
            self.metadata.network_tags.add("prod-network")
        else:
            self.metadata.network_tags.add("dev-network")

        # Service ports (will be calculated based on port_offset)
        self.service_ports: Dict[str, int] = {}
        self._calculate_service_ports()

    def _generate_instance_id(self, instance_name: Optional[str] = None) -> str:
        """Generate a unique instance ID"""
        # Use UUID4 for uniqueness
        unique_id = str(uuid.uuid4())

        if instance_name:
            # Create a readable prefix from the name
            prefix = instance_name.replace(" ", "-").lower()[:8]
            return f"{prefix}-{unique_id[:8]}"
        else:
            # Use hostname prefix if no name provided
            hostname = socket.gethostname().split(".")[0][:8]
            return f"{hostname}-{unique_id[:8]}"

    def _get_machine_info(self) -> MachineInfo:
        """Get comprehensive machine information"""
        hostname = socket.gethostname()
        try:
            fqdn = socket.getfqdn()
        except:
            fqdn = hostname

        # Get all IP addresses
        all_ips = []
        primary_ip = "127.0.0.1"

        try:
            # Try using netifaces if available
            import netifaces
            # Get all network interfaces
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr['addr']
                        if ip != '127.0.0.1':
                            all_ips.append(ip)
        except ImportError:
            # Fallback to socket method if netifaces not available
            try:
                # Get all IPs for hostname
                host_info = socket.getaddrinfo(hostname, None)
                for info in host_info:
                    ip = info[4][0]
                    if ip not in all_ips and ip != '127.0.0.1':
                        all_ips.append(ip)
            except:
                pass

        try:
            # Try to get primary IP by connecting to external server
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                primary_ip = s.getsockname()[0]
                if primary_ip not in all_ips:
                    all_ips.append(primary_ip)
        except Exception:
            # Fallback to first non-localhost IP if available
            if all_ips:
                primary_ip = all_ips[0]

        # Generate machine fingerprint based on hardware
        machine_fingerprint = self._generate_machine_fingerprint()

        # Generate unique machine ID (combines hostname and fingerprint)
        machine_id = f"{hostname.split('.')[0]}-{machine_fingerprint[:8]}"

        # Get datacenter/location info from environment
        datacenter = os.getenv("GLEITZEIT_DATACENTER", "default")
        rack = os.getenv("GLEITZEIT_RACK", "default")
        network_zone = os.getenv("GLEITZEIT_NETWORK_ZONE", "default")

        return MachineInfo(
            machine_id=machine_id,
            machine_fingerprint=machine_fingerprint,
            hostname=hostname,
            fqdn=fqdn,
            primary_ip=primary_ip,
            all_ips=all_ips or [primary_ip],
            datacenter=datacenter,
            rack=rack,
            network_zone=network_zone
        )

    def _generate_machine_fingerprint(self) -> str:
        """Generate a unique fingerprint for this machine based on hardware"""
        import hashlib
        import platform

        # Collect machine-specific data
        fingerprint_data = []

        # Platform information
        fingerprint_data.append(platform.node())
        fingerprint_data.append(platform.machine())
        fingerprint_data.append(platform.processor())

        # MAC addresses (stable across reboots)
        try:
            import netifaces
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_LINK in addrs:
                    for addr in addrs[netifaces.AF_LINK]:
                        if 'addr' in addr:
                            fingerprint_data.append(addr['addr'])
        except:
            pass

        # CPU info
        fingerprint_data.append(str(psutil.cpu_count(logical=False)))
        fingerprint_data.append(str(psutil.cpu_count(logical=True)))

        # Memory size (rounded to GB)
        memory_gb = round(psutil.virtual_memory().total / (1024**3))
        fingerprint_data.append(str(memory_gb))

        # Create hash
        fingerprint_str = ":".join(fingerprint_data)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    def _detect_capabilities(self) -> InstanceCapabilities:
        """Detect hardware and software capabilities"""
        import sys

        # CPU and Memory
        cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024 ** 3)

        # Platform info
        platform_info = platform.platform()
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # GPU detection (basic, can be enhanced with specific GPU libraries)
        gpu_available = False
        gpu_count = 0
        gpu_memory_gb = 0.0

        try:
            # Try to detect NVIDIA GPUs using nvidia-ml-py if available
            import pynvml
            pynvml.nvmlInit()
            gpu_count = pynvml.nvmlDeviceGetCount()
            gpu_available = gpu_count > 0
            if gpu_available:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu_memory_gb = mem_info.total / (1024 ** 3)
        except (ImportError, Exception):
            pass

        # Detect specialized features
        specialized_features = set()

        # Check for Docker
        if os.path.exists("/.dockerenv"):
            specialized_features.add("docker")

        # Check for Kubernetes
        if os.getenv("KUBERNETES_SERVICE_HOST"):
            specialized_features.add("kubernetes")

        # Check for cloud providers
        if os.getenv("AWS_EXECUTION_ENV"):
            specialized_features.add("aws")
        elif os.getenv("GOOGLE_CLOUD_PROJECT"):
            specialized_features.add("gcp")
        elif os.getenv("AZURE_SUBSCRIPTION_ID"):
            specialized_features.add("azure")

        return InstanceCapabilities(
            cpu_count=cpu_count,
            memory_gb=round(memory_gb, 2),
            gpu_available=gpu_available,
            gpu_count=gpu_count,
            gpu_memory_gb=round(gpu_memory_gb, 2),
            platform=platform_info,
            python_version=python_version,
            specialized_features=specialized_features
        )

    def _calculate_service_ports(self):
        """Calculate service ports based on port offset"""
        base_ports = {
            "api": 8000,
            "ui": 8004,
            "metrics": 9090,
            "health": 8080,
            "grpc": 50051
        }

        self.service_ports = {
            service: base_port + self.port_offset
            for service, base_port in base_ports.items()
        }

    def get_service_port(self, service_name: str) -> int:
        """Get the port for a specific service"""
        return self.service_ports.get(service_name, 0)

    def update_heartbeat(self):
        """Update the last heartbeat timestamp"""
        self.last_heartbeat = datetime.utcnow()

    def get_uptime_seconds(self) -> float:
        """Get instance uptime in seconds"""
        return (datetime.utcnow() - self.started_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert instance identity to dictionary for serialization"""
        return {
            "instance_id": self.instance_id,
            "instance_name": self.instance_name,
            "machine_id": self.machine_id,
            "machine_ip": self.machine_ip,
            "machine_info": self.machine_info.to_dict(),
            "deployment_id": self.deployment_id,
            "role": self.role,
            "port_offset": self.port_offset,
            "started_at": self.started_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "uptime_seconds": self.get_uptime_seconds(),
            "capabilities": self.capabilities.to_dict(),
            "metadata": self.metadata.to_dict(),
            "service_ports": self.service_ports
        }

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstanceIdentity":
        """Create instance identity from dictionary"""
        instance = cls(
            instance_name=data.get("instance_name"),
            role=data.get("role", "standalone"),
            port_offset=data.get("port_offset", 0)
        )

        # Restore specific fields
        if "instance_id" in data:
            instance.instance_id = data["instance_id"]
        if "deployment_id" in data:
            instance.deployment_id = data["deployment_id"]
        if "started_at" in data:
            instance.started_at = datetime.fromisoformat(data["started_at"])
        if "last_heartbeat" in data:
            instance.last_heartbeat = datetime.fromisoformat(data["last_heartbeat"])
        if "capabilities" in data:
            instance.capabilities = InstanceCapabilities.from_dict(data["capabilities"])
        if "metadata" in data:
            instance.metadata = InstanceMetadata.from_dict(data["metadata"])
        if "machine_info" in data:
            instance.machine_info = MachineInfo.from_dict(data["machine_info"])
        if "service_ports" in data:
            instance.service_ports = data["service_ports"]

        return instance

    def get_redis_namespace(self) -> str:
        """Get Redis namespace for this instance"""
        return f"gleitzeit:{self.instance_name}"

    def get_fingerprint(self) -> str:
        """Get a fingerprint hash of this instance"""
        data = f"{self.instance_id}:{self.machine_id}:{self.deployment_id}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def get_machine_fingerprint(self) -> str:
        """Get the machine's hardware fingerprint"""
        return self.machine_info.machine_fingerprint

    def is_same_machine(self, other_instance: 'InstanceIdentity') -> bool:
        """Check if another instance is on the same machine"""
        return self.machine_info.machine_fingerprint == other_instance.machine_info.machine_fingerprint

    def is_same_datacenter(self, other_instance: 'InstanceIdentity') -> bool:
        """Check if another instance is in the same datacenter"""
        return self.machine_info.datacenter == other_instance.machine_info.datacenter

    def is_same_network_zone(self, other_instance: 'InstanceIdentity') -> bool:
        """Check if another instance is in the same network zone"""
        return self.machine_info.network_zone == other_instance.machine_info.network_zone

    def can_communicate_with(self, other_instance: 'InstanceIdentity') -> bool:
        """Check if this instance can communicate with another based on network tags"""
        # Check if they share any network tags
        return bool(self.metadata.network_tags & other_instance.metadata.network_tags)

    def __str__(self) -> str:
        """String representation"""
        return f"Instance({self.instance_name}, role={self.role}, id={self.instance_id[:8]})"

    def __repr__(self) -> str:
        """Detailed representation"""
        return (f"InstanceIdentity(name={self.instance_name}, "
                f"id={self.instance_id}, machine={self.machine_id}, "
                f"role={self.role}, uptime={self.get_uptime_seconds():.0f}s)")


# Singleton instance holder
_current_instance: Optional[InstanceIdentity] = None


def get_current_instance() -> Optional[InstanceIdentity]:
    """Get the current instance identity (if initialized)"""
    return _current_instance


def initialize_instance(instance_name: Optional[str] = None,
                        role: str = "standalone",
                        port_offset: int = 0) -> InstanceIdentity:
    """Initialize and set the current instance identity"""
    global _current_instance
    _current_instance = InstanceIdentity(instance_name, role, port_offset)
    return _current_instance