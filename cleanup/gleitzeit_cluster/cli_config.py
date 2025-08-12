#!/usr/bin/env python3
"""
Gleitzeit CLI - Configuration Management

Commands for managing provider configurations
"""

import asyncio
import json
import logging
import yaml
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def config_command_handler(args) -> None:
    """Handle configuration management commands"""
    
    if args.config_command == 'show':
        await show_config(args)
    elif args.config_command == 'validate':
        await validate_config(args)
    elif args.config_command == 'create':
        await create_config(args)
    elif args.config_command == 'providers':
        await list_config_providers(args)
    else:
        print(f"Unknown config command: {args.config_command}")


async def show_config(args) -> None:
    """Show current configuration"""
    
    config_file = args.config_file or "config/providers.yaml"
    config_path = Path(config_file)
    
    if not config_path.exists():
        print(f"❌ Configuration file not found: {config_path}")
        return
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        print(f"📋 Configuration: {config_path}")
        print("=" * 50)
        
        # Global settings
        if 'global' in config:
            print("🌍 Global Settings:")
            for key, value in config['global'].items():
                print(f"   {key}: {value}")
            print()
        
        # Providers
        if 'providers' in config:
            providers = config['providers']
            enabled_count = sum(1 for p in providers.values() if p.get('enabled', True))
            
            print(f"🔧 Providers ({len(providers)} total, {enabled_count} enabled):")
            
            for name, provider_config in providers.items():
                enabled = "✅" if provider_config.get('enabled', True) else "❌"
                provider_type = provider_config.get('type', 'unknown').upper()
                description = provider_config.get('description', 'No description')
                
                print(f"   {enabled} {name} ({provider_type})")
                print(f"      {description}")
                
                if 'config' in provider_config:
                    config_keys = list(provider_config['config'].keys())
                    print(f"      Config: {', '.join(config_keys[:5])}")
                    if len(config_keys) > 5:
                        print(f"              +{len(config_keys) - 5} more")
                print()
        
    except Exception as e:
        print(f"❌ Error reading configuration: {e}")


async def validate_config(args) -> None:
    """Validate configuration file"""
    
    config_file = args.config_file or "config/providers.yaml"
    config_path = Path(config_file)
    
    print(f"🔍 Validating configuration: {config_path}")
    print("=" * 40)
    
    if not config_path.exists():
        print(f"❌ Configuration file not found: {config_path}")
        return
    
    errors = []
    warnings = []
    
    try:
        # Load and parse YAML
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        print("✅ YAML syntax is valid")
        
        # Validate structure
        if not isinstance(config, dict):
            errors.append("Configuration must be a dictionary")
        else:
            # Check required sections
            if 'providers' not in config:
                warnings.append("No 'providers' section found")
            
            # Validate providers
            if 'providers' in config:
                providers = config['providers']
                if not isinstance(providers, dict):
                    errors.append("'providers' must be a dictionary")
                else:
                    for name, provider_config in providers.items():
                        provider_errors = _validate_provider_config(name, provider_config)
                        errors.extend(provider_errors)
            
            # Validate global config
            if 'global' in config:
                global_config = config['global']
                if not isinstance(global_config, dict):
                    warnings.append("'global' section should be a dictionary")
        
        # Report results
        if errors:
            print(f"\n❌ {len(errors)} error(s) found:")
            for error in errors:
                print(f"   • {error}")
        else:
            print("✅ Configuration is valid")
        
        if warnings:
            print(f"\n⚠️  {len(warnings)} warning(s):")
            for warning in warnings:
                print(f"   • {warning}")
        
    except yaml.YAMLError as e:
        print(f"❌ YAML syntax error: {e}")
    except Exception as e:
        print(f"❌ Error validating configuration: {e}")


def _validate_provider_config(name: str, config: Dict[str, Any]) -> list:
    """Validate a single provider configuration"""
    errors = []
    
    # Check required fields
    if 'class' not in config:
        errors.append(f"Provider '{name}': missing required 'class' field")
    
    if 'type' not in config:
        errors.append(f"Provider '{name}': missing 'type' field")
    elif config['type'] not in ['llm', 'tool', 'extension']:
        errors.append(f"Provider '{name}': invalid type '{config['type']}', must be 'llm', 'tool', or 'extension'")
    
    # Check config section
    if 'config' in config:
        provider_config = config['config']
        if not isinstance(provider_config, dict):
            errors.append(f"Provider '{name}': 'config' must be a dictionary")
        elif 'name' not in provider_config:
            errors.append(f"Provider '{name}': 'config.name' is required")
    
    return errors


