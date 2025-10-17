"""
Tests for shard distribution algorithm used in Docker mode

The shard distribution algorithm ensures that when multiple workers
of the same type are deployed, each worker gets a fair share of the
16 total shards, enabling true horizontal scaling.
"""

import pytest


class TestShardDistribution:
    """Test shard distribution across multiple workers"""

    def distribute_shards(self, total_shards: int, worker_count: int, worker_index: int):
        """
        Calculate shard assignment for a specific worker instance.
        This is the same algorithm used in serve_docker.py

        Args:
            total_shards: Total number of shards (typically 16)
            worker_count: Total number of workers of this type
            worker_index: Index of this specific worker (0-based)

        Returns:
            List of shard IDs assigned to this worker
        """
        shards_per_worker = total_shards // worker_count
        remainder = total_shards % worker_count

        # Each worker gets base share, first `remainder` workers get +1 shard
        start_shard = worker_index * shards_per_worker + min(worker_index, remainder)
        end_shard = start_shard + shards_per_worker + (1 if worker_index < remainder else 0)

        return list(range(start_shard, end_shard))

    def test_single_worker_gets_all_shards(self):
        """Test that a single worker gets all 16 shards"""
        shards = self.distribute_shards(total_shards=16, worker_count=1, worker_index=0)

        assert shards == list(range(16))
        assert len(shards) == 16

    def test_two_workers_split_evenly(self):
        """Test that 2 workers each get 8 shards"""
        worker_0_shards = self.distribute_shards(total_shards=16, worker_count=2, worker_index=0)
        worker_1_shards = self.distribute_shards(total_shards=16, worker_count=2, worker_index=1)

        assert worker_0_shards == [0, 1, 2, 3, 4, 5, 6, 7]
        assert worker_1_shards == [8, 9, 10, 11, 12, 13, 14, 15]
        assert len(worker_0_shards) == 8
        assert len(worker_1_shards) == 8

    def test_four_workers_split_evenly(self):
        """Test that 4 workers each get 4 shards"""
        all_shards = []

        for i in range(4):
            shards = self.distribute_shards(total_shards=16, worker_count=4, worker_index=i)
            all_shards.extend(shards)
            assert len(shards) == 4

        # Verify all shards assigned exactly once
        assert sorted(all_shards) == list(range(16))

    def test_three_workers_uneven_distribution(self):
        """Test that 3 workers distribute 16 shards as fairly as possible

        With 16 shards and 3 workers:
        - 16 // 3 = 5 (base allocation)
        - 16 % 3 = 1 (remainder)
        - Worker 0 gets 6 shards (5 + 1)
        - Worker 1 gets 5 shards
        - Worker 2 gets 5 shards
        """
        worker_0_shards = self.distribute_shards(total_shards=16, worker_count=3, worker_index=0)
        worker_1_shards = self.distribute_shards(total_shards=16, worker_count=3, worker_index=1)
        worker_2_shards = self.distribute_shards(total_shards=16, worker_count=3, worker_index=2)

        assert len(worker_0_shards) == 6  # Gets extra shard
        assert len(worker_1_shards) == 5
        assert len(worker_2_shards) == 5

        # Verify all shards assigned
        all_shards = worker_0_shards + worker_1_shards + worker_2_shards
        assert sorted(all_shards) == list(range(16))

    def test_five_workers_uneven_distribution(self):
        """Test that 5 workers distribute 16 shards fairly

        With 16 shards and 5 workers:
        - 16 // 5 = 3 (base allocation)
        - 16 % 5 = 1 (remainder)
        - Worker 0 gets 4 shards (3 + 1)
        - Workers 1-4 get 3 shards each
        """
        all_shards = []
        shard_counts = []

        for i in range(5):
            shards = self.distribute_shards(total_shards=16, worker_count=5, worker_index=i)
            all_shards.extend(shards)
            shard_counts.append(len(shards))

        assert shard_counts == [4, 3, 3, 3, 3]
        assert sorted(all_shards) == list(range(16))

    def test_no_shard_overlap(self):
        """Test that workers never get overlapping shards"""
        for worker_count in range(1, 17):
            all_shards = []

            for worker_index in range(worker_count):
                shards = self.distribute_shards(
                    total_shards=16,
                    worker_count=worker_count,
                    worker_index=worker_index
                )
                all_shards.extend(shards)

            # Should have no duplicates
            assert len(all_shards) == len(set(all_shards))
            # Should cover all 16 shards
            assert sorted(all_shards) == list(range(16))

    def test_all_shards_covered(self):
        """Test that all 16 shards are always assigned regardless of worker count"""
        for worker_count in range(1, 17):
            all_shards = []

            for worker_index in range(worker_count):
                shards = self.distribute_shards(
                    total_shards=16,
                    worker_count=worker_count,
                    worker_index=worker_index
                )
                all_shards.extend(shards)

            assert sorted(all_shards) == list(range(16))

    def test_fair_distribution_max_difference_one(self):
        """Test that shard counts differ by at most 1 between workers"""
        for worker_count in range(1, 17):
            shard_counts = []

            for worker_index in range(worker_count):
                shards = self.distribute_shards(
                    total_shards=16,
                    worker_count=worker_count,
                    worker_index=worker_index
                )
                shard_counts.append(len(shards))

            # Max difference should be at most 1
            assert max(shard_counts) - min(shard_counts) <= 1

    def test_sixteen_workers_one_shard_each(self):
        """Test that 16 workers each get exactly 1 shard"""
        all_shards = []

        for i in range(16):
            shards = self.distribute_shards(total_shards=16, worker_count=16, worker_index=i)
            assert len(shards) == 1
            assert shards[0] == i
            all_shards.extend(shards)

        assert sorted(all_shards) == list(range(16))

    def test_more_workers_than_shards(self):
        """Test edge case: more workers than shards (some workers get no shards)"""
        # This is an edge case that shouldn't happen in production
        # but the algorithm should handle it gracefully
        all_shards = []
        empty_workers = 0

        for i in range(20):  # 20 workers, only 16 shards
            shards = self.distribute_shards(total_shards=16, worker_count=20, worker_index=i)
            if len(shards) == 0:
                empty_workers += 1
            all_shards.extend(shards)

        # 4 workers should get no shards (20 - 16 = 4)
        assert empty_workers == 4
        # All 16 shards should still be covered
        assert sorted(all_shards) == list(range(16))


