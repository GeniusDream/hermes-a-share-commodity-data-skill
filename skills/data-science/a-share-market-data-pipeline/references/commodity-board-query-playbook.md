# Commodity and Board Query Playbook for A-share Morning/Evening Reports

Use this reference when another Hermes window needs to answer questions such as:

- “某个商品有没有被早晚报采到？”
- “某个商品窗口涨跌幅是多少？”
- “某个A股板块最近有没有行情/历史样本？”
- “某条商品→板块链路映射了哪些上游和下游？”
- “今天某商品相关链路为什么进/没进报告？”

The goal is to query the existing local PostgreSQL database and maintained universe files before reaching for live scraping or ad-hoc web search.

## Fixed local paths

- Docker compose: `$HERMES_HOME/a_share_daily_db/docker-compose.yml`
- Main collector/scorer: `$HERMES_HOME/scripts/a_share_market_db.py`
- Morning report wrapper: `$HERMES_HOME/scripts/a_share_morning_prediction.sh`
- Evening report wrapper: `$HERMES_HOME/scripts/a_share_chain_daily.sh`
- Commodity universe: `$HERMES_HOME/scripts/a_share_commodity_universe.py`
- Commodity signal ranking: `$HERMES_HOME/scripts/a_share_commodity_signal.py`

## First check database availability

```bash
docker compose -f $HERMES_HOME/a_share_daily_db/docker-compose.yml ps
```

If the container is not healthy, start it:

```bash
docker compose -f $HERMES_HOME/a_share_daily_db/docker-compose.yml up -d
```

Use this psql wrapper in examples:

```bash
docker exec a-share-daily-postgres psql -U a_share -d a_share_daily -P pager=off
```

## Important tables

- `commodity_window_moves`: stored cutoff-window commodity moves for morning/evening reports. This is usually the first table to query for “商品有没有被采到 / 窗口涨跌幅是多少”.
- `market_quotes`: A-share board/index/futures quote rows, including live snapshots and historical backfills. Query this for board行情, historical samples, and source coverage.
- `kline_candles`: 4H/daily candles used by K-line phase visualizations when available.
- `link_mappings`: official commodity→affected-board mappings, including upstream names, downstream board patterns, expected relation, and logic.
- `link_scores`: daily scored chains with evidence JSON, best lag/correlation, and LLM audit verdicts.
- `candidate_links`: discovered but not yet official candidate chains.
- `news_items`: local news/event rows used as event evidence.
- `source_status`: source health and failures for a run/date.

## Query commodity window moves

Latest stored commodity windows:

```sql
select report_type, target_date, name, symbol,
       round(pct_chg, 2) as pct_chg,
       round(amplitude, 2) as amplitude,
       source, first_ts, last_ts, updated_at
from commodity_window_moves
order by target_date desc, report_type, abs(pct_chg) desc nulls last
limit 80;
```

Search one commodity by Chinese name or symbol:

```sql
select report_type, target_date, name, symbol,
       round(pct_chg, 2) as pct_chg,
       round(amplitude, 2) as amplitude,
       start_price, end_price, first_ts, last_ts, source, updated_at
from commodity_window_moves
where name ilike '%焦煤%' or symbol ilike '%JM%'
order by target_date desc, report_type, abs(pct_chg) desc nulls last
limit 50;
```

For morning/evening distinction:

- Morning report window: previous A-share day 15:00 → current day 09:30.
- Evening report window: previous A-share day 15:00 → current day 15:00.
- Query by `report_type` and `target_date`; do not infer from current realtime quotes after cutoff.

```sql
select name, symbol, round(pct_chg, 2) pct_chg, round(amplitude, 2) amplitude,
       first_ts, last_ts, source
from commodity_window_moves
where report_type = 'evening'
  and target_date = current_date
order by abs(pct_chg) desc nulls last
limit 40;
```

## Query A-share board quote/history coverage

Latest rows for a board name:

```sql
select trade_date, asset_type, code, name,
       round(pct_chg, 2) pct_chg, source, updated_at
from market_quotes
where name ilike '%煤炭%'
order by trade_date desc, updated_at desc
limit 80;
```

Check historical sample coverage by source/name:

```sql
select source, asset_type, code, name,
       count(*) as rows,
       min(trade_date) as first_date,
       max(trade_date) as last_date,
       max(updated_at) as latest_write
from market_quotes
where name ilike '%钢铁%'
group by source, asset_type, code, name
order by rows desc, latest_write desc
limit 50;
```

