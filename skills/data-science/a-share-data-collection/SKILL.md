---
name: a-share-data-collection
description: "Collect Chinese A-share board, commodity futures, index, and news data as JSON/JSONL/CSV."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [a-share, market-data, commodity, akshare, sina, eastmoney, data-collection]
---

# A-share Data Collection

## When to use

Use this skill when the user asks to **collect / scrape / fetch raw data** for Chinese A-share and raw-material workflows, including:

- domestic commodity futures quotes, minute lines, or daily K-lines;
- A-share index quotes;
- A-share industry/concept board daily history;
- A-share industry/concept board-name listing and keyword search;
- Eastmoney finance news;
- WallstreetCN live news;
- exporting collected rows as JSON, JSONL, or CSV.

## Installed command

After running `install.sh`, the collector is installed at:

```bash
$HERMES_HOME/scripts/a_share_data_collector.py
```

The Python environment is installed at:

```bash
$HERMES_HOME/venvs/a_share_data/bin/python
```

## Common commands

### Commodity futures quotes

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source commodity-quotes \
  --symbols 白银连续,液化石油气连续,碳酸锂连续 \
  --format json
```

### Commodity minute lines

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source commodity-minline \
  --symbols 白银连续,液化石油气连续 \
  --format jsonl \
  --output /tmp/commodity_minline.jsonl
```

### Commodity daily K-lines

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source commodity-daily \
  --symbols 碳酸锂连续,鸡蛋连续 \
  --format csv \
  --output /tmp/commodity_daily.csv
```

### A-share board daily moves

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source board-history \
  --boards 电池,锂电池概念,贵金属,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10 \
  --format json
```

The collector tries 同花顺 industry first and concept second by default. Override with `--board-type industry` or `--board-type concept` when you already know the board type.

### A-share board-name listing and search

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --list-boards industry \
  --format csv

$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --search-board 锂 \
  --format json
```

`--search-board` defaults to searching both industry and concept boards unless `--list-boards industry|concept` narrows the type.

### Index quotes

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source index-quotes \
  --format json
```

### News

```bash
$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source news-eastmoney \
  --format jsonl

$HERMES_HOME/venvs/a_share_data/bin/python \
  $HERMES_HOME/scripts/a_share_data_collector.py \
  --source news-wscn \
  --format jsonl
```

## Data sources

- Sina Finance:
  - `hq.sinajs.cn` for commodity futures quotes and A-share index quotes;
  - `InnerFuturesNewService.getMinLine` for domestic commodity minute lines;
  - `InnerFuturesNewService.getDailyKLine` for domestic commodity daily K-lines.
- AKShare wrappers:
  - `stock_board_industry_index_ths` for 同花顺 industry board daily history;
  - `stock_board_concept_index_ths` for 同花顺 concept board daily history.
- Eastmoney:
  - `np-listapi.eastmoney.com/comm/web/getNewsByColumns` for finance news.
- WallstreetCN:
  - `api-prod.wallstreetcn.com/apiv1/content/lives` for live news.

## Default commodity universe

When `--symbols` is omitted, the collector uses the built-in domestic commodity continuous-futures universe verified against Sina quotes. It currently covers 74 contracts across SHFE/INE, GFEX, DCE, and CZCE, including metals, black commodities, energy/chemicals, shipping index, new-energy materials, and agricultural products.

Pass `--symbols name=code,...` to override or narrow the universe for one run.

## Collection frequency guidance

This skill does not schedule jobs by itself. Suggested polling cadence for downstream systems:

- commodity quotes: every 1-5 minutes during futures trading sessions;
- commodity minute lines: every 5-15 minutes, or once after a target window closes;
- board daily history: once after A-share close, or on demand for historical ranges;
- A-share index quotes: every 1-5 minutes during A-share trading hours;
- news/livenews: every 5-15 minutes if monitoring events.

Respect each public data source's terms of service and rate limits.

## Output schema

Rows are normalized into fields such as:

- `source`
- `dataset`
- `name`
- `code`
- `trade_date`
- `timestamp`
- `open`, `high`, `low`, `close`
- `pct_chg`
- `amplitude`
- `amount`, `volume`
- `title`, `body`, `url`
- `raw`

`raw` keeps source-specific payloads for later inspection.

## Pitfalls

1. Public web interfaces can fail, throttle, or change response shapes. Always keep raw payloads when debugging.
2. AKShare board lookup depends on the exact 同花顺 board name. If `auto` fails, try `--board-type industry` or `--board-type concept` with the exact board name.
3. Sina continuous futures symbols such as `nf_AG0` are continuous series for chart/data purposes, not tradable contract codes.
4. `pct_chg` for board history is calculated from the previous close available in the returned date range. Include at least one prior trading day before the day you want to compute.
