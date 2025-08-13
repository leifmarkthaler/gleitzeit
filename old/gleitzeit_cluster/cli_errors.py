#!/usr/bin/env python3
"""
Error Management CLI for Gleitzeit

Provides commands for exploring, searching, and understanding the error catalog.
Useful for development, debugging, and documentation.
"""

import sys
import json
from typing import List, Optional, Dict, Any
from enum import Enum
import argparse

from .core.errors import (
    ERROR_CATALOG, ErrorCode, ErrorDomain, ErrorDefinition, 
    get_errors_by_domain, get_errors_by_severity, get_errors_by_category,
    search_errors, get_related_errors, get_error_statistics,
    validate_error_catalog
)
from .core.error_handling import ErrorSeverity, ErrorCategory


class OutputFormat(Enum):
    TABLE = "table"
    JSON = "json"
    YAML = "yaml"
    MARKDOWN = "markdown"


def format_error_table(errors: List[ErrorDefinition], show_details: bool = False) -> str:
    """Format errors as a table"""
    if not errors:
        return "No errors found."
    
    # Header
    if show_details:
        header = f"{'Code':<8} {'Domain':<12} {'Severity':<8} {'Category':<12} {'Message':<50} {'Hint':<30}"
        separator = "-" * len(header)
    else:
        header = f"{'Code':<8} {'Domain':<12} {'Severity':<8} {'Message':<60}"
        separator = "-" * len(header)
    
    lines = [header, separator]
    
    for error in errors:
        message = error.message[:57] + "..." if len(error.message) > 60 else error.message
        
        if show_details:
            hint = (error.resolution_hint[:27] + "..." if error.resolution_hint and len(error.resolution_hint) > 30 
                   else error.resolution_hint or "")
            line = f"{error.code.value:<8} {error.domain.value:<12} {error.severity.value:<8} {error.category.value:<12} {message:<50} {hint:<30}"
        else:
            line = f"{error.code.value:<8} {error.domain.value:<12} {error.severity.value:<8} {message:<60}"
        
        lines.append(line)
    
    return "\n".join(lines)


def format_error_json(errors: List[ErrorDefinition], pretty: bool = True) -> str:
    """Format errors as JSON"""
    error_data = []
    for error in errors:
        data = {
            "code": error.code.value,
            "domain": error.domain.value,
            "message": error.message,
            "category": error.category.value,
            "severity": error.severity.value,
            "user_message": error.user_message,
            "resolution_hint": error.resolution_hint,
            "documentation_url": error.documentation_url,
            "retry_after": error.retry_after,
            "tags": error.tags,
            "related_errors": [e.value for e in error.related_errors] if error.related_errors else None
        }
        error_data.append(data)
    
    if pretty:
        return json.dumps(error_data, indent=2)
    else:
        return json.dumps(error_data)


def format_error_markdown(errors: List[ErrorDefinition]) -> str:
    """Format errors as Markdown"""
    if not errors:
        return "No errors found."
    
    lines = ["# Error Catalog", ""]
    
    # Group by domain
    domains = {}
    for error in errors:
        if error.domain not in domains:
            domains[error.domain] = []
        domains[error.domain].append(error)
    
    for domain, domain_errors in domains.items():
        lines.append(f"## {domain.value.title()} Errors")
        lines.append("")
        
        for error in domain_errors:
            lines.append(f"### {error.code.value}")
            lines.append("")
            lines.append(f"**Message**: {error.message}")
            lines.append(f"**Severity**: {error.severity.value}")
            lines.append(f"**Category**: {error.category.value}")
            
            if error.user_message:
                lines.append(f"**User Message**: {error.user_message}")
            
            if error.resolution_hint:
                lines.append(f"**Resolution**: {error.resolution_hint}")
            
            if error.documentation_url:
                lines.append(f"**Documentation**: [{error.documentation_url}]({error.documentation_url})")
            
            if error.retry_after:
                lines.append(f"**Retry After**: {error.retry_after} seconds")
            
            if error.tags:
                lines.append(f"**Tags**: {', '.join(error.tags)}")
            
            lines.append("")
    
    return "\n".join(lines)


