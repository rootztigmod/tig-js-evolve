# TIG Job Scheduling - DeepEvolve

An automated algorithm evolution system for the **TIG Job Scheduling challenge**.  
Uses [DeepEvolve](https://github.com/liugangcode/deepevolve) to research, implement and evaluate  
algorithmic improvements to your Rust algorithm — automatically, iteration by iteration.

---

## How it works

1. **You provide** your existing algorithm in the TIG monorepo
2. **You choose** which module to evolve, which tracks to test, and how many iterations to run
3. **You fill in** `ideas.md` with your expert knowledge and directions
4. **DeepEvolve** researches academic papers and recent work, generates a novel implementation idea, writes the Rust code, builds it via Docker, tests it, and reports the result
5. **Repeat** — each iteration builds on the best result so far

---

## Prerequisites

- Ubuntu / WSL2
- Docker (installed and running)
- `tig-monorepo` cloned locally, with your algorithm placed in the correct location:
  `tig-monorepo/tig-algorithms/src/job_scheduling/<your_algorithm_name>/`

If you don't have `tig-monorepo`:
```bash
git clone https://github.com/tig-foundation/tig-monorepo.git
```

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/tig-js-evolve.git
cd tig-js-evolve
./setup.sh
```

`setup.sh` handles everything automatically:
- Installs Miniconda if not present
- Creates a `deepevolve` conda environment (Python 3.11)
- Installs all dependencies
- Locates your `tig-monorepo`
- Collects your API key(s)
- Writes a `.env` file (never committed to git)

> **Important:** After setup completes, you must activate the conda environment  
> **every time** you open a new terminal:
> ```bash
> conda activate deepevolve
> ```

---

## Placing your algorithm

Your algorithm must already exist in the TIG monorepo under:

```
tig-monorepo/tig-algorithms/src/job_scheduling/
```

### ⚠️ Required: populate `initial_algorithm/`

You **must** also copy your algorithm's original, unmodified `.rs` files into the `initial_algorithm/` folder in this repo:

```
tig-js-evolve/
└── initial_algorithm/
    ├── flow_shop.rs
    ├── fjsp_high.rs
    ├── infra.rs
    └── ...          ← all .rs files from your algorithm
```

**Why this matters:** Before every baseline evaluation, `run.py` automatically restores these files to the monorepo. This guarantees the baseline is always measured against the true original code — not a leftover evolved version from a previous run. If `initial_algorithm/` contains modified files, your baseline will be wrong and all quality deltas will be meaningless.

> Keep `initial_algorithm/` as a permanent read-only reference. Never overwrite these files with evolved versions.

Two layouts are supported:

**Single file algorithm:**
```
job_scheduling/
├── mod.rs              ← contains: pub mod my_algorithm;
└── my_algorithm.rs     ← entire algorithm in one file
```

**Modular algorithm (directory):**
```
job_scheduling/
├── mod.rs              ← contains: pub mod my_algorithm;
└── my_algorithm/
    ├── mod.rs
    ├── solver.rs
    ├── infra.rs
    ├── flow_shop.rs
    ├── fjsp_high.rs
    └── ...
```

> **Track vs module detection:** The launcher automatically identifies track-specific files  
> by name. Files named `flow_shop.rs`, `hybrid_flow_shop.rs`, `job_shop.rs`, `fjsp_medium.rs`  
> or `fjsp_high.rs` are treated as track files and offered individually for single-track evolution.  
>  
> All other `.rs` files (e.g. `infra.rs`, `types.rs`, `solver.rs`, `operators.rs`) are module files.  
> These **can** be individually selected for evolution, but with caution:  
> - Shared modules affect **all tracks simultaneously** — a change to `infra.rs` impacts every track
> - `mod.rs` is structural and should never be evolved — it is excluded from the file list automatically  
> - For algorithms without track-specific files (e.g. VRPTW-style), all module files are listed  
>   and the user selects which one to evolve

Optionally, keep a backup copy of your untouched original in:
```
tig-js-evolve/initial_algorithm/
```

---

## Running

```bash
conda activate deepevolve
python run.py
```

### First run — full menu

```
=======================================================
  TIG Job Scheduling - DeepEvolve Launcher
=======================================================

  Algorithms found in tig-monorepo:

  1) my_algorithm  (modular)
  2) another_algo  (single)

  Which algorithm do you want to evolve? [1-2]: 1

  Evolution mode:

  1) Single track / module file
  2) Full algorithm (single .rs algorithm file)

  Choose evolution mode [1-2]: 1

  Track files detected (files whose names match known track names):

  1) flow_shop        (flow_shop.rs)
  2) hybrid_flow_shop (hybrid_flow_shop.rs)
  3) job_shop         (job_shop.rs)
  4) fjsp_medium      (fjsp_medium.rs)
  5) fjsp_high        (fjsp_high.rs)

  Which track file to evolve? [1-5]: 5

  Which tracks to test? (comma-separated or 'a' for all)

  1) flow_shop
  2) hybrid_flow_shop
  3) job_shop
  4) fjsp_medium
  5) fjsp_high
  6) All tracks

  Select tracks: 5

  Nonces per track [default 100]: 100
  Workers          [default 16]:  16
  Max iterations   [default 20]:  5

  LLM Provider:
  (default: claude)

  1) OpenAI (GPT)
  2) Anthropic (Claude)
  3) Google (Gemini)

  Select provider [1-3]: 2
