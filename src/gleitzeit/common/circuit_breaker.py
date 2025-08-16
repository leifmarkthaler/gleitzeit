"""
Generic Circuit Breaker for fault tolerance
"""
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """
    Generic circuit breaker implementation
    
    Prevents cascading failures by temporarily blocking requests
    to failing resources.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_requests: int = 3,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker
        
        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before trying half-open
            half_open_requests: Max requests in half-open state
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        self.success_threshold = success_threshold
        
        # State tracking per resource
        self.states: Dict[str, Dict[str, Any]] = {}
        
    def get_state(self, resource_id: str) -> CircuitState:
        """Get current state for resource"""
        if resource_id not in self.states:
            return CircuitState.CLOSED
            
        state_info = self.states[resource_id]
        current_state = CircuitState(state_info['state'])
        
        # Check if should transition from OPEN to HALF_OPEN
        if current_state == CircuitState.OPEN:
            if self._should_attempt_reset(state_info):
                self._transition_to_half_open(resource_id)
                return CircuitState.HALF_OPEN
                
        return current_state
        
    def is_open(self, resource_id: str) -> bool:
        """Check if circuit is open (blocking requests)"""
        return self.get_state(resource_id) == CircuitState.OPEN
        
    def is_closed(self, resource_id: str) -> bool:
        """Check if circuit is closed (normal operation)"""
        return self.get_state(resource_id) == CircuitState.CLOSED
        
    def is_half_open(self, resource_id: str) -> bool:
        """Check if circuit is half-open (testing recovery)"""
        return self.get_state(resource_id) == CircuitState.HALF_OPEN
        
    def can_execute(self, resource_id: str) -> bool:
        """Check if request can be executed"""
        state = self.get_state(resource_id)
        
        if state == CircuitState.CLOSED:
            return True
            
        if state == CircuitState.OPEN:
            return False
            
        if state == CircuitState.HALF_OPEN:
            state_info = self.states[resource_id]
            return state_info['half_open_attempts'] < self.half_open_requests
            
        return False
        
    def record_success(self, resource_id: str):
        """Record successful request"""
        if resource_id not in self.states:
            return
            
        state_info = self.states[resource_id]
        current_state = CircuitState(state_info['state'])
        
        if current_state == CircuitState.HALF_OPEN:
            state_info['consecutive_successes'] += 1
            
            # Check if enough successes to close circuit
            if state_info['consecutive_successes'] >= self.success_threshold:
                self._close_circuit(resource_id)
                logger.info(f"Circuit closed for resource {resource_id}")
                
        elif current_state == CircuitState.CLOSED:
            # Reset failure count on success
            state_info['consecutive_failures'] = 0
            
    def record_failure(self, resource_id: str, error: Optional[Exception] = None):
        """Record failed request"""
        if resource_id not in self.states:
            self._initialize_state(resource_id)
            
        state_info = self.states[resource_id]
        current_state = CircuitState(state_info['state'])
        
        state_info['last_failure'] = datetime.now()
        state_info['last_error'] = str(error) if error else None
        
        if current_state == CircuitState.CLOSED:
            state_info['consecutive_failures'] += 1
            
            # Check if should open circuit
            if state_info['consecutive_failures'] >= self.failure_threshold:
                self._open_circuit(resource_id)
                logger.warning(
                    f"Circuit opened for resource {resource_id} after "
                    f"{state_info['consecutive_failures']} failures"
                )
                
        elif current_state == CircuitState.HALF_OPEN:
            # Single failure in half-open reopens circuit
            self._open_circuit(resource_id)
            logger.warning(f"Circuit reopened for resource {resource_id}")
            
    def reset(self, resource_id: str):
        """Manually reset circuit to closed state"""
        if resource_id in self.states:
            self._close_circuit(resource_id)
            logger.info(f"Circuit manually reset for resource {resource_id}")
            
    def get_stats(self, resource_id: str) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        if resource_id not in self.states:
            return {
                'state': CircuitState.CLOSED.value,
                'consecutive_failures': 0,
                'consecutive_successes': 0
            }
            
        state_info = self.states[resource_id]
        return {
            'state': state_info['state'],
            'consecutive_failures': state_info['consecutive_failures'],
            'consecutive_successes': state_info['consecutive_successes'],
            'last_failure': state_info.get('last_failure'),
            'last_error': state_info.get('last_error'),
            'half_open_attempts': state_info.get('half_open_attempts', 0)
        }
        
    async def call_with_circuit_breaker(
        self,
        resource_id: str,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function with circuit breaker protection
        
        Args:
            resource_id: Resource identifier
            func: Async function to execute
            *args, **kwargs: Function arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitOpenError: If circuit is open
        """
        if not self.can_execute(resource_id):
            raise CircuitOpenError(
                f"Circuit breaker is open for resource {resource_id}"
            )
            
        try:
            # Track half-open attempts
            if self.is_half_open(resource_id):
                self.states[resource_id]['half_open_attempts'] += 1
                
            # Execute function
            result = await func(*args, **kwargs)
            
            # Record success
            self.record_success(resource_id)
            return result
            
        except Exception as e:
            # Record failure
            self.record_failure(resource_id, e)
            raise
            
    # Private methods
    
    def _initialize_state(self, resource_id: str):
        """Initialize state for new resource"""
        self.states[resource_id] = {
            'state': CircuitState.CLOSED.value,
            'consecutive_failures': 0,
            'consecutive_successes': 0,
            'last_failure': None,
            'last_error': None,
            'half_open_attempts': 0
        }
        
    def _open_circuit(self, resource_id: str):
        """Open the circuit"""
        state_info = self.states[resource_id]
        state_info['state'] = CircuitState.OPEN.value
        state_info['consecutive_successes'] = 0
        state_info['circuit_opened_at'] = datetime.now()
        
    def _close_circuit(self, resource_id: str):
        """Close the circuit"""
        if resource_id not in self.states:
            self._initialize_state(resource_id)
        else:
            state_info = self.states[resource_id]
            state_info['state'] = CircuitState.CLOSED.value
            state_info['consecutive_failures'] = 0
            state_info['consecutive_successes'] = 0
            state_info['half_open_attempts'] = 0
            
    def _transition_to_half_open(self, resource_id: str):
        """Transition to half-open state"""
        state_info = self.states[resource_id]
        state_info['state'] = CircuitState.HALF_OPEN.value
        state_info['half_open_attempts'] = 0
        state_info['consecutive_successes'] = 0
        
    def _should_attempt_reset(self, state_info: Dict[str, Any]) -> bool:
        """Check if should try to reset from open state"""
        if 'circuit_opened_at' not in state_info:
            return True
            
        elapsed = datetime.now() - state_info['circuit_opened_at']
        return elapsed.total_seconds() >= self.recovery_timeout


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open"""
    pass