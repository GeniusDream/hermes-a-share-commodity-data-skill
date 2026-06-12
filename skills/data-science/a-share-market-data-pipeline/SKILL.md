---
name: a-share-market-data-pipeline
description: "Build, debug, and verify Chinese A-share market-data pipelines, especially AKShare/Eastmoney/Sina-backed daily reports."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [a-share, market-data, akshare, eastmoney, sina, data-pipeline, debugging]
---

# A-share Market Data Pipeline

## When to use

Use this skill when working on Chinese A-share daily-report data collection, historical backfills, AKShare/Eastmoney/Sina interfaces, commodity-to-equity chain transmission data, or data-source reliability checks.

## Core principles

1. Verify with live probes before claiming an interface works or fails.
2. Separate these layers in the conclusion:
   - library wrapper behavior, such as AKShare parameter defaults;
   - upstream data endpoint behavior, such as Eastmoney disconnecting large requests;
   - local runtime environment, such as proxy variables;
   - script logic, such as symbol-name-to-code mapping.
3. Prefer concise, human-facing conclusions for the user, but keep exact errors and probe commands in references or logs.
4. For daily-report work, do not dump backend self-evolution diagnostics by default. The user's current evening-report preference is to include a compact “潜力候选链路与晋升/降级观察” section: show only higher-potential candidate links and meaningful promotion/demotion/LLM rejection signals, while keeping raw candidate/link_experience tables out of the report.
5. For raw-material/night-session A-share reports, the research object is all affected boards, not only downstream manufacturing. Include supply/resource, midstream materials, downstream manufacturing/consumption, and related concept boards when evidence supports them, but label the pathway type explicitly.

## AKShare / Eastmoney historical data checklist

Before deciding AKShare historical data is broken:

1. Print versions and proxy state:
   - `akshare.__version__`
   - `requests.utils.get_environ_proxies(url)`
   - `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`
2. Test the raw Eastmoney endpoint with `requests` and `curl`.
3. Test both proxied and direct/no-proxy paths.
4. Test a small explicit date range before testing all-history defaults.
5. For board/sector history, test both Chinese names and direct BK codes.
6. Record row counts, date ranges, and exact exceptions.

## Durable AKShare/Eastmoney lessons

- Do not call historical AKShare endpoints with broad defaults when only recent history is needed. Always pass explicit `start_date` and `end_date`.
- Eastmoney `push2his` endpoints may close connections on very large ranges, while the same endpoint succeeds for near-term ranges.
- Proxy variables can break Eastmoney historical endpoints through `requests`; test or configure `NO_PROXY` for Eastmoney before blaming AKShare.
- Eastmoney `push2his` may also fail on IPv6/CDN routes with `RemoteDisconnected` / empty reply while IPv4 sometimes succeeds. Probe `curl -4 --noproxy '*'` versus default DNS, and consider a scoped IPv4-only resolver context for Eastmoney-backed AKShare calls.
- If Eastmoney history is unstable, add source-specific fallbacks rather than just increasing retries: Tencent index history (`stock_zh_index_daily_tx`) can replace index history; Tonghuashun board index history (`stock_board_industry_index_ths`) can cover a maintained subset of industry boards while preserving the original BK code in stored rows.
- Use BK codes directly when possible instead of relying on AKShare's live Chinese-name-to-code lookup.
- AKShare period parameters can differ by endpoint:
  - industry board history: `period='日k'`
  - concept board history: `period='daily'`

## Recommended collection-script pattern

1. Maintain a local mapping table for important board names to BK codes.
2. For historical pulls, compute bounded dates, for example recent 31 calendar days or needed trading window.
3. Use direct/no-proxy settings for Eastmoney domains if the environment has global proxies.
4. Add retry with bounded backoff.
5. Add fallback from AKShare wrapper to direct Eastmoney `requests` for critical endpoints.
6. Store probe metadata with each run: source, status, rows, attempts, latency, error.
7. Give the script separate modes for current-day collection, history interface tests, and history backfills; do not make operators edit code to switch modes.
8. Persist historical rows into the same quote table with source-specific labels, so scoring/correlation code can reuse the same query path while still distinguishing live snapshots from backfilled history.

