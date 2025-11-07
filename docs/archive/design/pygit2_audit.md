# PyGit2 Audit for Gleitzeit Replayability

## Executive Summary

This document evaluates using pygit2 (Python bindings for libgit2) to enhance Gleitzeit's replayability through git-based versioning, event storage, and distributed replay capabilities.

## PyGit2 Overview

**pygit2** provides:
- Pure Python bindings to libgit2 (no shell commands needed)
- Thread-safe operations
- In-memory repository support
- Direct object database access
- Efficient diff computation

## Use Case Analysis

### 1. Workflow Versioning: Each workflow change creates a git commit

#### Benefits
- **Immutable History**: Every workflow modification tracked
- **Branching**: Test workflow variations without affecting production
- **Rollback**: Easy revert to previous workflow versions
- **Blame/Annotation**: Track who changed what and when
- **Merge Capabilities**: Combine workflow changes from multiple sources

#### Implementation Approach

```python
import pygit2
from pathlib import Path

class WorkflowVersionControl:
    def __init__(self, repo_path: Path):
        self.repo = pygit2.Repository(repo_path)

    async def commit_workflow(self, workflow_id: str, workflow_data: dict):
        # Store workflow as JSON file
        workflow_path = f"workflows/{workflow_id}/workflow.json"

        # Write to working directory
        with open(self.repo.workdir / workflow_path, 'w') as f:
            json.dump(workflow_data, f, indent=2)

        # Stage changes
        index = self.repo.index
        index.add(workflow_path)
        index.write()

        # Create commit
        signature = pygit2.Signature("Gleitzeit", "gleitzeit@system")
        tree = index.write_tree()

        message = f"Update workflow {workflow_id}\n\nTasks: {len(workflow_data.get('tasks', []))}"
        self.repo.create_commit(
            'refs/heads/main',
            signature,
            signature,
            message,
            tree,
            [self.repo.head.target]
        )
```

#### Storage Overhead
- ~1-5KB per workflow commit (compressed)
- Efficient delta storage for incremental changes
- Can use shallow clones for recent history only

#### Verdict: ✅ **RECOMMENDED**
Git is excellent for workflow versioning. Natural fit for tracking definition changes.

---

### 2. Event Journaling: Events stored as git commits for immutable audit trail

#### Benefits
- **Immutability**: Events cannot be altered after commit
- **Cryptographic Verification**: Git SHA ensures integrity
- **Distributed Backup**: Every clone has full event history
- **Rich Metadata**: Commit messages can contain structured event data

#### Implementation Approach

```python
class EventJournal:
    def __init__(self, repo_path: Path):
        self.repo = pygit2.Repository(repo_path)
        # Use separate branch for events to avoid conflicts
        self.event_branch = "events"

    async def store_event(self, event: WorkflowEvent):
        # Each event as a file in events/ directory
        event_path = f"events/{event.workflow_id}/{event.event_id}.json"

        # Write event data
        event_data = event.to_dict()
        with open(self.repo.workdir / event_path, 'w') as f:
            json.dump(event_data, f)

        # Commit with structured message
        message = f"{event.event_type}: {event.task_id or 'workflow'}\n\n"
        message += f"Workflow: {event.workflow_id}\n"
        message += f"Timestamp: {event.timestamp}\n"
        message += json.dumps(event.data)

        # Fast-forward commit (no merge required)
        self._commit_event(event_path, message)
```

#### Performance Concerns
- **Write Speed**: ~10-50ms per commit (slower than Redis streams)
- **Scaling Issues**: Git slows with millions of objects
- **Query Performance**: No native querying, need to walk commits
- **Concurrent Writes**: Requires locking/coordination

#### Verdict: ⚠️ **NOT RECOMMENDED**
Git commits are too slow for high-frequency events. Better for checkpoint/summary storage.

---

### 3. Distributed Replay: Use git's distributed nature for multi-site replay

#### Benefits
- **Multi-Site Sync**: Push/pull between data centers
- **Offline Capability**: Local replay without central server
- **Conflict Resolution**: Git merge for divergent executions
- **Federation**: Different teams manage different workflow repos

#### Implementation Approach

