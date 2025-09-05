"""
Simplified OpenTelemetry Integration for Gleitzeit

This provides OpenTelemetry integration with graceful fallbacks when 
the dependencies are not available.
"""

import logging
from typing import Dict, Any, Optional, AsyncContextManager, ContextManager
from contextlib import asynccontextmanager, contextmanager

logger = logging.getLogger(__name__)

# Try to import OpenTelemetry
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace.status import Status, StatusCode
    from opentelemetry.trace import SpanKind
    
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ImportError:
        OTLPSpanExporter = None
    
    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    except ImportError:
        JaegerExporter = None
    
    try:
        from opentelemetry.exporter.zipkin.json import ZipkinExporter
    except ImportError:
        ZipkinExporter = None
    
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    
    # Create stub classes
    class StubSpanKind:
        INTERNAL = "internal"
    
    SpanKind = StubSpanKind()
    trace = None
    Status = None
    StatusCode = None

# Global state
_telemetry_enabled = False
_tracer = None


class TelemetryConfig:
    """Configuration for OpenTelemetry integration"""
    
    def __init__(
        self,
        service_name: str = "gleitzeit",
        service_version: str = "0.0.6",
        exporter_type: str = "console",
        exporter_endpoint: Optional[str] = None,
        enable_logging_instrumentation: bool = True,
        sample_rate: float = 1.0
    ):
        self.service_name = service_name
        self.service_version = service_version
        self.exporter_type = exporter_type
        self.exporter_endpoint = exporter_endpoint
        self.enable_logging_instrumentation = enable_logging_instrumentation
        self.sample_rate = sample_rate


def initialize_telemetry(config: TelemetryConfig) -> bool:
    """Initialize OpenTelemetry with the provided configuration."""
    global _tracer, _telemetry_enabled
    
    if not OPENTELEMETRY_AVAILABLE:
        logger.warning("OpenTelemetry not available - telemetry disabled")
        return False
    
    try:
        # Create resource
        resource = Resource.create({
            "service.name": config.service_name,
            "service.version": config.service_version
        })
        
        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)
        
        # Configure exporter
        exporter = None
        if config.exporter_type == "console":
            exporter = ConsoleSpanExporter()
        elif config.exporter_type == "otlp" and OTLPSpanExporter:
            endpoint = config.exporter_endpoint or "http://localhost:4317"
            exporter = OTLPSpanExporter(endpoint=endpoint)
        elif config.exporter_type == "jaeger" and JaegerExporter:
            endpoint = config.exporter_endpoint or "http://localhost:14268/api/traces"
            exporter = JaegerExporter(endpoint=endpoint)
        elif config.exporter_type == "zipkin" and ZipkinExporter:
            endpoint = config.exporter_endpoint or "http://localhost:9411/api/v2/spans"
            exporter = ZipkinExporter(endpoint=endpoint)
        else:
            logger.warning(f"Exporter {config.exporter_type} not available, using console")
            exporter = ConsoleSpanExporter()
        
        if exporter:
            span_processor = BatchSpanProcessor(exporter)
            tracer_provider.add_span_processor(span_processor)
        
        # Get tracer
        _tracer = trace.get_tracer(__name__)
        _telemetry_enabled = True
        
        logger.info(f"OpenTelemetry initialized with {config.exporter_type} exporter")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return False


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled and available"""
    return _telemetry_enabled and OPENTELEMETRY_AVAILABLE


def get_tracer():
    """Get the global tracer instance"""
    if not OPENTELEMETRY_AVAILABLE:
        return None
    return _tracer if is_telemetry_enabled() else None


@asynccontextmanager
async def trace_operation(operation_name: str, kind=None, **attributes):
    """Async context manager for tracing operations"""
    if not is_telemetry_enabled():
        yield None
        return
    
    tracer = get_tracer()
    if not tracer:
        yield None
        return
    
    import time
    start_time = time.time()
    
    try:
        with tracer.start_as_current_span(
            operation_name,
            kind=kind or SpanKind.INTERNAL,
            attributes=attributes
        ) as span:
            try:
                yield span
            except Exception as e:
                if span and Status and StatusCode:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                raise
            finally:
                if span:
                    duration = time.time() - start_time
                    span.set_attribute("duration_seconds", duration)
    except Exception:
        # If anything fails, just yield None
        yield None


def add_span_attributes(**attributes) -> None:
    """Add attributes to the current active span"""
    if not is_telemetry_enabled():
        return
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            for key, value in attributes.items():
                current_span.set_attribute(key, value)
    except Exception:
        pass  # Don't let telemetry errors break the application


def record_exception(exception: Exception) -> None:
    """Record an exception in the current span"""
    if not is_telemetry_enabled():
        return
    
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.record_exception(exception)
            if Status and StatusCode:
                current_span.set_status(Status(StatusCode.ERROR, str(exception)))
    except Exception:
        pass  # Don't let telemetry errors break the application


def shutdown_telemetry() -> None:
    """Shutdown telemetry and flush any remaining spans"""
    global _tracer, _telemetry_enabled
    
    if is_telemetry_enabled():
        try:
            tracer_provider = trace.get_tracer_provider()
            if hasattr(tracer_provider, 'shutdown'):
                tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown complete")
        except Exception as e:
            logger.error(f"Error during telemetry shutdown: {e}")
        finally:
            _tracer = None
            _telemetry_enabled = False