## Quick commodity / board information queries

When another window needs to answer “某个商品/板块有没有被早晚报采到、涨跌幅是多少、映射到哪些链路、为什么进/没进报告”, use this skill before ad-hoc web search.

Primary query path:

1. Check PostgreSQL availability with `$HERMES_HOME/a_share_daily_db/docker-compose.yml`.
2. Query stored cutoff-window commodity moves in `commodity_window_moves` first. This answers the report-window question and avoids after-cutoff realtime contamination.
3. Query board/index rows in `market_quotes` for A-share board行情 and historical coverage.
4. Query official mappings in `link_mappings` before saying a commodity has no mapped affected boards.
5. Query `link_scores.evidence` and LLM verdict fields to explain why a mapped chain did or did not appear in the report.
6. Query `candidate_links` only as hypothesis/watchlist evidence, not as confirmed transmission.
7. Inspect `$HERMES_HOME/scripts/a_share_commodity_universe.py` when the question is whether a commodity belongs to the core pool or expanded anomaly radar.
8. For an ad-hoc user-provided commodity anomaly list, if local `market_quotes` does not cover all affected boards, use Tonghuashun industry/concept index history via AKShare, fetch previous trading day + target day, and compute board `pct_chg` from close-to-close. Keep the output board-level only and separate 同向反馈 from 反向/未跟随 signals.

Use `references/commodity-board-query-playbook.md` for ready-to-copy SQL and command examples. Use `references/ad-hoc-affected-board-move-scrape.md` for the Tonghuashun fallback recipe and board-name examples.

## Historical backfill implementation pattern

A proven A-share daily pipeline shape is:

- `--test-history`: run historical interfaces only and record source health.
- `--backfill-history`: fetch and persist historical quotes without generating a full report.
- `--history-days`, `--start-date`, `--end-date`: explicitly bound the window.
- Current-day main flow may call history backfill first, then live snapshots, then scoring; this lets correlation/lag scoring improve without a separate manual step.
- Use source names such as `sina_futures_history`, `akshare_index_history`, and `akshare_board_history` rather than overwriting live-source provenance.

## Board-history expansion pattern

When adding downstream boards for commodity-to-equity chain scoring:

1. Treat board coverage as a maintained mapping, not an ad-hoc scrape. Include both industry and concept BK codes for important downstream chains.
2. Probe Eastmoney/AKShare live to confirm Chinese board name, BK code, board type, row count, and date range before adding it.
3. For board-history collectors, isolate per-board failures: one broken or renamed BK code should be logged/skipped while the rest of the board universe continues. Only fail the whole source if every board fails.
4. Add stale-row cleanup for `akshare_board_history` before rewriting a historical window. Delete rows for board symbols no longer present in the maintained mapping so old name/type/BK mistakes do not silently remain in scoring data.
5. Add regression tests for both mapping coverage and partial-failure behavior before relying on the expanded universe in daily reports.
6. Keep the daily report concise: use the expanded historical universe to improve correlation/lag scoring, but do not print the full backend board universe unless the user asks for diagnostics.

## Verification output shape

When reporting to the user, include:

- What was tested;
- Which interfaces succeeded/failed;
- Row counts and date ranges for successes;
- Exact root cause class for failures;
- Specific script changes recommended or made.

## Explaining lag/correlation scores in daily reports

When the user asks how a phrase such as `历史相关倾向：A股交易日T+1、市场调整Pearson-0.56，Spearman-0.45，n=22，样本对=甲醇连续×石油石化` was calculated, ground the answer in the actual scoring code and database rows rather than giving a generic statistics explanation.

