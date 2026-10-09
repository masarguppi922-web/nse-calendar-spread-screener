# NSE Calendar Spread Screener

A small project for screening liquid NSE F&O stocks for a buy-near / sell-far monthly calendar-spread setup.

## Project structure

- `nse_futures_fetcher.py` — fetches futures contract data and computes monthly contract pairs.
- `nse_calendar_spread_screener.py` — screens symbols across historical months and ranks them.
- `requirements.txt` — Python dependencies.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the screener

```bash
python nse_calendar_spread_screener.py --months 12
python nse_calendar_spread_screener.py --months 12 --symbols DMART,RELIANCE,TCS
```

## Notes

- The script is designed to work with the `jugaad-data` NSE backend when available.
- NSE access is subject to external network/server behavior; if the upstream provider changes endpoints or column names, the compatibility helpers in `nse_futures_fetcher.py` and the screener are the places to patch.
- The script saves CSV output under the default data directory, which is configured in the fetcher module.
