#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$HERMES_HOME/venvs/a_share_daily"
START_DB=0
RUN_TESTS=0

for arg in "$@"; do
  case "$arg" in
    --start-db) START_DB=1 ;;
    --test) RUN_TESTS=1 ;;
    --help|-h)
      cat <<EOF
Usage: ./install.sh [--start-db] [--test]

Installs A-share raw-material market-data scripts, DB init files, and Hermes skill into:
  HERMES_HOME=$HERMES_HOME

Options:
  --start-db   docker compose up -d the bundled PostgreSQL service
  --test       run lightweight Python import/unit tests after install
EOF
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$HERMES_HOME/scripts" "$HERMES_HOME/a_share_daily_db/init" "$HERMES_HOME/skills/data-science"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  mkdir -p "$(dirname "$VENV_DIR")"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/requirements.txt"

cp "$REPO_DIR"/scripts/a_share_* "$HERMES_HOME/scripts/"
chmod +x "$HERMES_HOME/scripts/a_share_chain_daily.sh" "$HERMES_HOME/scripts/a_share_morning_prediction.sh"

cp "$REPO_DIR/db/docker-compose.yml" "$HERMES_HOME/a_share_daily_db/docker-compose.yml"
cp "$REPO_DIR/db/init/"*.sql "$HERMES_HOME/a_share_daily_db/init/"
if [ ! -f "$HERMES_HOME/a_share_daily_db/prediction_experience.json" ]; then
  printf '{}\n' > "$HERMES_HOME/a_share_daily_db/prediction_experience.json"
fi

rm -rf "$HERMES_HOME/skills/data-science/a-share-market-data-pipeline"
cp -R "$REPO_DIR/skills/data-science/a-share-market-data-pipeline" "$HERMES_HOME/skills/data-science/a-share-market-data-pipeline"

if [ "$START_DB" = "1" ]; then
  if command -v docker >/dev/null 2>&1; then
    docker compose -f "$HERMES_HOME/a_share_daily_db/docker-compose.yml" up -d
  else
    echo "docker not found; skipped DB startup" >&2
  fi
fi

if [ "$RUN_TESTS" = "1" ]; then
  PYTHONPATH="$HERMES_HOME/scripts" "$VENV_DIR/bin/python" -m pytest "$REPO_DIR/tests" -q
fi

cat <<EOF
Installed A-share market-data pack.

Key files:
  $HERMES_HOME/scripts/a_share_market_db.py
  $HERMES_HOME/scripts/a_share_morning_prediction.sh
  $HERMES_HOME/scripts/a_share_chain_daily.sh
  $HERMES_HOME/a_share_daily_db/docker-compose.yml
  $HERMES_HOME/skills/data-science/a-share-market-data-pipeline/SKILL.md

Next steps:
  1) Start DB: docker compose -f "$HERMES_HOME/a_share_daily_db/docker-compose.yml" up -d
  2) Smoke test: HERMES_HOME="$HERMES_HOME" "$VENV_DIR/bin/python" "$HERMES_HOME/scripts/a_share_market_db.py" --test-history --history-days 3
  3) Morning report: HERMES_HOME="$HERMES_HOME" "$HERMES_HOME/scripts/a_share_morning_prediction.sh"
  4) Evening report: HERMES_HOME="$HERMES_HOME" "$HERMES_HOME/scripts/a_share_chain_daily.sh"
EOF
