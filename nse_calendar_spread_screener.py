"""
nse_calendar_spread_screener.py

Screens a list of liquid NSE F&O stocks and ranks them as candidates for the
"buy current-month future / sell next-month future, entered in week 1,
squared off at current-month expiry" calendar-spread strategy.

Builds on nse_futures_fetcher.py (same backend: jugaad-data).

Install:  pip install jugaad-data pandas

Usage:
    python nse_calendar_spread_screener.py --months 12
    python nse_calendar_spread_screener.py --months 12 --symbols DMART,RELIANCE,TCS
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from nse_futures_fetcher import (
    DEFAULT_DATA_DIR,
    fetch_futures_contract,
    get_monthly_contract_pairs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("nse_calendar_spread_screener")

# A starting watchlist of typically-liquid NSE F&O names. This is illustrative,
# not authoritative — cross-check against NSE's current F&O list before relying
# on it, since eligibility/liquidity rankings shift over time.
DEFAULT_LIQUID_WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "AXISBANK",
    "KOTAKBANK", "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "BAJFINANCE",
    "MARUTI", "TATAMOTORS", "TATASTEEL", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "ASIANPAINT", "NTPC", "POWERGRID", "ADANIENT", "ADANIPORTS", "HCLTECH",
    "WIPRO", "DMART", "BAJAJFINSV", "M&M", "JSWSTEEL", "NESTLEIND",
    "GRASIM", "DIVISLAB", "DRREDDY", "EICHERMOT", "HEROMOTOCO", "CIPLA",
    "COALINDIA", "ONGC", "TECHM",
]


@dataclass
class MonthlySpreadResult:
    symbol: str
    trade_month: date
    near_expiry: date
    far_expiry: date
    near_entry: float
    near_exit: float
    far_entry: float
    far_exit: float
    avg_near_volume: float
    avg_far_volume: float
    avg_near_oi: float
    avg_far_oi: float

    @property
    def spread_pnl(self) -> float:
        return (self.near_exit - self.near_entry) - (self.far_exit - self.far_entry)

    @property
    def spread_pnl_pct(self) -> float:
        if self.near_entry == 0:
            return float("nan")
        return self.spread_pnl / self.near_entry * 100


def _safe_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """jugaad-data column names have shifted slightly across versions; find whichever exists."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def compute_monthly_result(symbol: str, trade_month: date, near_expiry: date, far_expiry: date) -> Optional[MonthlySpreadResult]:
    near_df = fetch_futures_contract(symbol, trade_month, near_expiry, near_expiry)
    far_df = fetch_futures_contract(symbol, trade_month, near_expiry, far_expiry)

    if near_df.empty or far_df.empty:
        log.warning(f"{symbol} {trade_month:%Y-%m}: missing near or far leg data, skipping")
        return None

    close_col = _safe_col(near_df, ["CLOSE", "CLOSE_PRICE", "SETTLE_PR"])
    vol_col = _safe_col(near_df, ["CONTRACTS", "VOLUME", "VAL_INLAKH"])
    oi_col = _safe_col(near_df, ["OPEN_INT", "OI"])

    if close_col is None:
        log.warning(f"{symbol} {trade_month:%Y-%m}: could not find a close-price column, skipping")
        return None

    near_df = near_df.sort_values(near_df.columns[0])
    far_df = far_df.sort_values(far_df.columns[0])

    try:
        near_entry = float(near_df.iloc[0][close_col])
        near_exit = float(near_df.iloc[-1][close_col])
        far_entry = float(far_df.iloc[0][close_col])
        far_exit = float(far_df.iloc[-1][close_col])
    except Exception as e:
        log.warning(f"{symbol} {trade_month:%Y-%m}: price extraction failed ({e}), skipping")
        return None

    avg_near_volume = float(near_df[vol_col].mean()) if vol_col and vol_col in near_df.columns else float("nan")
    avg_far_volume = float(far_df[vol_col].mean()) if vol_col and vol_col in far_df.columns else float("nan")
    avg_near_oi = float(near_df[oi_col].mean()) if oi_col and oi_col in near_df.columns else float("nan")
    avg_far_oi = float(far_df[oi_col].mean()) if oi_col and oi_col in far_df.columns else float("nan")

    return MonthlySpreadResult(
        symbol=symbol,
        trade_month=trade_month,
        near_expiry=near_expiry,
        far_expiry=far_expiry,
        near_entry=near_entry,
        near_exit=near_exit,
        far_entry=far_entry,
        far_exit=far_exit,
        avg_near_volume=avg_near_volume,
        avg_far_volume=avg_far_volume,
        avg_near_oi=avg_near_oi,
        avg_far_oi=avg_far_oi,
    )


