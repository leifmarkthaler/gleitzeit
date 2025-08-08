# Gleitzeit Professional Monitoring

Enterprise-grade terminal monitoring for Gleitzeit clusters with real-time metrics, professional visualizations, and comprehensive system observability.

## 🚀 Quick Start

```bash
# Start development environment
gleitzeit dev

# Launch professional monitor (in new terminal)
gleitzeit pro

# Or use basic monitoring
gleitzeit monitor

# Simple status check
gleitzeit status --watch
```

## 📊 Monitoring Options

### Professional Dashboard (`gleitzeit pro`)

**Enterprise-grade monitoring with:**
- 🎨 **Professional styling** with corporate color scheme
- 📈 **Real-time performance charts** with ASCII graphs
- 🚨 **Intelligent alerting** with severity levels
- 🔄 **Live updates** at 2 FPS with smooth animations
- ⌨️ **Keyboard shortcuts** for efficient navigation
- 📊 **Multiple view modes** (Overview, Nodes, Tasks, Workflows, Alerts)

**Features:**
- **System Overview**: Key metrics cards with health indicators
- **Node Management**: Detailed resource usage, uptime, load averages
- **Performance Metrics**: Throughput graphs, resource charts
- **Alert System**: Critical, Warning, Error, Info notifications
- **Smart Filtering**: Status-based filtering and sorting

### Basic Dashboard (`gleitzeit monitor`)

**Simplified monitoring with:**
- 📋 **Multi-panel layout** for nodes, tasks, workflows
- ⚡ **Real-time updates** with configurable refresh rate
- 📈 **Basic performance graphs** and statistics
- 🔍 **Task queue monitoring** with status indicators

### Status Command (`gleitzeit status`)

**Quick system check:**
- 📄 **Snapshot view** of cluster state
- 📊 **Summary statistics** and health metrics
- 👁️ **Watch mode** for continuous monitoring
- 💾 **Lightweight** resource usage

## 🎮 Professional Interface Guide

### Layout Structure
```
┌─────────────────────────────────────────────────────────┐
│                    HEADER (Status Bar)                  │
├──────────────┬──────────────────────────┬────────────────┤
│   SIDEBAR    │        MAIN CONTENT      │    SECONDARY   │
│              │                          │                │
│ • Navigation │  Current View Panel      │  • Performance │
│ • Controls   │  (Overview/Nodes/Tasks)  │  • Alerts      │
│ • Health     │                          │  • Metrics     │
│              │                          │                │
├──────────────┴──────────────────────────┴────────────────┤
│                    FOOTER (Controls)                     │
└─────────────────────────────────────────────────────────┘
```

### Color Scheme
- 🔵 **Primary**: Information and highlights (`#2563eb`)
- 🟢 **Success**: Healthy status and completions (`#059669`)
- 🟡 **Warning**: Alerts and attention needed (`#d97706`)
- 🔴 **Danger**: Errors and critical issues (`#dc2626`)
- 🔷 **Info**: Additional information (`#0891b2`)

### Keyboard Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `1-5` | **Switch Views** | Navigate between Overview, Nodes, Workflows, Tasks, Alerts |
| `↑↓` | **Navigate Items** | Scroll through lists and tables |
| `SPACE` | **Pause/Resume** | Toggle live updates |
| `F` | **Filter Status** | Filter by active/inactive/all |
| `S` | **Sort Column** | Change sorting criteria |
| `D` | **Toggle Details** | Show/hide detailed information |
| `R` | **Refresh Now** | Force immediate data refresh |
| `Q` | **Quit** | Exit monitoring dashboard |

## 📈 Metrics and Monitoring

### Key Performance Indicators

**System Health:**
- 🖥️ **Node Status**: Active/offline nodes with health indicators
- ⚡ **Task Throughput**: Tasks per second with trend analysis
- 🧠 **Resource Usage**: CPU and memory utilization across cluster
- 📊 **Queue Depth**: Pending tasks and processing capacity

**Performance Metrics:**
- 📈 **Throughput Graphs**: Real-time task completion rates
- ⏱️ **Response Times**: Average task execution duration
- 📉 **Error Rates**: Failed task percentage with trending
- 🔄 **Update Performance**: Dashboard refresh rates and latency

