# Evening candidate-watch section and reset/regeneration workflow

Session-derived notes for the A-share raw-material affected-board reports.

## Evening report candidate-watch preference

The evening report should remain concise, but it should include a compact section named roughly:

`潜力候选链路与晋升/降级观察`

Purpose:
- Surface emerging commodity → A-share affected-board chains early, before they become fully confirmed mappings.
- Show promotion/demotion/rejection signals so the user can both notice opportunities and avoid noisy links.
- Avoid dumping all backend `candidate_links`, `link_experience`, schema state, or raw diagnostics.

Recommended content filter:
1. Candidate observations:
   - recent `watch`/`proposed` candidates;
   - repeated sightings or strong rule/LLM evidence;
   - same-industry-family evidence between commodity, board, and/or news;
   - exclude reasons containing noise markers such as `噪声`, `误命中`, `无产业`, `无清晰`, `剔除`, `已禁用`.
2. Promotion observations:
   - show only promoted links that pass same-industry-family screening;
   - if promoted links are cross-industry or theme-only, do not present them as promising; move them to demotion/rejection reminders.
3. Demotion/rejection reminders:
   - show high rule-score links that LLM downgraded/rejected;
   - useful for排雷, e.g. commodity keyword hits into semiconductor/AI themes with no price/cost/inventory transmission.

Suggested wording:

`说明：本节只筛选近期反复出现、规则/LLM证据较强、或当日被明显上调/下调的链路；不是确认结论，用于提前关注和排雷。`

Example item shapes:
- `候选观察：原油/甲醇 → 化纤/塑料制品/化工行业｜出现2次；证据：...；关注：...`
- `晋升观察：...｜候选出现N次后晋升；当日中/高置信；下一步看T+0/T+1后验验证。`
- `剔除提醒：...｜原规则分85，调整-25；原因：...`

## Reset/regenerate workflow

When the user asks to clear historical DB contents and regenerate reports:

1. Treat it as destructive. Do not clear anything until a backup command actually succeeds.
2. Preflight schema/reset scope:
   - preserve stable seeded `link_mappings` unless the user explicitly wants to rebuild mappings from scratch;
   - clear generated/analysis tables such as `market_quotes`, `news_items`, `link_scores`, `source_status`, `candidate_links`, `link_validations`, `link_experience`, `link_hypothesis_notes`, `morning_predictions`;
   - reset sidecar `prediction_experience.json` after backing it up.
3. Backup first:
   - full PostgreSQL dump under `~/.hermes/a_share_daily_db/backups/`;
   - copy `prediction_experience.json` with the same timestamp if present.
4. If the command approval/safety layer denies a destructive or backup/reset command, stop immediately and report the blocker. Do not retry with a rephrased command or alternative route in the same turn.
5. After a successful reset, regenerate in order:
   - ensure PostgreSQL is running and schema is initialized;
   - run the morning report script so today’s predictions are captured from the clean sidecar;
   - run the evening chain report, which performs collection, history refresh, scoring, LLM audit, validation, and candidate promotion before rendering;
   - verify row counts, source status, report sections, and send results.

## Verification checklist

Before telling the user the new version is active:
- Syntax check both scripts if edited.
- Confirm reset table counts immediately after clearing.
- Confirm regenerated `market_quotes`, `news_items`, `link_scores`, and `source_status` have today’s rows.
- Confirm the evening report contains the candidate-watch section and not an `OperationalError` placeholder.
- Confirm Feishu `send_message` returned success/message id for both morning and evening reports.
