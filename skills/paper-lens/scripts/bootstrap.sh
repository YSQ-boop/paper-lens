#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_BASE="${XDG_CACHE_HOME:-${HOME}/.cache}"
VENV_DIR="${PAPER_LENS_VENV:-${CACHE_BASE}/paper-lens/venv}"

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${SKILL_ROOT}/requirements.txt"

echo "Paper Lens environment ready."
echo "Python executable: ${VENV_DIR}/bin/python"