class TestShardDistributionFormula:
    """Test the mathematical properties of the distribution formula"""

    def test_contiguous_ranges(self):
        """Test that each worker gets a contiguous range of shards"""
        for worker_count in range(1, 17):
            for worker_index in range(worker_count):
                total_shards = 16
                shards_per_worker = total_shards // worker_count
                remainder = total_shards % worker_count

                start_shard = worker_index * shards_per_worker + min(worker_index, remainder)
                end_shard = start_shard + shards_per_worker + (1 if worker_index < remainder else 0)
                expected_shards = list(range(start_shard, end_shard))

                # Verify contiguous range
                if len(expected_shards) > 0:
                    assert expected_shards == list(range(expected_shards[0], expected_shards[-1] + 1))

    def test_first_workers_get_extra_shards(self):
        """Test that when shards don't divide evenly, first workers get extra shards"""
        # Test with 5 workers (16 % 5 = 1, so first worker gets extra)
        worker_0_shards = list(range(16))[:4]  # First 4 shards

        total_shards = 16
        worker_count = 5
        worker_index = 0

        shards_per_worker = total_shards // worker_count  # 3
        remainder = total_shards % worker_count  # 1

        start_shard = worker_index * shards_per_worker + min(worker_index, remainder)  # 0
        end_shard = start_shard + shards_per_worker + (1 if worker_index < remainder else 0)  # 4

        assert start_shard == 0
        assert end_shard == 4
        assert list(range(start_shard, end_shard)) == [0, 1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
