ALTER TABLE link_scores
  ADD COLUMN IF NOT EXISTS llm_model text,
  ADD COLUMN IF NOT EXISTS llm_verdict text,
  ADD COLUMN IF NOT EXISTS llm_adjustment numeric,
  ADD COLUMN IF NOT EXISTS llm_reason text,
  ADD COLUMN IF NOT EXISTS llm_missing_links jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS llm_reviewed_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_link_scores_llm_reviewed ON link_scores (trade_date DESC, llm_reviewed_at DESC);
