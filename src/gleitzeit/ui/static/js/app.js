// Gleitzeit UI - Main Application JavaScript

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    console.log('Gleitzeit UI initialized');
    
    // Update server time
    updateServerTime();
    setInterval(updateServerTime, 1000);
    
    // Initialize tooltips
    initTooltips();
    
    // Setup HTMX error handling
    setupHTMXErrorHandling();
});

// Update server time in footer
function updateServerTime() {
    const serverTimeElement = document.getElementById('server-time');
    if (serverTimeElement) {
        serverTimeElement.textContent = new Date().toLocaleString();
    }
}

// Initialize tooltips
function initTooltips() {
    // Add tooltip functionality if needed
}

// Setup HTMX error handling
function setupHTMXErrorHandling() {
    document.body.addEventListener('htmx:responseError', function(evt) {
        console.error('HTMX request failed:', evt.detail);
        
        // Show error notification
        showNotification('Request failed. Please try again.', 'error');
    });
    
    document.body.addEventListener('htmx:sendError', function(evt) {
        console.error('HTMX send error:', evt.detail);
        showNotification('Connection error. Please check your network.', 'error');
    });
}

// Show notification
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Add to body
    document.body.appendChild(notification);
    
    // Animate in
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// Format bytes to human readable
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Format duration
function formatDuration(seconds) {
    if (seconds < 60) {
        return `${seconds}s`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${minutes}m ${secs}s`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }
}

// Global functions for templates
window.formatTime = function(timestamp) {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleString();
};

window.getStatusIcon = function(status) {
    switch(status) {
        case 'completed': return '✓';
        case 'running': return '▶';
        case 'failed': return '✗';
        case 'pending': return '○';
        case 'cancelled': return '⊘';
        default: return '•';
    }
};

// Add notification styles
const style = document.createElement('style');
style.textContent = `
    .notification {
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        border-radius: 0.5rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        background: white;
        transform: translateX(400px);
        transition: transform 0.3s ease;
        z-index: 10000;
        max-width: 300px;
    }
    
    .notification.show {
        transform: translateX(0);
    }
    
    .notification-info {
        background: #EBF8FF;
        color: #2B6CB0;
        border: 1px solid #90CDF4;
    }
    
    .notification-success {
        background: #F0FDF4;
        color: #166534;
        border: 1px solid #86EFAC;
    }
    
    .notification-error {
        background: #FEF2F2;
        color: #991B1B;
        border: 1px solid #FCA5A5;
    }
    
    .notification-warning {
        background: #FFFBEB;
        color: #92400E;
        border: 1px solid #FCD34D;
    }
`;
document.head.appendChild(style);