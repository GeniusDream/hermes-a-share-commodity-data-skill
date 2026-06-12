# A-share daily-report self-evolution closure

Use this reference when improving the A-share commodity-to-equity daily report's learning loop. The durable pattern is to separate confirmed evidence from LLM hypotheses, make validation explicit, and run the loop inside the same report script before rendering user-facing text.

## Tables / state roles

- `link_scores`: today's scored upstream/downstream chains and LLM audit fields.
- `link_validations`: realized validation events, including same-day/T+0 checks and later lag checks.
- `link_experience`: aggregate statistics derived from `link_validations`; do not write speculative LLM notes here.
- `candidate_links`: discovered but not-yet-official links; track repeated appearances and promotion state.
- `link_mappings`: official scoring universe; promoted candidates should land here.
- `link_hypothesis_notes`: LLM's explanatory or exploratory notes; keep separate from confirmed experience.
- `morning_predictions`: structured morning-report predictions synced from JSON or other runtime state so they can be validated and aggregated later.

## Implementation pattern

1. Add schema idempotently with `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` so cron runs can self-heal without manual migrations.
2. After initial scoring and LLM audit, run a closure step before report rendering:
   - validate today's accepted links into `link_validations` with `expected_lag = 0` for same-day review;
   - refresh `link_experience` from validation rows;
   - promote repeated high-quality candidates from `candidate_links` into `link_mappings`;
   - sync morning-prediction JSON/state into `morning_predictions` if the morning report participates in later validation.
3. Keep promotion conservative: require repeated sightings (for example `seen_count >= 3`) and a non-rejected status such as `watch`/`proposed`; store `promoted_link_id` and set status to `promoted` after insertion.
4. Morning reports should consume past prediction precision/realization records only as a confidence/priority adjustment, not as a hard override of current market evidence.
5. LLM `experience_notes` or audit comments are hypotheses. Persist them in `link_hypothesis_notes`; only confirmed/inconclusive/failed validation outcomes update `link_experience`.

## User-facing report rule

The daily report should stay concise and human-facing. Do not expose `link_experience`, `candidate_links`, promotion counts, or schema/self-evolution internals unless the user explicitly asks for diagnostics. Use the learning loop to improve confidence, ranking, and explanations behind the scenes.

## Verification checklist

- Run syntax checks on every touched script before destructive operations.
- Use a non-destructive DB query to confirm new tables/columns exist and that closure functions can run idempotently.
- Before clearing data, create a timestamped backup under the pipeline's backup directory and surface the path.
- After any reset or regeneration, verify row counts and latest timestamps for `market_quotes`, `news_items`, `link_scores`, `link_validations`, `link_experience`, `candidate_links`, `source_status`, `link_hypothesis_notes`, and `morning_predictions`.
- Run the full report script, check the exit code, and inspect the generated report for concise wording and absence of backend self-evolution chatter.

## Destructive reset caution

If a destructive clear/reset is requested, verify scope first and use the platform's approval path. If the destructive command is denied, stop that branch immediately; do not retry the same outcome through a different command. Report what was completed and exactly what remains blocked.