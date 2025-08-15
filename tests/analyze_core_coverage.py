#!/usr/bin/env python3
"""
Core Architecture Test Coverage Analysis
Analyzes which core components have tests and identifies gaps.
"""

import os
import sys
from pathlib import Path
import importlib.util

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)


def analyze_core_coverage():
    """Analyze test coverage for core architecture components"""
    print("🔍 Gleitzeit V4 Core Architecture Test Coverage Analysis")
    print("=" * 70)
    
    # Define core components
    core_components = {
        'core/models.py': {
            'description': 'Core data models (Task, Workflow, TaskResult)',
            'key_classes': ['Task', 'Workflow', 'TaskResult', 'WorkflowExecution'],
            'key_functions': ['task validation', 'workflow management', 'status tracking']
        },
        'core/execution_engine.py': {
            'description': 'Task execution orchestration',
            'key_classes': ['ExecutionEngine'],
            'key_functions': ['task submission', 'workflow execution', 'provider routing']
        },
        'core/workflow_manager.py': {
            'description': 'Workflow lifecycle management',
            'key_classes': ['WorkflowManager'],
            'key_functions': ['workflow creation', 'template processing', 'execution tracking']
        },
        'core/scheduler.py': {
            'description': 'Event-driven task scheduling',
            'key_classes': ['EventScheduler'],
            'key_functions': ['event scheduling', 'retry management', 'task queuing']
        },
        'core/retry_manager.py': {
            'description': 'Task retry logic and backoff strategies',
            'key_classes': ['RetryManager'],
            'key_functions': ['retry scheduling', 'backoff calculation', 'failure handling']
        },
        'core/dependency_tracker.py': {
            'description': 'Task dependency resolution and tracking',
            'key_classes': ['DependencyTracker'],
            'key_functions': ['dependency resolution', 'circular dependency detection', 'task ordering']
        },
        'core/events.py': {
            'description': 'Event system and coordination',
            'key_classes': ['Event', 'EventBus'],
            'key_functions': ['event publishing', 'event subscription', 'event correlation']
        },
        'core/errors.py': {
            'description': 'Error handling and exception management',
            'key_classes': ['GleitzeitError', 'ValidationError', 'ExecutionError'],
            'key_functions': ['error classification', 'error reporting', 'error recovery']
        },
        'core/jsonrpc.py': {
            'description': 'JSON-RPC 2.0 protocol implementation',
            'key_classes': ['JSONRPCRequest', 'JSONRPCResponse'],
            'key_functions': ['request validation', 'response formatting', 'error handling']
        },
        'core/protocol.py': {
            'description': 'Protocol definition and validation',
            'key_classes': ['Protocol', 'ProtocolValidator'],
            'key_functions': ['protocol registration', 'method validation', 'parameter checking']
        }
    }
    
    # Define persistence components
    persistence_components = {
        'persistence/base.py': {
            'description': 'Base persistence interface',
            'key_classes': ['PersistenceBackend'],
            'key_functions': ['CRUD operations', 'backend abstraction']
        },
        'persistence/redis_backend.py': {
            'description': 'Redis persistence implementation',
            'key_classes': ['RedisBackend'],
            'key_functions': ['Redis operations', 'pub/sub', 'caching']
        },
        'persistence/sqlite_backend.py': {
            'description': 'SQLite persistence implementation', 
            'key_classes': ['SQLiteBackend'],
            'key_functions': ['SQLite operations', 'local storage', 'migration']
        },
        'persistence/inmemory_backend.py': {
            'description': 'In-memory persistence for testing',
            'key_classes': ['InMemoryBackend'],
            'key_functions': ['memory storage', 'fast access', 'testing support']
        }
    }
    
    # Define provider system components  
    provider_components = {
        'providers/base.py': {
            'description': 'Base provider interface',
            'key_classes': ['ProtocolProvider'],
            'key_functions': ['provider lifecycle', 'request handling', 'health checks']
        },
        'providers/ollama_provider.py': {
            'description': 'Ollama LLM provider',
            'key_classes': ['OllamaProvider'],
            'key_functions': ['LLM requests', 'model management', 'streaming']
        },
        'providers/python_function_provider.py': {
            'description': 'Python code execution provider',
            'key_classes': ['PythonFunctionProvider'],
            'key_functions': ['code execution', 'security', 'result handling']
        },
        'providers/mcp_jsonrpc_provider.py': {
            'description': 'MCP JSON-RPC provider',
            'key_classes': ['MCPProvider'],
            'key_functions': ['MCP protocol', 'JSON-RPC routing', 'tool execution']
        }
    }
    
    # Define queue/task management components
    queue_components = {
        'task_queue/task_queue.py': {
            'description': 'Task queue implementation',
            'key_classes': ['TaskQueue'],
            'key_functions': ['task queuing', 'priority handling', 'queue management']
        },
        'task_queue/queue_manager.py': {
            'description': 'Queue management and coordination',
            'key_classes': ['QueueManager'],
            'key_functions': ['multiple queues', 'load balancing', 'queue monitoring']
        },
        'task_queue/dependency_resolver.py': {
            'description': 'Task dependency resolution',
            'key_classes': ['DependencyResolver'],
            'key_functions': ['dependency resolution', 'parameter substitution', 'circular detection']
        }
    }
    
    # Registry system
    registry_components = {
        'registry.py': {
            'description': 'Protocol and provider registry',
            'key_classes': ['ProtocolProviderRegistry'],
            'key_functions': ['provider registration', 'protocol matching', 'load balancing']
        }
    }
    
    all_components = {
        **core_components,
        **persistence_components,
        **provider_components,  
        **queue_components,
        **registry_components
    }
    
    # Find existing test files
    test_dir = Path(current_dir) / 'tests'
    test_files = list(test_dir.glob('test_*.py')) if test_dir.exists() else []
    
    print(f"📂 Found {len(test_files)} test files in tests/ directory")
    print(f"🏗️  Analyzing {len(all_components)} core architecture components")
    print()
    
    # Analyze coverage
    covered_components = []
    partially_covered = []
    not_covered = []
    
    for component_path, info in all_components.items():
        component_name = component_path.split('/')[-1].replace('.py', '')
        
        # Check if component file exists
        full_path = Path(current_dir) / component_path
        if not full_path.exists():
            print(f"⚠️  Component file not found: {component_path}")
            continue
        
        # Look for tests that might cover this component
        potential_tests = []
        for test_file in test_files:
            test_name = test_file.stem.lower()
            component_lower = component_name.lower()
            
            # Direct match
            if component_lower in test_name:
                potential_tests.append(test_file.name)
            # Functional match
            elif any(keyword in test_name for keyword in [
                'execution' if 'execution_engine' in component_lower else '',
                'workflow' if 'workflow' in component_lower else '',
                'retry' if 'retry' in component_lower else '',
                'scheduler' if 'scheduler' in component_lower else '',
                'dependency' if 'dependency' in component_lower else '',
                'queue' if 'queue' in component_lower else '',
                'redis' if 'redis' in component_lower else '',
                'sqlite' if 'sqlite' in component_lower else '',
                'provider' if 'provider' in component_lower else '',
                'ollama' if 'ollama' in component_lower else '',
                'python' if 'python' in component_lower and 'provider' in component_lower else '',
                'mcp' if 'mcp' in component_lower else '',
                'registry' if 'registry' in component_lower else '',
                'jsonrpc' if 'jsonrpc' in component_lower else '',
                'protocol' if 'protocol' in component_lower else '',
                'events' if 'events' in component_lower else '',
                'models' if 'models' in component_lower else ''
            ]):
                potential_tests.append(test_file.name)
        
        # Remove empty strings and deduplicate
        potential_tests = list(set([t for t in potential_tests if t]))
        
        if len(potential_tests) >= 2:
            covered_components.append((component_path, info, potential_tests))
        elif len(potential_tests) == 1:
            partially_covered.append((component_path, info, potential_tests))
        else:
            not_covered.append((component_path, info, potential_tests))
    
    # Report results
    print("📊 TEST COVERAGE ANALYSIS RESULTS")
    print("=" * 50)
    
    total_components = len(all_components)
    well_covered = len(covered_components)
    some_coverage = len(partially_covered)
    no_coverage = len(not_covered)
    
    print(f"📈 Coverage Summary:")
    print(f"  ✅ Well Covered: {well_covered}/{total_components} ({well_covered/total_components*100:.1f}%)")
    print(f"  ⚠️  Partial Coverage: {some_coverage}/{total_components} ({some_coverage/total_components*100:.1f}%)")
    print(f"  ❌ No Coverage: {no_coverage}/{total_components} ({no_coverage/total_components*100:.1f}%)")
    
    overall_coverage = (well_covered + some_coverage * 0.5) / total_components * 100
    print(f"  📊 Overall Coverage Score: {overall_coverage:.1f}%")
    
    # Detailed results
    if covered_components:
        print(f"\n✅ WELL COVERED COMPONENTS ({len(covered_components)}):")
        for component, info, tests in covered_components:
            print(f"  📦 {component}")
            print(f"      {info['description']}")
            print(f"      Tests: {', '.join(tests)}")
    
    if partially_covered:
        print(f"\n⚠️  PARTIALLY COVERED COMPONENTS ({len(partially_covered)}):")
        for component, info, tests in partially_covered:
            print(f"  📦 {component}")
            print(f"      {info['description']}")
            print(f"      Tests: {', '.join(tests) if tests else 'None found'}")
    
    if not_covered:
        print(f"\n❌ NOT COVERED COMPONENTS ({len(not_covered)}):")
        for component, info, tests in not_covered:
            print(f"  📦 {component}")
            print(f"      {info['description']}")
            print(f"      Key functionality: {', '.join(info['key_functions'])}")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    
    if overall_coverage >= 80:
        print("🎉 Excellent test coverage! Core architecture is well-tested.")
        print("🔧 Consider adding integration tests for edge cases.")
    elif overall_coverage >= 60:
        print("✅ Good test coverage with room for improvement.")
        print("🎯 Focus on components with no coverage first.")
    else:
        print("⚠️  Test coverage needs significant improvement.")
        print("🚨 Priority: Create tests for critical uncovered components.")
    
    # Priority components that need testing
    critical_components = []
    for component, info, tests in not_covered + partially_covered:
        if any(keyword in component.lower() for keyword in [
            'execution_engine', 'models', 'errors', 'retry_manager', 
            'dependency_tracker', 'base.py'
        ]):
            critical_components.append((component, info))
    
    if critical_components:
        print(f"\n🚨 HIGH PRIORITY COMPONENTS NEEDING TESTS:")
        for component, info in critical_components[:5]:  # Top 5
            print(f"  🔥 {component} - {info['description']}")
    
    return {
        'total_components': total_components,
        'well_covered': well_covered,
        'partially_covered': some_coverage,
        'not_covered': no_coverage,
        'overall_coverage': overall_coverage,
        'critical_missing': critical_components
    }


if __name__ == '__main__':
    results = analyze_core_coverage()
    
    # Exit code based on coverage
    if results['overall_coverage'] >= 75:
        print(f"\n🎉 CORE ARCHITECTURE TEST COVERAGE: EXCELLENT")
        sys.exit(0)
    elif results['overall_coverage'] >= 50:
        print(f"\n✅ CORE ARCHITECTURE TEST COVERAGE: GOOD")
        sys.exit(0)
    else:
        print(f"\n⚠️  CORE ARCHITECTURE TEST COVERAGE: NEEDS IMPROVEMENT")
        sys.exit(1)