#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}${CYAN}=========================================${NC}"
echo -e "${BOLD}${CYAN}  TIG Job Scheduling - DeepEvolve Setup  ${NC}"
echo -e "${BOLD}${CYAN}=========================================${NC}"
echo ""

# ─── Already set up? ──────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}Setup already complete.${NC}"
    echo -e "Run ${BOLD}python run.py${NC} to start evolving."
    echo ""
    echo -e "To redo setup, delete ${BOLD}.env${NC} and run this script again."
    exit 0
fi

# ─── Step 1: System packages ──────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Checking system packages...${NC}"

if ! command -v curl &>/dev/null; then
    echo "  Installing curl..."
    sudo apt-get update -q && sudo apt-get install -y -q curl
fi

if ! command -v git &>/dev/null; then
    echo "  Installing git..."
    sudo apt-get update -q && sudo apt-get install -y -q git
fi

if ! command -v docker &>/dev/null; then
    echo -e "${YELLOW}  Warning: Docker not found.${NC}"
    echo "  Docker is required to build and test algorithms."
    echo "  Install it from: https://docs.docker.com/engine/install/ubuntu/"
    echo "  Then re-run this script."
    exit 1
fi

echo -e "${GREEN}  System packages OK.${NC}"
echo ""

# ─── Step 2: Miniconda ────────────────────────────────────────────────────────
echo -e "${BOLD}[2/5] Checking conda...${NC}"

CONDA_SH=""
for candidate in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh" \
    "/usr/local/conda/etc/profile.d/conda.sh"
do
    if [ -f "$candidate" ]; then
        CONDA_SH="$candidate"
        break
    fi
done

if [ -z "$CONDA_SH" ]; then
    echo "  Conda not found - installing Miniconda..."
    MINICONDA_INSTALLER="/tmp/miniconda_installer.sh"
    curl -fsSL "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" \
        -o "$MINICONDA_INSTALLER"
    bash "$MINICONDA_INSTALLER" -b -p "$HOME/miniconda3"
    rm -f "$MINICONDA_INSTALLER"
    CONDA_SH="$HOME/miniconda3/etc/profile.d/conda.sh"
    echo -e "${GREEN}  Miniconda installed.${NC}"
else
    echo -e "${GREEN}  Conda found.${NC}"
fi

# shellcheck source=/dev/null
source "$CONDA_SH"

# Initialise conda in bash so it's available in future shell sessions
conda init bash &>/dev/null || true

# Accept Anaconda Terms of Service (required since 2024)
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r 2>/dev/null || true

echo ""

# ─── Step 3: Conda environment + dependencies ─────────────────────────────────
echo -e "${BOLD}[3/5] Setting up Python environment...${NC}"

if conda env list | grep -q "^deepevolve "; then
    echo -e "${YELLOW}  Environment 'deepevolve' already exists - skipping creation.${NC}"
else
    echo "  Creating conda environment 'deepevolve' (Python 3.11)..."
    conda create -n deepevolve python=3.11 -y -q
    echo -e "${GREEN}  Environment created.${NC}"
fi

echo "  Installing dependencies..."
conda run -n deepevolve pip install -r "$SCRIPT_DIR/requirements-mini.txt" -q
echo -e "${GREEN}  Dependencies installed.${NC}"
echo ""

# ─── Step 4: Locate tig-monorepo ──────────────────────────────────────────────
echo -e "${BOLD}[4/5] Locating tig-monorepo...${NC}"

COMMON_PATHS=(
    "$HOME/tig-monorepo"
    "$HOME/work/tig-monorepo"
    "$HOME/projects/tig-monorepo"
    "/opt/tig-monorepo"
)

FOUND_PATH=""
for p in "${COMMON_PATHS[@]}"; do
    if [ -d "$p/tig-algorithms/src/job_scheduling" ]; then
        FOUND_PATH="$p"
        break
    fi
done

if [ -n "$FOUND_PATH" ]; then
    echo -e "  Found: ${BOLD}$FOUND_PATH${NC}"
    read -rp "  Is this correct? [Y/n]: " confirm
    confirm="${confirm:-Y}"
    if [[ "$confirm" =~ ^[Nn] ]]; then
        FOUND_PATH=""
    fi