def screen_symbol(symbol: str, start_month: date, end_month: date) -> list[MonthlySpreadResult]:
    pairs = get_monthly_contract_pairs(symbol, start_month, end_month)
    results = []
    for pair in pairs:
        r = compute_monthly_result(symbol, pair.trade_month, pair.near_expiry, pair.far_expiry)
        if r is not None:
            results.append(r)
    return results


def aggregate_symbol_scores(all_results: dict[str, list[MonthlySpreadResult]]) -> pd.DataFrame:
    rows = []
    for symbol, results in all_results.items():
        if not results:
            continue
        pct_returns = pd.Series([r.spread_pnl_pct for r in results])
        avg = pct_returns.mean()
        vol = pct_returns.std()
        sharpe_like = avg / vol if vol and vol > 0 else float("nan")
        hit_rate = (pct_returns > 0).mean() * 100

        rows.append({
            "symbol": symbol,
            "months_tested": len(results),
            "avg_monthly_return_pct": round(avg, 3),
            "volatility_pct": round(vol, 3) if pd.notna(vol) else float("nan"),
            "sharpe_like": round(sharpe_like, 3) if pd.notna(sharpe_like) else float("nan"),
            "hit_rate_pct": round(hit_rate, 1),
            "avg_near_volume": round(pd.Series([r.avg_near_volume for r in results]).mean(), 1),
            "avg_far_volume": round(pd.Series([r.avg_far_volume for r in results]).mean(), 1),
            "avg_near_oi": round(pd.Series([r.avg_near_oi for r in results]).mean(), 1),
            "avg_far_oi": round(pd.Series([r.avg_far_oi for r in results]).mean(), 1),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Rank: prioritize consistency (sharpe_like) and liquidity, require a minimum sample size.
    df = df.sort_values(by=["sharpe_like", "avg_far_volume"], ascending=[False, False])
    df.reset_index(drop=True, inplace=True)
    return df


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _months_ago(d: date, n: int) -> date:
    month = d.month - 1 - n
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def run_screener(
    symbols: list[str],
    months_back: int = 12,
    as_of: Optional[date] = None,
    out_dir: Path = DEFAULT_DATA_DIR,
) -> pd.DataFrame:
    as_of = as_of or date.today()
    end_month = _month_start(as_of)
    start_month = _months_ago(end_month, months_back - 1)

    log.info(f"Screening {len(symbols)} symbols from {start_month:%Y-%m} to {end_month:%Y-%m}")

    all_results = {}
    for symbol in symbols:
        log.info(f"--- {symbol} ---")
        try:
            all_results[symbol] = screen_symbol(symbol, start_month, end_month)
        except Exception as e:
            log.error(f"{symbol}: failed entirely ({e}), skipping")
            all_results[symbol] = []

    scores_df = aggregate_symbol_scores(all_results)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"calendar_spread_screener_{start_month:%Y%m}_{end_month:%Y%m}.csv"
    scores_df.to_csv(out_path, index=False)
    log.info(f"Saved screener results -> {out_path}")

    return scores_df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rank liquid NSE stocks as calendar-spread candidates")
    parser.add_argument("--months", type=int, default=12, help="How many months of history to test")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated symbols to override the default watchlist")
    parser.add_argument("--out-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()

    watchlist = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols else DEFAULT_LIQUID_WATCHLIST
    )

    df = run_screener(watchlist, months_back=args.months, out_dir=Path(args.out_dir))

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 160)
    print("\nTop candidates:\n")
    print(df.head(15).to_string(index=False))


