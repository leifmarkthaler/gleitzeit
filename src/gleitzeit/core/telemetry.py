"""
OpenTelemetry Integration for Gleitzeit

Provides distributed tracing and observability integration that works
seamlessly with the existing LoggingMixin infrastructure.
"""

import logging
from typing import Dict, Any, Optional, AsyncContextManager, ContextManager
from contextlib import asynccontextmanager, contextmanager
import time
import functools

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.exporter.zipkin.json import ZipkinExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.trace.status import Status, StatusCode
    from opentelemetry.trace import SpanKind
    
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None
    SpanKind = None
    Status = None
    StatusCode = None

logger = logging.getLogger(__name__)

# Global tracer instance
if OPENTELEMETRY_AVAILABLE:
    _tracer: Optional[trace.Tracer] = None
else:
    _tracer = None
_telemetry_enabled = False


class TelemetryConfig:
    """Configuration for OpenTelemetry integration"""
    
    def __init__(
        self,
        service_name: str = "gleitzeit",
        service_version: str = "0.0.6",
        exporter_type: str = "console",  # console, otlp, jaeger, zipkin
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
    """
    Initialize OpenTelemetry with the provided configuration.
    
    Args:
        config: Telemetry configuration
        
    Returns:
        True if initialization succeeded, False otherwise
    """
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
        exporter = _create_exporter(config)
        if exporter:
            span_processor = BatchSpanProcessor(exporter)
            tracer_provider.add_span_processor(span_processor)
        
        # Get tracer
        _tracer = trace.get_tracer(__name__)
        
        # Enable logging instrumentation if requested
        if config.enable_logging_instrumentation:
            LoggingInstrumentor().instrument(set_logging_format=True)
        
        _telemetry_enabled = True
        logger.info(f"OpenTelemetry initialized with {config.exporter_type} exporter")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return False


def _create_exporter(config: TelemetryConfig):
    """Create the appropriate span exporter based on configuration"""
    
    if config.exporter_type == "console":
        return ConsoleSpanExporter()
    
    elif config.exporter_type == "otlp":
        endpoint = config.exporter_endpoint or "http://localhost:4317"
        return OTLPSpanExporter(endpoint=endpoint)
    
    elif config.exporter_type == "jaeger":
        endpoint = config.exporter_endpoint or "http://localhost:14268/api/traces"
        return JaegerExporter(endpoint=endpoint)
    
    elif config.exporter_type == "zipkin":
        endpoint = config.exporter_endpoint or "http://localhost:9411/api/v2/spans"
        return ZipkinExporter(endpoint=endpoint)
    
    else:
        logger.warning(f"Unknown exporter type: {config.exporter_type}")
        return ConsoleSpanExporter()


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled and available"""
    return _telemetry_enabled and _tracer is not None


def get_tracer():
    """Get the global tracer instance"""
    if not OPENTELEMETRY_AVAILABLE:
        return None
    return _tracer if is_telemetry_enabled() else None


if OPENTELEMETRY_AVAILABLE:
    @asynccontextmanager
    async def trace_operation(
        operation_name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        **attributes
    ) -> AsyncContextManager[Optional[trace.Span]]:
        """
        Async context manager for tracing operations.
        
        Args:
            operation_name: Name of the operation to trace
            kind: Type of span (INTERNAL, CLIENT, SERVER, etc.)
            **attributes: Additional span attributes
            
        Yields:
            The active span if telemetry is enabled, None otherwise
            
        Example:
            async with trace_operation("workflow_execution", workflow_id="123") as span:
                if span:
                    span.set_attribute("task_count", 5)
                # ... perform work ...
        """
        if not is_telemetry_enabled():
            yield None
            return
        
        tracer = get_tracer()
        if not tracer:
            yield None
            return
        
        start_time = time.time()
        
        with tracer.start_as_current_span(
            operation_name,
            kind=kind,
            attributes=attributes
        ) as span:
            try:
                yield span
            except Exception as e:
                if span:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                raise
            finally:
                if span:
                    duration = time.time() - start_time
                    span.set_attribute("duration_seconds", duration)
else:
    @asynccontextmanager
    async def trace_operation(operation_name: str, kind=None, **attributes):
        yield None
    """
    Async context manager for tracing operations.
    
    Args:
        operation_name: Name of the operation to trace
        kind: Type of span (INTERNAL, CLIENT, SERVER, etc.)
        **attributes: Additional span attributes
        
    Yields:
        The active span if telemetry is enabled, None otherwise
        
    Example:
        async with trace_operation("workflow_execution", workflow_id="123") as span:
            if span:
                span.set_attribute("task_count", 5)
            # ... perform work ...
    """
    if not is_telemetry_enabled():
        yield None
        return
    
    tracer = get_tracer()
    if not tracer:
        yield None
        return
    
    start_time = time.time()
    
    with tracer.start_as_current_span(
        operation_name,
        kind=kind,
        attributes=attributes
    ) as span:
        try:
            yield span
        except Exception as e:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
            raise
        finally:
            if span:
                duration = time.time() - start_time
                span.set_attribute("duration_seconds", duration)


@contextmanager
def trace_sync_operation(
    operation_name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    **attributes
) -> ContextManager[Optional[trace.Span]]:
    """
    Synchronous context manager for tracing operations.
    
    Args:
        operation_name: Name of the operation to trace
        kind: Type of span (INTERNAL, CLIENT, SERVER, etc.)
        **attributes: Additional span attributes
        
    Yields:
        The active span if telemetry is enabled, None otherwise
    """
    if not is_telemetry_enabled():
        yield None
        return
    
    tracer = get_tracer()
    if not tracer:
        yield None
        return
    
    start_time = time.time()
    
    with tracer.start_as_current_span(
        operation_name,
        kind=kind,
        attributes=attributes
    ) as span:
        try:
            yield span
        except Exception as e:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
            raise
        finally:
            if span:
                duration = time.time() - start_time
                span.set_attribute("duration_seconds", duration)


def trace_async_function(
    operation_name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    **default_attributes
):
    """
    Decorator for automatically tracing async functions.
    
    Args:
        operation_name: Name for the span (defaults to function name)
        kind: Type of span
        **default_attributes: Default attributes to add to spans
        
    Example:
        @trace_async_function("execute_task", task_type="workflow")
        async def execute_task(self, task):
            # Function is automatically traced
            return result
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            span_name = operation_name or f"{func.__module__}.{func.__qualname__}"
            
            # Extract attributes from function arguments
            attributes = dict(default_attributes)
            
            # Add function info
            attributes["function.name"] = func.__name__
            attributes["function.module"] = func.__module__
            
            async with trace_operation(span_name, kind, **attributes) as span:
                if span and args:
                    # Try to extract common IDs from arguments
                    for arg in args:
                        if hasattr(arg, 'id'):
                            if hasattr(arg, '__class__'):
                                class_name = arg.__class__.__name__.lower()
                                span.set_attribute(f"{class_name}_id", str(arg.id))
                
                result = await func(*args, **kwargs)
                
                if span and hasattr(result, '__dict__'):
                    # Add result info if available
                    if hasattr(result, 'success'):
                        span.set_attribute("result.success", result.success)
                
                return result
        
        return wrapper
    return decorator


def trace_function(
    operation_name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    **default_attributes
):
    """
    Decorator for automatically tracing synchronous functions.
    
    Args:
        operation_name: Name for the span (defaults to function name)
        kind: Type of span
        **default_attributes: Default attributes to add to spans
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            span_name = operation_name or f"{func.__module__}.{func.__qualname__}"
            
            attributes = dict(default_attributes)
            attributes["function.name"] = func.__name__
            attributes["function.module"] = func.__module__
            
            with trace_sync_operation(span_name, kind, **attributes) as span:
                if span and args:
                    for arg in args:
                        if hasattr(arg, 'id'):
                            if hasattr(arg, '__class__'):
                                class_name = arg.__class__.__name__.lower()
                                span.set_attribute(f"{class_name}_id", str(arg.id))
                
                result = func(*args, **kwargs)
                
                if span and hasattr(result, '__dict__'):
                    if hasattr(result, 'success'):
                        span.set_attribute("result.success", result.success)
                
                return result
        
        return wrapper
    return decorator


def add_span_attributes(**attributes) -> None:
    """
    Add attributes to the current active span.
    
    Args:
        **attributes: Attributes to add to the current span
    """
    if not is_telemetry_enabled():
        return
    
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        for key, value in attributes.items():
            current_span.set_attribute(key, value)


def record_exception(exception: Exception) -> None:
    """
    Record an exception in the current span.
    
    Args:
        exception: Exception to record
    """
    if not is_telemetry_enabled():
        return
    
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.record_exception(exception)
        current_span.set_status(Status(StatusCode.ERROR, str(exception)))


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