# TIG Job Scheduling - DeepEvolve

An automated algorithm evolution system for the **TIG Job Scheduling challenge**.  
Uses [DeepEvolve](https://github.com/liugangcode/deepevolve) to research, implement and evaluate  
algorithmic improvements to your Rust algorithm — automatically, iteration by iteration.

---

## How it works

1. **You provide** your existing algorithm in the TIG monorepo
2. **You choose** which single algorithm file or algorithm module file to evolve, which tracks to test, and how many iterations to run
3. **You fill in** `ideas.md` with your expert knowledge and directions
4. **DeepEvolve** researches academic papers and recent work, generates a novel implementation idea, writes the Rust code, builds it via Docker, tests it, and reports the result
5. **Repeat** — each iteration builds on the best result so far

---

## Prerequisites

- Ubuntu / WSL2
- Docker (installed and running)
- `tig-monorepo` cloned locally, with your algorithm placed in the correct location:
  - **Single-file algorithm:** `tig-monorepo/tig-algorithms/src/job_scheduling/my_algorithm.rs`
  - **Modular algorithm:** `tig-monorepo/tig-algorithms/src/job_scheduling/my_algorithm/` (its own named directory)

If you don't have `tig-monorepo`:
```bash
git clone https://github.com/tig-foundation/tig-monorepo.git
```

---

## Installation

```bash
git clone https://github.com/rootztigmod/tig-js-evolve.git
cd tig-js-evolve
./setup.sh
```

`setup.sh` handles everything automatically:
- Installs Miniconda if not present
- Creates a `deepevolve` conda environment (Python 3.11)
- Installs all dependencies
- Locates your `tig-monorepo`
- Collects and verifies your API key(s) — stored only in `.env`, never committed to git
- Writes a `.env` file

> **Important:** After setup completes, you must activate the conda environment  
> **every time** you open a new terminal:
> ```bash
> conda activate deepevolve
> ```

---

## Placing your algorithm

Your algorithm must exist in the TIG monorepo under `tig-monorepo/tig-algorithms/src/job_scheduling/`.

Two layouts are supported:

**Single-file algorithm** — the entire algorithm in one `.rs` file:
```
job_scheduling/
├── mod.rs              ← contains: pub mod my_algorithm;
└── my_algorithm.rs     ← entire algorithm in one file
```

**Modular algorithm** — split across multiple files in its own named directory:
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

> **Track vs module detection:** The launcher looks for files whose names exactly match the five  
> known TIG track IDs: `flow_shop.rs`, `hybrid_flow_shop.rs`, `job_shop.rs`, `fjsp_medium.rs`,  
> `fjsp_high.rs`. If any of these are found they are listed as track-specific files for  
> single-track evolution.  
>  
> **This detection is name-based.** If your algorithm uses different filenames (e.g. `solver.rs`  
> containing all track logic, or `track1.rs`), none will be detected as track files. In that case  
> the launcher skips the track/module split and lists all `.rs` files as module files — every file  
> is assumed to affect all tracks simultaneously.  
>  
> `mod.rs` is always excluded from the file list regardless of naming.

---

### ⚠️ Required: populate `initial_algorithm/`

You **must** copy your algorithm's original, unmodified `.rs` files into the `initial_algorithm/` folder, **in their own named subfolder**:

**Single-file algorithm:**
```
tig-js-evolve/
└── initial_algorithm/
    └── my_algorithm/
        └── my_algorithm.rs
```

**Modular algorithm:**
```
tig-js-evolve/
└── initial_algorithm/
    └── my_algorithm/
        ├── solver.rs
        ├── infra.rs
        ├── flow_shop.rs
        ├── fjsp_high.rs
        └── ...
```

**Why this matters:** Before every baseline evaluation, `run.py` automatically restores these files to the monorepo. This guarantees the baseline is always measured against the true original code — not a leftover evolved version from a previous run. If `initial_algorithm/` contains modified files, your baseline will be wrong and all quality deltas will be meaningless.

> Keep `initial_algorithm/` as a permanent read-only reference. Never overwrite these files with evolved versions.

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

  1) Evolve a single file
  2) Single file algorithm (do not use this option if your algorithm is modular)

  Choose evolution mode [1-2]: 1

  Files available for evolution:

  1) fjsp_high        (fjsp_high.rs)
  2) flow_shop        (flow_shop.rs)
  ...
  6) infra.rs         (shared module - affects all tracks)

  Which file to evolve? [1-6]: 1

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

  Select provider [1-2]: 2
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
- **Option 3** — Delete a previous run (asks for confirmation before deleting)

---

## Providing your ideas (important)

Before each run, edit `ideas.md` in the project root.  
This is your expert guidance to the AI — the more specific, the better results.

```
ideas.md
├── Section 1: Fixed Context  (auto-used, rarely edit)
│   - Problem description, track types, Rust rules
└── Section 2: Your Ideas     (edit before EVERY run)
    - Which algorithm/file you are targeting
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

Both OpenAI and Anthropic are supported. You are asked which to use during setup and at each run.

| Role | OpenAI | Anthropic | Notes |
|------|--------|-----------|-------|
| Planner | gpt-4o-mini | claude-haiku-4-5 | Cheap - structured output |
| Searcher | gpt-4o-mini | gpt-4o-mini | Web search (always OpenAI) |
| Writer | gpt-4o | claude-sonnet-4-6 | Research report - most important |
| Developer | gpt-4o | claude-sonnet-4-6 | Rust code generation |
| Debugger | gpt-4o-mini | claude-haiku-4-5 | Compile error fixing |

> **Anthropic users:** The web search role requires a secondary OpenAI key (`gpt-4o-mini`).  
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
The LLM returned code but it was identical to the current version. DeepEvolve will move on to
the next iteration automatically with a different idea.

**Every iteration scores the same**  
Check the diagnostic line:
- `OK: RUST_CODE modified (390 -> 516 lines)` — evolution happened, score is genuine
- `INFO: RUST_CODE line count unchanged` — the LLM made no change, or the change was reverted

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