```python
class DistributedReplay:
    def __init__(self, local_repo: Path, remotes: Dict[str, str]):
        self.repo = pygit2.Repository(local_repo)
        self.remotes = remotes

    async def sync_with_remote(self, remote_name: str):
        # Fetch remote changes
        remote = self.repo.remotes[remote_name]
        remote.fetch()

        # Merge or rebase
        self.repo.merge(remote.get_refspec())

    async def replay_from_site(self, site_name: str, workflow_id: str):
        # Checkout site-specific branch
        site_branch = f"{site_name}/{workflow_id}"
        self.repo.checkout(site_branch)

        # Load workflow and events from that branch
        workflow_data = self._load_workflow(workflow_id)
        events = self._load_events(workflow_id)

        # Trigger replay with site-specific data
        return await self.replay_engine.replay(workflow_data, events)
```

#### Network Considerations
- **Bandwidth**: Full history transfer can be large
- **Latency**: Git protocols not optimized for real-time
- **Authentication**: Need SSH/HTTPS setup for each site
- **Firewall**: Git ports must be accessible

#### Verdict: 🤔 **CONDITIONAL**
Good for batch synchronization, not real-time. Works if replay is periodic, not continuous.

---

### 4. Diff-Based Replay: Use git diff to determine what changed between executions

#### Benefits
- **Semantic Diffs**: Understand what changed, not just that it changed
- **Efficient Comparison**: Binary diff algorithms are fast
- **Three-way Merge**: Compare original, current, and new versions
- **Patch Generation**: Create minimal change sets

#### Implementation Approach

```python
class DiffBasedReplay:
    def __init__(self, repo_path: Path):
        self.repo = pygit2.Repository(repo_path)

    async def compute_replay_delta(
        self,
        workflow_id: str,
        from_commit: str,
        to_commit: str
    ) -> ReplayDelta:
        # Get commits
        commit1 = self.repo.get(from_commit)
        commit2 = self.repo.get(to_commit)

        # Compute diff
        diff = self.repo.diff(commit1.tree, commit2.tree)

        # Analyze changes
        tasks_added = []
        tasks_removed = []
        tasks_modified = []

        for patch in diff:
            if f"workflows/{workflow_id}" in patch.delta.new_file.path:
                # Parse the changes
                changes = self._parse_workflow_changes(patch)
                tasks_added.extend(changes.added_tasks)
                tasks_removed.extend(changes.removed_tasks)
                tasks_modified.extend(changes.modified_tasks)

        return ReplayDelta(
            added=tasks_added,
            removed=tasks_removed,
            modified=tasks_modified
        )

    async def selective_replay(self, delta: ReplayDelta):
        # Only replay changed tasks
        for task_id in delta.modified:
            await self.clear_task_result(task_id)

        # Remove deleted tasks from workflow
        for task_id in delta.removed:
            await self.remove_task(task_id)

        # Add new tasks
        for task_id in delta.added:
            await self.add_task(task_id)
```

#### Use Cases
- **Incremental Replay**: Only re-run what changed
- **A/B Testing**: Compare two workflow versions
- **Impact Analysis**: Understand effects of changes
- **Rollback Planning**: Preview what reverting would do

#### Verdict: ✅ **RECOMMENDED**
Excellent for understanding and optimizing replay scope. Reduces unnecessary re-computation.

---

## Recommended Architecture

### Hybrid Approach: Git for Structure, Redis for Events

```python
class HybridReplaySystem:
    """
    Uses git for workflow versioning and replay planning,
    Redis for high-frequency event storage
    """

    def __init__(self, git_repo: Path, redis_client):
        self.git = WorkflowVersionControl(git_repo)
        self.redis = redis_client
        self.events = EventStore(redis_client)

    async def checkpoint_workflow(self, workflow_id: str):
        """Periodic git commits of workflow + execution summary"""
        # Get workflow definition
        workflow_data = await self.redis.hget(
            f"workflow:data:{workflow_id}", "workflow"
        )

        # Get execution summary (not all events)
        summary = await self.events.get_execution_summary(workflow_id)

        # Commit to git
        await self.git.commit_workflow(workflow_id, {
            'definition': json.loads(workflow_data),
            'summary': summary,
            'timestamp': datetime.utcnow().isoformat()
        })

    async def plan_replay(self, workflow_id: str, from_version: str = None):
        """Use git diff to plan efficient replay"""
        if from_version:
            delta = await self.git.compute_delta(workflow_id, from_version)
            return ReplayPlan(mode='incremental', delta=delta)
        else:
            return ReplayPlan(mode='full')
```

