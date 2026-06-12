CREATE TABLE IF NOT EXISTS source_status (
  run_date date NOT NULL,
  source text NOT NULL,
  status text NOT NULL,
  rows_count int NOT NULL DEFAULT 0,
  attempts int NOT NULL DEFAULT 0,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  latency_ms int,
  error text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_date, source)
);

CREATE TABLE IF NOT EXISTS candidate_links (
  candidate_id text PRIMARY KEY,
  first_seen_date date NOT NULL,
  last_seen_date date NOT NULL,
  link_name text NOT NULL,
  upstream_hint text,
  downstream_hint text,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  llm_reason text,
  seen_count int NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'proposed',
  promoted_link_id text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS link_validations (
  signal_date date NOT NULL,
  validation_date date NOT NULL,
  link_id text NOT NULL,
  link_name text NOT NULL,
  expected_lag int NOT NULL,
  prior_verdict text,
  prior_score numeric,
  validation_result text NOT NULL,
  validation_score numeric NOT NULL DEFAULT 0,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  llm_comment text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (signal_date, validation_date, link_id, expected_lag)
);

CREATE TABLE IF NOT EXISTS link_experience (
  link_id text PRIMARY KEY,
  link_name text NOT NULL,
  confirmed_count int NOT NULL DEFAULT 0,
  failed_count int NOT NULL DEFAULT 0,
  inconclusive_count int NOT NULL DEFAULT 0,
  precision_estimate numeric,
  best_lag int,
  notes text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_status_date_status ON source_status (run_date DESC, status);
CREATE INDEX IF NOT EXISTS idx_candidate_links_status_seen ON candidate_links (status, seen_count DESC, last_seen_date DESC);
CREATE INDEX IF NOT EXISTS idx_link_validations_dates ON link_validations (validation_date DESC, signal_date DESC);


CREATE TABLE IF NOT EXISTS link_hypothesis_notes (
  note_id text PRIMARY KEY,
  link_name text NOT NULL,
  note_date date NOT NULL,
  note text NOT NULL,
  source text NOT NULL DEFAULT 'llm',
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS morning_predictions (
  prediction_id text PRIMARY KEY,
  signal_date date NOT NULL,
  target_date date NOT NULL,
  upstream text NOT NULL,
  expected_sign text NOT NULL,
  downstream_patterns text[] NOT NULL DEFAULT '{}',
  basis jsonb NOT NULL DEFAULT '{}'::jsonb,
  prediction text NOT NULL,
  outcome jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_morning_predictions_target ON morning_predictions (target_date DESC, upstream);
CREATE INDEX IF NOT EXISTS idx_link_hypothesis_notes_date ON link_hypothesis_notes (note_date DESC, link_name);
