# Dynamic daily-report status copy

Use this reference when a recurring A-share daily report needs status/reminder wording that reflects the real run state.

## Durable lesson

Do not hard-code a single fallback message such as "using existing scores". A report can fail to refresh historical quote interfaces while still recomputing today's link scores from the database's last successful historical quote samples plus today's live quotes/news. The user-facing wording must distinguish those states.

## Data to gather before composing copy

- `source_status` for current `run_date`: `source`, `status`, `rows_count`, `attempts`, `latency_ms`, `error`, `updated_at`.
- Historical sample state from `market_quotes`, grouped by source family:
  - row count;
  - min/max `trade_date`;
  - latest `updated_at`.
- Today's scoring state from `link_scores`:
  - total rows recomputed today;
  - rows with `best_lag`/`best_corr` populated;
  - latest `created_at`;
  - latest `llm_reviewed_at`.

## Suggested source grouping

- Historical quote sources: e.g. `akshare_board_history`, `akshare_index_history`, `sina_futures_history`.
- Live/current sources: today's stock, board, futures, news, and other real-time snapshot sources.

## Message cases

1. All sources succeeded

   `数据源状态：全部数据源本次刷新成功。`

2. Historical quote refresh failed, but historical samples exist

   `数据源状态：⚠️ 部分历史行情接口本次刷新失败；本次没有复用旧链路评分，而是使用数据库中最近一次成功回补的历史行情样本，结合今日实时行情/新闻重新计算今日链路评分。历史样本合计{n}条，最近写入{time}。`

3. Historical quote refresh failed, and no historical samples exist

   `数据源状态：⚠️ 历史行情接口本次刷新失败，且数据库未发现可用历史样本；滞后/相关性评分可能缺失或降级。`

4. Live/current source failed

   `数据源状态：⚠️ 部分实时行情/新闻数据源本次刷新失败，今日覆盖可能不完整。`

Cases can be combined when both live and historical source families fail.

## Diagnostics to include below the status line

- Each failed source: source display name, attempts, rows, latency, and concise error.
- Historical sample status: counts, date ranges, latest write time by source family.
- Scoring status: recomputed link-score row count, count with lag/correlation populated, recompute time, LLM audit time.

## Verification

After modifying wording logic, run the actual report script and inspect:

- command exit code;
- generated status block;
- that a success run says success without stale warnings;
- that a fallback run says historical samples were reused for recomputation, not that old scores were reused.
