#!/usr/bin/env python3
"""
Script to clean up orphaned tasks and workflows from Redis.

Deletes:
1. Tasks that have no workflow_id
2. Workflows that have no associated tasks
"""

import asyncio
import json
import logging
from typing import Set, List, Dict, Any
import redis.asyncio as aioredis
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OrphanedDataCleaner:
    def __init__(self, redis_url: str = "redis://localhost:6379", dry_run: bool = False):
        self.redis_url = redis_url
        self.dry_run = dry_run
        self.redis = None

    async def __aenter__(self):
        self.redis = await aioredis.from_url(self.redis_url, decode_responses=False)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.redis:
            await self.redis.aclose()

    async def scan_all_shards(self, pattern: str) -> List[bytes]:
        """Scan all shards for keys matching pattern."""
        all_keys = []

        # Scan across all possible shards (0-15)
        for shard_id in range(16):
            shard_pattern = f"{{shard:{shard_id}}}:{pattern}".encode()
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=shard_pattern, count=100)
                all_keys.extend(keys)
                if cursor == 0:
                    break

        # Also scan without shard prefix for legacy data
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern.encode(), count=100)
            all_keys.extend(keys)
            if cursor == 0:
                break

        return all_keys

    async def get_orphaned_tasks(self) -> List[bytes]:
        """Find all tasks that have no workflow_id."""
        orphaned = []

        logger.info("Scanning for tasks...")
        task_keys = await self.scan_all_shards("task:*")
        logger.info(f"Found {len(task_keys)} total tasks")

        for task_key in task_keys:
            try:
                # Check key type first
                key_type = await self.redis.type(task_key)

                if key_type == b'string':
                    # Task is stored as JSON string
                    task_data = await self.redis.get(task_key)
                    if task_data:
                        task = json.loads(task_data)
                        workflow_id = task.get("workflow_id")
                elif key_type == b'hash':
                    # Task is stored as hash
                    workflow_id = await self.redis.hget(task_key, b"workflow_id")
                    if workflow_id:
                        workflow_id = workflow_id.decode() if isinstance(workflow_id, bytes) else workflow_id
                else:
                    logger.warning(f"Unknown type {key_type} for task {task_key.decode()}")
                    continue

                if not workflow_id:
                    orphaned.append(task_key)
                    logger.debug(f"Task {task_key.decode()} has no workflow_id")

            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"Error parsing task {task_key.decode()}: {e}")
            except Exception as e:
                logger.warning(f"Error processing task {task_key.decode()}: {e}")

        logger.info(f"Found {len(orphaned)} orphaned tasks (no workflow_id)")
        return orphaned

    async def get_orphaned_workflows(self) -> List[bytes]:
        """Find all workflows that have no associated tasks."""
        orphaned = []

        logger.info("Scanning for workflows...")
        workflow_keys = await self.scan_all_shards("workflow:*")
        logger.info(f"Found {len(workflow_keys)} total workflows")

        # Get all task workflow_ids for reference
        logger.info("Building task->workflow mapping...")
        workflows_with_tasks = set()

        task_keys = await self.scan_all_shards("task:*")
        for task_key in task_keys:
            try:
                # Check key type first
                key_type = await self.redis.type(task_key)

                workflow_id = None
                if key_type == b'string':
                    # Task is stored as JSON string
                    task_data = await self.redis.get(task_key)
                    if task_data:
                        task = json.loads(task_data)
                        workflow_id = task.get("workflow_id")
                elif key_type == b'hash':
                    # Task is stored as hash
                    workflow_id = await self.redis.hget(task_key, b"workflow_id")
                    if workflow_id:
                        workflow_id = workflow_id.decode() if isinstance(workflow_id, bytes) else workflow_id

                if workflow_id:
                    workflows_with_tasks.add(workflow_id)

            except Exception as e:
                logger.debug(f"Error processing task {task_key.decode()}: {e}")

        logger.info(f"Found {len(workflows_with_tasks)} workflows with tasks")

        # Check each workflow
        for workflow_key in workflow_keys:
            # Extract workflow_id from key
            key_str = workflow_key.decode()
            # Format could be {shard:N}:workflow:ID or just workflow:ID
            if "}:workflow:" in key_str:
                workflow_id = key_str.split("}:workflow:")[1]
            elif "workflow:" in key_str:
                workflow_id = key_str.split("workflow:")[1]
            else:
                continue

            if workflow_id not in workflows_with_tasks:
                orphaned.append(workflow_key)
                logger.debug(f"Workflow {workflow_id} has no tasks")

        logger.info(f"Found {len(orphaned)} orphaned workflows (no tasks)")
        return orphaned

    async def delete_keys(self, keys: List[bytes], key_type: str):
        """Delete the given keys from Redis."""
        if not keys:
            logger.info(f"No orphaned {key_type} to delete")
            return

        if self.dry_run:
            logger.info(f"DRY RUN: Would delete {len(keys)} orphaned {key_type}")
            for key in keys[:10]:  # Show first 10 keys
                logger.info(f"  Would delete: {key.decode()}")
            if len(keys) > 10:
                logger.info(f"  ... and {len(keys) - 10} more")
        else:
            logger.info(f"Deleting {len(keys)} orphaned {key_type}...")

            # Delete in batches
            batch_size = 100
            for i in range(0, len(keys), batch_size):
                batch = keys[i:i + batch_size]
                deleted = await self.redis.delete(*batch)
                logger.info(f"  Deleted batch {i//batch_size + 1}: {deleted} keys")

            logger.info(f"Completed deletion of orphaned {key_type}")

    async def cleanup(self):
        """Run the full cleanup process."""
        logger.info("=" * 60)
        logger.info("Starting orphaned data cleanup")
        logger.info(f"Redis URL: {self.redis_url}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("=" * 60)

        # Find and delete orphaned tasks
        orphaned_tasks = await self.get_orphaned_tasks()
        await self.delete_keys(orphaned_tasks, "tasks")

        # Find and delete orphaned workflows
        orphaned_workflows = await self.get_orphaned_workflows()
        await self.delete_keys(orphaned_workflows, "workflows")

        # Summary
        logger.info("=" * 60)
        logger.info("Cleanup Summary:")
        logger.info(f"  Orphaned tasks: {len(orphaned_tasks)}")
        logger.info(f"  Orphaned workflows: {len(orphaned_workflows)}")
        if self.dry_run:
            logger.info("  Mode: DRY RUN (no data was deleted)")
        else:
            logger.info("  Mode: LIVE (data was deleted)")
        logger.info("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="Clean up orphaned tasks and workflows from Redis")
    parser.add_argument("--redis-url", default="redis://localhost:6379",
                        help="Redis connection URL (default: redis://localhost:6379)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without actually deleting")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    async with OrphanedDataCleaner(args.redis_url, args.dry_run) as cleaner:
        await cleaner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())