Compare board moves on a target date:

```sql
select trade_date, code, name, round(pct_chg, 2) pct_chg, source
from market_quotes
where trade_date = current_date
  and asset_type in ('board', 'industry_board', 'concept_board', 'index')
  and (name ilike '%有色%' or name ilike '%铜%' or name ilike '%金属%')
order by pct_chg desc nulls last;
```

## Query official commodity→board mappings

Find official mappings by upstream commodity or downstream board keyword:

```sql
select link_id, link_name, upstream_names, downstream_patterns,
       expected_relation, lag_days, logic, enabled, updated_at
from link_mappings
where enabled
  and (
    upstream_names::text ilike '%焦煤%'
    or downstream_patterns::text ilike '%煤炭%'
    or link_name ilike '%黑色%'
  )
order by link_id;
```

Use this before saying “没有链路”. If the mapping exists but the report did not print it, inspect `link_scores` and cutoff-window commodity/board evidence.

## Query scored links and evidence

Latest scored links involving a keyword:

```sql
select trade_date, link_id, link_name, score, confidence,
       best_lag, round(best_corr, 3) best_corr,
       llm_verdict, llm_adjustment, llm_reason, created_at, llm_reviewed_at
from link_scores
where link_name ilike '%黑色%'
   or evidence::text ilike '%焦煤%'
   or evidence::text ilike '%煤炭%'
order by trade_date desc, score desc nulls last
limit 30;
```

Inspect evidence JSON for one scored link:

```sql
select trade_date, link_id, link_name, evidence
from link_scores
where trade_date = current_date
  and (link_id = 'PUT_LINK_ID_HERE' or link_name ilike '%黑色%')
order by score desc nulls last
limit 3;
```

When explaining why a chain did or did not appear, separate these layers:

1. Did the commodity appear in `commodity_window_moves` for the correct report window?
2. Did affected A-share boards appear in `market_quotes` for the correct date/window?
3. Does `link_mappings` include an official mapping for the commodity/board family?
4. Did `link_scores` compute a strong enough score, lag/correlation evidence, and LLM verdict?
5. Was it only a `candidate_links` discovery rather than official mapping?

## Query candidate links

```sql
select *
from candidate_links
where upstream_names::text ilike '%锡%'
   or downstream_patterns::text ilike '%电子%'
   or link_name ilike '%锡%'
order by updated_at desc
limit 30;
```

Candidate links are not confirmed user-facing transmission conclusions. Treat them as watchlist/hypothesis unless repeated evidence, same-industry-family board feedback, news/logic, history, and LLM review support promotion.

## Query news/event clues

```sql
select published_at, source, channel, title, url
from news_items
where published_at >= now() - interval '2 days'
  and (title ilike '%焦煤%' or body ilike '%焦煤%' or tags::text ilike '%焦煤%')
order by published_at desc
limit 50;
```

News is supporting evidence only. Do not let broad global-news keyword matches override same-family commodity/board evidence.

## Query maintained commodity universe file

When asking whether a commodity is supposed to be in the core pool or expanded radar, inspect:

`$HERMES_HOME/scripts/a_share_commodity_universe.py`

Search inside it for the Chinese name, futures symbol, family keywords, and impact mapping. If adding a new commodity, probe both Sina quote and minute-line interfaces before editing the universe.

## Refresh data when needed

If the question is about stored/cutoff data, query DB first. If data is missing or stale and the user wants a refresh, use the collector modes rather than ad-hoc scraping:

```bash
python3 $HERMES_HOME/scripts/a_share_market_db.py --collect-only
python3 $HERMES_HOME/scripts/a_share_market_db.py --analyze-only
```

For history checks/backfills:

```bash
python3 $HERMES_HOME/scripts/a_share_market_db.py --test-history --history-days 31
python3 $HERMES_HOME/scripts/a_share_market_db.py --backfill-history --history-days 31
```

If plain `python3` lacks dependencies in the current shell, find and use the same virtualenv/interpreter used by the cron job or report wrapper rather than installing packages globally.

## Answering style for other windows

For user-facing answers:

- Give the direct result first: commodity/board found or not found, latest date/window, pct change, source, mapping/scoring status.
- Mention whether the result is from stored cutoff DB data or a live refresh.
- Keep backend diagnostics short unless asked.
- Do not cite individual stocks; the report evidence model is board/sector level only.
- If no rows are found, say which table/window/name pattern was checked and suggest the next concrete check.
