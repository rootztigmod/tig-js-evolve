# TIG Job Scheduling - DeepEvolve: Project Handoff Document

> **Purpose**: Read this at the start of any new conversation to restore full context.
> This is an internal development document, not user-facing. The public README is `README.md`.

---

## 1. What This Project Is

`tig-js-evolve` is a fully operational automated algorithm evolution system for the
**TIG Job Scheduling challenge**. It uses **DeepEvolve** to research, implement and
evaluate algorithmic improvements to a user's Rust algorithm - automatically, iteration
by iteration.

The system is designed to be:
- **Published on GitHub** for the TIG community to clone and use
- **Generic** - works with any TIG job scheduling algorithm (single file or modular)
- **Provider-agnostic** - supports both OpenAI (GPT) and Anthropic (Claude)
- **Self-contained** - includes a fresh clone of DeepEvolve, all configs, evaluator template

---

## 2. Repository Location & Structure

**WSL path**: `/home/kevin/tig-js-evolve/`

```
tig-js-evolve/
├── README.md                        ← Public-facing user documentation
├── DEEPEVOLVE_JSS_README.md         ← This handoff document
├── setup.sh                         ← One-time setup (conda, deps, API keys, monorepo path)
├── run.py                           ← Launch every time (menus, baseline, DeepEvolve launch)
├── ideas.md                         ← User fills this before each run (guidance to AI)
├── requirements-mini.txt            ← Python deps (openai-agents, litellm, hydra-core etc.)
├── .env.example                     ← Key template (.env is gitignored)
├── .gitignore
├── initial_algorithm/               ← Untouched originals, one subfolder per algorithm
│   ├── adaptive_js_v2/              ←   modular algorithm (all .rs files)
│   └── dispatching_rules/           ←   single-file algorithm (.rs file)
├── backups/                         ← Auto-created per-iteration backups of evolved files
│   └── <algo_name>/
│       └── <timestamp>_<module>_avg<score>.rs
├── configs/models/
│   ├── claude.yaml                  ← Custom cost-optimised Claude model config
│   └── openai.yaml                  ← Custom cost-optimised OpenAI model config
├── evaluator/
│   └── deepevolve_interface.py      ← Template - run.py fills placeholders and copies per run
└── deepevolve/                      ← Fresh clone of https://github.com/liugangcode/deepevolve
    └── configs/models/              ← Our model configs copied here too
```

---

## 3. How It Works (End to End)

### setup.sh (run once)
1. Installs Miniconda if not present, creates `deepevolve` conda env (Python 3.11)
2. Installs `requirements-mini.txt`
3. Detects or prompts for `tig-monorepo` path
4. Collects API keys (OpenAI and/or Anthropic), writes `.env`
5. Auto-accepts Anaconda ToS, runs `conda init bash`

### run.py (run every time)
1. Checks conda environment is active (warns if not)
2. Detects existing checkpoints → offers resume / new run / delete
3. **New run menu:**
   - Scans `tig-monorepo/tig-algorithms/src/job_scheduling/` for algorithms
   - Auto-detects single-file vs modular
   - For modular: detects track files by name, offers individual file or full algorithm
   - User picks: nonces, workers, max iterations, LLM provider
4. **Initial baseline run**: builds algorithm via Docker, tests selected tracks, stores scores
5. Generates `deepevolve_interface.py` (from template with placeholders filled) and `info.json`
6. Injects `ideas.md` content as USER GUIDANCE into `info.json` description
7. Launches DeepEvolve with correct Hydra overrides including checkpoint loading on resume

### deepevolve_interface.py (called by DeepEvolve each iteration)
- Contains `RUST_CODE` (original Rust source embedded as string) - DeepEvolve modifies this
- Contains `RUST_CODE_ORIGINAL` (unchanged copy for diagnostic comparison)
- Writes `RUST_CODE` to monorepo, builds via Docker, tests selected tracks
- Prints to stderr (stdout is captured by DeepEvolve)
- Backs up every successfully evaluated file to `backups/`
- Returns `combined_score = avg_quality` and per-track metrics

### DeepEvolve display fix
`deepevolve/deepevolve.py` was modified to show delta vs **overall best** (not vs parent).
This ensures NEW BEST only shows when the rolling best is genuinely beaten.

---

## 4. The TIG Job Scheduling Challenge

- **Objective**: Minimise makespan (total completion time across all jobs)
- **Quality metric**: `1.0 - make_span / greedy_makespan` (higher is better, fixed-point 6dp)
- **Docker image**: `ghcr.io/tig-foundation/tig-monorepo/job_scheduling/dev:0.0.5`
- Algorithm calls `save_solution()` during execution; last saved solution is evaluated
- No wall-clock time limit on TIG itself; Docker test timeout is 600s per track

### 5 Tracks

| Track | n= | s= | Description |
|-------|----|----|-------------|
| FlowShop | 50 | flow_shop | Strict sequential, single machine per stage |
| HybridFlowShop | 50 | hybrid_flow_shop | Flow-like with parallel machines |
| JobShop | 50 | job_shop | Random routing, low flexibility |
| FjspMedium | 50 | fjsp_medium | Moderate flexibility (flex 2-4) |
| FjspHigh | 50 | fjsp_high | High flexibility (flex 5+), chaotic |

---

## 5. Algorithm Detection Logic

