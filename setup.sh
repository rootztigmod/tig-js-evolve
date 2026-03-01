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

# Run setup.py — it handles everything from here
python3 "$SCRIPT_DIR/setup.py" "$@"
