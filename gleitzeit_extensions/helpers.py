"""
Helper Functions

Convenience functions for integrating extensions with Gleitzeit clusters.
"""

from typing import List, Optional, Dict, Any

from .manager import ExtensionManager, auto_discover_and_load_extensions


def create_cluster_with_extensions(
    search_paths: Optional[List[str]] = None,
    extensions: Optional[List[str]] = None,
    extension_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    **cluster_kwargs
):
    """
    Create Gleitzeit cluster with extension support
    
    Args:
        search_paths: Paths to search for extensions
        extensions: List of extension names to load
        extension_configs: Configuration for each extension
        **cluster_kwargs: Arguments passed to GleitzeitCluster constructor
        
    Returns:
        Tuple of (cluster, extension_manager)
        
    Example:
        cluster, ext_manager = create_cluster_with_extensions(
            search_paths=["./extensions", "./custom_providers"],
            extensions=["openai", "claude"],
            extension_configs={
                "openai": {"api_key": "your-key-here"},
                "claude": {"api_key": "your-claude-key"}
            }
        )
    """
    from gleitzeit_cluster.core.cluster import GleitzeitCluster
    
    # Create extension manager and discover extensions
    extension_manager = auto_discover_and_load_extensions(search_paths)
    
    # Create cluster
    cluster = GleitzeitCluster(**cluster_kwargs)
    
    # Attach extension manager to cluster
    extension_manager.attach_to_cluster(cluster)
    
    # Load requested extensions
    if extensions:
        extension_configs = extension_configs or {}
        
        for ext_name in extensions:
            config = extension_configs.get(ext_name, {})
            try:
                extension_manager.load_extension(ext_name, **config)
                print(f"✅ Loaded extension: {ext_name}")
            except Exception as e:
                print(f"❌ Failed to load extension '{ext_name}': {e}")
    
    return cluster, extension_manager


async def start_cluster_with_extensions(
    cluster,
    extension_manager: ExtensionManager,
    start_extensions: bool = True
):
    """
    Start cluster and extensions together
    
    Args:
        cluster: Gleitzeit cluster instance
        extension_manager: Extension manager instance
        start_extensions: Whether to start all loaded extensions
        
    Example:
        cluster, ext_manager = create_cluster_with_extensions(...)
        await start_cluster_with_extensions(cluster, ext_manager)
    """
    print("🚀 Starting cluster with extensions...")
    
    # Start cluster first
    if hasattr(cluster, 'start') and callable(cluster.start):
        print("🔄 Starting cluster...")
        if hasattr(cluster, 'start'):
            await cluster.start()
    
    # Start extensions if requested
    if start_extensions:
        print("🔄 Starting extensions...")
        await extension_manager.start_all_extensions()
    
    print("✅ Cluster and extensions started successfully")


async def stop_cluster_with_extensions(
    cluster,
    extension_manager: ExtensionManager,
    stop_extensions: bool = True
):
    """
    Stop cluster and extensions gracefully
    
    Args:
        cluster: Gleitzeit cluster instance
        extension_manager: Extension manager instance
        stop_extensions: Whether to stop all running extensions
    """
    print("🛑 Stopping cluster with extensions...")
    
    # Stop extensions first
    if stop_extensions:
        print("🔄 Stopping extensions...")
        await extension_manager.stop_all_extensions()
    
    # Stop cluster
    if hasattr(cluster, 'stop') and callable(cluster.stop):
        print("🔄 Stopping cluster...")
        if hasattr(cluster, 'stop'):
            await cluster.stop()
    
    print("✅ Cluster and extensions stopped successfully")


