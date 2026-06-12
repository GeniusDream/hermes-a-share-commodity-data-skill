#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$HERMES_HOME/venvs/a_share_data"
RUN_TESTS=0

for arg in "$@"; do
  case "$arg" in
    --test) RUN_TESTS=1 ;;
    --help|-h)
      cat <<EOF
Usage: ./install.sh [--test]

Installs the A-share data-collection-only Hermes skill and collector script into:
  HERMES_HOME=$HERMES_HOME

Options:
  --test       run lightweight import/unit tests after install
EOF
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$HERMES_HOME/scripts" "$HERMES_HOME/skills/data-science" "$(dirname "$VENV_DIR")"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/requirements.txt"

cp "$REPO_DIR/scripts/a_share_data_collector.py" "$HERMES_HOME/scripts/a_share_data_collector.py"
chmod +x "$HERMES_HOME/scripts/a_share_data_collector.py"

rm -rf "$HERMES_HOME/skills/data-science/a-share-data-collection"
cp -R "$REPO_DIR/skills/data-science/a-share-data-collection" "$HERMES_HOME/skills/data-science/a-share-data-collection"

if [ "$RUN_TESTS" = "1" ]; then
  bash -n "$REPO_DIR/install.sh"
  "$VENV_DIR/bin/python" -m py_compile "$HERMES_HOME/scripts/a_share_data_collector.py"
  PYTHONPATH="$HERMES_HOME/scripts" "$VENV_DIR/bin/python" -m pytest "$REPO_DIR/tests" -q
fi

cat <<EOF
Installed A-share data-collection skill.

Key files:
  $HERMES_HOME/scripts/a_share_data_collector.py
  $HERMES_HOME/venvs/a_share_data/bin/python
  $HERMES_HOME/skills/data-science/a-share-data-collection/SKILL.md

Smoke examples:
  "$VENV_DIR/bin/python" "$HERMES_HOME/scripts/a_share_data_collector.py" --source index-quotes --format json
  "$VENV_DIR/bin/python" "$HERMES_HOME/scripts/a_share_data_collector.py" --source board-history --boards 电池,贵金属 --start-date 2026-06-08 --end-date 2026-06-10 --format json
EOF
