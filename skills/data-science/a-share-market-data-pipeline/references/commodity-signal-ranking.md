# Commodity signal ranking for A-share raw-material reports

## Lesson from the 2026-06 ranking correction

For this user's morning/evening raw-material reports, the first-layer ranking object is the upstream commodity move itself, not the commodity→A-share chain.

Correct workflow:

1. Rank raw-material commodity signals.
2. For the ranked commodities, scan same-family A-share board responses.
3. Use historical correlation, validations, candidate promotion, and LLM review only in the chain-validation layer.

Do not mix downstream A-share feedback or chain hit-rate into the first-layer commodity anomaly ranking. That creates selection bias: historically responsive chains get surfaced even when the current commodity signal is weak, while new or sample-poor raw-material signals may be hidden.

## Ranking objective

The commodity anomaly section should be an upstream price-signal radar:

- capture clear directional raw-material changes;
- normalize against each commodity's own historical behavior when possible;
- prefer sustained moves that close near the direction of travel;
- keep core raw-material research variables visible;
- avoid promoting noisy high-amplitude reversals.

## Preferred factors

Use a commodity signal score shaped like:

- directional window return: main factor;
- self-history percentile or z-score: cross-commodity normalization when enough samples exist;
- close-location/trend quality: high for up moves closing near highs and down moves closing near lows;
- commodity research weight: higher for core, liquid,产业映射清晰 raw materials;
- amplitude: quality/noise modifier only, not a standalone additive factor.

A high-amplitude move that ends close to flat should be treated as noisy unless it also closes near the directional endpoint.

## Implementation pattern in the current pipeline

The shared implementation lives at:

`$HERMES_HOME/scripts/a_share_commodity_signal.py`

The report scripts should call this module instead of open-coding `abs(return) + amplitude` formulas:

- morning: `$HERMES_HOME/scripts/a_share_morning_prediction.sh`
- evening: `$HERMES_HOME/scripts/a_share_chain_daily.sh`

The window source should remain `commodity_window_moves`:

- morning: previous A-share day 15:00 to target day 09:30;
- evening: previous A-share day 15:00 to target day 15:00.

`market_quotes` current-day/open-relative fields can be displayed or used as fallback, but should not dominate the evening ranking when `commodity_window_moves` exists.

## Testing expectations

Keep regression tests around these behaviors:

- a directional core move such as 焦煤 -4% beats a large-amplitude but flat/reversal move;
- historical percentile boosts a self-significant commodity move;
- amplitude alone does not pass the material-move gate;
- core and expanded pools remain separated, but core-pool internal order follows the signal score.

Current test file:

`$HERMES_HOME/scripts/tests/test_a_share_commodity_signal.py`

## User-facing wording

When explaining the ranking, say:

"商品异动排序是原材料商品信号排序，不是链条排序。先按商品自身的方向性窗口收益、历史分位、趋势质量和品种研究权重发现上游信号，再看A股板块反馈和链条验证。"

Avoid saying that the commodity anomaly list is sorted by downstream performance, LLM verdict, candidate score, or historical prediction hit-rate.