fi

if [ -z "$FOUND_PATH" ]; then
    echo ""
    echo -e "${YELLOW}  tig-monorepo not found automatically.${NC}"
    echo "  tig-monorepo is required to build and test algorithms."
    echo "  If you don't have it yet, clone it with:"
    echo -e "    ${BOLD}git clone https://github.com/tig-foundation/tig-monorepo.git ~/tig-monorepo${NC}"
    echo ""
    read -rp "  Enter full path to tig-monorepo [~/tig-monorepo]: " user_path
    user_path="${user_path:-$HOME/tig-monorepo}"
    user_path="${user_path/#\~/$HOME}"

    if [ ! -d "$user_path/tig-algorithms/src/job_scheduling" ]; then
        echo -e "${RED}  Error: '$user_path' does not look like a valid tig-monorepo.${NC}"
        echo "  Expected: $user_path/tig-algorithms/src/job_scheduling"
        echo "  Please clone tig-monorepo and re-run setup.sh."
        exit 1
    fi
    FOUND_PATH="$user_path"
fi

echo -e "${GREEN}  tig-monorepo: $FOUND_PATH${NC}"
echo ""

# ─── Step 5: API Keys ─────────────────────────────────────────────────────────
echo -e "${BOLD}[5/5] Configuring API keys...${NC}"
echo ""
echo "  Which LLM provider will you be using?"
echo "    1) OpenAI (GPT)"
echo "    2) Anthropic (Claude)"
echo ""
read -rp "  Enter choice [1/2]: " provider_choice

LLM_PROVIDER=""
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""

if [ "$provider_choice" = "2" ]; then
    LLM_PROVIDER="claude"
    echo ""
    read -rsp "  Enter your Anthropic API key: " ANTHROPIC_API_KEY
    echo ""

    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo -e "${RED}  Error: Anthropic API key cannot be empty.${NC}"
        exit 1
    fi

    echo ""
    echo -e "  ${YELLOW}Note:${NC} The research phase uses gpt-4o-mini (OpenAI) for web search."
    echo "  Providing an OpenAI key enables this (recommended but optional)."
    echo ""
    read -rsp "  Enter OpenAI key (or press Enter to skip web search): " OPENAI_API_KEY
    echo ""

    if [ -z "$OPENAI_API_KEY" ]; then
        echo -e "  ${YELLOW}Web search disabled. Research will run without internet search.${NC}"
        OPENAI_API_KEY="sk-dummy-no-web-search"
    fi
else
    LLM_PROVIDER="openai"
    echo ""
    read -rsp "  Enter your OpenAI API key: " OPENAI_API_KEY
    echo ""

    if [ -z "$OPENAI_API_KEY" ]; then
        echo -e "${RED}  Error: OpenAI API key cannot be empty.${NC}"
        exit 1
    fi
fi

# ─── Write .env ───────────────────────────────────────────────────────────────
cat > "$ENV_FILE" <<EOF
# Generated by setup.sh - do not commit this file
TIG_MONOREPO_PATH=$FOUND_PATH
LLM_PROVIDER=$LLM_PROVIDER
OPENAI_API_KEY=$OPENAI_API_KEY
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
CONDA_SH=$CONDA_SH
EOF

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}=========================================${NC}"
echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
echo -e "${GREEN}${BOLD}=========================================${NC}"
echo ""
echo -e "  Provider : ${BOLD}$LLM_PROVIDER${NC}"
echo -e "  Monorepo : ${BOLD}$FOUND_PATH${NC}"
echo ""
echo -e "  ${YELLOW}IMPORTANT:${NC} You must activate the conda environment EVERY TIME"
echo -e "  you open a new terminal before running the launcher:"
echo ""
echo -e "    ${BOLD}conda activate deepevolve${NC}"
echo -e "    ${BOLD}python run.py${NC}"
echo ""
echo -e "  If you see 'ModuleNotFoundError' when running run.py, it means"
echo -e "  the conda environment is not active. Run the above commands."
echo ""
