"""
Comprehensive Error Handling and Retry System for Gleitzeit Cluster

Provides structured error logging, retry logic, circuit breakers,
and failure categorization for robust workflow execution.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass, field
from pathlib import Path
import traceback


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"  
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categorization for retry decisions"""
    TRANSIENT = "transient"      # Temporary issues, retry
    PERMANENT = "permanent"      # Won't be fixed by retry
    RATE_LIMITED = "rate_limited"  # Need backoff
    RESOURCE = "resource"        # Resource exhaustion
    NETWORK = "network"         # Network connectivity
    AUTHENTICATION = "auth"     # Auth/permission issues
    VALIDATION = "validation"   # Input validation errors


@dataclass
class ErrorInfo:
    """Structured error information"""
    error_type: str
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    timestamp: datetime
    context: Dict[str, Any] = field(default_factory=dict)
    stacktrace: Optional[str] = None
    retry_after: Optional[int] = None  # Seconds to wait before retry


class ErrorCategorizer:
    """Categorizes errors for appropriate retry behavior"""
    
    @staticmethod
    def categorize_error(error: Exception, context: Dict[str, Any] = None) -> ErrorInfo:
        """Categorize an error for retry decisions"""
        
        error_type = type(error).__name__
        message = str(error)
        context = context or {}
        
        # Network-related errors
        if any(keyword in message.lower() for keyword in [
            "connection", "timeout", "network", "unreachable", "refused"
        ]):
            return ErrorInfo(
                error_type=error_type,
                message=message,
                category=ErrorCategory.TRANSIENT,
                severity=ErrorSeverity.MEDIUM,
                timestamp=datetime.utcnow(),
                context=context,
                stacktrace=traceback.format_exc(),
                retry_after=5  # Wait 5 seconds
            )
        
        # Rate limiting
        if any(keyword in message.lower() for keyword in [
            "rate limit", "too many requests", "quota exceeded"
        ]):
            return ErrorInfo(
                error_type=error_type,
                message=message,
                category=ErrorCategory.RATE_LIMITED,
                severity=ErrorSeverity.MEDIUM,
                timestamp=datetime.utcnow(),
                context=context,
                retry_after=60  # Wait 1 minute
            )
        
        # Resource issues
        if any(keyword in message.lower() for keyword in [
            "memory", "disk", "space", "resource", "capacity"
        ]):
            return ErrorInfo(
                error_type=error_type,
                message=message,
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.HIGH,
                timestamp=datetime.utcnow(),
                context=context,
                retry_after=30  # Wait 30 seconds
            )
        
        # Authentication/Authorization
        if any(keyword in message.lower() for keyword in [
            "auth", "token", "permission", "unauthorized", "forbidden"
        ]):
            return ErrorInfo(
                error_type=error_type,
                message=message,
                category=ErrorCategory.AUTHENTICATION,
                severity=ErrorSeverity.HIGH,
                timestamp=datetime.utcnow(),
                context=context
            )
        
        # Validation errors (permanent)
        if any(keyword in message.lower() for keyword in [
            "validation", "invalid", "missing", "required", "format"
        ]):
            return ErrorInfo(
                error_type=error_type,
                message=message,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.LOW,
                timestamp=datetime.utcnow(),
                context=context
            )
        
        # Default: transient with low severity
        return ErrorInfo(
            error_type=error_type,
            message=message,
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            timestamp=datetime.utcnow(),
            context=context,
            stacktrace=traceback.format_exc()
        )


class RetryConfig:
    """Configuration for retry behavior"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt with exponential backoff"""
        import random
        
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            # Add random jitter ±25%
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


class CircuitBreaker:
    """Circuit breaker pattern for failing services"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half-open
    
    def can_execute(self) -> bool:
        """Check if execution is allowed"""
        if self.state == "closed":
            return True
        elif self.state == "open":
            # Check if recovery timeout has passed
            if (self.last_failure_time and 
                datetime.utcnow() - self.last_failure_time > timedelta(seconds=self.recovery_timeout)):
                self.state = "half-open"
                return True
            return False
        elif self.state == "half-open":
            return True
        
        return False
    
    def record_success(self):
        """Record successful execution"""
        self.failure_count = 0
        self.state = "closed"
        self.last_failure_time = None
    
    def record_failure(self):
        """Record failed execution"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


