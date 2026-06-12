# Lag/correlation scoring in A-share chain reports

Use this when explaining report phrases such as `历史相关倾向：A股交易日T+1、市场调整Pearson-0.56，Spearman-0.45，n=22，样本对=甲醇连续×石油石化`.

## What the numbers mean

- `best_lag` is selected from the link's configured candidate `lag_days` array, not searched over every possible lag.
- Dates are aligned by A-share trading days, not calendar days. If a commodity date is not an A-share trading day, T+0 maps to the next available A-share trading day; T+1/T+3/T+5 are counted from the A-share trading-date sequence.
- `best_corr` is the market-adjusted Pearson correlation coefficient over paired historical percentage changes:
  - `x`: upstream commodity/security `pct_chg` on the upstream date;
  - `y`: matched downstream board/sector `pct_chg` on the lagged downstream date, adjusted by an available broad-market benchmark (`沪深300`/`中证全指`/`上证指数`/`深证成指` priority; missing benchmark dates treated as 0 adjustment).
- The report also stores/displayed `spearman_market_adjusted` as a robustness check against outliers and rank-only monotonic relationships.
- Samples with fewer than 20 valid pairs are ignored by default. The threshold is configurable through `A_SHARE_MIN_CORR_SAMPLES`.
- The winner is selected by adjusted correlation strength, sample-size factor, Spearman sign stability, and whether the sign matches `link_mappings.expected_relation` when that relation is configured.
- The winning pair is recorded in `link_scores.evidence->'correlation'`, including `upstream_name`, `downstream_name`, `lag`, `sample_size`, `pearson_market_adjusted`, `pearson_raw`, `spearman_market_adjusted`, `expected_relation`, and `direction_match`.
- `corr_score` is capped at 15 and discounts small samples, Spearman sign mismatch, and expected-direction mismatch.

## Verification recipe

1. Query the stored score first:
   - `link_scores`: `trade_date`, `link_id`, `link_name`, `best_lag`, `best_corr`, `corr_score`, `evidence`.
2. Inspect `link_scores.evidence->'correlation'` for the winning upstream/downstream pair, sample size, raw/adjusted correlations, and lag basis.
3. Query the mapping:
   - `link_mappings`: `upstream_names`, `downstream_patterns`, `lag_days`, `expected_relation`.
4. Reproduce the scan over:
   - each `upstream_names` entry;
   - current-day matched downstream boards/sectors from `downstream_patterns`;
   - each candidate lag in `lag_days`.
5. For each combination, map upstream dates to A-share trading-day lag dates, build pairs where both sides have `pct_chg`, subtract benchmark `pct_chg` from downstream returns, compute Pearson/Spearman, and compare by the same selection strength.

## Reporting caveats

When explaining to the user, avoid overstating the statistic:

- Say "candidate lags" or "configured lags" rather than "all possible lags".
- Say "A-share trading-day T+N" rather than calendar-day lag.
- Say it is a sample correlation / historical tendency, not proof of causality.
- If the chosen relation is negative, explain it as possible cost-pressure, spread/margin repair, demand weakness, or sentiment transmission only when it fits the industry logic.
- Include sample size and the winning upstream×downstream pair when available.

## Future improvement

For more rigorous A-share reporting, continue shifting the self-evolution layer from generic correlation toward event-study validation: when a commodity move/event is detected, record T+0/T+1/T+3/T+5 downstream abnormal returns and use confirmation rate, failure rate, average excess return, and direction consistency to refresh `link_experience`.
