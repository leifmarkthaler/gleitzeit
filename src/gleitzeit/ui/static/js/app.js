// Gleitzeit UI JavaScript

// Check API status
async function checkAPIStatus() {
    const indicator = document.getElementById('api-status');
    if (!indicator) return;

    try {
        const response = await fetch('/api/health');
        if (response.ok) {
            indicator.style.background = 'var(--success-color)';
        } else {
            indicator.style.background = 'var(--error-color)';
        }
    } catch (error) {
        indicator.style.background = 'var(--error-color)';
    }
}

// Initialize HTMX
document.addEventListener('DOMContentLoaded', function() {
    // Check API status on load and periodically
    checkAPIStatus();
    setInterval(checkAPIStatus, 10000); // Every 10 seconds

    // Configure HTMX
    htmx.config.defaultSwapStyle = 'innerHTML';
    htmx.config.defaultSettleDelay = 100;

    // Handle HTMX events
    document.body.addEventListener('htmx:afterRequest', function(event) {
        // Handle errors
        if (event.detail.xhr.status >= 400) {
            console.error('Request failed:', event.detail);
        }
    });

    // Handle workflow submission
    document.body.addEventListener('htmx:afterSwap', function(event) {
        if (event.detail.target.id === 'workflow-result') {
            // Check if submission was successful
            const result = event.detail.target.innerText;
            if (result.includes('workflow_id')) {
                // Parse response and redirect
                try {
                    const data = JSON.parse(result);
                    window.location.href = `/workflows/${data.workflow_id}`;
                } catch (e) {
                    console.log('Workflow submitted successfully');
                }
            }
        }
    });
});

// Utility functions
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}

function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
        return `${minutes}m ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Show temporary success message
        const msg = document.createElement('div');
        msg.textContent = 'Copied to clipboard!';
        msg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: var(--success-color); color: white; padding: 10px 20px; border-radius: 5px; z-index: 9999;';
        document.body.appendChild(msg);
        setTimeout(() => msg.remove(), 2000);
    });
}