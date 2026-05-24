#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$ROOT/.venv/bin/python" "$ROOT/import_movements.py" "$1"
"$ROOT/.venv/bin/python" "$ROOT/generate_dashboard.py"
