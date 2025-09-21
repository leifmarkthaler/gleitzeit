#!/usr/bin/env python3
"""
Test OpenTelemetry integration with full SDK initialization.

This script demonstrates the complete OpenTelemetry setup and integration.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

# Configure environment for telemetry
os.environ["GLEITZEIT_TELEMETRY_EXPORTER"] = "console"
os.environ["GLEITZEIT_SERVICE_NAME"] = "gleitzeit-test"
os.environ["GLEITZEIT_SERVICE_VERSION"] = "0.0.6"
os.environ["GLEITZEIT_TELEMETRY_LOGGING"] = "true"
os.environ["GLEITZEIT_TELEMETRY_SAMPLE_RATE"] = "1.0"

# Initialize OpenTelemetry manually for testing
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    
    print("🔧 Initializing OpenTelemetry SDK...")
    
    # Create resource
    resource = Resource.create({
        "service.name": "gleitzeit-test",
        "service.version": "0.0.6"
    })
    
    # Create tracer provider
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)
    
    # Configure console exporter
    exporter = ConsoleSpanExporter()
    span_processor = BatchSpanProcessor(exporter)
    tracer_provider.add_span_processor(span_processor)
    
    # Enable logging instrumentation
    LoggingInstrumentor().instrument(set_logging_format=True)
    
    TELEMETRY_INITIALIZED = True
    print("✅ OpenTelemetry SDK initialized successfully")
    
except ImportError as e:
    print(f"❌ OpenTelemetry not available: {e}")
    TELEMETRY_INITIALIZED = False


async def test_telemetry_integration():
    """Test the full OpenTelemetry integration."""
    print("\n🔄 Running Full OpenTelemetry Integration Test")
    print("=" * 60)
    print("OpenTelemetry SDK Status:", "✅ Available" if TELEMETRY_INITIALIZED else "❌ Not Available")
    print("=" * 60)
    print()
    
    if not TELEMETRY_INITIALIZED:
        print("❌ Skipping test - OpenTelemetry not properly initialized")
        return
    
    try:
        print("📊 Testing LoggingMixin with OpenTelemetry spans...")
        
        # Import after OpenTelemetry is initialized
        from gleitzeit.core.logging_mixin import LoggingMixin
        from gleitzeit.core.logs import LogLevel
        
        class TestComponent(LoggingMixin):
            def __init__(self):
                super().__init__()
        
        # Create test component
        test_component = TestComponent()
        
        # Get tracer for manual span creation
        tracer = trace.get_tracer(__name__)
        
        print("🧪 Creating manual spans and testing logging integration...")
        
        # Test with manual span creation
        with tracer.start_as_current_span("test_workflow_execution") as workflow_span:
            workflow_span.set_attribute("workflow.id", "test-workflow-123")
            workflow_span.set_attribute("workflow.name", "opentelemetry_test")
            
            print("   📈 Inside workflow span - testing component logging...")
            
            # Test logging within span context
            await test_component.log_operation("workflow_started", 
                                               task_id="task-456", 
                                               workflow_id="test-workflow-123")
            
            # Create nested span for task execution
            with tracer.start_as_current_span("task_execution") as task_span:
                task_span.set_attribute("task.id", "task-456")
                task_span.set_attribute("task.type", "python")
                task_span.set_attribute("provider.type", "python_provider")
                
                print("     🔧 Inside task span - testing nested logging...")
                
                await test_component.log_operation("task_started", level=LogLevel.INFO)
                await test_component.log_success("task_processing", duration=2.5, result="processed")
                
                # Test error logging with span
                try:
                    raise ValueError("Test error for span recording")
                except Exception as e:
                    await test_component.log_error("task_error", e, context="span_test")
                    task_span.record_exception(e)
                    task_span.set_status(trace.Status(trace.StatusCode.ERROR))
                
                await test_component.log_operation("task_completed")
            
            await test_component.log_success("workflow_completed", total_tasks=1)
        
        print("\n🎯 Testing provider-level logging integration...")
        
        # Test provider-style logging
        with tracer.start_as_current_span("provider_operation") as provider_span:
            provider_span.set_attribute("provider.name", "test_provider")
            provider_span.set_attribute("provider.protocol", "python/v1")
            
            await test_component.log_operation("provider_request_received", 
                                               provider_id="test_provider_123",
                                               method="execute")
            
            await test_component.log_debug("provider_debug", "Processing request parameters", 
                                           params_count=3)
            
            await test_component.log_warning("provider_warning", 
                                             "Resource usage high", 
                                             cpu_percent=85.5)
            
            await test_component.log_success("provider_response_sent", 
                                           response_size=1024,
                                           execution_time=1.2)
        
        # Force span export
        print("\n🚀 Forcing span export...")
        tracer_provider = trace.get_tracer_provider()
        if hasattr(tracer_provider, 'force_flush'):
            tracer_provider.force_flush()
        
        print("\n✅ Full OpenTelemetry integration test completed!")
        print("\n🔍 You should see above:")
        print("  - Detailed span information with attributes")
        print("  - Nested spans showing workflow -> task hierarchy") 
        print("  - Log correlation with span context")
        print("  - Exception recording in spans")
        print("  - Provider operation tracing")
        print("  - Resource and service information")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


async def test_system_level_telemetry():
    """Test telemetry at the system level."""
    print("\n🏗️  Testing System-Level OpenTelemetry Integration")
    print("=" * 60)
    
    try:
        # Test telemetry simple module
        from gleitzeit.core.telemetry_simple import initialize_telemetry, TelemetryConfig, is_telemetry_enabled
        
        config = TelemetryConfig(
            service_name="gleitzeit-system-test",
            service_version="0.0.6",
            exporter_type="console"
        )
        
        result = initialize_telemetry(config)
        print(f"📊 Telemetry initialization: {'✅ Success' if result else '❌ Failed'}")
        print(f"🔧 Telemetry enabled: {'✅ Yes' if is_telemetry_enabled() else '❌ No'}")
        
        if is_telemetry_enabled():
            # Test trace_operation context manager
            from gleitzeit.core.telemetry_simple import trace_operation, add_span_attributes
            
            async with trace_operation("system_startup", service="gleitzeit") as span:
                print("   🚀 Inside system startup span")
                if span:
                    add_span_attributes(component="system_manager", version="0.0.6")
                
                # Simulate system operations
                async with trace_operation("component_initialization") as comp_span:
                    print("     🔧 Inside component initialization span")
                    if comp_span:
                        add_span_attributes(components_count=5, initialization_time=3.2)
        
        print("✅ System-level telemetry test completed!")
        
    except Exception as e:
        print(f"❌ System telemetry test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    async def main():
        await test_telemetry_integration()
        await test_system_level_telemetry()
        
        # Cleanup
        if TELEMETRY_INITIALIZED:
            print("\n🧹 Cleaning up OpenTelemetry...")
            try:
                tracer_provider = trace.get_tracer_provider()
                if hasattr(tracer_provider, 'shutdown'):
                    tracer_provider.shutdown()
                print("✅ OpenTelemetry cleanup completed")
            except Exception as e:
                print(f"⚠️  Cleanup warning: {e}")
    
    asyncio.run(main())