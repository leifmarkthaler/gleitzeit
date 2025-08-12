"""
Event routing and correlation tracking for Gleitzeit V5

Provides utilities for tracking event flows across distributed components
and routing events efficiently.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class EventTrace:
    """Represents a single event in an execution trace"""
    correlation_id: str
    event_name: str
    timestamp: datetime
    source_component: str
    target_component: Optional[str] = None
    data_size: int = 0
    processing_time_ms: Optional[float] = None


@dataclass
class EventCorrelation:
    """Tracks related events by correlation ID"""
    correlation_id: str
    root_event: str
    started_at: datetime
    events: List[EventTrace] = field(default_factory=list)
    completed: bool = False
    error: Optional[str] = None


class CorrelationTracker:
    """
    Tracks event correlations for distributed tracing and debugging
    
    Helps understand event flows across multiple components and 
    identify performance bottlenecks or failures.
    """
    
    def __init__(self, max_correlations: int = 1000):
        self.max_correlations = max_correlations
        self.correlations: Dict[str, EventCorrelation] = {}
        self.component_events: Dict[str, List[str]] = defaultdict(list)
        
    def start_correlation(
        self, 
        correlation_id: str, 
        root_event: str,
        source_component: str
    ) -> EventCorrelation:
        """Start tracking a new event correlation"""
        
        # Clean up old correlations if we're at capacity
        if len(self.correlations) >= self.max_correlations:
            self._cleanup_old_correlations()
        
        correlation = EventCorrelation(
            correlation_id=correlation_id,
            root_event=root_event,
            started_at=datetime.utcnow()
        )
        
        self.correlations[correlation_id] = correlation
        self.component_events[source_component].append(correlation_id)
        
        return correlation
    
    def track_outgoing(
        self,
        correlation_id: str,
        event_name: str,
        data: Dict[str, Any],
        source_component: str = "unknown"
    ):
        """Track an outgoing event"""
        
        # Get or create correlation
        if correlation_id not in self.correlations:
            self.start_correlation(correlation_id, event_name, source_component)
        
        correlation = self.correlations[correlation_id]
        
        # Create event trace
        trace = EventTrace(
            correlation_id=correlation_id,
            event_name=event_name,
            timestamp=datetime.utcnow(),
            source_component=source_component,
            data_size=len(str(data))
        )
        
        correlation.events.append(trace)
    
    def track_incoming(
        self,
        correlation_id: str,
        event_name: str,
        data: Dict[str, Any],
        target_component: str,
        processing_time_ms: Optional[float] = None
    ):
        """Track an incoming event"""
        
        if correlation_id not in self.correlations:
            # This shouldn't happen in normal flow, but handle gracefully
            self.start_correlation(correlation_id, event_name, "unknown")
        
        correlation = self.correlations[correlation_id]
        
        # Find the corresponding outgoing event and update it
        for trace in reversed(correlation.events):
            if trace.event_name == event_name and trace.target_component is None:
                trace.target_component = target_component
                trace.processing_time_ms = processing_time_ms
                break
        else:
            # No matching outgoing event found, create new trace
            trace = EventTrace(
                correlation_id=correlation_id,
                event_name=event_name,
                timestamp=datetime.utcnow(),
                source_component="unknown",
                target_component=target_component,
                data_size=len(str(data)),
                processing_time_ms=processing_time_ms
            )
            correlation.events.append(trace)
    
    def complete_correlation(self, correlation_id: str, error: Optional[str] = None):
        """Mark a correlation as completed"""
        if correlation_id in self.correlations:
            self.correlations[correlation_id].completed = True
            self.correlations[correlation_id].error = error
    
    def get_correlation(self, correlation_id: str) -> Optional[EventCorrelation]:
        """Get correlation by ID"""
        return self.correlations.get(correlation_id)
    
    def get_component_correlations(self, component_id: str) -> List[EventCorrelation]:
        """Get all correlations involving a specific component"""
        correlation_ids = self.component_events.get(component_id, [])
        return [self.correlations[cid] for cid in correlation_ids if cid in self.correlations]
    
    def get_active_correlations(self) -> List[EventCorrelation]:
        """Get all active (non-completed) correlations"""
        return [c for c in self.correlations.values() if not c.completed]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get correlation tracking statistics"""
        total_correlations = len(self.correlations)
        active_correlations = len(self.get_active_correlations())
        
        # Event statistics
        total_events = sum(len(c.events) for c in self.correlations.values())
        
        # Component statistics
        component_stats = {}
        for component, correlation_ids in self.component_events.items():
            component_stats[component] = len(correlation_ids)
        
        return {
            'total_correlations': total_correlations,
            'active_correlations': active_correlations,
            'completed_correlations': total_correlations - active_correlations,
            'total_events': total_events,
            'components_involved': len(self.component_events),
            'component_stats': component_stats
        }
    
    def _cleanup_old_correlations(self):
        """Remove old completed correlations to free memory"""
        # Remove oldest 20% of completed correlations
        completed = [c for c in self.correlations.values() if c.completed]
        completed.sort(key=lambda x: x.started_at)
        
        to_remove = completed[:len(completed) // 5]
        for correlation in to_remove:
            self.correlations.pop(correlation.correlation_id, None)
            
            # Also clean up component tracking
            for component, correlation_ids in self.component_events.items():
                if correlation.correlation_id in correlation_ids:
                    correlation_ids.remove(correlation.correlation_id)


class EventRouter:
    """
    Routes events between components based on component capabilities and load
    
    Used by the Central Hub to efficiently distribute events to appropriate
    components based on their type, capabilities, and current load.
    """
    
    def __init__(self):
        self.components: Dict[str, Dict[str, Any]] = defaultdict(dict)  # component_type -> sid -> info
        self.component_capabilities: Dict[str, Set[str]] = {}  # sid -> capabilities
        self.load_balancing_state: Dict[str, int] = defaultdict(int)  # component_type -> round_robin_index
    
    def register_component(
        self, 
        sid: str, 
        component_type: str, 
        component_id: str,
        capabilities: List[str]
    ):
        """Register a component for event routing"""
        
        component_info = {
            'id': component_id,
            'type': component_type,
            'capabilities': set(capabilities),
            'registered_at': datetime.utcnow(),
            'last_seen': datetime.utcnow(),
            'event_count': 0,
            'load_score': 0.0  # Could be enhanced with actual metrics
        }
        
        self.components[component_type][sid] = component_info
        self.component_capabilities[sid] = set(capabilities)
    
    def unregister_component(self, sid: str):
        """Unregister a component"""
        # Find and remove from components dict
        for component_type, components in self.components.items():
            if sid in components:
                del components[sid]
                break
        
        # Remove from capabilities
        self.component_capabilities.pop(sid, None)
    
    def find_component_for_capability(self, capability: str) -> Optional[str]:
        """Find a component that has the specified capability"""
        
        # Find all components with this capability
        eligible_sids = [
            sid for sid, capabilities in self.component_capabilities.items()
            if capability in capabilities
        ]
        
        if not eligible_sids:
            return None
        
        # Simple round-robin selection
        # In production, this could consider load, latency, etc.
        index = self.load_balancing_state[capability] % len(eligible_sids)
        self.load_balancing_state[capability] = (index + 1) % len(eligible_sids)
        
        return eligible_sids[index]
    
    def find_component_by_type(self, component_type: str) -> Optional[str]:
        """Find a component of the specified type"""
        
        if component_type not in self.components:
            return None
        
        available_sids = list(self.components[component_type].keys())
        if not available_sids:
            return None
        
        # Round-robin selection
        index = self.load_balancing_state[component_type] % len(available_sids)
        self.load_balancing_state[component_type] = (index + 1) % len(available_sids)
        
        selected_sid = available_sids[index]
        
        # Update component metrics
        self.components[component_type][selected_sid]['event_count'] += 1
        self.components[component_type][selected_sid]['last_seen'] = datetime.utcnow()
        
        return selected_sid
    
    def get_all_components_by_type(self, component_type: str) -> List[str]:
        """Get all component SIDs of the specified type"""
        return list(self.components.get(component_type, {}).keys())
    
    def get_component_info(self, sid: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific component"""
        for components in self.components.values():
            if sid in components:
                return components[sid]
        return None
    
    def get_routing_statistics(self) -> Dict[str, Any]:
        """Get routing statistics"""
        
        stats = {
            'total_components': sum(len(components) for components in self.components.values()),
            'components_by_type': {
                comp_type: len(components) 
                for comp_type, components in self.components.items()
            },
            'total_capabilities': len(set().union(*self.component_capabilities.values())),
            'load_balancing_state': dict(self.load_balancing_state)
        }
        
        return stats
    
    def update_component_health(self, sid: str, health_metrics: Dict[str, Any]):
        """Update component health metrics for better routing decisions"""
        component_info = self.get_component_info(sid)
        if component_info:
            component_info['last_seen'] = datetime.utcnow()
            component_info['health_metrics'] = health_metrics
            
            # Update load score based on health metrics
            # This is a simple example - could be much more sophisticated
            events_processed = health_metrics.get('events_processed', 0)
            uptime = health_metrics.get('uptime_seconds', 1)
            component_info['load_score'] = events_processed / uptime if uptime > 0 else 0