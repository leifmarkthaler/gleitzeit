/**
 * Gleitzeit Cluster Dashboard - Real-time Client
 * 
 * Connects to Socket.IO server for live cluster monitoring
 */

class GleitzeitDashboard {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.stats = {
            activeWorkflows: 0,
            processingTasks: 0,
            activeNodes: 0,
            completedWorkflows: 0
        };
        this.workflows = new Map();
        this.nodes = new Map();
        this.activities = [];
        this.maxActivities = 50;
        
        this.init();
    }
    
    init() {
        this.setupSocketConnection();
        this.setupEventHandlers();
        this.startPeriodicUpdates();
        
        // Initial UI setup
        this.updateConnectionStatus('connecting');
        this.addActivity('system', 'Dashboard starting up...');
    }
    
    setupSocketConnection() {
        try {
            // Connect to Socket.IO server on same host
            this.socket = io('/cluster', {
                transports: ['websocket', 'polling'],
                timeout: 5000,
                reconnection: true,
                reconnectionDelay: 1000,
                reconnectionAttempts: 5
            });
            
            // Connection events
            this.socket.on('connect', () => {
                console.log('🚀 Connected to Gleitzeit cluster');
                this.connected = true;
                this.updateConnectionStatus('connected');
                this.addActivity('system', 'Connected to cluster server');
                
                // Authenticate
                this.socket.emit('authenticate', {
                    client_type: 'dashboard',
                    token: 'demo_token'
                });
            });
            
            this.socket.on('disconnect', (reason) => {
                console.log('❌ Disconnected from cluster:', reason);
                this.connected = false;
                this.updateConnectionStatus('disconnected');
                this.addActivity('error', `Disconnected: ${reason}`);
            });
            
            this.socket.on('connect_error', (error) => {
                console.error('❌ Connection error:', error);
                this.connected = false;
                this.updateConnectionStatus('disconnected');
                this.addActivity('error', `Connection failed: ${error.message}`);
            });
            
            // Authentication response
            this.socket.on('authenticated', (data) => {
                if (data.success) {
                    this.addActivity('system', 'Successfully authenticated');
                    this.requestClusterStats();
                } else {
                    this.addActivity('error', 'Authentication failed');
                }
            });
            
            // Workflow events
            this.socket.on('workflow:started', (data) => {
                this.handleWorkflowStarted(data);
            });
            
            this.socket.on('workflow:completed', (data) => {
                this.handleWorkflowCompleted(data);
            });
            
            this.socket.on('workflow:cancelled', (data) => {
                this.handleWorkflowCancelled(data);
            });
            
            // Task events
            this.socket.on('task:completed', (data) => {
                this.handleTaskCompleted(data);
            });
            
            this.socket.on('task:failed', (data) => {
                this.handleTaskFailed(data);
            });
            
            this.socket.on('task:progress', (data) => {
                this.handleTaskProgress(data);
            });
            
            // Node events
            this.socket.on('node:registered', (data) => {
                this.handleNodeRegistered(data);
            });
            
            this.socket.on('node:disconnected', (data) => {
                this.handleNodeDisconnected(data);
            });
            
            this.socket.on('node:status_change', (data) => {
                this.handleNodeStatusChange(data);
            });
            
            // Cluster stats response
            this.socket.on('cluster:stats_response', (data) => {
                this.updateClusterStats(data);
            });
            
        } catch (error) {
            console.error('❌ Failed to initialize Socket.IO:', error);
            this.updateConnectionStatus('disconnected');
            this.addActivity('error', `Failed to initialize connection: ${error.message}`);
        }
    }
    
    setupEventHandlers() {
        // Refresh button (if added later)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
                e.preventDefault();
                this.refreshDashboard();
            }
        });
    }
    
    startPeriodicUpdates() {
        // Request cluster stats every 5 seconds
        setInterval(() => {
            if (this.connected) {
                this.requestClusterStats();
            }
        }, 5000);
        
        // Update timestamps every second
        setInterval(() => {
            this.updateTimestamps();
        }, 1000);
    }
    
    // ========================
    // Connection Management
    // ========================
    
    updateConnectionStatus(status) {
        const indicator = document.getElementById('connection-indicator');
        const text = document.getElementById('connection-text');
        
        indicator.className = `status-${status}`;
        
        switch (status) {
            case 'connected':
                text.textContent = 'Connected';
                break;
            case 'connecting':
                text.textContent = 'Connecting...';
                break;
            case 'disconnected':
                text.textContent = 'Disconnected';
                break;
        }
    }
    
    requestClusterStats() {
        if (this.socket && this.connected) {
            this.socket.emit('cluster:stats');
        }
    }
    
    // ========================
    // Event Handlers
    // ========================
    
    handleWorkflowStarted(data) {
        console.log('📋 Workflow started:', data);
        
        const workflow = {
            id: data.workflow_id,
            name: data.name || 'Unnamed Workflow',
            status: 'running',
            totalTasks: data.total_tasks || 0,
            completedTasks: 0,
            failedTasks: 0,
            startedAt: new Date(data.timestamp),
            progress: 0
        };
        
        this.workflows.set(workflow.id, workflow);
        this.stats.activeWorkflows++;
        this.stats.processingTasks += workflow.totalTasks;
        
        this.updateStatsDisplay();
        this.updateWorkflowsList();
        this.addActivity('workflow', `Started: ${workflow.name} (${workflow.totalTasks} tasks)`);
    }
    
    handleWorkflowCompleted(data) {
        console.log('✅ Workflow completed:', data);
        
        const workflow = this.workflows.get(data.workflow_id);
        if (workflow) {
            workflow.status = data.status;
            workflow.completedTasks = data.completed_tasks || 0;
            workflow.failedTasks = data.failed_tasks || 0;
            workflow.completedAt = new Date(data.timestamp);
            workflow.progress = 100;
            
            this.stats.activeWorkflows--;
            this.stats.completedWorkflows++;
            this.stats.processingTasks -= workflow.totalTasks;
            
            // Remove from active workflows after a delay
            setTimeout(() => {
                this.workflows.delete(data.workflow_id);
                this.updateWorkflowsList();
            }, 30000);
        }
        
        this.updateStatsDisplay();
        this.updateWorkflowsList();
        this.addActivity('workflow', `Completed: ${workflow?.name || data.workflow_id} (${data.completed_tasks}/${data.completed_tasks + data.failed_tasks})`);
    }
    
    handleWorkflowCancelled(data) {
        console.log('❌ Workflow cancelled:', data);
        
        const workflow = this.workflows.get(data.workflow_id);
        if (workflow) {
            workflow.status = 'cancelled';
            workflow.cancelledAt = new Date(data.timestamp);
            
            this.stats.activeWorkflows--;
        }
        
        this.updateStatsDisplay();
        this.updateWorkflowsList();
        this.addActivity('workflow', `Cancelled: ${workflow?.name || data.workflow_id}`);
    }
    
    handleTaskCompleted(data) {
        const workflow = this.workflows.get(data.workflow_id);
        if (workflow) {
            workflow.completedTasks++;
            workflow.progress = Math.round((workflow.completedTasks + workflow.failedTasks) / workflow.totalTasks * 100);
        }
        
        this.updateWorkflowsList();
        this.addActivity('task', `Task completed: ${data.task_id.slice(0, 8)}`);
    }
    
    handleTaskFailed(data) {
        const workflow = this.workflows.get(data.workflow_id);
        if (workflow) {
            workflow.failedTasks++;
            workflow.progress = Math.round((workflow.completedTasks + workflow.failedTasks) / workflow.totalTasks * 100);
        }
        
        this.updateWorkflowsList();
        this.addActivity('error', `Task failed: ${data.task_id.slice(0, 8)} - ${data.error}`);
    }
    
    handleTaskProgress(data) {
        // Optional: Update task progress bars if implemented
        this.addActivity('task', `Progress: ${data.task_id.slice(0, 8)} - ${data.message || data.progress + '%'}`);
    }
    
    handleNodeRegistered(data) {
        console.log('🖥️ Node registered:', data);
        
        const node = {
            id: data.node_id,
            name: data.name,
            capabilities: data.capabilities,
            status: 'ready',
            registeredAt: new Date(data.timestamp),
            lastHeartbeat: new Date()
        };
        
        this.nodes.set(node.id, node);
        this.stats.activeNodes++;
        
        this.updateStatsDisplay();
        this.updateNodesList();
        this.addActivity('node', `Node registered: ${node.name}`);
    }
    
    handleNodeDisconnected(data) {
        console.log('❌ Node disconnected:', data);
        
        const node = this.nodes.get(data.node_id);
        if (node) {
            node.status = 'offline';
            node.disconnectedAt = new Date(data.timestamp);
            this.stats.activeNodes--;
        }
        
        this.updateStatsDisplay();
        this.updateNodesList();
        this.addActivity('node', `Node disconnected: ${data.name}`);
    }
    
    handleNodeStatusChange(data) {
        const node = this.nodes.get(data.node_id);
        if (node) {
            node.status = data.new_status;
            node.lastHeartbeat = new Date(data.timestamp);
        }
        
        this.updateNodesList();
    }
    
    // ========================
    // UI Updates
    // ========================
    
    updateClusterStats(data) {
        if (data.redis_stats) {
            this.stats.activeWorkflows = data.redis_stats.active_workflows || 0;
            this.stats.completedWorkflows = data.redis_stats.completed_workflows || 0;
        }
        
        this.stats.activeNodes = data.executor_nodes || 0;
        this.stats.processingTasks = Array.from(this.workflows.values())
            .filter(w => w.status === 'running')
            .reduce((sum, w) => sum + (w.totalTasks - w.completedTasks - w.failedTasks), 0);
        
        this.updateStatsDisplay();
    }
    
    updateStatsDisplay() {
        document.getElementById('active-workflows').textContent = this.stats.activeWorkflows;
        document.getElementById('processing-tasks').textContent = this.stats.processingTasks;
        document.getElementById('active-nodes').textContent = this.stats.activeNodes;
        document.getElementById('completed-workflows').textContent = this.stats.completedWorkflows;
    }
    
    updateWorkflowsList() {
        const container = document.getElementById('workflows-list');
        const workflows = Array.from(this.workflows.values());
        
        if (workflows.length === 0) {
            container.innerHTML = '<div class="empty-state"><p>No active workflows</p></div>';
            return;
        }
        
        container.innerHTML = workflows.map(workflow => `
            <div class="workflow-item">
                <div class="workflow-header">
                    <div class="workflow-name">${workflow.name}</div>
                    <span class="workflow-status status-${workflow.status}">${workflow.status}</span>
                </div>
                <div class="workflow-progress">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${workflow.progress}%"></div>
                    </div>
                    <span class="progress-text">${workflow.completedTasks}/${workflow.totalTasks}</span>
                </div>
            </div>
        `).join('');
    }
    
    updateNodesList() {
        const container = document.getElementById('nodes-list');
        const nodes = Array.from(this.nodes.values());
        
        if (nodes.length === 0) {
            container.innerHTML = '<div class="empty-state"><p>No nodes connected</p></div>';
            return;
        }
        
        container.innerHTML = nodes.map(node => `
            <div class="node-item">
                <div class="node-info">
                    <div class="node-name">${node.name}</div>
                    <div class="node-details">${node.capabilities?.cpu_cores || 'N/A'} cores, ${node.capabilities?.memory_gb || 'N/A'}GB RAM</div>
                </div>
                <div class="node-status node-${node.status}"></div>
            </div>
        `).join('');
    }
    
    addActivity(type, message) {
        const activity = {
            type,
            message,
            timestamp: new Date(),
            id: Date.now() + Math.random()
        };
        
        this.activities.unshift(activity);
        
        // Keep only recent activities
        if (this.activities.length > this.maxActivities) {
            this.activities = this.activities.slice(0, this.maxActivities);
        }
        
        this.updateActivityFeed();
    }
    
    updateActivityFeed() {
        const container = document.getElementById('activity-feed');
        
        container.innerHTML = this.activities.map(activity => `
            <div class="activity-item activity-type-${activity.type}">
                <div class="activity-time">${this.formatTime(activity.timestamp)}</div>
                <div class="activity-message">${activity.message}</div>
            </div>
        `).join('');
    }
    
    updateTimestamps() {
        const timeElements = document.querySelectorAll('.activity-time');
        timeElements.forEach((element, index) => {
            if (this.activities[index]) {
                element.textContent = this.formatTime(this.activities[index].timestamp);
            }
        });
    }
    
    // ========================
    // Utility Methods
    // ========================
    
    formatTime(date) {
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) { // Less than 1 minute
            return 'Just now';
        } else if (diff < 3600000) { // Less than 1 hour
            return `${Math.floor(diff / 60000)}m ago`;
        } else if (diff < 86400000) { // Less than 1 day
            return `${Math.floor(diff / 3600000)}h ago`;
        } else {
            return date.toLocaleDateString();
        }
    }
    
    refreshDashboard() {
        console.log('🔄 Refreshing dashboard...');
        this.addActivity('system', 'Dashboard refreshed');
        
        if (this.connected) {
            this.requestClusterStats();
        } else {
            // Try to reconnect
            this.socket?.connect();
        }
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Initializing Gleitzeit Dashboard...');
    window.dashboard = new GleitzeitDashboard();
});

// Handle page visibility changes
document.addEventListener('visibilitychange', () => {
    if (!document.hidden && window.dashboard) {
        // Page became visible, refresh data
        window.dashboard.refreshDashboard();
    }
});

// Global error handler
window.addEventListener('error', (event) => {
    console.error('💥 Dashboard error:', event.error);
    if (window.dashboard) {
        window.dashboard.addActivity('error', `JavaScript error: ${event.error.message}`);
    }
});