```

After the menu, the system:
1. Builds your algorithm to confirm it compiles
2. Runs a baseline test to measure your current quality
3. Launches DeepEvolve to begin evolving

### Subsequent runs — checkpoint resume

If a previous run exists, you will see:

```
  Previous run(s) detected:

  1) job_scheduling_my_algorithm_fjsp_high
       Algorithm  : my_algorithm
       Evolving   : fjsp_high.rs
       Tracks     : fjsp_high
       Progress   : iteration 3/20
       Baseline   : avg 44732

  1) job_scheduling_my_algorithm_fjsp_high
  2) Start a new run
  3) Delete a previous run

  Enter choice [1-3]:
```

- **Option 1** — Resume from where you left off (all progress preserved)
- **Option 2** — Start a completely new run (keeps old checkpoint intact)
- **Option 3** — Delete a previous run and start fresh

---

## Providing your ideas (important)

Before each run, edit `ideas.md` in the project root.  
This is your expert guidance to the AI — the more specific, the better results.

```
ideas.md
├── Section 1: Fixed Context  (auto-used, rarely edit)
│   - Problem description, track types, baselines
│   - Algorithm structure, Rust rules
└── Section 2: Your Ideas     (edit before EVERY run)
    - Which module/track you are targeting
    - What you think is limiting current performance
    - Specific algorithmic ideas to try
    - Papers or techniques to research
    - Target quality scores
```

If `ideas.md` still has unfilled `[FILL IN]` placeholders when you launch,  
the system will warn you and ask if you want to continue.

---

## Reading the output

### Baseline run
```
=======================================================
  Running initial baseline evaluation...
=======================================================
  Set mod.rs -> pub mod my_algorithm;
  Building my_algorithm...
  Build successful.
  Testing fjsp_high (100 nonces)... quality = 44732

  Baseline avg_quality: 44732
=======================================================
```

### Evolution iterations
```
============================================================
Job Scheduling - my_algorithm
Evolving: fjsp_high.rs
Tracks: fjsp_high
============================================================
OK: RUST_CODE modified (390 -> 516 lines, delta=+126)
  Testing: fjsp_high (100 nonces)
    [OK] quality=44833  baseline=44732  delta=+0.23%  time=91.1s

Results:
  avg_quality  = 44833
  current_best = 44732  delta = +101
  vs_original  = +101   (original baseline: 44732)
  tracks improved vs original: 1/1
  total_time = 145.6s
  Backup saved: backups/my_algorithm/1234567890_fjsp_high_avg44833.rs
============================================================
```

### DeepEvolve summary table
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * NEW BEST   iter 2  497ff218  (+101.0 -> 44833.0)
────────────────────────────────────────────────────────────
  Track              Quality    Delta%      Time    Change
  ---------------- ---------  --------  --------  --------
  FjspHigh            44,833    +0.23%     91.1s    +101
────────────────────────────────────────────────────────────
  avg_quality        44,833.0              145.6s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- **NEW BEST** — evolved code beat the current best. Delta shown vs previous best.
- **no change** — evolved code did not improve on the current best. Delta shown vs current best (will be negative or zero).

---

## Evolved file backups

Every successfully evaluated evolved file is automatically backed up to:
```
backups/<algorithm_name>/<timestamp>_<module>_avg<score>.rs
```

Example:
```
backups/my_algorithm/1772311572_fjsp_high_avg44833.rs
```

Use these to manually test any previous version:
```bash
cp backups/my_algorithm/1772311572_fjsp_high_avg44833.rs \
   /path/to/tig-monorepo/tig-algorithms/src/job_scheduling/my_algorithm/fjsp_high.rs
