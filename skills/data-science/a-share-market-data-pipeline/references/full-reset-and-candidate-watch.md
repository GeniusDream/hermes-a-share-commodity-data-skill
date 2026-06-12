# Full reset + regenerated report workflow and candidate-watch filtering

Session-derived notes for the A-share raw-material/night-session report pipeline.

## When the user asks to clear historical DB contents and restart the report version

Use a conservative, verifiable reset sequence:

1. Ensure PostgreSQL is running and healthy.
2. Back up the full database with `pg_dump` before any destructive action.
3. Back up the early-report sidecar `prediction_experience.json` before resetting it.
4. Reset the database volume or truncate only analysis/data tables, while preserving stable seed mappings when appropriate.
5. Recreate/verify schema from init SQL and confirm counts before regeneration.
6. Reset `prediction_experience.json` to `{"records": [], "experience": {}}` so the new version starts clean.
7. Generate the morning report first, then the evening report. The evening script depends on the morning prediction record for validation text.
8. Verify regenerated DB counts, report section presence, and obvious bad-candidate absence before sending.
9. Send both reports to Feishu and record actual send results/message IDs in the final user response.

Expected post-reset sanity checks include:

- `market_quotes` and `news_items` repopulated.
- `morning_predictions` contains today's selected predictions.
- `link_scores` recomputed for today.
- `candidate_links`, `link_validations`, and `link_experience` repopulate from the new run, not old history.
- Evening report contains `潜力候选链路与晋升/降级观察`.
- Cross-industry noise such as `焦煤连续 → 第三代半导体` is absent from the user-facing report.

## Candidate discovery pitfall: global news keyword contamination

A discovered failure mode: rule-based candidate discovery matched upstream commodity families against broad same-day news text. If the news stream contained a family keyword, any strong A-share theme board could become a candidate even when the board itself was unrelated. This produced noise such as:

- `焦煤连续 → 第三代半导体`
- `焦煤连续 → 元件`
- `甲醇连续 → 光刻胶`

Durable fix:

- Candidate discovery must require the A-share board name itself to match the same industry family as the upstream commodity.
- Do not use whole-day/global news keyword presence as a substitute for board-family matching.
- The evening candidate-watch section should also apply a same-family guard before displaying candidates or promotions.
- Cross-industry promoted candidates should be shown, if at all, as downgrade/rejection warnings rather than as promising promotions.

## User-facing candidate-watch policy

The evening report should include a compact candidate-watch section, but not raw backend dumps:

- Show higher-potential candidate links: repeated sightings, strong rule/LLM evidence, and same-family industry logic.
- Show meaningful promotions only if they pass same-family filtering.
- Show selected demotion/rejection warnings to help the user avoid false links.
- Keep the section explicitly labeled as observation, not confirmation.