`run.py` scans `tig-monorepo/tig-algorithms/src/job_scheduling/` and skips:
- `mod.rs`, `test/`, `template`, `template.rs`, `template.md`
- Any directory starting with `deepevolve_` (old generated artifacts)

**Single file**: `.rs` file alongside `mod.rs` → whole file is evolved

**Modular (with track files)**: directory containing files named:
`flow_shop.rs`, `hybrid_flow_shop.rs`, `job_shop.rs`, `fjsp_medium.rs`, `fjsp_high.rs`
→ user picks a track file OR a module file (with warning that shared modules affect all tracks)

**Modular (no track files)**: directory with only module files (e.g. VRPTW fast_lane_v2)
→ all `.rs` files listed, user picks which module to evolve

`mod.rs` is always excluded from evolution.

---

## 6. LLM Configuration

### Model configs (cost-optimised)

**Claude** (`configs/models/claude.yaml`):
- planner: `claude-haiku-4-5-20251001` (cheap)
- searcher: `gpt-4o-mini` (web search requires OpenAI)
- writer: `claude-sonnet-4-6` (quality)
- developer: `claude-sonnet-4-6` (quality)
- debugger: `claude-haiku-4-5-20251001` (cheap)

**OpenAI** (`configs/models/openai.yaml`):
- planner: `gpt-4o-mini`
- searcher: `gpt-4o-mini`
- writer: `gpt-4o`
- developer: `gpt-4o`
- debugger: `gpt-4o-mini`

### LiteLLM support
The fresh DeepEvolve clone did NOT have LiteLLM support out of the box.
We copied `coder.py`, `researcher.py`, `deepevolve.py` from the working `~/deepevolve` 
and added `litellm_models` list to `deepevolve/utils/datatypes.py`.
`litellm` is installed in the conda env and listed in `requirements-mini.txt`.

### Environment variables (stored in .env)
- `TIG_MONOREPO_PATH` - path to tig-monorepo
- `LLM_PROVIDER` - `openai` or `claude`
- `OPENAI_API_KEY` - always needed (even for Claude, for web search)
- `ANTHROPIC_API_KEY` - needed for Claude
- `CONDA_SH` - path to conda.sh for environment activation

---

## 7. Key Files Modified in DeepEvolve Clone

These files differ from the upstream GitHub clone and must not be overwritten:

| File | Change |
|------|--------|
| `deepevolve/deepevolve.py` | Delta display uses overall best not parent; copied from working ~/deepevolve |
| `deepevolve/coder.py` | Added `extract_diffs` import; LiteLLM routing; copied from working ~/deepevolve |
| `deepevolve/researcher.py` | LiteLLM routing; copied from working ~/deepevolve |
| `deepevolve/utils/datatypes.py` | Added `litellm_models` list and `is_litellm_model()` |
| `deepevolve/utils/code.py` | Improved diff pattern (accepts `<<<<<<< <filename>` not just `<<<<<<< SEARCH`) |
| `deepevolve/configs/models/claude.yaml` | Our custom cost-optimised Claude config |
| `deepevolve/configs/models/openai.yaml` | Our custom cost-optimised OpenAI config |

---

## 8. Known Issues & Solutions

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: hydra` | `conda activate deepevolve` not run |
| `conda: command not found` | Run `exec bash` to reload .bashrc after setup.sh |
| `mod.rs points to old deepevolve_*` | run.py now writes correct mod.rs before baseline build |
| File selection mismatch (wrong file evolved) | Bug fixed: `all_evolvable` now built from `sorted(track_files.keys())` to match display order |
| `RUST_CODE not modified` | DeepEvolve diff didn't apply. Root cause: LLM generates partial Rust diffs that don't match the Python string wrapper. Fix: query explicitly instructs LLM to replace entire RUST_CODE string in one SEARCH/REPLACE block. |
| Delta shows parent not best | Fixed in deepevolve.py - compares vs overall best |
| Resume starts from 0 | Fixed in run.py - passes `database.db_path` to load checkpoint |
| DeepEvolve only loads .py files | Fixed by embedding RUST_CODE inside deepevolve_interface.py |

---

## 9. What Still Needs Doing / Future Work

- [ ] `ideas.md` redesign: Section 1 auto-generated by run.py from detected algorithm; Section 2 blank canvas template for user
- [ ] Multi-file selection for full algorithm evolution (checklist of files to include)
- [ ] Public GitHub repo creation (as git submodule pointing to liugangcode/deepevolve)
- [ ] Test with a single-file algorithm
- [ ] Test with a VRPTW-style modular algorithm (no track files)
- [ ] Consider adding `min_improvement` threshold option to menu

---

## 10. Session Log

| Date | Action |
|------|--------|
| 2026-02-28 | Full system built and tested. First evolution run: 5 iterations on fjsp_high.rs, best result 44,860 vs baseline 44,732 (+128). All core issues resolved. README.md written. This handoff document created. |

---

## 11. Acknowledgements

**DeepEvolve** by Liu et al. (2025) — https://github.com/liugangcode/deepevolve

```bibtex
@article{liu2025scientific,
  title={Scientific Algorithm Discovery by Augmenting AlphaEvolve with Deep Research},
  author={Liu, Gang and Zhu, Yihan and Chen, Jie and Jiang, Meng},
  journal={arXiv preprint arXiv:2510.06056},
  year={2025}
}
```

**TIG (The Innovation Game)** — https://tig.foundation