**Operational Metrics:**
- 🔌 **Connection Status**: Cluster connectivity with latency
- 📋 **Workflow Progress**: Active workflows and completion rates
- 🚨 **Alert Frequency**: System alerts by severity level
- 🕐 **Uptime Tracking**: Node availability and stability

### Alert System

**Alert Levels:**
- 🔥 **CRITICAL**: System failures requiring immediate action
- ⚠️ **WARNING**: Performance issues needing attention  
- ❌ **ERROR**: Operational errors with impact
- ℹ️ **INFO**: General system notifications

**Smart Alerting:**
- **Threshold Monitoring**: CPU >90%, Memory >90%, Error Rate >10%
- **Anomaly Detection**: Unusual patterns in throughput
- **Connection Issues**: Node disconnections and timeouts
- **Performance Degradation**: Response time increases

## 🛠️ Configuration

### Environment Variables
```bash
# Monitor settings
export GLEITZEIT_MONITOR_REFRESH=0.5    # Refresh rate in seconds
export GLEITZEIT_MONITOR_WIDTH=120      # Terminal width
export GLEITZEIT_MONITOR_HEIGHT=40      # Terminal height
export GLEITZEIT_MONITOR_THEME=dark     # Color theme

# Connection settings  
export GLEITZEIT_CLUSTER_URL=http://localhost:8000
export GLEITZEIT_MONITOR_TIMEOUT=10     # Connection timeout
export GLEITZEIT_MONITOR_RETRIES=3      # Retry attempts
```

### Command Line Options
```bash
# Professional monitoring
gleitzeit pro --cluster http://remote:8000 --refresh 1.0

# Basic monitoring with custom settings
gleitzeit monitor --pro --refresh 2.0

# Status with watch mode
gleitzeit status --watch --interval 5
```

## 🎯 Use Cases

### Development Workflow
```bash
# Terminal 1: Start development cluster
gleitzeit dev --executors 3

# Terminal 2: Monitor cluster performance  
gleitzeit pro

# Terminal 3: Submit workflows
gleitzeit run --workflow pipeline.yaml
```

### Production Monitoring
```bash
# Full-screen professional monitoring
gleitzeit pro --cluster https://prod.cluster.com

# Background status logging
gleitzeit status --watch --interval 30 > monitor.log
```

### Performance Analysis
```bash
# High-frequency monitoring for debugging
gleitzeit pro --refresh 0.1

# Resource usage tracking
gleitzeit monitor --pro > performance.log
```

## 🔧 Troubleshooting

### Common Issues

**Connection Problems:**
```bash
# Check cluster connectivity
gleitzeit status --cluster http://localhost:8000

# Verify service is running
curl http://localhost:8000/health
```

**Performance Issues:**
```bash
# Reduce refresh rate
gleitzeit pro --refresh 2.0

# Use basic monitoring
gleitzeit monitor
```

**Display Problems:**
```bash
# Check terminal size
echo $COLUMNS $LINES

# Use smaller interface
gleitzeit status --watch
```

### Requirements
```bash
# Install monitoring dependencies
pip install -r requirements-monitor.txt

# Rich library for professional interface
pip install "rich>=13.0.0"
```

## 🚀 Advanced Features

### Custom Themes
- **Dark Mode**: Professional dark theme (default)
- **Corporate**: Enterprise color scheme
- **High Contrast**: Accessibility-focused colors

### Data Export
- **JSON Export**: Metrics and logs in structured format
- **CSV Export**: Performance data for analysis
- **Log Integration**: Compatible with system logging

### Integration
- **Prometheus**: Metrics export for external monitoring
- **Grafana**: Dashboard integration capabilities
- **Alertmanager**: Alert routing and management

## 📚 API Reference

The monitoring system provides programmatic access:

```python
from gleitzeit_cluster.cli_monitor_pro import ProfessionalGleitzeitMonitor

# Create monitor instance
monitor = ProfessionalGleitzeitMonitor(
    cluster_url="http://localhost:8000",
    refresh_rate=0.5
)

# Connect and start monitoring
await monitor.connect()
await monitor.run()
```

---

**Professional monitoring for professional workflows.** 🚀