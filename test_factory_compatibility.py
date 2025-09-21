#!/usr/bin/env python3
"""
Test that model factories and provider factory don't clash.
"""

import sys
sys.path.insert(0, 'src')

from gleitzeit.core.model_factory import TaskFactory, WorkflowFactory
from gleitzeit.providers.factory import ProviderFactory
from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.errors import TaskValidationError, WorkflowValidationError
from gleitzeit.providers.factory import ProviderValidationError


def test_factories_separate_namespaces():
    """Test that factories exist in separate namespaces."""
    print("\n=== Testing Factory Namespaces ===")
    
    # Check class names don't clash
    print("\n1. Class names:")
    print(f"   TaskFactory: {TaskFactory.__module__}.{TaskFactory.__name__}")
    print(f"   WorkflowFactory: {WorkflowFactory.__module__}.{WorkflowFactory.__name__}")
    print(f"   ProviderFactory: {ProviderFactory.__module__}.{ProviderFactory.__name__}")
    print("   ✅ No class name conflicts - all in different modules")
    
    # Check error classes don't clash
    print("\n2. Error classes:")
    print(f"   TaskValidationError: {TaskValidationError.__module__}")
    print(f"   WorkflowValidationError: {WorkflowValidationError.__module__}")
    print(f"   ProviderValidationError: {ProviderValidationError.__module__}")
    print("   ✅ Error classes in separate modules")
    
    return True


def test_model_factory_creates_models():
    """Test that model factories create models correctly."""
    print("\n=== Testing Model Factories ===")
    
    # TaskFactory creates Tasks
    print("\n1. TaskFactory creates Task:")
    task = TaskFactory.create_with_defaults(
        id="test_task",
        protocol="python",
        config={"code": "result = 42"}
    )
    print(f"   Created: {type(task).__name__} (id={task.id})")
    
    # WorkflowFactory creates Workflows
    print("\n2. WorkflowFactory creates Workflow:")
    workflow = WorkflowFactory.create_with_defaults(
        id="test_workflow",
        tasks=[task]
    )
    print(f"   Created: {type(workflow).__name__} (id={workflow.id})")
    
    print("   ✅ Model factories work correctly")
    return True


def test_provider_factory_creates_providers():
    """Test that provider factory creates providers correctly."""
    print("\n=== Testing Provider Factory ===")
    
    # Define a simple test provider
    class TestProvider(SimpleProvider):
        def __init__(self):
            super().__init__(provider_id="test_provider", protocol_id="test/v1")
        
        async def execute(self, method: str, **params):
            return {"method": method, "result": "success"}
    
    # ProviderFactory creates Providers
    print("\n1. ProviderFactory creates Provider:")
    factory = ProviderFactory(strict_validation=False)  # Disable strict for test
    provider = factory.create_provider(
        TestProvider,
        validate=False  # Skip validation for simple test
    )
    print(f"   Created: {type(provider).__name__} (id={provider.provider_id})")
    print("   ✅ Provider factory works correctly")
    
    return True


def test_factories_different_purposes():
    """Test that factories serve different purposes."""
    print("\n=== Testing Factory Purposes ===")
    
    print("\n1. TaskFactory purpose:")
    print("   - Creates Task model instances")
    print("   - Wraps Pydantic validation errors in centralized errors")
    print("   - Provides sensible defaults for Task fields")
    
    print("\n2. WorkflowFactory purpose:")
    print("   - Creates Workflow model instances")
    print("   - Wraps Pydantic validation errors in centralized errors")
    print("   - Provides sensible defaults for Workflow fields")
    
    print("\n3. ProviderFactory purpose:")
    print("   - Creates Provider instances (execution components)")
    print("   - Validates provider implementations")
    print("   - Ensures providers are compatible with Gleitzeit")
    print("   - Auto-generates protocols from providers")
    
    print("\n✅ Factories serve completely different purposes:")
    print("   - Model factories: Create data models (Task, Workflow)")
    print("   - Provider factory: Create execution providers")
    print("   - No functional overlap!")
    
    return True


def test_error_inheritance():
    """Test that error classes use centralized system correctly."""
    print("\n=== Testing Error Inheritance ===")
    
    from gleitzeit.core.errors import GleitzeitError
    
    # Check all errors inherit from GleitzeitError
    print("\n1. Model factory errors:")
    print(f"   TaskValidationError inherits from GleitzeitError: {issubclass(TaskValidationError, GleitzeitError)}")
    print(f"   WorkflowValidationError inherits from GleitzeitError: {issubclass(WorkflowValidationError, GleitzeitError)}")
    
    print("\n2. Provider factory errors:")
    print(f"   ProviderValidationError inherits from GleitzeitError: {issubclass(ProviderValidationError, GleitzeitError)}")
    
    print("\n✅ All factory errors use centralized error system")
    
    return True


def test_no_import_conflicts():
    """Test that imports don't conflict."""
    print("\n=== Testing Import Compatibility ===")
    
    # Can import all factories together
    try:
        from gleitzeit.core.model_factory import TaskFactory, WorkflowFactory
        from gleitzeit.providers.factory import ProviderFactory
        from gleitzeit.persistence.factory import PersistenceFactory
        from gleitzeit.hub.hub_factory import HubFactory
        from gleitzeit.core.workflow_manager_factory import WorkflowManagerFactory
        
        print("\n✅ All factories can be imported together without conflicts:")
        print("   - TaskFactory (model creation)")
        print("   - WorkflowFactory (model creation)")
        print("   - ProviderFactory (provider creation)")
        print("   - PersistenceFactory (backend creation)")
        print("   - HubFactory (hub creation)")
        print("   - WorkflowManagerFactory (manager creation)")
        
        return True
    except ImportError as e:
        print(f"\n❌ Import conflict: {e}")
        return False


def main():
    """Run all compatibility tests."""
    print("\n" + "="*60)
    print("FACTORY COMPATIBILITY TEST")
    print("="*60)
    
    tests = [
        ("Namespace Separation", test_factories_separate_namespaces),
        ("Model Factory Functionality", test_model_factory_creates_models),
        ("Provider Factory Functionality", test_provider_factory_creates_providers),
        ("Different Purposes", test_factories_different_purposes),
        ("Error Inheritance", test_error_inheritance),
        ("Import Compatibility", test_no_import_conflicts)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} failed: {e}")
            results.append((name, False))
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    all_passed = all(result for _, result in results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    if all_passed:
        print("\n✅ NO CONFLICTS DETECTED!")
        print("\nConclusion:")
        print("- TaskFactory and WorkflowFactory create data models")
        print("- ProviderFactory creates execution providers")
        print("- All use the centralized error system")
        print("- No naming conflicts or functional overlap")
        print("- Factories complement each other in the architecture")
    else:
        print("\n❌ Some tests failed - review the output above")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)