```

---

## LLM providers and cost

OpenAI, Anthropic, and Google Gemini are all supported. You are asked which to use during setup and at each run.

| Role | OpenAI | Anthropic | Gemini | Notes |
|------|--------|-----------|-------|
| Planner | gpt-4o-mini | claude-haiku-4-5 | gemini-2.0-flash | Cheap - structured output |
| Searcher | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini | Web search (always OpenAI) |
| Writer | gpt-4o | claude-sonnet-4-6 | gemini-2.5-pro | Research report - most important |
| Developer | gpt-4o | claude-sonnet-4-6 | gemini-2.5-pro | Rust code generation |
| Debugger | gpt-4o-mini | claude-haiku-4-5 | gemini-2.0-flash | Compile error fixing |

> **Anthropic / Gemini users:** The web search role requires a secondary OpenAI key (`gpt-4o-mini`). This is optional — without it the research phase runs without internet search.  
> You will be asked for this during setup. It is optional but strongly recommended —  
> without it the research phase cannot search the internet for new ideas.

**Typical cost per iteration:** varies by idea complexity and code length.  
Keep `max_iterations` low (5-10) for initial testing to control spend.

---

## Tuning DeepEvolve

Edit `deepevolve/configs/config.yaml` to tune behaviour:

| Setting | Default | Effect |
|---------|---------|--------|
| `database.num_islands` | 5 | More islands = more diverse exploration. Increase to 10 for longer runs. |
| `database.population_size` | 25 | Total programs maintained. |
| `database.exploitation_ratio` | 0.7 | Proportion of iterations using the best program as parent. |
| `database.exploration_ratio` | 0.2 | Proportion using random programs as parent (diversity). |
| `max_coding_reflect` | 1 | Reflection passes for code generation. Increase to 2 for harder problems. |
| `max_debug_retry` | 5 | Max attempts to fix compile errors per iteration. |

---

## Job Scheduling tracks

| Track | n= | s= | Description | Baseline (Rootz) |
|-------|----|----|-------------|-----------------|
| FlowShop | 50 | flow_shop | Strict sequential routing | 28,434 |
| HybridFlowShop | 50 | hybrid_flow_shop | Parallel machines at each stage | 35,268 |
| JobShop | 50 | job_shop | Random routing, low flexibility | 53,875 |
| FjspMedium | 50 | fjsp_medium | Moderate flexibility | 47,882 |
| FjspHigh | 50 | fjsp_high | High flexibility, chaotic | 44,732 |

*Baselines shown are reference scores. Your algorithm's actual baseline is measured at runtime.*

Quality metric: `1.0 - make_span / greedy_makespan` (higher is better)

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'hydra'`**  
The conda environment is not active. Run:
```bash
conda activate deepevolve
python run.py
```

**`conda: command not found`**  
Restart your terminal after running `setup.sh` for the first time:
```bash
exec bash
conda activate deepevolve
python run.py
```

**Build failed during baseline run**  
Your algorithm has a compile error in the monorepo. Fix it first, then re-run.

**Build failures during evolution (not baseline)**  
When the LLM generates code that fails to compile, DeepEvolve automatically attempts to fix it
using a debugger model (up to `max_debug_retry` attempts, default 5). You will see messages like:
```
Retrying after debugging (attempt 2/5)...
```
If all retry attempts fail, that iteration is discarded and DeepEvolve moves on to the next one —
no harm done, the best program so far is preserved. This is normal behaviour; the LLM is not
perfect and will occasionally produce uncompilable code. Simply let it continue running.

**`RUST_CODE is IDENTICAL to original`**  
DeepEvolve generated code but the diff didn't apply to `RUST_CODE`. This can happen if the LLM  
used a SEARCH block that didn't match exactly. Delete the run and try again — a different idea  
will be generated next time.

**Every iteration scores the same**  
Check the diagnostic line:
- `OK: RUST_CODE modified (390 -> 516 lines)` — evolution happened, score is genuine
- `WARNING: RUST_CODE is IDENTICAL` — evolution failed silently, delete and restart

---

## Acknowledgements

This project is built on:

**DeepEvolve** by Liu et al. (2025)  
[https://github.com/liugangcode/deepevolve](https://github.com/liugangcode/deepevolve)

```bibtex
@article{liu2025scientific,
  title={Scientific Algorithm Discovery by Augmenting AlphaEvolve with Deep Research},
  author={Liu, Gang and Zhu, Yihan and Chen, Jie and Jiang, Meng},
  journal={arXiv preprint arXiv:2510.06056},
  year={2025}
}
```

**TIG (The Innovation Game)**  
[https://tig.foundation](https://tig.foundation)  
[https://github.com/tig-foundation/tig-monorepo](https://github.com/tig-foundation/tig-monorepo)

---

*A community tool for TIG algorithm evolution.*
