# Downstream board history expansion for A-share chain scoring

Use this reference when extending A-share commodity-to-downstream historical scoring with Eastmoney/AKShare board history.

## Session-tested pattern

The historical board source should cover the main downstream sectors that receive commodity price transmission. Keep the mapping explicit and versioned in the collection script, e.g. a `BOARD_HISTORY_SYMBOLS`-style list with:

- BK code
- Chinese display name
- board type/source type, such as industry vs concept
- chain rationale if useful for later maintenance

A validated expansion included 26 boards across core industrial chains:

Industry boards:

- BK0437 煤炭行业
- BK0479 钢铁
- BK0478 有色金属
- BK1027 小金属
- BK1626 稀土
- BK1031 光伏设备
- BK0546 玻璃玻纤
- BK1019 化学原料
- BK0471 化学纤维
- BK0481 汽车零部件
- BK1200 电力设备
- BK0739 工程机械
- BK1242 家电零部件Ⅱ
- BK1208 建筑材料
- BK0476 装修建材
- BK1419 煤化工
- BK0464 石油石化
- BK1265 包装印刷
- BK1032 风电设备
- BK1030 电机Ⅱ
- BK0457 电网设备
- BK1408 机器人

Concept boards:

- BK0578 稀土永磁
- BK0900 新能源车
- BK1175 玻璃基板
- BK1090 机器人概念

Do not assume these codes are permanently complete; re-probe live Eastmoney/AKShare before broad future changes.

## Collector behavior to preserve

1. Bound history windows explicitly, such as recent 31 calendar days, instead of all-history defaults.
2. Use direct/no-proxy Eastmoney calls where global proxy variables interfere.
3. Fetch each board independently.
4. If one board fails, record/log that board failure and continue collecting the rest.
5. Mark the entire board-history source failed only if all boards fail.
6. Before backfilling a historical window, delete stale `akshare_board_history` rows whose board symbol is no longer in the maintained mapping. This prevents old wrong type/name/BK combinations from remaining in the quote table and contaminating scoring.

## Verification checklist

After changing board coverage, verify all of the following:

- Unit/regression test that required downstream boards are present in the mapping.
- Unit/regression test that one board failure does not abort the whole board-history source.
- Syntax check for the collection script.
- `--test-history --history-days 31` returns ok and shows expected row counts/date ranges.
- `--backfill-history --history-days 31` persists rows.
- Database query confirms expected board count by source/type and confirms no stale symbols remain from old mappings.
- Current-day `--test-interfaces` still succeeds.
- Full main collection flow still succeeds.

## Reporting convention

When reporting this class of work to the user, emphasize:

- which board universe was added,
- row counts/date coverage after backfill,
- that partial board failures are isolated,
- that stale mapping rows are cleaned,
- and that daily-report text remains focused on strong current correlations rather than backend mapping details.
