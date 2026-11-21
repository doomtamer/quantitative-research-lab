"""Portfolio reporting for completed in-memory E005 results."""

import csv
import json
from math import sqrt
from pathlib import Path
from statistics import fmean, stdev

from quantlab.research.e005_backtest import COST_SCENARIOS, EXECUTION_REFERENCE, STRATEGIES, Result


def display(value, *, percent=False):
    if value is None:
        return "—"
    return f"{value:.2%}" if percent else f"{value:.3f}"


def metrics(result: Result) -> dict:
    points = result.points
    final = points[-1].equity
    elapsed_days = (points[-1].at - points[0].at).total_seconds() / 86_400
    daily = {}
    for point in points:
        daily[point.at.date()] = point.equity
    returns = []
    previous = result.initial_equity
    for equity in daily.values():
        returns.append(equity / previous - 1)
        previous = equity
    volatility = stdev(returns) if len(returns) > 1 else 0
    downside = sqrt(fmean(min(0, change) ** 2 for change in returns))

    peak = result.initial_equity
    drawdown = 0.0
    annual_closes = {}
    for point in points:
        peak = max(peak, point.equity)
        drawdown = min(drawdown, point.equity / peak - 1)
        annual_closes[point.at.year] = point.equity
    annual_returns = {}
    previous = result.initial_equity
    for year, equity in annual_closes.items():
        annual_returns[str(year)] = equity / previous - 1
        previous = equity

    avg_equity = fmean(point.equity for point in points)
    return {
        "final_equity": final,
        "total_return": final / result.initial_equity - 1,
        "cagr": (final / result.initial_equity) ** (365.25 / elapsed_days) - 1,
        "sharpe": sqrt(365) * fmean(returns) / volatility if volatility else None,
        "sortino": sqrt(365) * fmean(returns) / downside if downside and len(returns) > 1 else None,
        "max_drawdown": drawdown,
        "turnover": sum(fill.quantity * fill.price for fill in result.fills) / avg_equity,
        "fills": len(result.fills),
        "completed_round_trips": sum(fill.side == "sell" for fill in result.fills),
        "time_in_market": fmean(point.quantity > 0 for point in points[:-1]),
        "mean_gross_exposure": fmean(point.exposure for point in points[:-1]),
        "max_gross_exposure": max(point.exposure for point in points),
        "fees": sum(fill.fee for fill in result.fills),
        "adverse_price_shift_cost": sum(fill.price_shift_cost for fill in result.fills),
        "funding_status": "observed_funding" if result.funding_applied else "funding_excluded",
        "funding_pnl": result.funding_pnl if result.funding_applied else None,
        "equity_prices": "mark" if result.mark_prices_used else EXECUTION_REFERENCE,
        "annual_returns": annual_returns,
    }


def write_report(directory: Path, cases: dict, *, period_name: str):
    """Write a new run directory. All inputs are results supplied by the caller."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    expected_costs = {name for name, _ in COST_SCENARIOS}
    if "funding_excluded" not in cases or not set(cases) <= {"funding_excluded", "observed_funding"}:
        raise ValueError("Expected the funding-excluded scenario and optionally observed funding.")
    for levels in cases.values():
        if set(levels) != expected_costs or any(set(results) != set(STRATEGIES) for results in levels.values()):
            raise ValueError("Reports require every preregistered cost scenario and benchmark.")

    series = {
        f"{scenario}/{cost}/{strategy}": result
        for scenario, levels in cases.items()
        for cost, strategies in levels.items()
        for strategy, result in strategies.items()
    }
    results = {name: metrics(result) for name, result in series.items()}
    directory.mkdir(parents=True, exist_ok=False)
    payload = {
        "period": period_name,
        "execution_reference": EXECUTION_REFERENCE,
        "interpretation": "traded_open_proxy uses the traded 01:00 UTC hourly open. Historical fill attainability is unverified.",
        "full_futures_backtest_verified": False,
        "cost_scenarios": {
            name: {"commission_bps": cost.fee_bps, "adverse_price_shift_bps": cost.price_shift_bps,
                   "nominal_total_bps": cost.fee_bps + cost.price_shift_bps}
            for name, cost in COST_SCENARIOS
        },
        "scenarios": results,
    }
    with (directory / "metrics.json").open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, indent=2, allow_nan=False)
        output.write("\n")
    with (directory / "summary.md").open("x", encoding="utf-8", newline="\n") as output:
        output.write(f"# E005 — {period_name}\n\n{payload['interpretation']}\n\n")
        output.write("funding_excluded omits unverified funding. All results remain execution-proxy simulations.\n\n")
        output.write("| Costs | Commission per side (bps) | Adverse price shift per side (bps) |\n| --- | ---: | ---: |\n")
        for name, cost in COST_SCENARIOS:
            output.write(f"| {name} | {cost.fee_bps:g} | {cost.price_shift_bps:g} |\n")
        output.write("\n| Scenario / costs / strategy | Equity prices | Return | CAGR | Sharpe | Sortino | Max drawdown | Turnover | Fills | Time in market |\n")
        output.write("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
        for name, row in results.items():
            cells = [
                name, row["equity_prices"], display(row["total_return"], percent=True),
                display(row["cagr"], percent=True),
                display(row["sharpe"]), display(row["sortino"]), display(row["max_drawdown"], percent=True),
                display(row["turnover"]), str(row["fills"]), display(row["time_in_market"], percent=True),
            ]
            output.write("| " + " | ".join(cells) + " |\n")
        output.write("\n## Calendar-year returns\n\n")
        output.write("| Scenario / costs / strategy | Year | Return |\n| --- | ---: | ---: |\n")
        for name, row in results.items():
            for year, change in row["annual_returns"].items():
                output.write(f"| {name} | {year} | {change:.2%} |\n")
    with (directory / "equity.csv").open("x", encoding="utf-8", newline="") as output:
        table = csv.writer(output)
        table.writerow(("series", "timestamp_utc", "equity", "cash_residual", "quantity", "gross_exposure"))
        for name, result in series.items():
            table.writerows(
                (name, point.at.isoformat(), point.equity, point.cash, point.quantity, point.exposure)
                for point in result.points
            )
    with (directory / "fills.csv").open("x", encoding="utf-8", newline="") as output:
        table = csv.writer(output)
        table.writerow(("series", "timestamp_utc", "side", "quantity", "price_proxy", "fee", "adverse_price_shift_cost"))
        for name, result in series.items():
            table.writerows(
                (name, fill.at.isoformat(), fill.side, fill.quantity, fill.price, fill.fee, fill.price_shift_cost)
                for fill in result.fills
            )
    for scenario, levels in cases.items():
        figure = Figure(figsize=(10, 4.2), layout="constrained")
        FigureCanvasAgg(figure)
        ax = figure.subplots()
        for cost_name, strategies in levels.items():
            for strategy, result in strategies.items():
                if cost_name != "base_8bps" and strategy == "cash":
                    continue
                ax.plot(
                    [point.at for point in result.points], [100 * point.equity / result.initial_equity for point in result.points],
                    label=f"{strategy.replace('_', ' ')} · {cost_name}",
                    linestyle={"base_8bps": "-", "low_5bps": ":", "stress_16bps": "--"}[cost_name],
                )
        ax.set(title=f"E005 | {period_name} | {scenario} | {EXECUTION_REFERENCE}", ylabel="Equity index (initial = 100)")
        ax.grid(alpha=0.25)
        ax.legend(ncols=2)
        with (directory / f"equity_{scenario}.png").open("xb") as output:
            figure.savefig(output, format="png", dpi=160)
    return payload