def format_single_error(error: ErrorDefinition, format_type: OutputFormat = OutputFormat.TABLE) -> str:
    """Format a single error with full details"""
    if format_type == OutputFormat.JSON:
        data = {
            "code": error.code.value,
            "domain": error.domain.value,
            "message": error.message,
            "category": error.category.value,
            "severity": error.severity.value,
            "user_message": error.user_message,
            "resolution_hint": error.resolution_hint,
            "documentation_url": error.documentation_url,
            "retry_after": error.retry_after,
            "tags": error.tags,
            "related_errors": [e.value for e in error.related_errors] if error.related_errors else None
        }
        return json.dumps(data, indent=2)
    
    # Default table/text format
    lines = [
        f"Error Code: {error.code.value}",
        f"Domain: {error.domain.value}",
        f"Severity: {error.severity.value}",
        f"Category: {error.category.value}",
        f"Message: {error.message}",
    ]
    
    if error.user_message:
        lines.append(f"User Message: {error.user_message}")
    
    if error.resolution_hint:
        lines.append(f"Resolution Hint: {error.resolution_hint}")
    
    if error.documentation_url:
        lines.append(f"Documentation: {error.documentation_url}")
    
    if error.retry_after:
        lines.append(f"Retry After: {error.retry_after} seconds")
    
    if error.tags:
        lines.append(f"Tags: {', '.join(error.tags)}")
    
    if error.related_errors:
        related = [e.value for e in error.related_errors]
        lines.append(f"Related Errors: {', '.join(related)}")
    
    return "\n".join(lines)


def list_errors_command(args):
    """List errors with optional filtering"""
    errors = list(ERROR_CATALOG.values())
    
    # Apply filters
    if args.domain:
        try:
            domain = ErrorDomain(args.domain)
            errors = get_errors_by_domain(domain)
        except ValueError:
            print(f"Invalid domain: {args.domain}")
            print(f"Available domains: {', '.join([d.value for d in ErrorDomain])}")
            return 1
    
    if args.severity:
        try:
            severity = ErrorSeverity(args.severity)
            errors = [e for e in errors if e.severity == severity]
        except ValueError:
            print(f"Invalid severity: {args.severity}")
            print(f"Available severities: {', '.join([s.value for s in ErrorSeverity])}")
            return 1
    
    if args.category:
        try:
            category = ErrorCategory(args.category)
            errors = [e for e in errors if e.category == category]
        except ValueError:
            print(f"Invalid category: {args.category}")
            print(f"Available categories: {', '.join([c.value for c in ErrorCategory])}")
            return 1
    
    # Sort errors
    if args.sort == "code":
        errors.sort(key=lambda x: x.code.value)
    elif args.sort == "severity":
        severity_order = {ErrorSeverity.LOW: 1, ErrorSeverity.MEDIUM: 2, ErrorSeverity.HIGH: 3, ErrorSeverity.CRITICAL: 4}
        errors.sort(key=lambda x: severity_order[x.severity], reverse=True)
    elif args.sort == "domain":
        errors.sort(key=lambda x: x.domain.value)
    
    # Format output
    if args.format == OutputFormat.JSON.value:
        print(format_error_json(errors))
    elif args.format == OutputFormat.MARKDOWN.value:
        print(format_error_markdown(errors))
    else:
        print(format_error_table(errors, show_details=args.details))
    
    return 0


def show_error_command(args):
    """Show detailed information about a specific error"""
    error_code = args.code.upper()
    
    # Find error by code
    error = None
    for code, definition in ERROR_CATALOG.items():
        if code.value == error_code:
            error = definition
            break
    
    if not error:
        print(f"Error code '{error_code}' not found.")
        print("Use 'gleitzeit errors list' to see available error codes.")
        return 1
    
    # Show error details
    print(format_single_error(error, OutputFormat(args.format)))
    
    # Show related errors if any
    related = get_related_errors(error.code)
    if related:
        print("\nRelated Errors:")
        for related_error in related:
            print(f"  {related_error.code.value}: {related_error.message}")
    
    return 0


def search_errors_command(args):
    """Search errors by query"""
    results = search_errors(args.query)
    
    if not results:
        print(f"No errors found matching '{args.query}'")
        return 1
    
    print(f"Found {len(results)} error(s) matching '{args.query}':")
    print()
    
    if args.format == OutputFormat.JSON.value:
        print(format_error_json(results))
    elif args.format == OutputFormat.MARKDOWN.value:
        print(format_error_markdown(results))
    else:
        print(format_error_table(results, show_details=True))
    
    return 0