1. Check `link_scores` for the report date and link: `best_lag`, `best_corr`, `corr_score`, and `evidence`.
2. Check `link_scores.evidence->'correlation'` for the winning upstream/downstream pair, sample size, raw Pearson, market-adjusted Pearson, market-adjusted Spearman, expected relation, direction match, and lag basis.
3. Check `link_mappings` for `upstream_names`, `downstream_patterns`, configured `lag_days`, and `expected_relation`.
4. Explain that `T+N` is selected from the configured candidate lags, not every possible lag, and is aligned by A-share trading days: `T+1` means the next available A-share trading day.
5. Explain that `best_corr` is the market-adjusted Pearson correlation over paired historical `pct_chg` samples, with downstream board returns adjusted by an available broad-market index; combinations with fewer than 20 valid pairs are ignored by default (`A_SHARE_MIN_CORR_SAMPLES`).
6. Explain that Spearman is stored/displayed as a robustness check and the winner records the exact upstream×downstream pair rather than only the aggregate chain.
7. Include the practical caveat: this is historical sample correlation, not causal proof; negative correlation on cost chains may indicate upstream cost pressure,价差修复, demand weakness, or sentiment transmission only when industry logic supports it.

See `references/lag-correlation-scoring.md` for the reproduction recipe, formula, caveats, and improvement ideas.

## Reporting historical-refresh fallback accurately

When a daily report says a historical interface failed but the report still produced lag/correlation scores, be precise about what was reused:

1. Do not say the script used "existing link scores" unless you verified it literally copied prior `link_scores` rows.
2. Prefer: "some historical quote interfaces failed this run; the report used the database's last successful historical quote samples plus today's live quotes/news to recompute today's link scores."
3. Verify the distinction with database timestamps before explaining it:
   - `market_quotes`: group by `source`, count rows, min/max `trade_date`, min/max `updated_at`.
   - `link_scores`: check today's `created_at`, `best_lag`, `best_corr`, `corr_score`, and `llm_reviewed_at`.
   - `source_status`: check which source failed for the current `run_date` and the exact error.
4. Explain "first official run" vs "existing samples" explicitly: cron delivery may be the first official run while development/test backfills have already populated the same local database.
5. In user-facing report wording, call these "历史行情/历史报价接口" rather than vague "历史接口" when confusion is likely.

## Commodity anomaly ranking: commodity first, chain later

For the user's A-share morning/evening reports, the commodity-anomaly section is an upstream raw-material signal radar, not a commodity→A-share chain ranking. First rank raw-material commodities by their own directional window return, self-history percentile/z-score when available, close-location/trend quality, and commodity research weight. Keep amplitude as a noise/quality modifier only; do not use bare `abs(return)+amplitude` as the main cross-commodity score. Do not include A-share board feedback, historical prediction hit-rate, LLM verdicts, or candidate-link scores in the first-layer commodity selection; those belong to the later board-response and chain-validation layers. See `references/commodity-signal-ranking.md` for the implementation pattern and regression-test expectations.

## Daily report scope: all raw-material affected boards

When maintaining A-share raw-material/night-session reports, use the scope `夜盘原材料 → A股受影响板块`, not a narrow `原材料 → 下游制造` scope.

### Core pool + expanded anomaly radar

The current implementation centralizes the commodity universe in `$HERMES_HOME/scripts/a_share_commodity_universe.py`.

- Core pool: copper, aluminum, rebar, hot-rolled coil, iron ore, coking coal, soda ash, glass, Shanghai crude oil, methanol, plus key international mappings such as LME copper/aluminum/nickel, NY crude oil, and gold. These feed the main morning/evening conclusions.
- Expanded anomaly radar: zinc, lead, nickel, tin, alumina, stainless steel, industrial silicon, lithium carbonate, gold/silver, coke, ferroalloys, fuel oil/LSFO/bitumen/LPG, PTA/PX/MEG/styrene/PVC/PP/plastics/short fiber/urea/caustic soda, rubber series, and agriculture/consumer raw materials such as meal/oils/corn/cotton/sugar/hog/egg. These feed discovery, watchlists, and candidate promotion rather than automatically becoming formal transmission conclusions.
- A verified Sina probe on this host showed the expanded domestic symbols return both `hq.sinajs.cn` quotes and `InnerFuturesNewService.getMinLine` rows. If adding more commodities, first probe both interfaces and then add family keywords/impact mapping in the universe file.
- Reporting rule: expanded-pool moves can be printed in “商品异动” with an `扩展雷达` label, but enter formal transmission review only after commodity move + same-family A-share board feedback + news/logic or accumulated historical/LLM validation.


