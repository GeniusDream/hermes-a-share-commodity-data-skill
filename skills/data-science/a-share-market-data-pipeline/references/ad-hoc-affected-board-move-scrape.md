# Ad-hoc affected-board move scrape for commodity anomaly lists

Use this when the user provides a small list of commodity night-session moves and asks to “爬取潜在受影响板块的当日变化”.

## Goal

Return board/index-level A-share moves for the specified dates and affected sectors, not individual stocks. Keep the result concise and human-facing.

## Preferred data path

1. Check local PostgreSQL `market_quotes` first for already-collected `akshare_board_history` rows when the requested dates/boards are covered.
2. If the maintained board-history universe is too narrow for the ad-hoc board list, use Tonghuashun board index history through AKShare:
   - Industry boards: `ak.stock_board_industry_index_ths(symbol=..., start_date='YYYYMMDD', end_date='YYYYMMDD')`
   - Concept boards: `ak.stock_board_concept_index_ths(symbol=..., start_date='YYYYMMDD', end_date='YYYYMMDD')`
3. Set `NO_PROXY='*'` for Tonghuashun/Eastmoney-style probes when the host has global proxy variables that can disturb Chinese market-data endpoints.
4. Fetch at least the previous trading day plus the target day, then compute the displayed day move as:
   - `pct_chg = target_close / previous_trading_day_close - 1`
   - Do not infer it from intraday amplitude.

## Useful Tonghuashun board names seen in practice

Industry examples:

- `贵金属`, `工业金属`, `光伏设备`
- `燃气`, `石油加工贸易`, `化学原料`, `化学制品`
- `小金属`, `半导体`, `电子化学品`
- `能源金属`, `电池`
- `养殖业`, `食品加工制造`, `农产品加工`

Concept examples:

- `黄金概念`, `光伏概念`, `TOPCON电池`
- `天然气`, `丙烯酸`
- `新能源汽车`, `锂电池概念`, `固态电池`
- `养鸡`, `食品安全`

If a human board label does not exist exactly in THS, map it to the closest board-level proxy and label it honestly, e.g. `LPG/燃气` → `燃气` + `天然气`; `PDH 化工` → `丙烯酸`/chemical boards when appropriate.

## Output pattern

For each target date, group by the upstream commodity and list affected boards with percent changes. Then add a short observation separating:

- 同向反馈: commodity move and board move aligned;
- 反向/未跟随: commodity moved but board did not follow;
- 可能被其他因素覆盖: broad market, technology theme, risk appetite, or sector narrative dominated the commodity signal.

Avoid individual-stock evidence in the user-facing answer.