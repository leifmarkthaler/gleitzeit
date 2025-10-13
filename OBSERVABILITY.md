# Gleitzeit Observability Stack

**Redis + Loki + Grafana + Prometheus Integration**

Gleitzeit implements a hybrid logging architecture that provides both fast real-time queries and long-term persistent storage.

## Architecture Overview

```
┌─────────────────┐
│  Gleitzeit App  │
└────────┬────────┘
         │
         ├──────────────────┬─────────────────┐
         ▼                  ▼                 ▼
    ┌─────────┐       ┌──────────┐    ┌────────────┐
    │  Redis  │       │   Loki   │    │ Prometheus │
    │ (Hot)   │◄──────│ Exporter │    │  (/metrics)│
    └────┬────┘       └─────┬────┘    └──────┬─────┘
         │                  │                 │
         │                  ▼                 │
         │            ┌──────────┐            │
         └───────────►│ Grafana  │◄───────────┘
                      └──────────┘
```

### Components

1. **Redis** (Hot Storage)
   - Fast, in-memory log storage
   - 48-hour TTL (configurable)
   - Optimized for real-time queries
   - Structured logs with indexes

2. **Loki** (Cold Storage)
   - Long-term persistent storage
   - Compressed, cost-effective
   - 30-day retention (configurable)
   - Label-based indexing

3. **Loki Exporter**
   - Polls Redis every 5 seconds
   - Batches and pushes logs to Loki
   - Tracks progress to avoid duplicates
   - Handles backpressure and retries

4. **Prometheus**
   - Scrapes `/metrics` endpoint
   - Collects log counts and system metrics
   - Time-series database for metrics

5. **Grafana**
   - Unified dashboard for logs and metrics
   - Queries Loki for historical logs
   - Queries Redis for real-time logs
   - Queries Prometheus for metrics

## Quick Start

### 1. Start the Observability Stack

```bash
# Start Gleitzeit + Loki + Grafana + Prometheus
docker-compose -f docker-compose.yml -f docker-compose.observability.yml up
```

### 2. Access Grafana

- **URL**: http://localhost:3000
- **Username**: `admin`
- **Password**: `gleitzeit`

### 3. Explore Logs

Grafana comes pre-configured with:
- **Loki datasource** (for long-term logs)
- **Redis datasource** (for real-time logs)
- **Prometheus datasource** (for metrics)

## Configuration

### gleitzeit.yaml

```yaml
logging:
  # Redis TTL configuration (hot storage)
  ttl:
    debug: 172800     # 48 hours
    info: 172800      # 48 hours
    warning: 172800   # 48 hours
    error: 172800     # 48 hours

  # Loki integration (cold storage)
  loki:
    enabled: true                # Enable Loki exporter
    url: http://localhost:3100   # Loki server URL
    batch_size: 100              # Logs per batch
    poll_interval: 5             # Poll every 5 seconds
    retention_days: 30           # Loki retention period
```

### Enable Loki Exporter

Set `enabled: true` in the Loki configuration above, then restart Gleitzeit.

## Querying Logs

### Option 1: Grafana UI (Recommended)

1. Open Grafana: http://localhost:3000
2. Go to **Explore** (compass icon)
3. Select **Loki** datasource
4. Use LogQL queries:

```logql
# All logs
{job="gleitzeit"}

# Only errors
{job="gleitzeit", level="error"}

# Logs for specific workflow
{job="gleitzeit", workflow_id="abc123"}

# Search by text
{job="gleitzeit"} |= "timeout"

# Count errors per minute
rate({job="gleitzeit", level="error"}[1m])
```

### Option 2: Direct API Queries

**Query recent logs (from Redis):**
```bash
curl "http://localhost:8000/system/logs?level=INFO&limit=10"
```

**Query errors:**
```bash
curl "http://localhost:8000/system/logs/errors?limit=10"
```

**Query by workflow:**
```bash
curl "http://localhost:8000/system/logs/workflow/abc123?level=INFO"
```

**Get log statistics:**
```bash
curl "http://localhost:8000/system/logs/stats"
```

### Option 3: Query Loki Directly

```bash
# Query last 1 hour of logs
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job="gleitzeit"}' \
  --data-urlencode "start=$(date -u -d '1 hour ago' +%s)000000000" \
  --data-urlencode "end=$(date -u +%s)000000000" \
  | jq
```

## Metrics

### Prometheus Metrics Endpoint

Gleitzeit exposes metrics at: http://localhost:8000/metrics