async def create_config(args) -> None:
    """Create a new configuration file"""
    
    config_file = args.config_file or "config/providers.yaml"
    config_path = Path(config_file)
    
    print(f"📝 Creating configuration file: {config_path}")
    
    if config_path.exists() and not args.force:
        print(f"❌ Configuration file already exists. Use --force to overwrite.")
        return
    
    # Create directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create template configuration
    template = {
        'providers': {
            'ollama': {
                'enabled': True,
                'type': 'llm',
                'class': 'my_local_llm_provider.OllamaProvider',
                'config': {
                    'name': 'ollama',
                    'ollama_url': 'http://localhost:11434',
                    'server_url': 'http://localhost:8000'
                },
                'description': 'Local Ollama LLM models',
                'auto_discover_models': True
            },
            'local_tools': {
                'enabled': False,
                'type': 'tool',
                'class': 'providers.tool_provider.LocalToolsProvider',
                'config': {
                    'name': 'local-tools',
                    'server_url': 'http://localhost:8000'
                },
                'description': 'Local utility tools'
            }
        },
        'global': {
            'auto_start': True,
            'auto_restart': True,
            'health_check_interval': 30,
            'connection_timeout': 10,
            'max_retry_attempts': 3,
            'default_server_url': 'http://localhost:8000'
        }
    }
    
    try:
        with open(config_path, 'w') as f:
            yaml.dump(template, f, default_flow_style=False, indent=2)
        
        print(f"✅ Created configuration file: {config_path}")
        print("💡 Edit the file to customize your providers")
        
    except Exception as e:
        print(f"❌ Error creating configuration file: {e}")


async def list_config_providers(args) -> None:
    """List providers from configuration file"""
    
    config_file = args.config_file or "config/providers.yaml"
    config_path = Path(config_file)
    
    if not config_path.exists():
        print(f"❌ Configuration file not found: {config_path}")
        return
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        providers = config.get('providers', {})
        
        if not providers:
            print("📭 No providers configured")
            return
        
        enabled_providers = [name for name, cfg in providers.items() if cfg.get('enabled', True)]
        disabled_providers = [name for name, cfg in providers.items() if not cfg.get('enabled', True)]
        
        print(f"📋 Configured Providers: {config_path}")
        print("=" * 50)
        
        if enabled_providers:
            print(f"✅ Enabled ({len(enabled_providers)}):")
            for name in enabled_providers:
                provider_config = providers[name]
                provider_type = provider_config.get('type', 'unknown').upper()
                description = provider_config.get('description', 'No description')
                print(f"   • {name} ({provider_type}): {description}")
        
        if disabled_providers:
            print(f"\n❌ Disabled ({len(disabled_providers)}):")
            for name in disabled_providers:
                provider_config = providers[name]
                provider_type = provider_config.get('type', 'unknown').upper()
                description = provider_config.get('description', 'No description')
                print(f"   • {name} ({provider_type}): {description}")
        
    except Exception as e:
        print(f"❌ Error reading configuration: {e}")


def add_config_parser(subparsers):
    """Add configuration management commands to CLI"""
    
    config_parser = subparsers.add_parser(
        'config',
        help='Manage provider configurations'
    )
    
    config_subparsers = config_parser.add_subparsers(
        dest='config_command',
        help='Configuration commands'
    )
    
    # Show config
    show_cmd = config_subparsers.add_parser(
        'show',
        help='Show current configuration'
    )
    show_cmd.add_argument('--config-file', help='Configuration file path')
    
    # Validate config
    validate_cmd = config_subparsers.add_parser(
        'validate', 
        help='Validate configuration file'
    )
    validate_cmd.add_argument('--config-file', help='Configuration file path')
    
    # Create config
    create_cmd = config_subparsers.add_parser(
        'create',
        help='Create new configuration file'
    )
    create_cmd.add_argument('--config-file', help='Configuration file path')
    create_cmd.add_argument('--force', action='store_true', 
                           help='Overwrite existing file')
    
    # List providers
    providers_cmd = config_subparsers.add_parser(
        'providers',
        help='List configured providers'
    )
    providers_cmd.add_argument('--config-file', help='Configuration file path')