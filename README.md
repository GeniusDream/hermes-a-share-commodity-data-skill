# Hermes A-share Data Collection Skill

A **data-collection-only** Hermes skill and script pack for Chinese A-share / raw-material workflows.

This repository intentionally does **not** include:

- morning reports;
- evening reports;
- commodity → board link scoring;
- LLM audit;
- prediction validation;
- self-evolution / candidate promotion;
- investment conclusions.

It only installs a reusable Hermes skill plus a raw data collector that fetches public market/news data and exports normalized JSON/JSONL/CSV rows.

## What this repo installs

```text
.
├── install.sh
├── requirements.txt
├── scripts/
│   └── a_share_data_collector.py
├── skills/data-science/a-share-data-collection/
│   └── SKILL.md
└── tests/
    └── test_collector_core.py
```

After installation:

```text
$HERMES_HOME/scripts/a_share_data_collector.py
$HERMES_HOME/venvs/a_share_data/bin/python
$HERMES_HOME/skills/data-science/a-share-data-collection/SKILL.md
```

## Data sources

| Data | Source | Interface / wrapper | Notes |
|---|---|---|---|
| Domestic commodity futures quotes | Sina Finance | `https://hq.sinajs.cn/list=...` | Continuous futures quote snapshots such as `nf_AG0`, `nf_PG0`, `nf_LC0`. |
| Domestic commodity futures minute lines | Sina Finance | `InnerFuturesNewService.getMinLine` | Raw minute-level price/volume rows. |
| Domestic commodity futures daily K-lines | Sina Finance | `InnerFuturesNewService.getDailyKLine` | Daily OHLCV rows; script calculates pct change and amplitude when previous close is available. |
| A-share index quotes | Sina Finance | `s_sh000001`, `s_sz399001`, `s_sz399006` | Shanghai Composite, Shenzhen Component, ChiNext. |
| A-share industry board daily history | AKShare / 同花顺 | `stock_board_industry_index_ths` | Requires exact 同花顺 industry board name. |
| A-share concept board daily history | AKShare / 同花顺 | `stock_board_concept_index_ths` | Requires exact 同花顺 concept board name. |
| Finance news | Eastmoney | `np-listapi.eastmoney.com/comm/web/getNewsByColumns` | Raw news title/body/url rows. |
| Live news | WallstreetCN | `api-prod.wallstreetcn.com/apiv1/content/lives` | Raw live-news rows from configured channels. |

## Suggested collection frequency

This repository does not create scheduled jobs automatically. If you wire it into cron / Hermes cron / Airflow / another scheduler, common frequencies are:

| Dataset | Suggested cadence |
|---|---:|
| Commodity quote snapshots | Every 1-5 minutes during futures trading sessions. |
| Commodity minute lines | Every 5-15 minutes, or once immediately after your target window closes. |
| Commodity daily K-lines | Once per day after settlement / session close, or on demand for backfills. |
| A-share index quotes | Every 1-5 minutes during A-share trading hours. |
| A-share board daily history | Once after A-share close, or on demand for historical ranges. |
| Eastmoney / WallstreetCN news | Every 5-15 minutes for event monitoring. |

Please respect each public data source's terms of service and rate limits.

## Install

```bash
git clone https://github.com/GeniusDream/hermes-a-share-market-data-pack.git
cd hermes-a-share-market-data-pack
./install.sh --test
```

Install into another Hermes profile:

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --test
```

## Usage examples

### Commodity quotes

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-quotes \
  --symbols 白银连续,液化石油气连续,碳酸锂连续 \
  --format json
```

### Commodity minute lines

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-minline \
  --symbols 白银连续,液化石油气连续 \
  --format jsonl \
  --output /tmp/commodity_minline.jsonl
```

### Commodity daily K-lines

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-daily \
  --symbols 碳酸锂连续,鸡蛋连续 \
  --format csv \
  --output /tmp/commodity_daily.csv
```

### A-share board daily history / daily moves

Include at least one prior trading day so `pct_chg` and `amplitude` can be calculated against previous close.

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source board-history \
  --boards 电池,锂电池概念,贵金属,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10 \
  --format json
```

If the automatic industry/concept lookup fails, specify the board type:

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source board-history \
  --board-type concept \
  --boards 锂电池概念,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10
```

### A-share index quotes

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source index-quotes \
  --format json
```

### News

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source news-eastmoney \
  --format jsonl

~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source news-wscn \
  --format jsonl
```

## CLI reference

```bash
python a_share_data_collector.py \
  --source commodity-quotes|commodity-minline|commodity-daily|index-quotes|board-history|news-eastmoney|news-wscn|all \
  [--symbols 白银连续,nf_PG0,自定义=自定义代码] \
  [--boards 电池,锂电池概念] \
  [--board-type auto|industry|concept] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--format json|jsonl|csv] \
  [--output /path/to/file]
```

## Output schema

Each row is normalized to a common shape:

```json
{
  "source": "sina",
  "dataset": "commodity_quote",
  "name": "白银连续",
  "code": "nf_AG0",
  "trade_date": "2026-06-11",
  "timestamp": null,
  "open": 123.0,
  "high": 125.0,
  "low": 121.0,
  "close": 124.0,
  "pct_chg": 1.23,
  "amplitude": 3.21,
  "amount": null,
  "volume": null,
  "title": null,
  "body": null,
  "url": null,
  "raw": {}
}
```

`raw` preserves source-specific payloads for debugging or downstream parsing.

## Test

```bash
bash -n install.sh
python3 -m py_compile scripts/a_share_data_collector.py
PYTHONPATH=scripts python3 -m pytest tests -q
```

Or run the installer test in an isolated temp Hermes home:

```bash
tmp=$(mktemp -d)
HERMES_HOME="$tmp" ./install.sh --test
```

## Notes

- Continuous futures symbols like `nf_AG0` are for continuous chart/data series, not tradable contract codes.
- Public web interfaces can fail or change; keep `raw` payloads and retry conservatively.
- This repo is a data collection utility, not an investment recommendation system.

## License

MIT
