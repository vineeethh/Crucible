"""Pure budget/cache record math (the SQL-side behavior is integration-tested)."""

from crucible.application import BudgetStatus, CacheStats


def test_remaining_is_limit_minus_spend() -> None:
    status = BudgetStatus(monthly_limit_usd=10.0, month_spend_usd=2.5)
    assert status.remaining_usd == 7.5


def test_no_limit_means_no_remaining_number() -> None:
    status = BudgetStatus(monthly_limit_usd=None, month_spend_usd=2.5)
    assert status.remaining_usd is None


def test_hit_rate_counts_false_hits_as_misses() -> None:
    stats = CacheStats(hits=3, misses=1, false_hits=1, stores=2)
    assert stats.hit_rate == 0.6


def test_hit_rate_with_no_traffic_is_zero() -> None:
    assert CacheStats(hits=0, misses=0, false_hits=0, stores=0).hit_rate == 0.0
