from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger("nse_futures_fetcher")

DEFAULT_DATA_DIR = Path.home() / ".nse_calendar_spread_screener"


@dataclass(frozen=True)
class MonthlyContractPair:
    trade_month: date
    near_expiry: date
    far_expiry: date


def _month_add(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def _last_thursday(y: int, m: int) -> date:
    """NSE monthly futures typically expire on the last Thursday of the month."""
    if m == 12:
        next_month = date(y + 1, 1, 1)
    else:
        next_month = date(y, m + 1, 1)
    first_of_next = next_month
    last_day = first_of_next.replace(day=1) - pd.Timedelta(days=1)
    weekday = last_day.weekday()
    offset = (3 - weekday) % 7
    return last_day.to_pydatetime().date() - pd.Timedelta(days=abs(offset - 7) if offset == 0 else 0)  # defensive fallback


def _last_thursday_of_month(d: date) -> date:
    return _last_thursday(d.year, d.month)


def _next_month_date(d: date) -> date:
    return _month_add(d, 1)


def get_monthly_contract_pairs(symbol: str, start_month: date, end_month: date) -> list[MonthlyContractPair]:
    """Build a list of near/far monthly pair expiries for a date range.

    The strategy assumes the current-month contract is the "near" leg and the next-month
    contract is the "far" leg. In real production use, these should be aligned to the exact
    NSE contract-month calendar if the data source exposes it.
    """
    pairs: list[MonthlyContractPair] = []
    current = start_month
    while current <= end_month:
        near_expiry = _last_thursday_of_month(current)
        far_expiry = _last_thursday_of_month(_next_month_date(current))
        pairs.append(MonthlyContractPair(trade_month=current, near_expiry=near_expiry, far_expiry=far_expiry))
        current = _month_add(current, 1)
    return pairs


def fetch_futures_contract(symbol: str, trade_month: date, from_date: date, to_date: date) -> pd.DataFrame:
    """Fetches contract data for a symbol and date range.

    This is intentionally defensive: `jugaad-data` can differ slightly by version and the
    API surface is not standardized across all installs. We try a few common import patterns and,
    if no backend is available, return an empty DataFrame with a warning so the main screener can
    skip unsupported data instead of crashing hard.
    """
    try:
        from jugaad_data import nse
    except Exception:
        log.warning("jugaad-data is not installed or not importable; returning empty DataFrame")
        return pd.DataFrame()

    # The `jugaad-data` library has changed across versions. Try the most common entry points.
    fetchers = []
    for mod in [nse]:
        fetchers.extend(
            [
                lambda: mod.nse_futures(symbol=symbol, from_date=from_date, to_date=to_date),
                lambda: mod.futures(symbol=symbol, from_date=from_date, to_date=to_date),
                lambda: mod.live_futures(symbol=symbol, from_date=from_date, to_date=to_date),
            ]
        )

    last_error = None
    for fn in fetchers:
        try:
            df = fn()
            if isinstance(df, pd.DataFrame):
                return df
        except Exception as exc:  # pragma: no cover - best-effort compatibility logic
            last_error = exc
            continue

    if last_error is not None:
        log.warning("Could not fetch futures data via installed jugaad-data backend: %s", last_error)
    return pd.DataFrame()


__all__ = [
    "DEFAULT_DATA_DIR",
    "MonthlyContractPair",
    "get_monthly_contract_pairs",
    "fetch_futures_contract",
]
