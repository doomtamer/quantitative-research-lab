from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
import json

import pytest

from quantlab.research.e005_backtest import (
    COST_SCENARIOS, CUTOFF, Costs, DailyClose, FundingEvent, FundingLedger, MarketHour, Period,
    run_suite, simulate, trend_signal,
)
from quantlab.research.e005_report import metrics, write_report


UTC = timezone.utc
START = datetime(2024, 3, 1, 1, tzinfo=UTC)
END = datetime(2024, 3, 3, 23, tzinfo=UTC)
PERIOD = Period(START, END)


@pytest.fixture
def candles():
    warmup = START.date() - timedelta(days=200)
    daily = []
    for index in range(202):
        day = warmup + timedelta(days=index)
        available = datetime.combine(day + timedelta(days=1), time(0, 30), UTC)
        daily.append(DailyClose(day, 50 + index if index < 200 else 40, available))
    hours = [
        MarketHour(START + timedelta(hours=index), 100, 100)
        for index in range((END - START) // timedelta(hours=1) + 1)
    ]
    return daily, hours


def test_signal_uses_prior_daily_close_and_scheduled_execution(candles):
    daily, hours = candles
    switched = [replace(row, close=1_000_000) if row.day == START.date() else row for row in daily]
    original = simulate(PERIOD, hours, daily, strategy="trend")
    changed = simulate(PERIOD, hours, switched, strategy="trend")
    assert [(trade.side, trade.at) for trade in original.fills] == [
        ("buy", START), ("sell", START + timedelta(days=1)),
    ]
    assert original.fills[0] == changed.fills[0]
    assert all(point.quantity >= 0 and point.exposure <= 1 for point in original.points)


@pytest.mark.parametrize("delay", [0, 1])
def test_does_not_execute_a_signal_at_or_after_the_fill(candles, delay):
    daily, hours = candles
    previous = START.date() - timedelta(days=1)
    daily = [replace(row, available_at=START + timedelta(seconds=delay)) if row.day == previous else row for row in daily]
    with pytest.raises(ValueError, match="unavailable daily close"):
        simulate(PERIOD, hours, daily, strategy="trend")


def test_missing_history_and_price_gaps_stop_the_run(candles):
    daily, hours = candles
    with pytest.raises(ValueError, match="Missing warmup"):
        simulate(PERIOD, hours, daily[1:], strategy="trend")
    with pytest.raises(ValueError, match="Hourly coverage"):
        simulate(PERIOD, hours[:7] + hours[8:], daily, strategy="trend")


def test_rejects_e002_boundary_inputs(candles):
    daily, hours = candles
    protected = datetime(2025, 9, 13, 23, tzinfo=UTC)
    with pytest.raises(ValueError, match="E002 boundary"):
        simulate(Period(START, protected), hours, daily, strategy="trend")
    extra = DailyClose(protected.date(), 100, protected)
    with pytest.raises(ValueError, match="protected period"):
        simulate(PERIOD, hours, daily + [extra], strategy="trend")
    late_publication = DailyClose(CUTOFF.date() - timedelta(days=1), 100, CUTOFF)
    with pytest.raises(ValueError, match="protected period"):
        simulate(PERIOD, hours, daily + [late_publication], strategy="trend")
    with pytest.raises(ValueError, match="protected period"):
        trend_signal({}, CUTOFF + timedelta(hours=1))
    with pytest.raises(ValueError, match="incomplete hourly"):
        simulate(PERIOD, [*hours[:-1], MarketHour(CUTOFF, 100, 100)], daily, strategy="trend")


def test_costs_are_adverse_on_both_sides_and_keep_benchmarks_comparable(candles):
    daily, hours = candles
    results = run_suite(PERIOD, hours, daily)["funding_excluded"]
    assert tuple(results) == ("base_8bps", "low_5bps", "stress_16bps")
    assert [(cost.fee_bps, cost.price_shift_bps) for _, cost in COST_SCENARIOS] == [(5, 3), (5, 0), (5, 11)]
    base = results["base_8bps"]["trend"]
    entry, exit = base.fills
    assert entry.price == pytest.approx(100.03)
    assert exit.price == pytest.approx(99.97)
    assert entry.fee == pytest.approx(entry.quantity * entry.price * 0.0005)
    assert entry.price_shift_cost == pytest.approx(entry.quantity * 0.03)
    assert base.points[-1].equity == pytest.approx(
        base.initial_equity - entry.fee - exit.fee - entry.price_shift_cost - exit.price_shift_cost
    )
    low = results["low_5bps"]["trend"]
    assert not low.fills[0].price_shift_cost
    assert results["stress_16bps"]["trend"].points[-1].equity < base.points[-1].equity < low.points[-1].equity
    hold = results["base_8bps"]["buy_and_hold"]
    assert len(hold.fills) == 1 and hold.points[-1].quantity > 0
    cash = results["base_8bps"]["cash"]
    assert not cash.fills and all(point.equity == cash.initial_equity for point in cash.points)
    assert [point.at for point in hold.points] == [point.at for point in cash.points]


def test_execution_uses_the_hourly_trade_proxy_before_marking_pnl(candles):
    daily, hours = candles
    hours = [replace(hours[0], mark=102), replace(hours[1], open=140, mark=103), *hours[2:]]
    result = simulate(PERIOD, hours, daily, strategy="trend", costs=Costs(0, 0))
    assert result.fills[0].price == 100
    assert result.points[0].equity == 10_180
    assert result.points[1].equity == 10_270


def test_actual_funding_uses_event_mark_and_previous_position(candles):
    daily, hours = candles
    settlements = (
        FundingEvent(START, 0.01, 100),
        FundingEvent(START + timedelta(hours=8, seconds=1), 0.01, 110),
        FundingEvent(START + timedelta(days=1), -0.005, 120),
    )
    funding = FundingLedger(settlements, tuple(event.at for event in settlements))
    result = simulate(PERIOD, hours, daily, strategy="trend", costs=Costs(0, 0), funding=funding)
    assert result.fills[0].quantity == 90
    assert result.funding_pnl == pytest.approx(-45)
    assert result.points[-1].equity == pytest.approx(9955)
    incomplete = FundingLedger(settlements[:-1], funding.expected_times)
    with pytest.raises(ValueError, match="complete"):
        simulate(PERIOD, hours, daily, strategy="trend", funding=incomplete)
    without_event_mark = FundingLedger((replace(settlements[0], mark=None), *settlements[1:]), funding.expected_times)
    with pytest.raises(ValueError, match="Invalid or out-of-period funding"):
        simulate(PERIOD, hours, daily, strategy="trend", funding=without_event_mark)


def test_missing_market_marks_and_funding_are_explicit(candles):
    daily, hours = candles
    result = simulate(PERIOD, [replace(bar, mark=None) for bar in hours], daily, strategy="trend")
    summary = metrics(result)
    assert summary["equity_prices"] == "traded_open_proxy"
    assert summary["funding_status"] == "funding_excluded"
    assert summary["funding_pnl"] is None
    with pytest.raises(ValueError, match="incomplete hourly"):
        simulate(PERIOD, [replace(hours[0], mark=None), *hours[1:]], daily, strategy="trend")


def test_funding_shortfall_stops_without_an_invented_rebalance(candles):
    daily, hours = candles
    event = FundingEvent(START + timedelta(hours=8), 0.2, 100)
    funding = FundingLedger((event,), (event.at,))
    with pytest.raises(ValueError, match="1x cap"):
        simulate(PERIOD, hours, daily, strategy="trend", funding=funding)


def test_synthetic_portfolio_artifacts_and_no_overwrite(candles, tmp_path):
    daily, hours = candles
    cases = run_suite(PERIOD, hours, daily)
    cash = cases["funding_excluded"]["base_8bps"]["cash"]
    assert metrics(cash)["sharpe"] is None
    assert metrics(cash)["sortino"] is None
    assert metrics(cash)["cagr"] == 0
    assert metrics(cash)["annual_returns"] == {"2024": 0}
    assert metrics(cash)["funding_pnl"] is None
    output = tmp_path / "synthetic"
    write_report(output, cases, period_name="synthetic")
    report = json.loads((output / "metrics.json").read_bytes())
    trend = report["scenarios"]["funding_excluded/base_8bps/trend"]
    assert report["execution_reference"] == "traded_open_proxy"
    assert report["full_futures_backtest_verified"] is False
    assert len(report["scenarios"]) == 9
    assert [item["nominal_total_bps"] for item in report["cost_scenarios"].values()] == [8, 5, 16]
    assert trend["max_drawdown"] < 0 and trend["fills"] == 2 and trend["turnover"] > 0
    assert 0 < trend["time_in_market"] < 1
    assert "Calendar-year returns" in (output / "summary.md").read_text(encoding="utf-8")
    assert (output / "equity_funding_excluded.png").read_bytes().startswith(b"\x89PNG")
    assert len((output / "equity.csv").read_text().splitlines()) == 1 + 9 * len(hours)
    assert (output / "fills.csv").is_file()
    with pytest.raises(FileExistsError):
        write_report(output, cases, period_name="second")
    with pytest.raises(ValueError, match="every preregistered"):
        write_report(tmp_path / "partial", {"funding_excluded": {"base_8bps": {}}}, period_name="partial")