class GleitzeitLogger:
    """Enhanced logging system for Gleitzeit"""
    
    def __init__(self, name: str, log_level: str = "INFO", log_file: Optional[Path] = None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))
        
        # File handler (optional)
        handlers = [console_handler]
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)  # File gets all logs
            handlers.append(file_handler)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        for handler in handlers:
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def log_error(self, error_info: ErrorInfo, context: Dict[str, Any] = None):
        """Log structured error information"""
        context = context or {}
        
        log_data = {
            "error_type": error_info.error_type,
            "category": error_info.category.value,
            "severity": error_info.severity.value,
            "message": error_info.message,
            "timestamp": error_info.timestamp.isoformat(),
            **context
        }
        
        # Choose log level based on severity
        if error_info.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(f"CRITICAL ERROR: {log_data}")
        elif error_info.severity == ErrorSeverity.HIGH:
            self.logger.error(f"HIGH SEVERITY: {log_data}")
        elif error_info.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(f"MEDIUM SEVERITY: {log_data}")
        else:
            self.logger.info(f"LOW SEVERITY: {log_data}")
        
        # Log stack trace for debugging
        if error_info.stacktrace and error_info.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            self.logger.debug(f"Stack trace: {error_info.stacktrace}")
    
    def log_retry_attempt(self, attempt: int, max_attempts: int, delay: float, error_info: ErrorInfo):
        """Log retry attempt"""
        self.logger.warning(
            f"Retry attempt {attempt}/{max_attempts} after {delay:.2f}s delay. "
            f"Error: {error_info.message}"
        )
    
    def log_retry_exhausted(self, error_info: ErrorInfo):
        """Log when retries are exhausted"""
        self.logger.error(f"All retry attempts exhausted. Final error: {error_info.message}")


class RetryManager:
    """Manages retry logic with categorized errors"""
    
    def __init__(self, logger: Optional[GleitzeitLogger] = None):
        self.logger = logger or GleitzeitLogger("RetryManager")
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def get_circuit_breaker(self, service_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for service"""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker()
        return self.circuit_breakers[service_name]
    
    async def execute_with_retry(
        self,
        func: Callable,
        retry_config: RetryConfig,
        service_name: str = "unknown",
        context: Dict[str, Any] = None
    ) -> Any:
        """Execute function with retry logic and circuit breaker"""
        
        circuit_breaker = self.get_circuit_breaker(service_name)
        context = context or {}
        
        # Check circuit breaker
        if not circuit_breaker.can_execute():
            error_info = ErrorInfo(
                error_type="CircuitBreakerOpen",
                message=f"Circuit breaker open for service: {service_name}",
                category=ErrorCategory.RESOURCE,
                severity=ErrorSeverity.HIGH,
                timestamp=datetime.utcnow(),
                context=context
            )
            self.logger.log_error(error_info)
            raise Exception(error_info.message)
        
        last_error_info = None
        
        for attempt in range(retry_config.max_attempts):
            try:
                result = await func() if asyncio.iscoroutinefunction(func) else func()
                
                # Success - reset circuit breaker
                circuit_breaker.record_success()
                
                if attempt > 0:
                    self.logger.logger.info(f"Retry successful on attempt {attempt + 1}")
                
                return result
                
            except Exception as e:
                error_info = ErrorCategorizer.categorize_error(e, context)
                last_error_info = error_info
                
                # Log the error
                self.logger.log_error(error_info, {"attempt": attempt + 1, "service": service_name})
                
                # Record failure in circuit breaker
                circuit_breaker.record_failure()
                
                # Don't retry permanent errors
                if error_info.category in [ErrorCategory.VALIDATION, ErrorCategory.AUTHENTICATION]:
                    self.logger.logger.warning(f"Not retrying {error_info.category.value} error")
                    break
                
                # Don't retry if this was the last attempt
                if attempt == retry_config.max_attempts - 1:
                    break
                
                # Calculate delay
                delay = retry_config.get_delay(attempt)
                
                # Use error-specific retry_after if provided
                if error_info.retry_after:
                    delay = max(delay, error_info.retry_after)
                
                # Log retry attempt
                self.logger.log_retry_attempt(
                    attempt + 1, retry_config.max_attempts, delay, error_info
                )
                
                # Wait before retry
                await asyncio.sleep(delay)
        
        # All retries exhausted
        if last_error_info:
            self.logger.log_retry_exhausted(last_error_info)
            raise Exception(last_error_info.message)
        
        raise Exception("Unknown error in retry logic")


# Convenience decorator for retry
def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    service_name: str = "unknown"
):
    """Decorator to add retry logic to functions"""
    
    def decorator(func):
        async def wrapper(*args, **kwargs):
            retry_manager = RetryManager()
            retry_config = RetryConfig(max_attempts=max_attempts, base_delay=base_delay)
            
            async def execute():
                return await func(*args, **kwargs)
            
            return await retry_manager.execute_with_retry(
                execute, retry_config, service_name
            )
        
        return wrapper
    return decorator


# Global error manager instance
_error_manager = None

def get_error_manager() -> RetryManager:
    """Get global error manager instance"""
    global _error_manager
    if _error_manager is None:
        logger = GleitzeitLogger("GleitzeitErrors")
        _error_manager = RetryManager(logger)
    return _error_manager