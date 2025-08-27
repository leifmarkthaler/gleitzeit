"""
Service Discovery Module

Automatic service discovery with port scanning, DNS resolution,
and Kubernetes integration for finding provider endpoints.
"""

import asyncio
import aiohttp
import json
import os
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Information about a discovered service"""
    url: str
    service_type: str
    version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    discovered_at: Optional[datetime] = None
    priority: int = 0
    weight: int = 100


class ServiceDiscovery:
    """
    Automatic service discovery for providers.
    
    Supports multiple discovery methods:
    - Port range scanning
    - Environment variables
    - DNS/SRV records
    - Kubernetes services
    - Static configuration
    """
    
    def __init__(self):
        self.discovered_services = {}
        self.cache_ttl = 300  # 5 minutes
        
        # Common port ranges for different services
        self.port_ranges = {
            'vllm': (8000, 8010),
            'ollama': (11434, 11444),
            'openai': (8080, 8090),
            'llamacpp': (8080, 8100),
            'textgen': (5000, 5010),
            'huggingface': (8000, 8020),
            'custom': (8000, 9000),
            'http': (8000, 8100)
        }
        
        # Service-specific health and info endpoints
        self.service_endpoints = {
            'vllm': {
                'health': '/health',
                'models': '/v1/models',
                'info': '/v1/models'
            },
            'ollama': {
                'health': '/api/tags',
                'models': '/api/tags',
                'info': '/api/version'
            },
            'openai': {
                'health': '/v1/models',
                'models': '/v1/models',
                'info': '/v1/models'
            },
            'llamacpp': {
                'health': '/health',
                'models': '/v1/models',
                'info': '/props'
            }
        }
    
    async def discover_service(
        self,
        service_type: str,
        host: str = "localhost",
        port_range: Optional[Tuple[int, int]] = None,
        force_refresh: bool = False
    ) -> Optional[ServiceInfo]:
        """
        Discover a service endpoint automatically.
        
        Args:
            service_type: Type of service (vllm, ollama, openai, etc.)
            host: Host to scan (default: localhost)
            port_range: Custom port range to scan
            force_refresh: Skip cache and force fresh discovery
            
        Returns:
            ServiceInfo if found, None otherwise
        """
        cache_key = f"{service_type}:{host}"
        
        # Check cache first (unless forced refresh)
        if not force_refresh and cache_key in self.discovered_services:
            cached_service = self.discovered_services[cache_key]
            if self._is_cache_valid(cached_service):
                # Verify cached service is still alive
                if await self._verify_service_health(cached_service):
                    logger.debug(f"Using cached discovery for {service_type} at {cached_service.url}")
                    return cached_service
                else:
                    logger.info(f"Cached service {cached_service.url} is no longer healthy, rediscovering")
                    del self.discovered_services[cache_key]
        
        logger.info(f"Discovering {service_type} service on {host}...")
        
        # Try discovery methods in order of preference
        discovered = None
        
        # 1. Environment variables
        discovered = await self._discover_from_env(service_type, host)
        if discovered:
            logger.info(f"Found {service_type} via environment: {discovered.url}")
        
        # 2. Port scanning
        if not discovered:
            discovered = await self._discover_by_port_scan(service_type, host, port_range)
            if discovered:
                logger.info(f"Found {service_type} via port scan: {discovered.url}")
        
        # 3. DNS/SRV records (if available)
        if not discovered:
            discovered = await self._discover_by_dns(service_type, host)
            if discovered:
                logger.info(f"Found {service_type} via DNS: {discovered.url}")
        
        # 4. Kubernetes services (if in cluster)
        if not discovered:
            discovered = await self._discover_by_kubernetes(service_type)
            if discovered:
                logger.info(f"Found {service_type} via Kubernetes: {discovered.url}")
        
        if discovered:
            # Cache the result
            discovered.discovered_at = datetime.utcnow()
            self.discovered_services[cache_key] = discovered
            
            logger.info(f"Successfully discovered {service_type}: {discovered.url}")
            return discovered
        else:
            logger.warning(f"Could not discover {service_type} service on {host}")
            return None
    
    async def _discover_from_env(self, service_type: str, host: str) -> Optional[ServiceInfo]:
        """Try to find service from environment variables"""
        # Check common environment variable patterns
        env_vars = [
            f"{service_type.upper()}_URL",
            f"{service_type.upper()}_ENDPOINT",
            f"{service_type.upper()}_HOST",
            f"{service_type.upper()}_BASE_URL"
        ]
        
        for env_var in env_vars:
            url = os.getenv(env_var)
            if url:
                # Validate the URL
                if await self._verify_service_endpoint(url, service_type):
                    return ServiceInfo(
                        url=url,
                        service_type=service_type,
                        metadata={"discovery_method": "environment", "env_var": env_var}
                    )
        
        return None
    
    async def _discover_by_port_scan(
        self,
        service_type: str,
        host: str,
        custom_port_range: Optional[Tuple[int, int]] = None
    ) -> Optional[ServiceInfo]:
        """Discover service by scanning port range"""
        
        # Use custom range or default for service type
        port_range = custom_port_range or self.port_ranges.get(service_type, (8000, 9000))
        
        logger.debug(f"Scanning ports {port_range[0]}-{port_range[1]} on {host} for {service_type}")
        
        # Create scanning tasks for parallel execution
        scan_tasks = []
        for port in range(port_range[0], port_range[1] + 1):
            url = f"http://{host}:{port}"
            scan_tasks.append(self._check_service_endpoint(url, service_type))
        
        # Execute scans in parallel with reasonable concurrency
        semaphore = asyncio.Semaphore(20)  # Limit concurrent connections
        
        async def scan_with_semaphore(task):
            async with semaphore:
                return await task
        
        # Wait for all scans to complete
        results = await asyncio.gather(
            *[scan_with_semaphore(task) for task in scan_tasks],
            return_exceptions=True
        )
        
        # Find first successful result
        for result in results:
            if isinstance(result, ServiceInfo):
                result.metadata = {"discovery_method": "port_scan"}
                return result
        
        return None
    
    async def _check_service_endpoint(self, url: str, service_type: str) -> Optional[ServiceInfo]:
        """Check if URL hosts the expected service type"""
        try:
            # First, basic connectivity check
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                    if response.status >= 500:
                        return None
            
            # Then, service-specific verification
            if await self._verify_service_type(url, service_type):
                # Get additional service info
                version = await self._get_service_version(url, service_type)
                capabilities = await self._get_service_capabilities(url, service_type)
                
                return ServiceInfo(
                    url=url,
                    service_type=service_type,
                    version=version,
                    capabilities=capabilities
                )
                
        except Exception as e:
            logger.debug(f"Failed to check {url}: {e}")
            return None
    
    async def _verify_service_type(self, url: str, expected_type: str) -> bool:
        """Verify that the service at URL is of the expected type"""
        endpoints = self.service_endpoints.get(expected_type, {})
        
        try:
            async with aiohttp.ClientSession() as session:
                # Try service-specific endpoints
                for endpoint_type, path in endpoints.items():
                    try:
                        async with session.get(f"{url}{path}", timeout=aiohttp.ClientTimeout(total=3)) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                # Service-specific validation
                                if expected_type == 'vllm':
                                    # vLLM returns model list in specific format
                                    return "data" in data and isinstance(data.get("data"), list)
                                elif expected_type == 'ollama':
                                    # Ollama returns models array
                                    return "models" in data and isinstance(data.get("models"), list)
                                elif expected_type == 'openai':
                                    # OpenAI API format
                                    return "data" in data and isinstance(data.get("data"), list)
                                elif expected_type == 'llamacpp':
                                    # llama.cpp specific responses
                                    return True  # Basic connectivity is enough
                                else:
                                    # Generic HTTP service
                                    return True
                    except:
                        continue
                        
        except Exception as e:
            logger.debug(f"Service verification failed for {url}: {e}")
            
        return False
    
    async def _get_service_version(self, url: str, service_type: str) -> Optional[str]:
        """Get service version information"""
        endpoints = self.service_endpoints.get(service_type, {})
        info_endpoint = endpoints.get('info')
        
        if not info_endpoint:
            return None
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}{info_endpoint}", timeout=aiohttp.ClientTimeout(total=3)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extract version based on service type
                        if service_type == 'ollama':
                            return data.get('version')
                        elif service_type == 'vllm':
                            # vLLM doesn't have direct version endpoint, extract from response
                            return "unknown"
                        else:
                            return data.get('version', 'unknown')
        except:
            pass
            
        return None
    
    async def _get_service_capabilities(self, url: str, service_type: str) -> Optional[List[str]]:
        """Get service capabilities (e.g., available models)"""
        endpoints = self.service_endpoints.get(service_type, {})
        models_endpoint = endpoints.get('models')
        
        if not models_endpoint:
            return None
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}{models_endpoint}", timeout=aiohttp.ClientTimeout(total=3)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extract model names based on service type
                        if service_type == 'vllm' or service_type == 'openai':
                            return [model.get('id') for model in data.get('data', [])]
                        elif service_type == 'ollama':
                            return [model.get('name') for model in data.get('models', [])]
                        else:
                            return []
        except:
            pass
            
        return None
    
    async def _discover_by_dns(self, service_type: str, host: str) -> Optional[ServiceInfo]:
        """Discover service using DNS/SRV records"""
        try:
            # Try to import aiodns (optional dependency)
            import aiodns
            
            resolver = aiodns.DNSResolver()
            
            # Try SRV record lookup
            srv_queries = [
                f"_{service_type}._tcp.{host}",
                f"_gleitzeit-{service_type}._tcp.{host}",
                f"_http._tcp.{host}"
            ]
            
            for query in srv_queries:
                try:
                    srv_records = await resolver.query(query, 'SRV')
                    for record in srv_records:
                        url = f"http://{record.host}:{record.port}"
                        if await self._verify_service_endpoint(url, service_type):
                            return ServiceInfo(
                                url=url,
                                service_type=service_type,
                                priority=record.priority,
                                weight=record.weight,
                                metadata={"discovery_method": "dns_srv", "query": query}
                            )
                except:
                    continue
                    
        except ImportError:
            logger.debug("aiodns not available, skipping DNS discovery")
        except Exception as e:
            logger.debug(f"DNS discovery failed: {e}")
            
        return None
    
    async def _discover_by_kubernetes(self, service_type: str) -> Optional[ServiceInfo]:
        """Discover service in Kubernetes cluster"""
        try:
            # Check if we're in a Kubernetes cluster
            if not os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount'):
                return None
            
            # Try to import Kubernetes client (optional dependency)
            from kubernetes import client, config
            
            try:
                # Try in-cluster config first
                config.load_incluster_config()
            except:
                # Fall back to local kubectl config
                config.load_kube_config()
            
            v1 = client.CoreV1Api()
            
            # Look for services with specific labels
            label_selectors = [
                f"app=gleitzeit-{service_type}",
                f"service-type={service_type}",
                f"app={service_type}",
                "app=gleitzeit,type=provider"
            ]
            
            for selector in label_selectors:
                try:
                    services = v1.list_service_for_all_namespaces(label_selector=selector)
                    
                    for svc in services.items:
                        if svc.spec.ports:
                            port = svc.spec.ports[0].port
                            namespace = svc.metadata.namespace
                            name = svc.metadata.name
                            
                            # Build service URL
                            url = f"http://{name}.{namespace}.svc.cluster.local:{port}"
                            
                            if await self._verify_service_endpoint(url, service_type):
                                return ServiceInfo(
                                    url=url,
                                    service_type=service_type,
                                    metadata={
                                        "discovery_method": "kubernetes",
                                        "namespace": namespace,
                                        "service_name": name,
                                        "labels": svc.metadata.labels
                                    }
                                )
                except Exception as e:
                    logger.debug(f"K8s service discovery failed for selector {selector}: {e}")
                    continue
                    
        except ImportError:
            logger.debug("Kubernetes client not available, skipping K8s discovery")
        except Exception as e:
            logger.debug(f"Kubernetes discovery failed: {e}")
            
        return None
    
    async def _verify_service_endpoint(self, url: str, service_type: str) -> bool:
        """Verify that a URL hosts a working service of the expected type"""
        return await self._verify_service_type(url, service_type)
    
    async def _verify_service_health(self, service_info: ServiceInfo) -> bool:
        """Verify that a discovered service is still healthy"""
        try:
            endpoints = self.service_endpoints.get(service_info.service_type, {})
            health_endpoint = endpoints.get('health', '/health')
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{service_info.url}{health_endpoint}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status < 500
        except:
            return False
    
    def _is_cache_valid(self, service_info: ServiceInfo) -> bool:
        """Check if cached service info is still valid"""
        if not service_info.discovered_at:
            return False
        
        age = datetime.utcnow() - service_info.discovered_at
        return age < timedelta(seconds=self.cache_ttl)
    
    async def discover_all_services(
        self,
        hosts: List[str] = None,
        service_types: List[str] = None
    ) -> Dict[str, List[ServiceInfo]]:
        """
        Discover all available services across multiple hosts and types.
        
        Args:
            hosts: List of hosts to scan (default: ['localhost'])
            service_types: List of service types to look for (default: all known types)
            
        Returns:
            Dictionary mapping service types to lists of discovered services
        """
        if hosts is None:
            hosts = ['localhost']
        if service_types is None:
            service_types = list(self.port_ranges.keys())
        
        results = {}
        
        # Create discovery tasks
        tasks = []
        for host in hosts:
            for service_type in service_types:
                task = self.discover_service(service_type, host)
                tasks.append((service_type, task))
        
        # Execute all discoveries in parallel
        discoveries = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )
        
        # Organize results
        for (service_type, _), result in zip(tasks, discoveries):
            if isinstance(result, ServiceInfo):
                if service_type not in results:
                    results[service_type] = []
                results[service_type].append(result)
        
        return results
    
    def clear_cache(self):
        """Clear the discovery cache"""
        self.discovered_services.clear()
        logger.info("Service discovery cache cleared")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the discovery cache"""
        cache_info = {}
        for key, service in self.discovered_services.items():
            age = datetime.utcnow() - service.discovered_at if service.discovered_at else None
            cache_info[key] = {
                "url": service.url,
                "service_type": service.service_type,
                "discovered_at": service.discovered_at.isoformat() if service.discovered_at else None,
                "age_seconds": age.total_seconds() if age else None,
                "valid": self._is_cache_valid(service)
            }
        
        return {
            "cached_services": cache_info,
            "cache_ttl_seconds": self.cache_ttl,
            "total_cached": len(self.discovered_services)
        }


# Global discovery instance
_discovery = ServiceDiscovery()


# Convenience functions
async def discover_service(
    service_type: str,
    host: str = "localhost",
    port_range: Optional[Tuple[int, int]] = None,
    force_refresh: bool = False
) -> Optional[ServiceInfo]:
    """
    Convenience function to discover a single service.
    
    Example:
        service = await discover_service("vllm")
        if service:
            print(f"Found vLLM at {service.url}")
    """
    return await _discovery.discover_service(service_type, host, port_range, force_refresh)


async def discover_all_services(
    hosts: List[str] = None,
    service_types: List[str] = None
) -> Dict[str, List[ServiceInfo]]:
    """
    Convenience function to discover all services.
    
    Example:
        services = await discover_all_services()
        for service_type, service_list in services.items():
            print(f"Found {len(service_list)} {service_type} services")
    """
    return await _discovery.discover_all_services(hosts, service_types)


def get_discovery_cache_info() -> Dict[str, Any]:
    """Get information about the global discovery cache"""
    return _discovery.get_cache_info()


def clear_discovery_cache():
    """Clear the global discovery cache"""
    _discovery.clear_cache()