def stats_command(args):
    """Show error catalog statistics"""
    stats = get_error_statistics()
    
    if args.format == OutputFormat.JSON.value:
        print(json.dumps(stats, indent=2))
        return 0
    
    print("Error Catalog Statistics")
    print("=" * 25)
    print(f"Total Errors: {stats['total_errors']}")
    print()
    
    print("By Domain:")
    for domain, count in stats['domains'].items():
        print(f"  {domain}: {count}")
    print()
    
    print("By Severity:")
    for severity, count in stats['severities'].items():
        print(f"  {severity}: {count}")
    print()
    
    print("By Category:")
    for category, count in stats['categories'].items():
        print(f"  {category}: {count}")
    print()
    
    print(f"Retryable Errors: {stats['retryable_errors']}")
    print(f"Errors with Documentation: {stats['errors_with_documentation']}")
    print(f"Errors with Resolution Hints: {stats['errors_with_resolution_hints']}")
    
    # Show validation issues if any
    if stats['catalog_validation_issues']:
        print("\nCatalog Issues:")
        for issue in stats['catalog_validation_issues']:
            print(f"  ⚠️  {issue}")
    else:
        print("\n✅ Error catalog validation passed")
    
    return 0


def validate_command(args):
    """Validate error catalog consistency"""
    issues = validate_error_catalog()
    
    if not issues:
        print("✅ Error catalog validation passed")
        print(f"All {len(ERROR_CATALOG)} errors are properly defined")
        return 0
    else:
        print("❌ Error catalog validation failed")
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  • {issue}")
        return 1


def domains_command(args):
    """List available error domains"""
    print("Available Error Domains:")
    print("-" * 25)
    
    for domain in ErrorDomain:
        count = len(get_errors_by_domain(domain))
        print(f"{domain.value:<15} ({count} errors)")
    
    return 0


def errors_command_handler(args):
    """Main handler for error management commands"""
    
    # Create argument parser
    parser = argparse.ArgumentParser(
        prog='gleitzeit errors',
        description='Manage and explore Gleitzeit error catalog'
    )
    
    subparsers = parser.add_subparsers(dest='action', help='Available actions')
    
    # List errors command
    list_parser = subparsers.add_parser('list', help='List errors with optional filtering')
    list_parser.add_argument('--domain', help='Filter by error domain')
    list_parser.add_argument('--severity', help='Filter by severity level')
    list_parser.add_argument('--category', help='Filter by error category')
    list_parser.add_argument('--sort', choices=['code', 'severity', 'domain'], default='code', help='Sort order')
    list_parser.add_argument('--format', choices=[f.value for f in OutputFormat], default='table', help='Output format')
    list_parser.add_argument('--details', action='store_true', help='Show additional details in table format')
    
    # Show error command
    show_parser = subparsers.add_parser('show', help='Show detailed information about specific error')
    show_parser.add_argument('code', help='Error code to show (e.g., GZ1001)')
    show_parser.add_argument('--format', choices=[f.value for f in OutputFormat], default='table', help='Output format')
    
    # Search errors command
    search_parser = subparsers.add_parser('search', help='Search errors by query')
    search_parser.add_argument('query', help='Search query (searches message, code, hints, tags)')
    search_parser.add_argument('--format', choices=[f.value for f in OutputFormat], default='table', help='Output format')
    
    # Statistics command
    stats_parser = subparsers.add_parser('stats', help='Show error catalog statistics')
    stats_parser.add_argument('--format', choices=[f.value for f in OutputFormat], default='table', help='Output format')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate error catalog consistency')
    
    # Domains command
    domains_parser = subparsers.add_parser('domains', help='List available error domains')
    
    # Parse arguments (use the passed args or get from command line)
    if isinstance(args, list):
        parsed_args = parser.parse_args(args)
    else:
        # If called from main CLI, args is already parsed
        parsed_args = args
    
    # Route to appropriate command handler
    if parsed_args.action == 'list':
        return list_errors_command(parsed_args)
    elif parsed_args.action == 'show':
        return show_error_command(parsed_args)
    elif parsed_args.action == 'search':
        return search_errors_command(parsed_args)
    elif parsed_args.action == 'stats':
        return stats_command(parsed_args)
    elif parsed_args.action == 'validate':
        return validate_command(parsed_args)
    elif parsed_args.action == 'domains':
        return domains_command(parsed_args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(errors_command_handler(sys.argv[1:]))