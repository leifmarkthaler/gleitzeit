// WebSocket connection management for real-time updates

class GleitzeitWebSocket {
    constructor() {
        this.ws = null;
        this.reconnectInterval = 5000;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.subscriptions = new Set(['workflows', 'tasks', 'metrics', 'system']);
        this.connect();
    }
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/updates`;
        
        console.log('Connecting to WebSocket:', wsUrl);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => this.onOpen();
            this.ws.onmessage = (event) => this.onMessage(event);
            this.ws.onclose = () => this.onClose();
            this.ws.onerror = (error) => this.onError(error);
        } catch (error) {
            console.error('WebSocket connection failed:', error);
            this.scheduleReconnect();
        }
    }
    
    onOpen() {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        
        // Update connection status
        this.updateConnectionStatus('connected');
        
        // Subscribe to channels
        this.subscribe(Array.from(this.subscriptions));
        
        // Send initial ping
        this.ping();
        
        // Setup ping interval
        this.pingInterval = setInterval(() => this.ping(), 30000);
    }
    
    onMessage(event) {
        try {
            const message = JSON.parse(event.data);
            console.log('WebSocket message:', message);
            
            // Handle different message types
            switch (message.type) {
                case 'connection':
                    console.log('Connection confirmed:', message);
                    break;
                    
                case 'subscription':
                    console.log('Subscription updated:', message.channels);
                    break;
                    
                case 'workflow_update':
                    this.handleWorkflowUpdate(message.data);
                    break;
                    
                case 'task_update':
                    this.handleTaskUpdate(message.data);
                    break;
                    
                case 'metrics_update':
                    this.handleMetricsUpdate(message.data);
                    break;
                    
                case 'system_event':
                    this.handleSystemEvent(message);
                    break;
                    
                case 'status_update':
                    this.handleStatusUpdate(message.data);
                    break;
                    
                case 'pong':
                    // Ping response received
                    break;
                    
                case 'error':
                    console.error('WebSocket error:', message.message);
                    break;
                    
                default:
                    console.log('Unknown message type:', message.type);
            }
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    }
    
    onClose() {
        console.log('WebSocket disconnected');
        this.updateConnectionStatus('disconnected');
        
        // Clear ping interval
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
        
        // Schedule reconnection
        this.scheduleReconnect();
    }
    
    onError(error) {
        console.error('WebSocket error:', error);
        this.updateConnectionStatus('error');
    }
    
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            this.updateConnectionStatus('failed');
            return;
        }
        
        this.reconnectAttempts++;
        console.log(`Reconnecting in ${this.reconnectInterval}ms (attempt ${this.reconnectAttempts})`);
        
        setTimeout(() => {
            this.connect();
        }, this.reconnectInterval);
    }
    
    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('WebSocket not connected, cannot send message:', message);
        }
    }
    
    subscribe(channels) {
        this.send({
            type: 'subscribe',
            channels: channels
        });
        
        // Update subscriptions
        channels.forEach(channel => this.subscriptions.add(channel));
    }
    
    unsubscribe(channels) {
        this.send({
            type: 'unsubscribe',
            channels: channels
        });
        
        // Update subscriptions
        channels.forEach(channel => this.subscriptions.delete(channel));
    }
    
    ping() {
        this.send({ type: 'ping' });
    }
    
    updateConnectionStatus(status) {
        const statusElement = document.getElementById('connection-status');
        if (!statusElement) return;
        
        const statusDot = statusElement.querySelector('.status-dot');
        const statusText = statusElement.querySelector('.status-text');
        
        switch (status) {
            case 'connected':
                statusDot.className = 'status-dot connected';
                statusText.textContent = 'Connected';
                break;
            case 'disconnected':
                statusDot.className = 'status-dot';
                statusText.textContent = 'Disconnected';
                break;
            case 'error':
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Error';
                break;
            case 'failed':
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Connection Failed';
                break;
            default:
                statusDot.className = 'status-dot';
                statusText.textContent = 'Connecting...';
        }
    }
    
    handleWorkflowUpdate(data) {
        console.log('Workflow update:', data);
        
        // Trigger HTMX refresh for workflow-related elements
        const workflowsList = document.getElementById('workflows-list');
        if (workflowsList) {
            htmx.trigger(workflowsList, 'load');
        }
        
        const recentWorkflows = document.getElementById('recent-workflows');
        if (recentWorkflows) {
            htmx.trigger(recentWorkflows, 'load');
        }
        
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('workflow-update', { detail: data }));
    }
    
    handleTaskUpdate(data) {
        console.log('Task update:', data);
        
        // Trigger HTMX refresh for task-related elements
        const tasksList = document.getElementById('tasks-list');
        if (tasksList) {
            htmx.trigger(tasksList, 'load');
        }
        
        const taskQueue = document.querySelector('.queue-status');
        if (taskQueue) {
            htmx.trigger(taskQueue, 'load');
        }
        
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('task-update', { detail: data }));
    }
    
    handleMetricsUpdate(data) {
        console.log('Metrics update:', data);
        
        // Update metric cards directly
        const activeWorkflowsCard = document.querySelector('#active-workflows-card .metric-value');
        if (activeWorkflowsCard && data.active_workflows !== undefined) {
            activeWorkflowsCard.textContent = data.active_workflows;
        }
        
        const runningTasksCard = document.querySelector('#running-tasks-card .metric-value');
        if (runningTasksCard && data.running_tasks !== undefined) {
            runningTasksCard.textContent = data.running_tasks;
        }
        
        // Dispatch custom event for charts
        window.dispatchEvent(new CustomEvent('ws-metrics-update', { detail: data }));
    }
    
    handleSystemEvent(message) {
        console.log('System event:', message);
        
        // Show notification for important system events
        if (message.event === 'error' || message.event === 'warning') {
            showNotification(message.data.message || 'System event occurred', message.event);
        }
        
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('system-event', { detail: message }));
    }
    
    handleStatusUpdate(data) {
        console.log('Status update:', data);
        
        // Update dashboard if present
        const dashboard = document.querySelector('.dashboard');
        if (dashboard) {
            // Trigger refresh of status elements
            const statusGrid = document.querySelector('.status-grid');
            if (statusGrid) {
                htmx.trigger(statusGrid, 'load');
            }
        }
        
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('status-update', { detail: data }));
    }
    
    close() {
        if (this.ws) {
            this.ws.close();
        }
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
        }
    }
}

// Initialize WebSocket connection when page loads
let gleitzeitWS = null;

document.addEventListener('DOMContentLoaded', function() {
    // Only initialize WebSocket if we're not using HTMX WebSocket extension
    if (!document.querySelector('[hx-ext="ws"]')) {
        gleitzeitWS = new GleitzeitWebSocket();
    }
});

// Clean up on page unload
window.addEventListener('beforeunload', function() {
    if (gleitzeitWS) {
        gleitzeitWS.close();
    }
});