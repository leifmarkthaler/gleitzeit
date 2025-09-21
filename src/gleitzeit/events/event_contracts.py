"""
Event Contracts System for Gleitzeit

Defines the contract of which components should handle which events.
This ensures all critical events have handlers before the system starts.
"""

import logging
from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class HandlerStatus(Enum):
    """Status of a handler registration."""
    PENDING = "pending"
    REGISTERED = "registered"
    MISSING = "missing"


@dataclass
class EventContract:
    """Contract for an event type."""
    event_type: str
    required_handlers: List[str]  # Component names that must handle this
    optional_handlers: List[str] = None  # Components that may handle this
    critical: bool = True  # If True, system won't start without handlers


class EventContracts:
    """
    Central registry of event contracts.

    This defines which components MUST handle which events
    for the system to function correctly.
    """

    # Core workflow events - CRITICAL for operation
    WORKFLOW_CONTRACTS = {
        'workflow:submitted': EventContract(
            event_type='workflow:submitted',
            required_handlers=['StatelessTaskOrchestrator'],
            critical=True
        ),
        'task:ready': EventContract(
            event_type='task:ready',
            required_handlers=['StatelessTaskOrchestrator'],
            critical=True
        ),
        'task:completed': EventContract(
            event_type='task:completed',
            required_handlers=['StatelessTaskOrchestrator'],
            optional_handlers=['WorkflowManager'],
            critical=True
        ),
        'task:failed': EventContract(
            event_type='task:failed',
            required_handlers=['StatelessTaskOrchestrator'],
            optional_handlers=['RetryManager'],
            critical=True
        ),
        'workflow:completed': EventContract(
            event_type='workflow:completed',
            required_handlers=['WorkflowManager'],
            critical=True
        ),
        'workflow:failed': EventContract(
            event_type='workflow:failed',
            required_handlers=['WorkflowManager'],
            critical=True
        ),
    }

    # Queue events
    QUEUE_CONTRACTS = {
        'task:submitted': EventContract(
            event_type='task:submitted',
            required_handlers=['QueueManager'],
            critical=True
        ),
        'task:ready_for_retry': EventContract(
            event_type='task:ready_for_retry',
            required_handlers=['QueueManager'],
            critical=True
        ),
    }

    # Timer events (optional)
    TIMER_CONTRACTS = {
        'timer:created': EventContract(
            event_type='timer:created',
            required_handlers=['TimerManager'],
            critical=False
        ),
        'timer:expired': EventContract(
            event_type='timer:expired',
            required_handlers=['TimerManager'],
            critical=False
        ),
    }

    # Signal events (optional)
    SIGNAL_CONTRACTS = {
        'signal:sent': EventContract(
            event_type='signal:sent',
            required_handlers=['SignalManager'],
            critical=False
        ),
        'workflow:waiting_for_signal': EventContract(
            event_type='workflow:waiting_for_signal',
            required_handlers=['SignalManager'],
            critical=False
        ),
    }

    @classmethod
    def get_all_contracts(cls) -> Dict[str, EventContract]:
        """Get all event contracts."""
        contracts = {}
        contracts.update(cls.WORKFLOW_CONTRACTS)
        contracts.update(cls.QUEUE_CONTRACTS)
        contracts.update(cls.TIMER_CONTRACTS)
        contracts.update(cls.SIGNAL_CONTRACTS)
        return contracts

    @classmethod
    def get_critical_contracts(cls) -> Dict[str, EventContract]:
        """Get only critical contracts that must be fulfilled."""
        return {
            event_type: contract
            for event_type, contract in cls.get_all_contracts().items()
            if contract.critical
        }


class HandlerRegistry:
    """
    Registry that tracks handler registrations against contracts.
    """

    def __init__(self, contracts: Optional[Dict[str, EventContract]] = None):
        """
        Initialize the handler registry.

        Args:
            contracts: Event contracts to validate against
        """
        self.contracts = contracts or EventContracts.get_all_contracts()
        self.handlers: Dict[str, List[callable]] = {}
        self.handler_components: Dict[str, Set[str]] = {}  # event_type -> component names

        # Initialize tracking for all contracted events
        for event_type in self.contracts:
            self.handlers[event_type] = []
            self.handler_components[event_type] = set()

    def register_handler(
        self,
        event_type: str,
        handler: callable,
        component_name: str
    ):
        """
        Register a handler for an event type.

        Args:
            event_type: Event type to handle
            handler: Handler function
            component_name: Name of the component registering
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
            self.handler_components[event_type] = set()

        self.handlers[event_type].append(handler)
        self.handler_components[event_type].add(component_name)

        logger.info(
            f"Registered handler from {component_name} for {event_type}"
        )

    def get_handlers(self, event_type: str) -> List[callable]:
        """Get all handlers for an event type."""
        return self.handlers.get(event_type, [])

    def validate_contracts(self) -> Dict[str, List[str]]:
        """
        Validate that all contracts are fulfilled.

        Returns:
            Dict of event_type -> list of missing required handlers
        """
        violations = {}

        for event_type, contract in self.contracts.items():
            if not contract.critical:
                continue

            registered = self.handler_components.get(event_type, set())
            required = set(contract.required_handlers)
            missing = required - registered

            if missing:
                violations[event_type] = list(missing)
                logger.error(
                    f"Contract violation for {event_type}: "
                    f"missing handlers from {missing}"
                )

        return violations

    def validate_critical_contracts(self):
        """
        Validate critical contracts and raise error if not fulfilled.

        Raises:
            SystemError: If critical contracts are not fulfilled
        """
        violations = self.validate_contracts()

        if violations:
            msg = "Critical event contracts not fulfilled:\n"
            for event_type, missing in violations.items():
                msg += f"  - {event_type}: missing {missing}\n"
            raise SystemError(msg)

    def get_status(self) -> Dict[str, Dict]:
        """Get detailed status of all contracts."""
        status = {}

        for event_type, contract in self.contracts.items():
            registered = self.handler_components.get(event_type, set())
            required = set(contract.required_handlers)

            status[event_type] = {
                'critical': contract.critical,
                'required': list(required),
                'registered': list(registered),
                'missing': list(required - registered),
                'handler_count': len(self.handlers.get(event_type, [])),
                'status': HandlerStatus.REGISTERED if required.issubset(registered)
                         else HandlerStatus.MISSING if registered
                         else HandlerStatus.PENDING
            }

        return status

    def is_ready(self) -> bool:
        """Check if all critical contracts are fulfilled."""
        violations = self.validate_contracts()
        return len(violations) == 0