def get_available_models(extension_manager: ExtensionManager) -> Dict[str, Dict[str, Any]]:
    """
    Get all available models from loaded extensions
    
    Args:
        extension_manager: Extension manager instance
        
    Returns:
        Dictionary mapping model names to extension and model info
        
    Example:
        models = get_available_models(ext_manager)
        print(models)
        # {
        #   "gpt-4": {"extension": "openai", "capabilities": ["text", "vision"]},
        #   "claude-3": {"extension": "claude", "capabilities": ["text"]}
        # }
    """
    models = {}
    
    for ext_name, ext_info in extension_manager.list_available().items():
        for model in ext_info.meta.models:
            model_name = model.get('name')
            if model_name:
                models[model_name] = {
                    "extension": ext_name,
                    "capabilities": model.get('capabilities', []),
                    "max_tokens": model.get('max_tokens'),
                    "cost_per_token": model.get('cost_per_token'),
                    "metadata": {k: v for k, v in model.items() if k not in ['name', 'capabilities', 'max_tokens', 'cost_per_token']}
                }
    
    return models


def get_extensions_by_capability(
    extension_manager: ExtensionManager, 
    capability: str
) -> List[str]:
    """
    Find extensions that support a specific capability
    
    Args:
        extension_manager: Extension manager instance
        capability: Capability to search for
        
    Returns:
        List of extension names supporting the capability
        
    Example:
        streaming_extensions = get_extensions_by_capability(ext_manager, "streaming")
    """
    matching_extensions = extension_manager.registry.list_by_capability(capability)
    return list(matching_extensions.keys())


def validate_all_dependencies(extension_manager: ExtensionManager) -> Dict[str, Dict[str, Any]]:
    """
    Validate dependencies for all registered extensions
    
    Args:
        extension_manager: Extension manager instance
        
    Returns:
        Dictionary with validation results for each extension
        
    Example:
        results = validate_all_dependencies(ext_manager)
        for ext_name, result in results.items():
            if not result['valid']:
                print(f"Extension {ext_name} missing: {result['missing']}")
    """
    results = {}
    
    for ext_name in extension_manager.list_available():
        try:
            valid, missing = extension_manager.registry.validate_dependencies(ext_name)
            results[ext_name] = {
                "valid": valid,
                "missing": missing
            }
        except Exception as e:
            results[ext_name] = {
                "valid": False,
                "error": str(e),
                "missing": []
            }
    
    return results


def create_extension_summary_report(extension_manager: ExtensionManager) -> str:
    """
    Generate a human-readable summary report of extensions
    
    Args:
        extension_manager: Extension manager instance
        
    Returns:
        Formatted string report
    """
    summary = extension_manager.get_summary()
    available = extension_manager.list_available()
    loaded = extension_manager.list_loaded()
    models = get_available_models(extension_manager)
    
    report = []
    report.append("🔧 Gleitzeit Extensions Summary")
    report.append("=" * 40)
    report.append(f"Total Extensions: {summary['available_extensions']}")
    report.append(f"Loaded Extensions: {summary['loaded_extensions']}")
    report.append(f"Running Services: {summary['running_services']}")
    report.append(f"Available Models: {len(models)}")
    report.append("")
    
    # Extension details
    if available:
        report.append("📦 Available Extensions:")
        for name, info in available.items():
            status = "🟢 loaded" if name in loaded else "⚫ available"
            report.append(f"  - {name} ({info.type}) - {status}")
            report.append(f"    {info.meta.description}")
            if info.meta.models:
                model_names = [m.get('name', 'unknown') for m in info.meta.models]
                report.append(f"    Models: {', '.join(model_names)}")
            if info.meta.capabilities:
                report.append(f"    Capabilities: {', '.join(info.meta.capabilities)}")
            report.append("")
    
    # Model summary
    if models:
        report.append("🤖 Available Models:")
        for model_name, model_info in models.items():
            caps = ", ".join(model_info['capabilities']) if model_info['capabilities'] else "none"
            report.append(f"  - {model_name} (via {model_info['extension']}) - {caps}")
        report.append("")
    
    return "\n".join(report)


# Convenience aliases for backward compatibility
create_cluster = create_cluster_with_extensions
start_cluster = start_cluster_with_extensions
stop_cluster = stop_cluster_with_extensions