# Windmill Platform Analysis - Scaling & Issues Report

## Executive Summary

Windmill is an open-source workflow automation platform built with Rust that claims to be 13x faster than Airflow. While it demonstrates strong performance in benchmarks and has garnered 14.6k GitHub stars, our analysis reveals significant architectural limitations that impact scalability beyond 100-500 workers.

## Core Architecture

### Technology Stack
- **Backend**: Rust (high-performance core engine)
- **Frontend**: Svelte
- **Database**: PostgreSQL (job queue and state management)
- **Supported Languages**: Python, TypeScript, Go, Bash, SQL, GraphQL
- **Runtime Isolation**: nsjail for sandboxed execution

### Performance Claims
- 13x faster than Airflow
- 26 million jobs/month per worker (100ms jobs)
- Supports up to 1000 workers on Kubernetes
- ~50ms job execution overhead

## Critical Scaling Bottlenecks

### 1. PostgreSQL as Job Queue (Primary Bottleneck)

**The Problem:**
- Workers poll database every 50ms for new jobs
- With 1000 workers = 20,000 DB queries/second just for polling
- Creates massive load even when system is idle

**Impact at Scale:**
```
Workers: 100  → 2,000 polls/sec → Manageable
Workers: 500  → 10,000 polls/sec → Database stress
Workers: 1000 → 20,000 polls/sec → Likely bottleneck
```

**Why This Matters:**
- PostgreSQL connection limits (typically 100-200 connections)
- Lock contention when workers compete for jobs
- CPU overhead from constant polling
- Network saturation from polling traffic

### 2. Single Job Per Worker Design

**Limitations:**
- Each worker executes only one job at a time
- Inefficient for lightweight tasks (wastes resources)
- Cannot batch small operations
- Memory underutilization for simple scripts

**Real-World Impact:**
- Poor resource utilization for microservices
- Expensive scaling for high-frequency, lightweight tasks
- Linear cost scaling with job volume

### 3. Database Write Bottlenecks

**Issues:**
- All job results written to PostgreSQL
- Job logs stored in database
- State updates create write contention
- No built-in sharding or partitioning

## Production Issues Analysis

### Critical Bugs (Recent)

1. **Bun Runtime Failure** (Issue #5552)
   - All Bun jobs failing in versions 1.479.3+
   - Complete breakdown of Bun-based workflows
   - Production-breaking bug

2. **Worker Stability Issues**
   - Undefined errors with signal 5
   - Worker crashes during setup
   - Timeout problems with AI features (5+ minutes)

### Open Issues Overview
- **Total Open Issues**: 440
- **Bug Reports**: ~40%
- **Feature Requests**: ~45%
- **Documentation**: ~15%

### Concerning Patterns
- Integration problems (S3, AI, databases) recurring
- Worker failures and undefined errors
- UI glitches and navigation issues
- No reported memory leaks or security vulnerabilities (positive)

## Cost & Licensing Concerns

### Pricing Model Issues
Users report frustration with:
- Charges based on worker count even when self-hosted
- Enterprise features (alerts, autoscaling) behind paywall
- Paying for own infrastructure usage
- AGPLv3 licensing limiting commercial adoption

### Community Feedback (Issue #5014)
> "The platform prohibits triggering an alert when a critical process fails without paying for EE, which undermines the usability of the platform for production-level workflows"

## Scalability Comparison

### vs. Redis-based Systems
- Redis handles 100k+ ops/sec easily
- Pub/sub eliminates polling overhead
- Better suited for high-frequency operations
- No connection limit issues

### vs. Dedicated Queue Systems
- **RabbitMQ**: 50k+ msgs/sec
- **Kafka**: 1M+ msgs/sec
- No polling required (push-based)
- Built for scale from ground up

## When Windmill Scales Well

### Optimal Use Cases
- < 100 workers
- Long-running, CPU-intensive tasks
- Low-frequency workflows (minutes between jobs)
- Complex workflows with UI requirements

### Production Success Stories
- **Photoroom**: Running business-critical automations
- **Pave**: 100+ scripts with 15+ cron jobs

## When Windmill Struggles

### Poor Fit Scenarios
- 500+ workers
- High-frequency, lightweight tasks (< 100ms)
- Microservice architectures
- Real-time event processing
- Millions of jobs per hour

## Recommended Improvements

### Short-term Mitigations
1. Increase `SLEEP_QUEUE` to reduce polling frequency
2. Use dedicated workers for high-throughput scripts
3. Deploy PgBouncer for connection pooling
4. Consider multiple Windmill instances

### Long-term Architectural Changes Needed
1. Replace PostgreSQL polling with message queue (Redis/RabbitMQ)
2. Implement worker pooling for lightweight tasks
3. Add job batching capabilities
4. Create caching layer for job distribution
5. Support database sharding/partitioning

## Recommendations for Gleitzeit

Based on Windmill's limitations, Gleitzeit should:

1. **Keep Redis-based coordination** - Avoids PostgreSQL polling bottleneck
2. **Implement job batching** - Learn from Windmill's single-job limitation
3. **Add sandboxing** - Adopt Windmill's nsjail approach for security
4. **Consider UI generation** - Windmill's auto-UI is a key differentiator
5. **Document scaling limits** - Be transparent about architectural boundaries
6. **Avoid per-worker pricing** - Don't repeat Windmill's licensing friction

## Conclusion

Windmill is a capable platform with impressive single-worker performance and excellent developer experience. However, its PostgreSQL-polling architecture creates a fundamental scaling ceiling around 100-500 workers. Organizations requiring true web-scale capabilities (thousands of workers, millions of jobs/hour) should carefully evaluate these limitations against their requirements.

The platform excels at complex, long-running workflows with UI requirements but struggles with high-frequency, lightweight task processing at scale. The aggressive polling strategy that enables low latency becomes its Achilles' heel at scale.

---

*Analysis Date: January 2025*
*Based on: GitHub repository analysis, issue tracking, documentation review, and performance benchmarks*