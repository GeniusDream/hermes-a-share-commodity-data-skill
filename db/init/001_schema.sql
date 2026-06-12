CREATE TABLE IF NOT EXISTS market_quotes (
  trade_date date NOT NULL,
  asset_type text NOT NULL,
  code text NOT NULL,
  name text NOT NULL,
  close numeric,
  pct_chg numeric,
  amount numeric,
  volume numeric,
  amplitude numeric,
  leading_stock text,
  leading_stock_pct numeric,
  source text NOT NULL,
  raw jsonb DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (trade_date, asset_type, code, source)
);

CREATE TABLE IF NOT EXISTS news_items (
  item_id text PRIMARY KEY,
  published_at timestamptz,
  source text NOT NULL,
  channel text,
  title text NOT NULL,
  body text,
  url text,
  tags text[] DEFAULT '{}',
  raw jsonb DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS link_mappings (
  link_id text PRIMARY KEY,
  link_name text NOT NULL,
  upstream_names text[] NOT NULL,
  downstream_patterns text[] NOT NULL,
  news_patterns text[] NOT NULL,
  lag_days int[] NOT NULL DEFAULT ARRAY[0,1,3,5],
  logic text NOT NULL,
  direction_note text NOT NULL,
  expected_relation text NOT NULL DEFAULT 'mixed',
  enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS link_scores (
  trade_date date NOT NULL,
  link_id text NOT NULL REFERENCES link_mappings(link_id),
  link_name text NOT NULL,
  score numeric NOT NULL,
  confidence text NOT NULL,
  upstream_score numeric NOT NULL DEFAULT 0,
  downstream_score numeric NOT NULL DEFAULT 0,
  news_score numeric NOT NULL DEFAULT 0,
  corr_score numeric NOT NULL DEFAULT 0,
  best_lag int,
  best_corr numeric,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (trade_date, link_id)
);

CREATE INDEX IF NOT EXISTS idx_market_quotes_name_date ON market_quotes (name, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_market_quotes_type_date ON market_quotes (asset_type, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_link_scores_date_score ON link_scores (trade_date DESC, score DESC);
CREATE INDEX IF NOT EXISTS idx_news_items_published_at ON news_items (published_at DESC);
