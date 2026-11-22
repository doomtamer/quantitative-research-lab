"""In-memory E005 long/flat simulator. No network, approvals or historical runner."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import fsum, isfinite


UTC = timezone.utc
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
CUTOFF = datetime(2025, 9, 13, tzinfo=UTC)
ALLOCATION = 0.90
EXECUTION_REFERENCE = "traded_open_proxy"


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DailyClose:
    day: date
    close: float
    available_at: datetime
    availability_basis: str


@dataclass(frozen=True)
class MarketHour:
    at: datetime
    open: float
    mark: float | None = None


@dataclass(frozen=True)
class FundingEvent:
    at: datetime
    rate: float
    mark: float


@dataclass(frozen=True)
class FundingLedger:
    """Events and the independently audited settlement calendar for the period."""

    events: tuple[FundingEvent, ...]
    expected_times: tuple[datetime, ...]


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 5
    price_shift_bps: float = 3

    @property
    def fee(self):
        return self.fee_bps / 10_000

    @property
    def price_shift(self):
        return self.price_shift_bps / 10_000


COST_SCENARIOS = (
    ("base_8bps", Costs(5, 3)),
    ("low_5bps", Costs(5, 0)),
    ("stress_16bps", Costs(5, 11)),
)
STRATEGIES = ("trend", "buy_and_hold", "cash")


@dataclass(frozen=True)
class Point:
    at: datetime
    equity: float
    cash: float
    quantity: float
    exposure: float


@dataclass(frozen=True)
class Fill:
    at: datetime
    side: str
    quantity: float
    price: float
    fee: float
    price_shift_cost: float


@dataclass(frozen=True)
class Result:
    initial_equity: float
    points: tuple[Point, ...]
    fills: tuple[Fill, ...]
    funding_pnl: float
    funding_applied: bool
    mark_prices_used: bool


def require_utc(instant: datetime):
    if instant.utcoffset() != timedelta(0):
        raise ValueError("Every timestamp must be UTC.")


def positive(price: float | None):
    return price is not None and isfinite(price) and price > 0


def trend_signal(history: dict[date, DailyClose], execution: datetime) -> bool:
    """Use the 200 completed consecutive UTC sessions before this 01:00 open."""
    require_utc(execution)
    if execution.time() != time(1) or execution >= CUTOFF:
        raise ValueError("Signal requires a 01:00 UTC execution before the protected period.")
    day = execution.date() - DAY
    closes = []
    for lag in range(199, -1, -1):
        session = day - lag * DAY
        item = history.get(session)
        if item is None:
            raise ValueError(f"Missing warmup or signal session {session}.")
        require_utc(item.available_at)
        closed = datetime.combine(session + DAY, time(), UTC)
        if (item.day != session or not closed <= item.available_at < execution or not positive(item.close)
                or item.availability_basis not in ("historical_verified", "simulation_assumption")):
            raise ValueError(f"Invalid or unavailable daily close for {session}.")
        closes.append(item.close)
    return closes[-1] > fsum(closes) / 200 and closes[-1] > closes[-21]


def validate_inputs(period, hours, history, costs, initial_equity, funding):
    require_utc(period.start)
    require_utc(period.end)
    if (period.start.time() != time(1) or period.end.time() != time(23)
            or not period.start < period.end < CUTOFF):
        raise ValueError("Use an inclusive 01:00 to 23:00 UTC period before the E002 boundary.")
    if not positive(initial_equity) or not all(
        isfinite(value) and 0 <= value < 10_000
        for value in (costs.fee_bps, costs.price_shift_bps)
    ):
        raise ValueError("Invalid initial equity or costs.")
    if len(hours) != (period.end - period.start) // HOUR + 1:
        raise ValueError("Hourly coverage is incomplete.")
    marked = hours[0].mark is not None
    for index, bar in enumerate(hours):
        require_utc(bar.at)
        if (bar.at != period.start + index * HOUR or not positive(bar.open)
                or (bar.mark is not None) != marked or (marked and not positive(bar.mark))):
            raise ValueError("Invalid, unsorted or incomplete hourly prices.")
    if any(day >= CUTOFF.date() or item.available_at >= CUTOFF for day, item in history.items()):
        raise ValueError("Daily inputs may not reach the protected period.")
    if funding is not None:
        actual = tuple(event.at for event in funding.events)
        if not actual or actual != funding.expected_times or tuple(sorted(set(actual))) != actual:
            raise ValueError("Funding must match a complete, unique, ordered settlement schedule.")
        for event in funding.events:
            require_utc(event.at)
            if not period.start <= event.at <= period.end or not isfinite(event.rate) or not positive(event.mark):
                raise ValueError("Invalid or out-of-period funding event.")


def simulate(period, hours, daily, *, strategy, costs=Costs(), initial_equity=10_000.0, funding=None):
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy.")
    hours, daily = tuple(hours), tuple(daily)
    history = {item.day: item for item in daily}
    if len(history) != len(daily):
        raise ValueError("Duplicate daily sessions.")
    for item in daily:
        require_utc(item.available_at)
    validate_inputs(period, hours, history, costs, initial_equity, funding)

    cash, quantity, funding_pnl = initial_equity, 0.0, 0.0
    points, fills = [], []
    settlements = iter(funding.events if funding else ())
    event = next(settlements, None)
    for bar in hours:
        # Settlements since the last mark, including the exact execution instant,
        # belong to the position immediately before this hour's simulated fill.
        while event is not None and event.at <= bar.at:
            payment = -quantity * event.mark * event.rate
            funding_pnl += payment
            cash += payment
            if cash < 0:
                raise ValueError("Funding exhausted the reserve. The 1x cap cannot be maintained.")
            event = next(settlements, None)

        if bar.at.time() == time(1):
            want_long = strategy == "buy_and_hold" or (strategy == "trend" and trend_signal(history, bar.at))
            if want_long != (quantity > 0):
                direction = 1 if want_long else -1
                execution = bar.open * (1 + direction * costs.price_shift)
                traded = cash * ALLOCATION / (execution * (1 + costs.fee)) if want_long else quantity
                fee = traded * execution * costs.fee
                cash -= direction * traded * execution + fee
                quantity += direction * traded
                fills.append(Fill(
                    bar.at, "buy" if want_long else "sell", traded, execution, fee,
                    traded * abs(execution - bar.open),
                ))

        notional = quantity * (bar.mark if bar.mark is not None else bar.open)
        equity = cash + notional
        if not positive(equity) or quantity < 0 or cash < 0 or notional > equity:
            raise ValueError("The ledger cannot maintain positive equity and the 1x cap.")
        points.append(Point(bar.at, equity, cash, quantity, notional / equity))
    return Result(initial_equity, tuple(points), tuple(fills), funding_pnl, funding is not None, hours[0].mark is not None)


def run_suite(period, hours, daily, *, funding=None):
    """Compare all preregistered cost scenarios on exactly the same time grid."""
    hours, daily = tuple(hours), tuple(daily)
    funding_cases = {"funding_excluded": None}
    if funding is not None:
        funding_cases["observed_funding"] = funding
    return {
        scenario: {
            cost_name: {
                strategy: simulate(period, hours, daily, strategy=strategy, costs=cost, funding=ledger)
                for strategy in STRATEGIES
            }
            for cost_name, cost in COST_SCENARIOS
        }
        for scenario, ledger in funding_cases.items()
    }
