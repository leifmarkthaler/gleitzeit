#!/usr/bin/env python3
"""
Demo script showing how to use the error discovery functionality
to retrieve custom errors from protocols and providers.
"""

import json
from gleitzeit.core.error_discovery import (
    ErrorDiscovery, get_provider_errors, get_protocol_errors,
    get_error_hierarchy, discover_all_errors
)
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec, ParameterSpec, ParameterType
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple import SimpleProvider


def demo_provider_error_discovery():
    """Demonstrate discovering errors from a provider"""
    print("=" * 60)
    print("PROVIDER ERROR DISCOVERY")
    print("=" * 60)

    # Create a provider instance
    provider = PythonProvider(
        provider_id="python-demo",
        protocol_id="python/v1"
    )

    # Get all errors the provider might raise
    errors = get_provider_errors(provider)

    print(f"\nFound {len(errors)} error types for PythonProvider:\n")

    for error in errors:
        print(f"  • {error.name}")
        if error.description:
            print(f"    Description: {error.description.strip()}")
        if error.error_code:
            print(f"    Error Code: {error.error_code.name} ({error.error_code.value})")
        print(f"    Retryable: {error.is_retryable}")
        print(f"    Module: {error.module}")
        print()


def demo_protocol_error_discovery():
    """Demonstrate discovering errors from a protocol"""
    print("=" * 60)
    print("PROTOCOL ERROR DISCOVERY")
    print("=" * 60)

    # Create a protocol specification
    protocol = ProtocolSpec(
        name="demo",
        version="v1",
        description="Demo protocol for error discovery",
        methods={
            "calculate": MethodSpec(
                name="calculate",
                description="Perform calculation that might fail with validation errors",
                params_schema={
                    "x": ParameterSpec(
                        type=ParameterType.NUMBER,
                        description="First operand",
                        minimum=0,
                        maximum=100
                    ),
                    "y": ParameterSpec(
                        type=ParameterType.NUMBER,
                        description="Second operand",
                        minimum=0,
                        maximum=100
                    ),
                    "operation": ParameterSpec(
                        type=ParameterType.STRING,
                        description="Operation to perform",
                        enum=["add", "subtract", "multiply", "divide"]
                    )
                }
            ),
            "process": MethodSpec(
                name="process",
                description="Process data that might timeout or fail",
                params_schema={
                    "data": ParameterSpec(
                        type=ParameterType.STRING,
                        description="Data to process"
                    )
                }
            )
        }
    )

    # Get protocol errors
    errors = get_protocol_errors(protocol)

    print(f"\nFound {len(errors)} error types for protocol '{protocol.protocol_id}':\n")

    for error in errors:
        print(f"  • {error.name}")
        if error.description:
            print(f"    Description: {error.description.strip()}")
        if error.error_code:
            print(f"    Error Code: {error.error_code.name} ({error.error_code.value})")
        print()


def demo_error_hierarchy():
    """Demonstrate getting the complete error hierarchy"""
    print("=" * 60)
    print("ERROR HIERARCHY")
    print("=" * 60)

    hierarchy = get_error_hierarchy()

    def print_hierarchy(node, indent=0):
        """Recursively print the error hierarchy"""
        prefix = "  " * indent

        # Handle both dict nodes and string keys from subclasses
        if isinstance(node, dict):
            class_name = node.get('class', 'Unknown')
            print(f"{prefix}• {class_name}")
            if node.get('error_code_name'):
                print(f"{prefix}  Code: {node['error_code_name']}")
            if node.get('description'):
                desc = node['description'].strip() if node['description'] else ""
                if desc:
                    # Take first line only for brevity
                    first_line = desc.split('\n')[0]
                    if len(first_line) > 60:
                        first_line = first_line[:57] + "..."
                    print(f"{prefix}  {first_line}")

            for subclass_name, subclass_node in node.get('subclasses', {}).items():
                if isinstance(subclass_node, dict):
                    print_hierarchy(subclass_node, indent + 1)

    print("\nGleitzeit Error Hierarchy:\n")
    print_hierarchy(hierarchy)


def demo_all_provider_errors():
    """Demonstrate discovering all provider errors in the system"""
    print("=" * 60)
    print("ALL PROVIDER ERRORS")
    print("=" * 60)

    all_errors = discover_all_errors()

    print(f"\nDiscovered errors from {len(all_errors)} modules:\n")

    for module_name, errors in all_errors.items():
        if errors:  # Only show modules with errors
            print(f"Module: {module_name}")
            print(f"  Found {len(errors)} error types:")

            # Group by base class for better organization
            by_base = {}
            for error in errors:
                base_name = error.base_class.__name__
                if base_name not in by_base:
                    by_base[base_name] = []
                by_base[base_name].append(error)

            for base_name, base_errors in by_base.items():
                print(f"    {base_name} subclasses:")
                for error in base_errors:
                    retryable = "✓" if error.is_retryable else "✗"
                    print(f"      • {error.name} [Retryable: {retryable}]")
            print()


def demo_error_report():
    """Generate a formatted error report"""
    print("=" * 60)
    print("ERROR REPORT")
    print("=" * 60)

    # Get errors from a simple provider
    provider = SimpleProvider(
        provider_id="report-demo",
        protocol_id="demo/v1"
    )
    errors = get_provider_errors(provider)

    # Generate formatted report
    report = ErrorDiscovery.format_error_report(
        errors,
        title=f"Error Report for {provider.__class__.__name__}"
    )

    print("\nFormatted Error Report:\n")
    print(report)


def demo_error_to_json():
    """Demonstrate converting errors to JSON for API responses"""
    print("=" * 60)
    print("ERROR JSON SERIALIZATION")
    print("=" * 60)

    provider = PythonProvider(
        provider_id="json-demo",
        protocol_id="python/v1"
    )
    errors = get_provider_errors(provider)

    # Convert first few errors to JSON-serializable format
    error_list = [error.to_dict() for error in errors[:3]]

    print("\nErrors as JSON:\n")
    print(json.dumps(error_list, indent=2))


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ERROR DISCOVERY DEMO")
    print("=" * 60)
    print("\nThis demo shows how to discover and retrieve custom errors")
    print("from protocols and providers in the Gleitzeit system.\n")

    # Run all demos
    demo_provider_error_discovery()
    print()
    demo_protocol_error_discovery()
    print()
    demo_error_hierarchy()
    print()
    demo_all_provider_errors()
    print()
    demo_error_report()
    print()
    demo_error_to_json()

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)