# Cutoff-window collection/analysis split for replayable A-share reports

## Problem this prevents

A recurring A-share morning/evening report may be regenerated or redelivered hours after its official cutoff. If rendering code directly calls live Sina/Eastmoney/AKShare endpoints, the title can still say `08:50` or `15:00` while the commodity-anomaly ranking reflects a later market session. This creates false omissions: e.g. a core-pool commodity such as coking coal can be present in formal transmission evidence but disappear from the visible `商品异动` section because later high-volatility expanded-radar commodities crowded it out.

## Target architecture

Split the script into two explicit phases:

1. Collection phase: fetch external interfaces and upsert/de-duplicate into PostgreSQL.
2. Analysis/render phase: read only database rows that match the target report date and cutoff window.

The analysis phase must not call live quote/minute/news endpoints directly. Manual reruns should replay the stored target window, not the current endpoint state.

## Proven table pattern

Keep existing de-duplicated tables:

- `market_quotes`: keyed by `(trade_date, asset_type, code, source)` for current/historical quotes.
- `news_items`: keyed by stable `item_id` for news and live-news items.

Add a window-specific commodity table for report cutoffs:

- `commodity_window_moves`
  - `report_type`: `morning` or `evening`
  - `target_date`
  - `window_start`, `window_end`
  - `symbol`, `name`
  - `start_price`, `end_price`
  - `pct_chg`, `amplitude`, `high_price`, `low_price`
  - `first_ts`, `last_ts`
  - `source`
  - `raw`
  - `first_run_id`, `last_run_id`
  - `observed_at`, `updated_at`
  - primary key: `(report_type, target_date, symbol, source)`

Use `ON CONFLICT` upserts so repeated collection runs update the same target-window row instead of duplicating it.

## CLI shape

For the current local pipeline, encode modes like this:

- `a_share_market_db.py --collect-only`: collect external data, upsert/de-duplicate DB rows, and write `commodity_window_moves`; no scoring/report analysis.
- `a_share_market_db.py --collect-only --no-history`: fast morning collection, skipping historical backfill.
- `a_share_market_db.py --analyze-only`: read existing DB rows, score links, validate prior links, discover candidates; no external fetch.
- default mode may remain `collect + analyze` for backward compatibility.

Morning script sequence:

1. optionally run `--collect-only --no-history`;
2. render from `commodity_window_moves where report_type='morning' and target_date=today`;
3. use window `previous day 15:00 → target day 09:30`.

Evening script sequence:

1. run `--collect-only`;
2. run `--analyze-only`;
3. run LLM audit/evolution if configured;
4. render from DB rows with window `previous day 15:00 → target day 15:00`.

## Ranking rule learned from the coking-coal omission

Do not rank all commodities with one global `abs(return)+amplitude` top-N. It is an engineering radar, not a quant-quality prioritizer.

Use layered selection:

1. Core pool first, expanded radar second.
2. Within each layer, rank by a deterministic anomaly score such as:
   - morning: `abs(window_pct_chg) + 0.6 * window_amplitude`, with optional historical precision adjustment;
   - evening: `abs(day_pct_chg) + 0.6 * day_amplitude + 0.9 * abs(window_pct_chg) + 0.3 * window_amplitude`.
3. Guarantee core-pool display slots before expanded-radar slots.
4. Add strong-core fallback: if a core commodity has `abs(pct_chg) >= 2%` or `amplitude >= 3%`, append it even if it falls outside the normal core top-N.
5. Label each row as `核心池`, `扩展雷达`, or `观察池`.

This prevents high-volatility expanded commodities such as silver/LPG/tin/egg from hiding core research variables such as coking coal, crude oil, copper, aluminum, methanol, glass, soda ash, iron ore, rebar, or hot-rolled coil.

## Verification checklist

After changing this class of report pipeline:

1. Syntax check Python and shell scripts.
2. Run `--collect-only --no-history` and confirm all required live sources return rows.
3. Query `commodity_window_moves` for both `morning` and `evening` counts and for a known core commodity such as `焦煤连续`.
4. Run the morning script and verify the `夜盘/盘前重点异动` section includes eligible core-pool moves with labels.
5. Run the evening script and verify:
   - formal transmission review still draws from `link_scores`;
   - `今日商品异动` uses core-first ranking;
   - strong core-pool moves are not crowded out by expanded radar.
6. If the user is asking about Feishu/QQBot visibility, inspect the delivered platform message after local verification; do not infer delivered content only from cron stdout.