1. Include upstream supply/resource boards, midstream processing/material boards, downstream manufacturing/consumption boards, and related concept/theme boards when the commodity move plausibly affects price, inventory, margin, demand expectations, risk appetite, or industry narrative.
2. Do not downgrade or reject boards such as `煤炭开采加工`, `煤炭行业`, `有色资源`, `石油石化`, or `钢铁` merely because they are supply-side or material-side rather than downstream.
3. Do label the pathway type in user-facing text and LLM audit reasons: `资源端/供给端同向反馈`, `中游材料/加工价差`, `制造端成本压力/成本缓和`, `需求端/题材端验证`, or `宏观/避险/风险偏好传导`.
4. Rename chains that mix pathway levels so they do not imply all mapped boards are downstream. Example: prefer `黑色原料 → 煤炭/钢铁/基建机械/制造` over `黑色链 → 基建/机械/汽车/家电` when coal and steel are part of the evidence.
5. For self-evolution and candidate promotion, require same-industry-family evidence between commodity and board/news even though the scope is broad. This prevents broad upstream keyword matches from promoting noise such as `焦煤 → 半导体/其他电子`.

See `references/affected-board-scope.md` for examples, naming rules, and LLM audit guidance.

## Daily report prediction-validation wording pitfall

The user's A-share commodity-transmission analysis and chain reports are board-level only; do not use or display individual stocks in user-facing analysis. AKShare fund-flow board rows expose `领涨股` / stock fields, but these are not part of the report's evidence model. Morning-prediction validation, link scoring, candidate evidence, and daily-report wording should rely on board/index names and board `pct_chg` only.

## Daily report structure: avoid duplicate chain conclusions

When optimizing the A-share daily report content, check whether two sections are drawing from the same intermediate evidence before keeping both. A proven failure mode is:

- `link_scores` feeds `db_strong_links()`;
- `db_strong_links()` returns short core-conclusion lines;
- the same function also fills `PROPAGATION_LINES` for "昨日夜盘/今日商品异动 → 今日A股传导复盘".

If both sections are derived from the same scored links, do not present them as independent conclusions. Prefer keeping the richer transmission-review section and deleting or repurposing the short "今日核心结论" section. When keeping the transmission-review section:

1. Deduplicate upstream/downstream evidence by display name before printing, because scoring evidence can contain repeated sources for the same commodity or board.
2. Keep the section focused on confirmed commodity/night-session → A-share mappings, and format each chain with explicit `证据` and `链路分析` lines. Evidence should include raw-material night/day moves, affected A-share board moves, event/news clues when available, and lag/correlation. When showing correlation, explicitly explain the sign: positive correlation means historical same-direction movement; negative correlation means historical reverse movement and should be interpreted through cost pressure, spread/margin repair, demand weakness, or sentiment only when industry logic supports it. Chain analysis should label pathway type and explain why the evidence supports or weakens the transmission.
3. Avoid adding a separate "core conclusion" unless it is genuinely synthesized from a different source or adds a materially different decision layer.
4. Re-run the full report script and assert the removed section is absent while the transmission-review section remains present.
5. Keep backend candidate/self-evolution chains out of the user-facing transmission-review section unless they have strong statistical/LLM support. In particular, do not print `候选晋升链路` rows with insufficient history as if they were confirmed daily transmission chains; leave them in the backend experience/candidate tables.

## Self-evolution closure for recurring A-share reports

When the user asks to improve the report's self-evolution/learning loop, implement it as a verified backend closure rather than adding verbose text to the daily report.

1. Separate confirmed evidence from hypotheses:
   - `link_validations` stores realized validation events;
   - `link_experience` is aggregated only from validation outcomes;
   - LLM audit notes or `experience_notes` go to a separate hypothesis table such as `link_hypothesis_notes`.
