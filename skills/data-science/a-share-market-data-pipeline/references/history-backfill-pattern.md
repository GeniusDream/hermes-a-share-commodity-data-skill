# Historical backfill pattern for A-share daily pipelines

## Why this exists

A daily A-share report can start with only current-day snapshots, but lagged upstream/downstream scoring needs a rolling history. Add history capability as an operator-visible mode, not as hidden ad-hoc probes.

## Interface layout

Useful command-line modes:

```bash
python a_share_market_db.py --test-history --history-days 31
python a_share_market_db.py --backfill-history --history-days 31
python a_share_market_db.py --backfill-history --start-date 20260508 --end-date 20260608
```

Keep `--test-interfaces` for live/current-day sources and `--test-history` for historical sources, so failures are isolated.

## Data-source pattern

1. Sina futures daily K-line for commodities:
   - Endpoint class: `InnerFuturesNewService.getDailyKLine`.
   - Store as `asset_type='commodity'` with source `sina_futures_history`.
   - The latest completed futures daily K may lag today's date; report the actual min/max date.

2. AKShare index daily history:
   - Use `stock_zh_index_daily_em`.
   - Always pass explicit `start_date` and `end_date`.
   - Store as `asset_type='index'` with source `akshare_index_history`.

3. AKShare board history:
   - Prefer direct BK codes over Chinese names.
   - Industry boards may use `period='日k'`.
   - Concept boards may use `period='daily'`.
   - Store with source `akshare_board_history` and preserve `bk_code` in raw metadata.

## Proxy handling

For Eastmoney/AKShare historical calls, wrap the call in a temporary environment override:

```python
@contextlib.contextmanager
def eastmoney_no_proxy_env():
    old = {k: os.environ.get(k) for k in ('NO_PROXY', 'no_proxy')}
    try:
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

This avoids proxy-path failures without turning the session-specific proxy failure itself into a general rule.

## Persistence pattern

Reuse the normal `market_quotes` table when its primary key includes `(trade_date, asset_type, code, source)`:

- Add `upsert_quote(..., trade_date=TRADE_DATE)` so historical callers can pass a specific trade date.
- Add `upsert_history_quote(cur, row)` where row begins with the historical trade date.
- Keep source names distinct from live snapshot sources.

This lets existing correlation queries over `market_quotes` start working once enough historical rows exist.

## Verification checklist

After changing the script, verify all three layers:

1. Unit-level behavior for helper functions and AKShare parameter calls.
2. Historical interface probe:
   - `--test-history --history-days 31`
   - record rows, attempts, latency, and errors.
3. Database backfill:
   - `--backfill-history --history-days 31`
   - query row counts grouped by source and asset type, plus min/max trade dates and distinct trade-day count.
4. Current-day regression:
   - `--test-interfaces`
5. Full main flow:
   - run the normal script and confirm source statuses include both history and live sources.

## Reporting to the user

Report concise operational facts:

- files changed;
- new CLI modes;
- sources added;
- exact validation commands run;
- row counts and date ranges from real output;
- any normal data lag, such as futures daily K being available only through the latest completed trading day.
