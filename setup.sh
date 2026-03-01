#!/usr/bin/env bash
# Bootstrap: activate conda environment then hand off to setup.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source conda if available so 'conda' command works in this shell
for candidate in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh" \
    "/usr/local/conda/etc/profile.d/conda.sh"
do
    if [ -f "$candidate" ]; then
        # shellcheck source=/dev/null
        source "$candidate"
        break
    fi
done

# Accept Anaconda Terms of Service (required since 2024)
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r    2>/dev/null || true

# Bootstrap: ensure setup.py's UI dependencies are available before running it.
# If the deepevolve env already exists, use it; otherwise fall back to base.
if conda env list 2>/dev/null | grep -q "^deepevolve "; then
    SETUP_PYTHON="$(conda run -n deepevolve which python 2>/dev/null || true)"
fi
SETUP_PYTHON="${SETUP_PYTHON:-python3}"

# Install minimum deps needed to run setup.py itself
"$SETUP_PYTHON" -m pip install --quiet rich InquirerPy 2>/dev/null || \
    python3 -m pip install --quiet rich InquirerPy

# Run setup.py — it handles everything from here
"$SETUP_PYTHON" "$SCRIPT_DIR/setup.py" "$@"