2. Run closure before rendering the report: score links, run LLM audit, validate accepted same-day links (`expected_lag = 0` for T+0 review), refresh experience, promote repeated candidates, then generate user-facing text.
3. Candidate promotion should be conservative and auditable: require repeated sightings/non-rejected status, insert into official `link_mappings`, store the promoted id, and mark the candidate as promoted.
4. If morning predictions participate in the loop, sync them into a structured table and use historical precision only as a confidence/priority adjustment for future morning reports.
5. For resets or regenerations, verify syntax and create a timestamped backup first; if a destructive DB clear is denied by approval tooling, stop immediately and report the blocker rather than retrying the same outcome another way.
6. When a reset follows schema changes, run the collector's schema-init path first (for this pipeline, `a_share_market_db.py --promote-candidates` is a safe way to call `ensure_schema()` without collecting data) and inspect that expected new tables exist before issuing a multi-table `TRUNCATE`. Otherwise the truncate can fail on a missing newly-added table while adjacent non-transactional file resets still run.
7. Keep destructive DB reset commands transactionally scoped and verification-oriented: backup with `pg_dump`, reset/truncate only intended data and analysis tables while preserving stable seed mappings when appropriate, query post-reset counts, then reset sidecar JSON files.
8. If regenerating both reports after a reset, run the morning report before the evening report so `morning_predictions`/`prediction_experience.json` exists for the evening validation section; then verify DB counts, key report sections, and Feishu send results.
9. Before promising Feishu delivery, preflight messaging availability with `send_message(action='list')` or the gateway's target listing. If Feishu/gateway targets are not connected or discoverable, still generate and verify the reports locally when appropriate, but report the delivery blocker explicitly instead of implying the send succeeded.
10. Candidate discovery must guard against global-news keyword contamination: require the A-share board itself to match the same commodity/industry family before creating or displaying a high-potential candidate. Do not let broad same-day news text promote unrelated strong theme boards into candidates.

See `references/self-evolution-closure.md` for table roles, implementation sequence, verification checks, and destructive-reset cautions.

## Delivered-report verification and replay pitfalls

When the user asks about the “latest report” or corrects that the visible Feishu/QQBot report differs from local cron output, verify the delivered message, not only `~/.hermes/cron/output/...`.

### Cutoff-window architecture for replayable reports

When a report can be regenerated after its official cutoff, split data collection from analysis. The collector should fetch external sources and upsert/de-duplicate raw/current rows and precomputed window rows into PostgreSQL; the report renderer/analyzer should only read database rows filtered by target `report_type`, `target_date`, and the explicit cutoff window. Do not let manual reruns call live quote/minute endpoints directly inside rendering code.

For the current A-share commodity pipeline, the proven pattern is in `references/cutoff-window-collection-analysis-split.md`: `a_share_market_db.py --collect-only` writes `market_quotes`, `news_items`, and `commodity_window_moves`; `--analyze-only` reads existing DB rows for scoring/candidates; morning/evening scripts render from DB windows rather than live endpoints.

1. Distinguish three artifacts explicitly:
   - script stdout saved under `~/.hermes/cron/output/<job_id>/...`;
   - cron delivery wrapper/content actually sent through the gateway;
   - later manual redeliveries or regenerated reports sent to Feishu/QQBot.
2. If the question is about “latest sent to Feishu”, inspect the messaging side before concluding. Use gateway/Feishu message history when available, or the platform API with tenant token and the known chat/open_id to list recent bot messages; flatten Feishu `post` message JSON to compare user-visible sections.
3. Beware manual reruns after the cutoff. A report whose title says 08:50 or 15:00 can be regenerated at 23:40+ and accidentally read current Sina realtime/minute data from a later night session. Treat this as window contamination unless the report was generated from stored cutoff snapshots.
4. For morning reports, enforce the cutoff window “previous A-share day 15:00 to current day 09:30”; for evening reports, enforce “previous A-share day 15:00 to current day 15:00”. Manual regeneration should read database snapshots for the target report_date/cutoff, not live endpoints.
5. Commodity-anomaly display should not use a single global top-N where expanded radar品种 can crowd out core-pool variables. Prefer separate blocks or quotas: core-pool anomalies first/guaranteed, then expanded-radar discoveries; otherwise high-volatility expanded品种 such as 白银/LPG/锡 can hide a major core-pool焦煤 move even while the formal transmission section still references it.
6. When explaining ranking, separate “commodity radar ranking” from “formal transmission review”. A commodity may be absent from the anomaly list but still appear in confirmed transmission evidence; that is a report-UX/ranking issue, not necessarily a missing链路评分 issue.
7. From a quant-research perspective, flag bare `abs(return)+amplitude` cross-commodity ranking as a rough engineering radar only. The current implementation uses `$HERMES_HOME/scripts/a_share_commodity_signal.py` for upstream commodity discovery: rank raw-material commodities first by directional window return, self-history percentile when available, close-location/trend quality, and commodity research weight; amplitude is only a noise/quality modifier rather than a main additive factor. Keep A-share same-family feedback, historical validation, and LLM review in the later chain-validation layer, not in the first-layer commodity anomaly ranking.

