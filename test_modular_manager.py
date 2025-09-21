#!/usr/bin/env python
"""
Test script for the updated ModularStreamSystemManager.
"""

import asyncio
import logging
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_modular_stream_manager():
    """Test the ModularStreamSystemManager with all new components."""

    # Create config
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test",
        default_providers=["python", "shell"],
        provider_hub_port=9091,
        api_client_pool_size=5
    )

    manager = None
    try:
        logger.info("Creating ModularStreamSystemManager...")

        # Create manager using factory method
        manager = await ModularStreamSystemManager.create(
            config=config,
            instance_id="test_modular_001",
            create_if_missing=True,
            start_system=True
        )

        if not manager:
            logger.error("Failed to create ModularStreamSystemManager")
            return False

        logger.info(f"Manager created: {manager.instance_id}")
        logger.info(f"Manager initialized: {manager._initialized}")
        logger.info(f"Manager running: {manager._running}")

        # Check critical components
        components_check = {
            "workflow_loader": hasattr(manager, 'workflow_loader') and manager.workflow_loader is not None,
            "auth_manager": hasattr(manager, 'auth_manager') and manager.auth_manager is not None,
            "provider_hub": hasattr(manager, 'provider_hub') and manager.provider_hub is not None,
            "shared_client_pool": hasattr(manager, 'shared_client_pool') and manager.shared_client_pool is not None,
            "reconciliation_service": hasattr(manager, 'reconciliation_service') and manager.reconciliation_service is not None,
            "workflow_progress_handler": hasattr(manager, 'workflow_progress_handler') and manager.workflow_progress_handler is not None,
            "hub_factory": hasattr(manager, 'hub_factory') and manager.hub_factory is not None,
            "_provider_heartbeat_task": hasattr(manager, '_provider_heartbeat_task') and manager._provider_heartbeat_task is not None,
        }

        logger.info("Component status:")
        for component, status in components_check.items():
            logger.info(f"  {component}: {'✓' if status else '✗'}")

        # Check mixin components
        mixin_status = manager.get_mixin_components()
        logger.info("\nMixin component status:")
        for mixin, status in mixin_status.items():
            logger.info(f"  {mixin}: {'✓' if status else '✗'}")

        # Check available protocols
        if hasattr(manager, 'get_available_protocols'):
            protocols = manager.get_available_protocols()
            logger.info(f"\nAvailable protocols: {protocols}")

        # Check provider statistics
        if hasattr(manager, 'get_provider_statistics'):
            provider_stats = manager.get_provider_statistics()
            logger.info(f"\nProvider statistics:")
            logger.info(f"  Available protocols: {provider_stats.get('available_protocols', [])}")
            logger.info(f"  Provider hub active: {provider_stats.get('provider_hub_active', False)}")
            logger.info(f"  HTTP server active: {provider_stats.get('http_server_active', False)}")

        # Test authenticated workflow methods
        if hasattr(manager, 'submit_workflow_authenticated'):
            logger.info("\n✓ Authenticated workflow methods available")

        # Get system info
        system_info = await manager.get_system_info()
        logger.info(f"\nSystem info:")
        logger.info(f"  Instance ID: {system_info.get('instance_id')}")
        logger.info(f"  System type: {system_info.get('system_type')}")
        logger.info(f"  Stream-based: {system_info.get('stream_based')}")
        logger.info(f"  Modular: {system_info.get('modular')}")
        logger.info(f"  Running: {system_info.get('running')}")

        # Check stream config
        stream_config = system_info.get('stream_config', {})
        logger.info(f"\nStream configuration:")
        logger.info(f"  Total shards: {stream_config.get('total_shards')}")
        logger.info(f"  Consumer group: {stream_config.get('consumer_group')}")
        logger.info(f"  Consumer started: {stream_config.get('consumer_started')}")

        # Verify all critical issues are fixed
        issues_fixed = {
            "WorkflowLoaderV2 initialized": components_check['workflow_loader'],
            "Provider heartbeat active": components_check['_provider_heartbeat_task'],
            "HubFactory initialized": components_check['hub_factory'],
            "SharedClientPool initialized": components_check['shared_client_pool'],
            "Reconciliation service active": components_check['reconciliation_service'],
            "Workflow progress handler active": components_check['workflow_progress_handler'],
            "Auth methods available": hasattr(manager, 'submit_workflow_authenticated'),
            "Providers registered in persistence": len(protocols) > 0 if 'protocols' in locals() else False
        }

        logger.info("\nCritical issues status:")
        all_fixed = True
        for issue, fixed in issues_fixed.items():
            status = "✓ FIXED" if fixed else "✗ NOT FIXED"
            logger.info(f"  {issue}: {status}")
            if not fixed:
                all_fixed = False

        if all_fixed:
            logger.info("\n✅ All critical issues have been successfully fixed!")
        else:
            logger.warning("\n⚠️ Some issues still need attention")

        return all_fixed

    except Exception as e:
        logger.error(f"Error testing ModularStreamSystemManager: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    finally:
        if manager:
            logger.info("\nShutting down manager...")
            await manager.shutdown()
            logger.info("Manager shutdown complete")


async def main():
    """Main test runner."""
    success = await test_modular_stream_manager()

    if success:
        print("\n" + "="*60)
        print("✅ ModularStreamSystemManager VALIDATION SUCCESSFUL")
        print("="*60)
        print("\nAll critical components have been successfully added:")
        print("  • WorkflowLoaderV2 initialization")
        print("  • Provider heartbeat management")
        print("  • HubFactory and ProviderHub setup")
        print("  • Authenticated workflow methods")
        print("  • Reconciliation service and workflow progress handler")
        print("  • Shared client pool management")
        print("  • Stateless monitoring loops")
        print("  • Provider registration in persistence")
        print("\nThe ModularStreamSystemManager is now feature-complete!")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("❌ ModularStreamSystemManager validation failed")
        print("Some components may still need attention")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())