#!/usr/bin/env python3
"""
Stress Test: High-Volume Workflow Submission

Tests system performance and stability under heavy load by submitting
many workflows concurrently to the API.

Usage:
    python -m pytest tests/test_stress_workflows.py -v

    Or run directly:
    python tests/test_stress_workflows.py --workflows 50000 --concurrency 100
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
from typing import Dict, List, Any
import argparse


# Default configuration
DEFAULT_WORKFLOW_DEF = {
    "name": "Stress Test Workflow",
    "tasks": [
        {
            "id": "task1",
            "type": "python",
            "params": {
                "code": """
import time
result = {
    "message": "Stress test task completed",
    "timestamp": time.time()
}
"""
            }
        }
    ]
}


class WorkflowStressTest:
    """High-volume workflow submission stress test"""

    def __init__(
        self,
        api_url: str = "http://localhost:8000/workflows/submit",
        total_workflows: int = 50000,
        concurrent_requests: int = 100,
        workflow_def: Dict[str, Any] = None
    ):
        self.api_url = api_url
        self.total_workflows = total_workflows
        self.concurrent_requests = concurrent_requests
        self.workflow_def = workflow_def or DEFAULT_WORKFLOW_DEF

        self.results = {
            'submitted': 0,
            'succeeded': 0,
            'failed': 0,
            'durations': [],
            'errors': [],
            'workflow_ids': []
        }

    async def submit_workflow(self, session: aiohttp.ClientSession, workflow_num: int) -> Dict[str, Any]:
        """Submit a single workflow"""
        try:
            start = time.time()
            payload = {"workflow": self.workflow_def}

            async with session.post(self.api_url, json=payload) as response:
                duration = time.time() - start

                if response.status in (200, 201):
                    data = await response.json()
                    workflow_id = data.get('workflow_id', 'unknown')
                    return {
                        'success': True,
                        'workflow_num': workflow_num,
                        'workflow_id': workflow_id,
                        'duration': duration,
                        'status': response.status
                    }
                else:
                    text = await response.text()
                    return {
                        'success': False,
                        'workflow_num': workflow_num,
                        'error': f"HTTP {response.status}: {text}",
                        'duration': duration
                    }
        except Exception as e:
            return {
                'success': False,
                'workflow_num': workflow_num,
                'error': str(e),
                'duration': 0
            }

    async def submit_batch(self, session: aiohttp.ClientSession, start_num: int, batch_size: int) -> List[Dict[str, Any]]:
        """Submit a batch of workflows concurrently"""
        tasks = []
        for i in range(start_num, start_num + batch_size):
            tasks.append(self.submit_workflow(session, i))

        return await asyncio.gather(*tasks)

    def print_progress(self, batch_size: int, batch_duration: float, interval: int = 1000):
        """Print progress update (every N submissions)"""
        if self.results['submitted'] % interval == 0 or self.results['submitted'] == self.total_workflows:
            progress = (self.results['submitted'] / self.total_workflows) * 100
            rate = batch_size / batch_duration if batch_duration > 0 else 0

            print(f"Progress: {self.results['submitted']:,}/{self.total_workflows:,} ({progress:.1f}%) | "
                  f"Batch: {batch_size} in {batch_duration:.2f}s ({rate:.1f} req/s) | "
                  f"Success: {self.results['succeeded']:,} | Failed: {self.results['failed']:,}")

    async def run(self) -> Dict[str, Any]:
        """Run the stress test"""
        print("=" * 70)
        print("GLEITZEIT STRESS TEST")
        print("=" * 70)
        print(f"Total workflows: {self.total_workflows:,}")
        print(f"Concurrent requests: {self.concurrent_requests}")
        print(f"API endpoint: {self.api_url}")
        print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print()

        overall_start = time.time()

        # Create session with connection pooling
        # Use DummyCookieJar to ensure each request is independent
        timeout = aiohttp.ClientTimeout(total=60)
        connector = aiohttp.TCPConnector(limit=self.concurrent_requests)
        cookie_jar = aiohttp.DummyCookieJar()

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            cookie_jar=cookie_jar
        ) as session:
            # Submit in batches
            for batch_start in range(0, self.total_workflows, self.concurrent_requests):
                batch_size = min(self.concurrent_requests, self.total_workflows - batch_start)

                batch_start_time = time.time()
                batch_results = await self.submit_batch(session, batch_start, batch_size)
                batch_duration = time.time() - batch_start_time

                # Process batch results
                for result in batch_results:
                    self.results['submitted'] += 1

                    if result['success']:
                        self.results['succeeded'] += 1
                        self.results['durations'].append(result['duration'])
                        self.results['workflow_ids'].append(result['workflow_id'])
                    else:
                        self.results['failed'] += 1
                        self.results['errors'].append({
                            'workflow_num': result['workflow_num'],
                            'error': result['error']
                        })

                # Progress update
                self.print_progress(batch_size, batch_duration)

                # Small delay between batches to avoid overwhelming the system
                if batch_start + batch_size < self.total_workflows:
                    await asyncio.sleep(0.05)  # 50ms delay

        overall_duration = time.time() - overall_start

        # Print summary
        self.print_summary(overall_duration)

        return {
            'total_submitted': self.results['submitted'],
            'succeeded': self.results['succeeded'],
            'failed': self.results['failed'],
            'success_rate': (self.results['succeeded'] / self.results['submitted'] * 100) if self.results['submitted'] > 0 else 0,
            'total_duration': overall_duration,
            'average_rate': self.results['submitted'] / overall_duration if overall_duration > 0 else 0,
            'response_times': self.calculate_response_stats(),
            'errors': self.results['errors'][:100]  # First 100 errors
        }

    def calculate_response_stats(self) -> Dict[str, float]:
        """Calculate response time statistics"""
        if not self.results['durations']:
            return {
                'min': 0,
                'max': 0,
                'mean': 0,
                'median': 0,
                'p95': 0,
                'p99': 0
            }

        durations = sorted(self.results['durations'])
        return {
            'min': min(durations),
            'max': max(durations),
            'mean': sum(durations) / len(durations),
            'median': durations[len(durations) // 2],
            'p95': durations[int(len(durations) * 0.95)],
            'p99': durations[int(len(durations) * 0.99)]
        }

    def print_summary(self, overall_duration: float):
        """Print test summary"""
        print()
        print("=" * 70)
        print("STRESS TEST RESULTS")
        print("=" * 70)
        print(f"Total workflows submitted: {self.results['submitted']:,}")
        print(f"Succeeded: {self.results['succeeded']:,}")
        print(f"Failed: {self.results['failed']:,}")

        success_rate = (self.results['succeeded'] / self.results['submitted'] * 100) if self.results['submitted'] > 0 else 0
        print(f"Success rate: {success_rate:.2f}%")
        print()
        print(f"Total duration: {overall_duration:.2f}s")
        print(f"Average rate: {self.results['submitted'] / overall_duration:.2f} workflows/second")
        print()

        stats = self.calculate_response_stats()
        if stats['max'] > 0:
            print("Response Times:")
            print(f"  Min: {stats['min']:.3f}s")
            print(f"  Max: {stats['max']:.3f}s")
            print(f"  Mean: {stats['mean']:.3f}s")
            print(f"  Median: {stats['median']:.3f}s")
            print(f"  P95: {stats['p95']:.3f}s")
            print(f"  P99: {stats['p99']:.3f}s")

        print()

        if self.results['errors']:
            print(f"Errors ({len(self.results['errors'])} total):")
            # Show first 10 unique errors
            unique_errors = {}
            for err in self.results['errors']:
                error_msg = err['error']
                if error_msg not in unique_errors:
                    unique_errors[error_msg] = 0
                unique_errors[error_msg] += 1

            for i, (error, count) in enumerate(list(unique_errors.items())[:10]):
                print(f"  {i+1}. [{count}x] {error[:100]}")

            if len(unique_errors) > 10:
                print(f"  ... and {len(unique_errors) - 10} more error types")

        print("=" * 70)
        print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

    def save_results(self, filename: str = '/tmp/stress_test_results.json'):
        """Save detailed results to JSON file"""
        stats = self.calculate_response_stats()

        with open(filename, 'w') as f:
            json.dump({
                'total_submitted': self.results['submitted'],
                'succeeded': self.results['succeeded'],
                'failed': self.results['failed'],
                'success_rate': (self.results['succeeded'] / self.results['submitted'] * 100) if self.results['submitted'] > 0 else 0,
                'response_times': stats,
                'errors': self.results['errors'][:1000],  # First 1000 errors
                'sample_workflow_ids': self.results['workflow_ids'][:100]  # First 100 IDs
            }, f, indent=2)

        print(f"\nDetailed results saved to: {filename}")


async def main():
    """Main entry point for direct execution"""
    parser = argparse.ArgumentParser(description='Gleitzeit Workflow Stress Test')
    parser.add_argument('--workflows', type=int, default=50000,
                        help='Total number of workflows to submit (default: 50000)')
    parser.add_argument('--concurrency', type=int, default=100,
                        help='Number of concurrent requests (default: 100)')
    parser.add_argument('--api-url', type=str, default='http://localhost:8000/workflows/submit',
                        help='API endpoint URL')
    parser.add_argument('--output', type=str, default='/tmp/stress_test_results.json',
                        help='Output file for results')

    args = parser.parse_args()

    test = WorkflowStressTest(
        api_url=args.api_url,
        total_workflows=args.workflows,
        concurrent_requests=args.concurrency
    )

    await test.run()
    test.save_results(args.output)


# Pytest integration
def test_stress_1000_workflows():
    """Test: Submit 1000 workflows"""
    test = WorkflowStressTest(total_workflows=1000, concurrent_requests=50)
    results = asyncio.run(test.run())

    assert results['success_rate'] >= 95.0, f"Success rate too low: {results['success_rate']:.2f}%"
    assert results['failed'] <= 50, f"Too many failures: {results['failed']}"


def test_stress_10000_workflows():
    """Test: Submit 10,000 workflows"""
    test = WorkflowStressTest(total_workflows=10000, concurrent_requests=100)
    results = asyncio.run(test.run())

    assert results['success_rate'] >= 95.0, f"Success rate too low: {results['success_rate']:.2f}%"
    assert results['failed'] <= 500, f"Too many failures: {results['failed']}"


def test_stress_50000_workflows():
    """Test: Submit 50,000 workflows"""
    test = WorkflowStressTest(total_workflows=50000, concurrent_requests=100)
    results = asyncio.run(test.run())
    test.save_results('/tmp/stress_test_50k_results.json')

    assert results['success_rate'] >= 95.0, f"Success rate too low: {results['success_rate']:.2f}%"
    assert results['failed'] <= 2500, f"Too many failures: {results['failed']}"


if __name__ == "__main__":
    asyncio.run(main())