**Example metrics:**
```prometheus
# HELP gleitzeit_logs_total Total number of logs by level
# TYPE gleitzeit_logs_total gauge
gleitzeit_logs_total{level="debug"} 60
gleitzeit_logs_total{level="info"} 2112
gleitzeit_logs_total{level="warning"} 308
gleitzeit_logs_total{level="error"} 13

# HELP gleitzeit_logs_total_all Total number of all logs
# TYPE gleitzeit_logs_total_all gauge
gleitzeit_logs_total_all 2493
```

### Prometheus Configuration

Prometheus is pre-configured to scrape:
- Gleitzeit API metrics (port 8000)
- Loki metrics (port 3100)
- Prometheus itself (port 9090)

See [config/prometheus.yml](config/prometheus.yml)

## Advanced Features

### Custom Grafana Dashboards

Create custom dashboards using:

**Log panels** (Loki):
- Error rate over time
- Log volume by level
- Slowest workflows
- Failed tasks

**Metric panels** (Prometheus):
- Workflow execution time (p50, p95, p99)
- Task throughput
- Redis memory usage
- Worker health

### Alerting

Configure alerts in Grafana for:
- High error rate
- Low task throughput
- High Redis memory usage
- Worker downtime

### Log Retention

**Redis (Hot Storage):**
- Configured in `gleitzeit.yaml → logging.ttl`
- Default: 48 hours
- Automatically expires via Redis TTL

**Loki (Cold Storage):**
- Configured in `config/loki-config.yaml → limits_config.retention_period`
- Default: 30 days (720 hours)
- Automatically compacted and deleted

## Troubleshooting

### Loki Exporter Not Working

**Check exporter logs:**
```bash
docker logs gleitzeit_loki_exporter
```

**Verify Loki is reachable:**
```bash
curl http://localhost:3100/ready
```

**Check configuration:**
```bash
# Ensure enabled: true in gleitzeit.yaml
grep -A 5 "loki:" gleitzeit.yaml
```

### No Metrics in Grafana

**Verify Prometheus is scraping:**
```bash
curl http://localhost:9090/api/v1/targets
```

**Check /metrics endpoint:**
```bash
curl http://localhost:8000/metrics
```

### Redis Memory Issues

**Check Redis memory:**
```bash
redis-cli info memory
```

**Reduce TTL in gleitzeit.yaml:**
```yaml
logging:
  ttl:
    debug: 86400    # 24 hours instead of 48
    info: 86400
    warning: 86400
    error: 86400
```

## Architecture Decisions

### Why Redis + Loki?

**Redis strengths:**
- Sub-millisecond query latency
- Perfect for real-time dashboards
- Structured data with indexes
- Native to Gleitzeit architecture

**Redis limitations:**
- Expensive for long-term storage (RAM)
- No compression
- Limited retention due to memory

**Loki strengths:**
- Cost-effective long-term storage
- 10x-50x compression
- Designed for log aggregation
- Native Grafana integration

**Loki limitations:**
- Higher query latency than Redis
- Not suitable for real-time queries

**Hybrid approach:**
- Redis for last 48 hours (hot)
- Loki for everything (cold)
- Best of both worlds

### Label Design

Loki indexes only metadata, not full log text. We use these labels:
- `level`: DEBUG, INFO, WARNING, ERROR
- `component`: TaskExecutionWorker, DependencyWorker, etc.
- `workflow_id`: Workflow identifier
- `task_id`: Task identifier
- `operation`: Specific operation name
- `job`: Always "gleitzeit"

Full log messages are stored as JSON in Loki's chunks.

## Performance

### Storage

**Redis (2500 logs, 48 hours):**
- ~5-10 MB RAM
- No compression
- Fast queries

**Loki (1M logs, 30 days):**
- ~50-100 MB disk
- 10x-50x compression
- Slower queries

### Query Performance

**Redis:**
- Real-time queries: <10ms
- Perfect for dashboards
- Limited to 48 hours

**Loki:**
- Historical queries: 100-1000ms
- Good for investigations
- Unlimited retention

## Next Steps

1. **Create Dashboards**: Build custom Grafana dashboards for your workflows
2. **Set up Alerts**: Configure alerting for critical errors
3. **Tune Retention**: Adjust TTL and retention based on your needs
4. **Add Metrics**: Extend `/metrics` endpoint with workflow/task metrics
5. **Scale Loki**: Use object storage (S3) for production deployments

## Resources

- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [LogQL Cheat Sheet](https://grafana.com/docs/loki/latest/logql/)
