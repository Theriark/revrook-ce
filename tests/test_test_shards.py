"""The CI shards of the suite (tests/conftest.py, TEST_SHARD): every test runs in
exactly one shard, and the shards are as even as the count allows."""

import pytest
from conftest import in_shard, shard_of


def test_a_shard_is_read_as_index_of_total() -> None:
    assert shard_of("") is None
    assert shard_of("2/4") == (2, 4)
    for bad in ("0/4", "5/4", "x/4", "2"):
        with pytest.raises(ValueError):
            shard_of(bad)


@pytest.mark.parametrize("count", [0, 1, 7, 4053])
def test_the_shards_split_every_test_exactly_once_and_evenly(count: int) -> None:
    total = 4
    sizes = []
    for position in range(count):
        owners = [i for i in range(1, total + 1) if in_shard(position, i, total)]
        assert len(owners) == 1, position
    for index in range(1, total + 1):
        sizes.append(sum(1 for p in range(count) if in_shard(p, index, total)))
    assert sum(sizes) == count
    assert max(sizes) - min(sizes) <= 1