### Storage Strategy

| Data Type | Storage | Rationale |
|-----------|---------|-----------|
| Workflow Definitions | Git | Version control, branching, history |
| High-frequency Events | Redis Streams | Performance, real-time processing |
| Execution Summaries | Git | Checkpoints, audit trail |
| Task Results | Redis | Fast access, TTL support |
| Replay Plans | Git | Diff-based optimization |

### Implementation Phases

#### Phase 1: Workflow Versioning (Week 1)
```python
# Add to WorkflowLoaderWorker
async def handle_workflow_submission(self, workflow_data: dict):
    # Existing Redis storage
    await self.store_in_redis(workflow_data)

    # New: Version in git
    if self.version_control_enabled:
        await self.git_repo.commit_workflow(workflow_data)
```

#### Phase 2: Checkpoint System (Week 2)
```python
# Periodic checkpointing
async def checkpoint_completed_workflows():
    for workflow_id in completed_workflows:
        await checkpoint_to_git(workflow_id)
        await trim_redis_events(workflow_id)  # Keep git, trim Redis
```

#### Phase 3: Diff-based Replay (Week 3)
```python
# Intelligent replay using git diff
async def smart_replay(workflow_id: str):
    current = await git.get_current_version(workflow_id)
    previous = await git.get_last_execution_version(workflow_id)
    delta = await git.diff(previous, current)

    # Only replay what changed
    await replay_worker.replay_delta(workflow_id, delta)
```

## Performance Analysis

### Git Operations Performance

| Operation | Time | Suitable for Gleitzeit? |
|-----------|------|-------------------------|
| Commit workflow | 5-20ms | ✅ Yes (infrequent) |
| Commit event | 10-50ms | ❌ No (too slow) |
| Diff computation | 1-10ms | ✅ Yes |
| Clone repository | 100ms-10s | ⚠️ Conditional |
| Fetch changes | 50ms-1s | ✅ Yes (periodic) |

### Storage Comparison

| Metric | Git | Redis | Recommendation |
|--------|-----|-------|----------------|
| Write Speed | 20-50ms | <1ms | Redis for events |
| Query Speed | Slow | Fast | Redis for lookups |
| History | Unlimited | Limited | Git for archive |
| Distribution | Built-in | Requires setup | Git for multi-site |
| Integrity | SHA verified | None | Git for audit |

## Security Considerations

1. **Access Control**: Git repositories need proper permissions
2. **Signing**: Can sign commits for non-repudiation
3. **Encryption**: Git supports encrypted remotes
4. **Audit**: Every change tracked with author and timestamp

## Conclusion

### Recommendations

1. **✅ DO USE pygit2 for**:
   - Workflow definition versioning
   - Execution checkpointing (periodic summaries)
   - Diff-based replay optimization
   - Multi-site workflow distribution (batch sync)

2. **❌ DON'T USE pygit2 for**:
   - High-frequency event storage (use Redis)
   - Real-time event streaming
   - Primary task result storage
   - Sub-second operations

3. **💡 BEST PRACTICE**:
   - Hybrid architecture: Git for structure, Redis for streams
   - Checkpoint to git periodically (hourly/daily)
   - Use git diff for intelligent replay planning
   - Keep git repos focused (one per workflow or namespace)

### Proposed Integration

```python
# Configuration
GLEITZEIT_CONFIG = {
    'versioning': {
        'enabled': True,
        'backend': 'pygit2',
        'repo_path': '/var/gleitzeit/workflows.git',
        'checkpoint_interval': 3600,  # 1 hour
        'auto_commit': True,
        'branch_per_workflow': False
    },
    'replay': {
        'use_git_diff': True,
        'checkpoint_before_replay': True
    }
}
```

This hybrid approach leverages git's strengths (versioning, diff, distribution) while avoiding its weaknesses (slow writes, no querying) by keeping Redis for operational data.