## Dynamic data-source status wording for daily reports

When changing a recurring A-share daily report's status/reminder copy, make the copy data-driven from run state instead of static reassurance or static alarm text:

1. Build separate facts before composing text:
   - failed `source_status` rows grouped into live/current sources vs historical quote sources;
   - available historical sample counts/date ranges/latest `updated_at` from `market_quotes` by source;
   - today's `link_scores` recomputation count, count with `best_lag`/`best_corr`, latest `created_at`, and latest `llm_reviewed_at`.
2. Compose different user-facing status lines for at least these cases:
   - all sources refreshed successfully: "全部数据源本次刷新成功。"
   - historical quote refresh failed but usable historical samples exist: state that the report recomputed today's scores using the last successful historical quote samples plus today's live quotes/news; do not imply stale `link_scores` were reused.
   - historical quote refresh failed and no usable historical samples exist: state that lag/correlation scoring may be missing or degraded.
   - live/current sources failed: state that today's行情/新闻 coverage may be incomplete.
3. Always include concise diagnostics under the status line: failed source names with attempts/rows/latency/error, historical sample counts/date ranges/latest write time, score recomputation count/time, and LLM audit completion time when present.
4. Keep this copy human-facing. Do not expose backend chain-experience tables or candidate-link self-evolution details unless the user asks for diagnostics.
5. Verify by running the report script and checking exit code plus the generated status block for both success and fallback cases when feasible.

See `references/dynamic-daily-status-copy.md` for a compact implementation recipe and example wording.

## References

- `references/akshare-eastmoney-debugging.md` — session-tested AKShare/Eastmoney failure modes and working call patterns.
- `references/history-backfill-pattern.md` — implementation details for adding bounded historical backfills to an A-share daily pipeline.
- `references/commodity-board-query-playbook.md` — ready-to-copy SQL/commands for querying commodity windows, board rows, official mappings, scored links, candidates, news clues, and maintained commodity universe metadata.
- `references/full-reset-and-candidate-watch.md` — reset/regenerate/send workflow and candidate-watch filtering pitfalls, including global-news keyword contamination.
- `references/evening-candidate-watch-and-reset.md` — session-derived rules for the evening candidate/promotion/demotion watch section plus the safe reset/regenerate/send workflow.
- `references/downstream-board-history-expansion.md` — board-universe expansion, partial-failure isolation, stale-row cleanup, and verification checklist for downstream historical board coverage.
- `references/dynamic-daily-status-copy.md` — implementation recipe and example wording for data-driven daily-report source-status messages.
- `references/self-evolution-closure.md` — table roles, sequence, verification, and reset cautions for the daily report's self-evolution loop.
- `references/affected-board-scope.md` — scope, naming, pathway labels, and audit rules for treating supply-side, midstream, downstream, and concept boards as raw-material affected boards.
- `references/cutoff-window-collection-analysis-split.md` — split collector/analyzer architecture, cutoff-window table pattern, core-first anomaly ranking, and verification checklist for replayable morning/evening reports.
- `references/commodity-signal-ranking.md` — upstream-first commodity anomaly ranking: directional window return, self-history significance, trend quality, research weight, and amplitude-as-noise rules.
