"""
TIG Job Scheduling - DeepEvolve Launcher

Run this script every time you want to start or resume an evolution run.
Reads configuration from .env (created by setup.sh).
"""

import json
import os
import sys

# ─── Environment check ────────────────────────────────────────────────────────
_conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
if _conda_env != "deepevolve":
    print(f"\033[1;33mWarning: conda environment is '{_conda_env or 'not active'}' - expected 'deepevolve'.\033[0m")
    print("Run:  conda activate deepevolve && python run.py")
    print("Continuing anyway - imports may fail if dependencies are missing.\n")
import shutil
import subprocess
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent.resolve()
ENV_FILE      = SCRIPT_DIR / ".env"
IDEAS_FILE    = SCRIPT_DIR / "ideas.md"
EVALUATOR_DIR = SCRIPT_DIR / "evaluator"
DEEPEVOLVE_DIR = SCRIPT_DIR / "deepevolve"
BACKUPS_DIR   = SCRIPT_DIR / "backups"

TRACKS = [
    "flow_shop",
    "hybrid_flow_shop",
    "job_shop",
    "fjsp_medium",
    "fjsp_high",
]

TRACK_TO_FILE = {
    "flow_shop":         "flow_shop.rs",
    "hybrid_flow_shop":  "hybrid_flow_shop.rs",
    "job_shop":          "job_shop.rs",
    "fjsp_medium":       "fjsp_medium.rs",
    "fjsp_high":         "fjsp_high.rs",
}

DOCKER_IMAGE = "ghcr.io/tig-foundation/tig-monorepo/job_scheduling/dev:0.0.5"

# ─── Colours ──────────────────────────────────────────────────────────────────
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def c(colour, text):
    return f"{colour}{text}{NC}"

# ─── Env loading ──────────────────────────────────────────────────────────────
def load_env() -> dict:
    if not ENV_FILE.exists():
        print(c(RED, "Error: .env not found. Please run setup.sh first."))
        sys.exit(1)
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def apply_env(env: dict) -> None:
    for k, v in env.items():
        os.environ.setdefault(k, v)


# ─── Menu helpers ─────────────────────────────────────────────────────────────
def prompt_choice(prompt: str, options: list, allow_multi: bool = False) -> list:
    for i, opt in enumerate(options, 1):
        print(f"  {c(BOLD, str(i))}) {opt}")
    print()
    while True:
        raw = input(f"  {prompt}: ").strip()
        if not raw:
            continue
        try:
            if allow_multi and raw.lower() == "a":
                return list(range(len(options)))
            parts = [int(x.strip()) for x in raw.replace(",", " ").split()]
            if all(1 <= p <= len(options) for p in parts):
                return [p - 1 for p in parts]
        except ValueError:
            pass
        print(c(YELLOW, f"  Please enter a number between 1 and {len(options)}."))


def prompt_int(prompt: str, default: int, min_val: int = 1, max_val: int = 100000) -> int:
    while True:
        raw = input(f"  {prompt} [default {default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
        except ValueError:
            pass
        print(c(YELLOW, f"  Please enter a number between {min_val} and {max_val}."))


# ─── Algorithm detection ──────────────────────────────────────────────────────
def detect_algorithms(tig_path: str) -> list:
    """
    Scan tig-algorithms/src/job_scheduling/ and return list of detected algorithms.
    Each entry: {name, type, path, files}
      type = "single"   -> single .rs file alongside mod.rs
      type = "modular"  -> subdirectory with its own mod.rs

    Aborts if both a single-file <name>.rs AND a modular <name>/ directory exist for
    the same algorithm name - the monorepo cannot have both simultaneously.
    """
    jss_dir = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling"
    if not jss_dir.exists():
        print(c(RED, f"Error: {jss_dir} not found."))
        sys.exit(1)

    algorithms = []

    SKIP_NAMES = {"mod.rs", "test", "template", "template.rs", "template.md"}

    for entry in sorted(jss_dir.iterdir()):
        if entry.name in SKIP_NAMES:
            continue
        if entry.name.startswith("deepevolve_"):
            continue
        if entry.is_dir() and (entry / "mod.rs").exists():
            rs_files = sorted(f.name for f in entry.glob("*.rs") if f.name != "mod.rs")
            algorithms.append({
                "name":  entry.name,
                "type":  "modular",
                "path":  entry,
                "files": rs_files,
            })
        elif entry.suffix == ".rs":
            algorithms.append({
                "name":  entry.stem,
                "type":  "single",
                "path":  entry,
                "files": [entry.name],
            })

    # Check for name collisions (e.g. both test.rs and test/ exist)
    seen = {}
    for algo in algorithms:
        name = algo["name"]
        if name in seen:
            other = seen[name]
            print()
            print(c(RED, f"  ERROR: Algorithm name conflict detected for '{name}'"))
            print(c(RED, f"    Found: {other['type']} at {other['path']}"))
            print(c(RED, f"    Found: {algo['type']} at {algo['path']}"))
            print()
            print(c(YELLOW, f"  The monorepo cannot have both '{name}.rs' (single-file) and"))
            print(c(YELLOW, f"  '{name}/' (modular) at the same time."))
            print(c(YELLOW, f"  Delete one before running. If you converted '{name}' from"))
            print(c(YELLOW, f"  single-file to modular, remove '{name}.rs' from the"))
            print(c(YELLOW, f"  job_scheduling/ directory."))
            print()
            sys.exit(1)
        seen[name] = algo

    return algorithms


def detect_track_files(algo: dict) -> dict:
    """
    For a modular algorithm, detect which .rs files correspond to known tracks.
    Returns {track_name: filename} for matched tracks.
    """
    matched = {}
    for track, fname in TRACK_TO_FILE.items():
        if fname in algo["files"]:
            matched[track] = fname
    return matched


# ─── Ideas loading ────────────────────────────────────────────────────────────
def load_ideas() -> str:
    if not IDEAS_FILE.exists():
        print(c(YELLOW, "  Warning: ideas.md not found. AI will run without your guidance."))
        return ""
    content = IDEAS_FILE.read_text(encoding="utf-8")
    if "[FILL IN" in content:
        print(c(YELLOW, "\n  Warning: ideas.md still has unfilled [FILL IN] placeholders."))
        print(c(YELLOW,   "  Consider editing ideas.md before this run for better results."))
        input(f"  {c(BOLD, 'Press Enter to continue anyway, or Ctrl+C to edit first...')}")
    return content


# ─── Checkpoint detection ─────────────────────────────────────────────────────
def find_checkpoints() -> list:
    workspace = DEEPEVOLVE_DIR / "examples"
    checkpoints = []
    if not workspace.exists():
        return checkpoints
    for problem_dir in sorted(workspace.iterdir()):
        if not problem_dir.name.startswith("job_scheduling"):
            continue
        meta_file = problem_dir / ".run_meta.json"
        if not meta_file.exists():
            continue
        ckpt_dir = problem_dir / "ckpt"
        existing_ckpts = sorted(ckpt_dir.glob("checkpoint_*"), key=lambda p: p.name) if ckpt_dir.exists() else []
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            continue
        checkpoints.append({
            "problem":   problem_dir.name,
            "path":      problem_dir,
            "iteration": len(existing_ckpts),
            "meta":      meta,
        })
    return checkpoints


def display_checkpoint_menu(checkpoints: list) -> tuple:
    """Returns (problem_name, resume_flag). Loops until user picks resume or new run."""
    while True:
        # Re-scan checkpoints each loop so the list stays accurate after deletions
        checkpoints = find_checkpoints()
        if not checkpoints:
            print(c(YELLOW, "\n  All previous runs deleted."))
            return None, False

        print(c(CYAN, "\n  Previous run(s) detected:\n"))
        for i, ckpt in enumerate(checkpoints, 1):
            meta = ckpt["meta"]
            module  = meta.get("evolve_module", "unknown")
            tracks  = ", ".join(meta.get("tracks", []))
            iters   = meta.get("max_iterations", "?")
            current = ckpt["iteration"]
            baselines = meta.get("baselines", {})
            print(f"  {c(BOLD, str(i))}) {ckpt['problem']}")
            print(f"       Algorithm  : {meta.get('algo_name', '?')}")
            print(f"       Evolving   : {module}")
            print(f"       Tracks     : {tracks}")
            print(f"       Progress   : iteration {current}/{iters}")
            if baselines:
                avg = sum(baselines.values()) / len(baselines)
                print(f"       Baseline   : avg {avg:.0f}")
            print()

        options = [ckpt["problem"] for ckpt in checkpoints] + ["Start a new run", "Delete a previous run"]
        choice = prompt_choice("Enter choice", options)[0]

        if choice < len(checkpoints):
            return checkpoints[choice]["problem"], True
        elif choice == len(checkpoints):
            return None, False
        else:
            print()
            del_choice = prompt_choice("Which run to delete?", [c_["problem"] for c_ in checkpoints])[0]
            target = checkpoints[del_choice]["path"]
            print()
            print(c(YELLOW, f"  About to delete: {c(BOLD, target.name)}"))
            confirm = input(f"  {c(BOLD, 'Are you sure? [y/N]: ')}").strip().lower()
            if confirm in ("y", "yes"):
                shutil.rmtree(target, ignore_errors=True)
                print(c(GREEN, f"  Deleted {target.name}."))
            else:
                print(c(YELLOW, "  Cancelled."))


# ─── Initial baseline run ─────────────────────────────────────────────────────
def run_baseline(algo: dict, tracks: list, nonces: int, workers: int, tig_path: str, hyperparams: str = "null") -> dict:
    """
    Build and test the algorithm as-is to establish per-track baselines.
    Returns {track: quality} dict.
    """
    print()
    print(c(CYAN, "=" * 55))
    print(c(CYAN, "  Running initial baseline evaluation..."))
    print(c(CYAN, "=" * 55))

    algo_name = algo["name"]

    # Restore all original .rs files to the monorepo before baselining.
    # A previous run may have left evolved files in place, which would give
    # a false baseline score.
    # Files are stored under initial_algorithm/<algo_name>/ (one subdir per algorithm).
    initial_algo_dir = SCRIPT_DIR / "initial_algorithm" / algo_name
    algo_src_in_monorepo = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling" / algo_name
    if initial_algo_dir.is_dir() and algo_src_in_monorepo.is_dir():
        # Modular algorithm: restore all .rs files into the algorithm subdirectory
        for src_file in initial_algo_dir.glob("*.rs"):
            dest = algo_src_in_monorepo / src_file.name
            shutil.copy2(src_file, dest)
            print(f"  Restored original: {src_file.name}")
    elif initial_algo_dir.is_dir():
        # Single-file algorithm: restore the .rs file into the top-level jss directory
        jss_dir = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling"
        for src_file in initial_algo_dir.glob("*.rs"):
            dest = jss_dir / src_file.name
            shutil.copy2(src_file, dest)
            print(f"  Restored original: {src_file.name}")
    else:
        print(c(YELLOW, f"  Warning: initial_algorithm/{algo_name}/ not found - skipping restore"))

    # Ensure top-level mod.rs points to this algorithm before building
    top_mod = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling" / "mod.rs"
    top_mod.write_text(f"pub mod {algo_name};\n", encoding="utf-8")
    print(f"  Set mod.rs -> pub mod {algo_name};")

    cmd_build = [
        "docker", "run", "--rm",
        "-v", f"{tig_path}:/app",
        DOCKER_IMAGE,
        "bash", "-c", f"cargo clean && build_algorithm {algo_name}",
    ]
    print(f"  Building {algo_name}...")
    result = subprocess.run(cmd_build, capture_output=True, text=True,
                            timeout=300, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        print(c(RED, "  Build failed during baseline run:"))
        print(result.stderr[-1000:])
        sys.exit(1)
    print(c(GREEN, "  Build successful."))

    baselines = {}
    for track in tracks:
        track_id = f"n=50,s={track}"
        print(f"  Testing {track} ({nonces} nonces, hyperparams={hyperparams})...", end=" ", flush=True)
        cmd_test = [
            "docker", "run", "--rm",
            "-v", f"{tig_path}:/app",
            DOCKER_IMAGE,
            "test_algorithm", algo_name, track_id, hyperparams,
            "--nonces", str(nonces), "--workers", str(workers),
        ]
        res = subprocess.run(cmd_test, capture_output=True, text=True,
                             timeout=600, stdin=subprocess.DEVNULL)
        stdout = res.stdout + res.stderr
        quality = 0.0
        for line in reversed(stdout.splitlines()):
            if "avg_quality:" in line and "#finished:" in line:
                try:
                    quality = float(line.split("avg_quality:")[-1].strip()
                                    .replace(",", "").split()[0])
                    break
                except Exception:
                    pass
        baselines[track] = quality
        print(c(GREEN, f"quality = {quality:.0f}"))

    avg = sum(baselines.values()) / len(baselines)
    print()
    print(f"  {c(BOLD, 'Baseline avg_quality:')} {avg:.0f}")
    print(c(CYAN, "=" * 55))
    return baselines


# ─── Evolution menu ───────────────────────────────────────────────────────────
def evolution_menu(tig_path: str, env: dict) -> dict:
    algorithms = detect_algorithms(tig_path)
    if not algorithms:
        print(c(RED, f"No algorithms found in {tig_path}/tig-algorithms/src/job_scheduling/"))
        sys.exit(1)

    print(c(CYAN, "\n  Algorithms found in tig-monorepo:\n"))
    algo_labels = [f"{a['name']}  ({a['type']})" for a in algorithms]
    algo_idx = prompt_choice("Which algorithm do you want to evolve?", algo_labels)[0]
    algo = algorithms[algo_idx]
    print()

    evolve_mode = "full"
    evolve_module = None
    evolve_tracks = TRACKS

    if algo["type"] == "modular":
        track_files = detect_track_files(algo)
        all_rs_files = [f for f in algo["files"] if f != "mod.rs"]

        if track_files:
            print(c(CYAN, "  Evolution mode:\n"))
            mode_options = ["Evolve a single file", "Single file algorithm (do not use this option if your algorithm is modular)"]
            mode_idx = prompt_choice("Choose evolution mode", mode_options)[0]
            print()

            if mode_idx == 0:
                evolve_mode = "single_track"
                print(c(CYAN, "  Files available for evolution:\n"))
                track_names = sorted(track_files.keys())
                sorted_track_files = [track_files[t] for t in track_names]
                track_options = [f"{t}  ({track_files[t]})" for t in track_names]
                non_track = [f for f in all_rs_files if f not in track_files.values()]
                if non_track:
                    track_options += [f"{f}  (shared module - affects all tracks)" for f in non_track]
                    all_evolvable = sorted_track_files + non_track
                else:
                    all_evolvable = sorted_track_files
                t_idx = prompt_choice("Which file to evolve?", track_options)[0]
                evolve_module = all_evolvable[t_idx]
                matched_track = [t for t, f in track_files.items() if f == evolve_module]
                evolve_tracks = matched_track if matched_track else TRACKS
                print()
            else:
                evolve_mode = "full"
                evolve_module = None
        else:
            print(c(CYAN, "  No track-specific files detected.\n"))
            print(c(CYAN, "  Module files available for evolution:\n"))
            evolve_mode = "single_track"
            module_options = [f"{f}  (shared module - affects all tracks)" for f in all_rs_files]
            m_idx = prompt_choice("Which module file to evolve?", module_options)[0]
            evolve_module = all_rs_files[m_idx]
            evolve_tracks = TRACKS
            print(c(YELLOW, f"  Note: {evolve_module} is shared - changes affect all tracks.\n"))

    print(c(CYAN, "  Which tracks to test?\n"))
    track_options = TRACKS + ["All tracks"]
    track_indices = prompt_choice(
        "Select tracks (comma-separated or 'a' for all)",
        track_options, allow_multi=True,
    )
    if len(TRACKS) in track_indices:
        selected_tracks = TRACKS
    else:
        selected_tracks = [TRACKS[i] for i in track_indices if i < len(TRACKS)]
    print()

    nonces    = prompt_int("Nonces per track", default=100, min_val=1,  max_val=10000)
    workers   = prompt_int("Workers",          default=16,  min_val=1,  max_val=256)
    max_iters = prompt_int("Max iterations",   default=20,  min_val=1,  max_val=500)
    print()

    print(c(CYAN, "  Hyperparameters (passed to test_algorithm instead of null):\n"))
    print(c(YELLOW, "  Leave blank for null. String values must be quoted in strict JSON."))
    print(c(YELLOW, '  Examples: {"flow":"flow_shop"}   or   {"flow":"flow_shop","depth":3}'))
    print(c(YELLOW,  "  This is passed directly to test_algorithm - it must be exactly correct.\n"))
    raw_hyper = input(f"  {c(BOLD, 'Hyperparameters [default: null]: ')}").strip()
    hyperparams = raw_hyper if raw_hyper else "null"
    print()

    print(c(CYAN, "  LLM Provider:\n"))
    provider_options = ["OpenAI (GPT)", "Anthropic (Claude)"]
    default_provider = env.get("LLM_PROVIDER", "openai")
    default_idx = 1 if default_provider == "claude" else 0
    print(f"  (default: {provider_options[default_idx]})\n")
    provider_idx = prompt_choice("Select provider", provider_options)[0]
    provider = "claude" if provider_idx == 1 else "openai"
    print()

    # ── Confirmation summary ──
    print(c(CYAN, "  Ready to launch:\n"))
    print(f"    Algorithm  : {c(BOLD, algo['name'])} ({algo['type']})")
    print(f"    Evolving   : {c(BOLD, evolve_module or 'all files')}")
    print(f"    Tracks     : {c(BOLD, ', '.join(selected_tracks))}")
    print(f"    Nonces     : {c(BOLD, str(nonces))}")
    print(f"    Workers    : {c(BOLD, str(workers))}")
    print(f"    Iterations : {c(BOLD, str(max_iters))}")
    print(f"    Hyperparams: {c(BOLD, hyperparams)}")
    print(f"    Provider   : {c(BOLD, provider)}")
    print()
    confirm = input(f"  {c(BOLD, 'Confirm? [Y/n]: ')}").strip().lower()
    if confirm in ("n", "no"):
        print(c(YELLOW, "  Cancelled. Run again to make new selections."))
        sys.exit(0)
    print()

    return {
        "algo_name":      algo["name"],
        "algo_type":      algo["type"],
        "algo_path":      str(algo["path"]),
        "evolve_mode":    evolve_mode,
        "evolve_module":  evolve_module,
        "tracks":         selected_tracks,
        "nonces":         nonces,
        "workers":        workers,
        "max_iterations": max_iters,
        "hyperparams":    hyperparams,
        "provider":       provider,
    }


# ─── Problem name ─────────────────────────────────────────────────────────────
def make_problem_name(params: dict) -> str:
    algo  = params["algo_name"]
    if params["evolve_mode"] == "single_track" and params["evolve_module"]:
        mod = params["evolve_module"].replace(".rs", "")
        return f"job_scheduling_{algo}_{mod}"
    return f"job_scheduling_{algo}_full"


# ─── Generate DeepEvolve problem files ────────────────────────────────────────
def generate_problem_files(params: dict, problem_name: str, env: dict) -> Path:
    problem_dir      = DEEPEVOLVE_DIR / "examples" / problem_name
    initial_code_dir = problem_dir / "initial_code"
    initial_code_dir.mkdir(parents=True, exist_ok=True)

    tig_path     = env.get("TIG_MONOREPO_PATH", "~/tig-monorepo")
    algo_name    = params["algo_name"]
    algo_type    = params["algo_type"]
    evolve_mode  = params["evolve_mode"]
    evolve_module = params["evolve_module"]
    tracks       = params["tracks"]
    nonces       = params["nonces"]
    hyperparams  = params.get("hyperparams", "null")
    baselines    = params.get("baselines", {})
    ideas        = load_ideas()

    description = (
        f"TIG Job Scheduling Challenge. "
        f"Algorithm: {algo_name} ({algo_type}). "
        f"Evolving file: {evolve_module or 'all files'}. "
        f"Tracks being tested: {', '.join(tracks)}. "
        f"Objective: minimise makespan. Quality = 1.0 - make_span/greedy_makespan (higher is better). "
        f"Rust rules: ASCII only, no external crates beyond anyhow/rand/serde_json/tig_challenges, "
        f"keep 'use super::types::*' and 'use super::infra::*' in all solver files."
    )

    if baselines:
        avg = sum(baselines.values()) / len(baselines)
        bl_str = ", ".join(f"{t}: {q:.0f}" for t, q in baselines.items())
        description += f"\n\nACTUAL BASELINE (this algorithm, measured now): avg={avg:.0f} | {bl_str}"

    if ideas:
        description += f"\n\n--- USER GUIDANCE ---\n{ideas}"

    info = {
        "problem": {
            "name":        problem_name,
            "description": description,
            "metric":      "avg_quality",
            "interface":   "deepevolve_interface.py",
        },
        "initial_idea": {
            "title":      f"Improve {evolve_module or algo_name} for TIG Job Scheduling",
            "content":    (
                f"Research and implement algorithmic improvements to reduce makespan "
                f"on the selected tracks. See USER GUIDANCE for specific directions."
            ),
            "supplement": (
                "Job scheduling references (do not assume any of these are already implemented - "
                "read the provided Rust code to determine what is currently in place): "
                "Priority dispatching rules: Pinedo (2016) Scheduling: Theory, Algorithms, and Systems. "
                "Tabu search for JSS: Nowicki & Smutnicki (1996). "
                "Iterated greedy: Ruiz & Stutzle (2007). "
                "FJSP metaheuristics: Brandimarte (1993). "
                "ILS: Lourenco et al. (2003)."
            ),
        },
    }
    (problem_dir / "info.json").write_text(json.dumps(info, indent=4))

    meta = {
        "algo_name":      algo_name,
        "algo_type":      algo_type,
        "evolve_mode":    evolve_mode,
        "evolve_module":  evolve_module,
        "tracks":         tracks,
        "nonces":         nonces,
        "workers":        params.get("workers", 16),
        "max_iterations": params["max_iterations"],
        "hyperparams":    hyperparams,
        "provider":       params.get("provider", "openai"),
        "baselines":      baselines,
    }
    (problem_dir / ".run_meta.json").write_text(json.dumps(meta, indent=4))

    # Write initial_metrics.json from our baseline so DeepEvolve skips initial evaluation
    if baselines:
        avg = sum(baselines.values()) / len(baselines)
        initial_metrics = {
            "combined_score":            avg,
            "avg_quality":               avg,
            "baseline_avg":              avg,
            "improvement_over_baseline": 0.0,
            "n_tracks_improved":         0.0,
            "total_time_s":              0.0,
            "evolved_module":            evolve_module or "full",
        }
        for t, q in baselines.items():
            initial_metrics[f"quality_{t}"]   = q
            initial_metrics[f"time_{t}"]      = 0.0
            initial_metrics[f"delta_pct_{t}"] = 0.0
        (problem_dir / "initial_metrics.json").write_text(json.dumps(initial_metrics))

    interface_src = EVALUATOR_DIR / "deepevolve_interface.py"
    rust_code_src = EVALUATOR_DIR / "rust_code.py"
    if not interface_src.exists():
        print(c(RED, "Error: evaluator/deepevolve_interface.py not found."))
        sys.exit(1)
    if not rust_code_src.exists():
        print(c(RED, "Error: evaluator/rust_code.py not found."))
        sys.exit(1)

    baseline_repr = json.dumps(baselines, indent=4)
    track_repr    = json.dumps(tracks)

    # ── Read the Rust source to embed in rust_code.py ──
    # DeepEvolve only evolves .py files. The Rust code lives in rust_code.py as
    # RUST_CODE = """...""". The interface imports it from there - it never
    # touches the Rust code itself, so the LLM cannot accidentally break the
    # Python infrastructure.
    algo_src = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling"
    if algo_type == "modular":
        algo_src = algo_src / algo_name

    rust_code = ""
    if evolve_module:
        rs_path = algo_src / evolve_module
        if rs_path.exists():
            rust_code = rs_path.read_text(encoding="utf-8")
        else:
            print(c(YELLOW, f"  Warning: {rs_path} not found - RUST_CODE will be empty"))
    elif algo_type == "single":
        # Single-file algorithm: the whole .rs file is the algorithm
        rs_path = Path(tig_path) / "tig-algorithms" / "src" / "job_scheduling" / f"{algo_name}.rs"
        if rs_path.exists():
            rust_code = rs_path.read_text(encoding="utf-8")
        else:
            print(c(YELLOW, f"  Warning: {rs_path} not found - RUST_CODE will be empty"))

    # Write rust_code.py (the file DeepEvolve evolves)
    rc_content = rust_code_src.read_text()
    rc_content = rc_content.replace("__RUST_CODE__", rust_code)
    (initial_code_dir / "rust_code.py").write_text(rc_content)

    # Write deepevolve_interface.py (the static infrastructure file)
    content = interface_src.read_text()
    content = content.replace("__ALGO_NAME__",     algo_name)
    content = content.replace("__ALGO_TYPE__",     algo_type)
    content = content.replace("__EVOLVE_MODE__",   evolve_mode)
    content = content.replace("__EVOLVE_MODULE__", evolve_module or "")
    content = content.replace("__TRACKS__",        track_repr)
    content = content.replace("__NONCES__",        str(nonces))
    content = content.replace("__WORKERS__",       str(params.get("workers", 16)))
    content = content.replace("__HYPERPARAMS__",   hyperparams.replace('"', '\\"'))
    content = content.replace("__TIG_PATH__",      tig_path)
    content = content.replace("__DOCKER_IMAGE__",  DOCKER_IMAGE)
    content = content.replace("__BASELINES__",     baseline_repr)
    content = content.replace("__BACKUPS_DIR__",   str(BACKUPS_DIR))
    content = content.replace("__RUST_CODE_ORIGINAL_LINES__", str(len(rust_code.splitlines())))

    (initial_code_dir / "deepevolve_interface.py").write_text(content)

    return problem_dir


# ─── Launch DeepEvolve ────────────────────────────────────────────────────────
def launch_deepevolve(problem_name: str, params: dict, env: dict, resume: bool) -> None:
    provider  = params.get("provider") or env.get("LLM_PROVIDER", "openai")
    max_iters = params.get("max_iterations", 20)
    module    = params.get("evolve_module") or params.get("algo_name", "algorithm")

    # Save a checkpoint every ~20% of iterations, minimum every 1
    checkpoint_interval = max(1, max_iters // 5)

    query = (
        f"Improve the {module} Rust solver for the TIG Job Scheduling challenge "
        f"to reduce makespan and increase quality score on tracks: "
        f"{', '.join(params.get('tracks', TRACKS))}. "
        f"Research recent advances in combinatorial optimisation and job shop scheduling "
        f"metaheuristics and implement a concrete, focused improvement. "
        f"Do not add external crate dependencies. "
        f"See the problem description for full constraints and user guidance."
    )

    cmd = [
        sys.executable,  # uses the active conda env's python
        str(DEEPEVOLVE_DIR / "deepevolve.py"),
        f"query='{query}'",
        f"problem={problem_name}",
        f"workspace=examples",
        f"max_iterations={max_iters}",
        f"checkpoint_interval={checkpoint_interval}",
        f"+models={provider}",
    ]

    # If resuming, find and load the latest checkpoint
    if resume:
        ckpt_base = DEEPEVOLVE_DIR / "examples" / problem_name / "ckpt"
        if ckpt_base.exists():
            ckpt_dirs = sorted(
                [d for d in ckpt_base.iterdir() if d.name.startswith("checkpoint_")],
                key=lambda d: int(d.name.split("_")[-1])
            )
            if ckpt_dirs:
                latest_ckpt = ckpt_dirs[-1]
                cmd.append(f"database.db_path={latest_ckpt}")
                print(c(YELLOW, f"  Loading checkpoint: {latest_ckpt.name}"))

    print()
    print(c(CYAN, "=" * 55))
    print(c(CYAN, "  Launching DeepEvolve"))
    print(c(CYAN, f"  Algorithm  : {params.get('algo_name')}"))
    print(c(CYAN, f"  Evolving   : {module}"))
    print(c(CYAN, f"  Tracks     : {', '.join(params.get('tracks', []))}"))
    print(c(CYAN, f"  Nonces     : {params.get('nonces')}"))
    print(c(CYAN, f"  Iterations : {max_iters}"))
    print(c(CYAN, f"  Provider   : {provider}"))
    if resume:
        print(c(YELLOW, "  Resuming from checkpoint"))
    print(c(CYAN, "=" * 55))
    print()

    subprocess.run(cmd, cwd=str(DEEPEVOLVE_DIR), check=False)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print()
    print(c(BOLD, c(CYAN, "=" * 55)))
    print(c(BOLD, c(CYAN, "  TIG Job Scheduling - DeepEvolve Launcher")))
    print(c(BOLD, c(CYAN, "=" * 55)))

    env = load_env()
    apply_env(env)
    tig_path = env.get("TIG_MONOREPO_PATH", "~/tig-monorepo")

    BACKUPS_DIR.mkdir(exist_ok=True)

    checkpoints = find_checkpoints()
    problem_name = None
    resume = False
    params = {}

    if checkpoints:
        problem_name, resume = display_checkpoint_menu(checkpoints)

    if resume and problem_name:
        meta_file = DEEPEVOLVE_DIR / "examples" / problem_name / ".run_meta.json"
        if meta_file.exists():
            params = json.loads(meta_file.read_text())
            print(c(GREEN, f"  Resuming: {problem_name}"))
        else:
            print(c(YELLOW, "  Run metadata not found - starting fresh."))
            resume = False

    if not resume:
        params = evolution_menu(tig_path, env)
        problem_name = make_problem_name(params)

        baselines = run_baseline(
            {"name": params["algo_name"], "type": params["algo_type"]},
            params["tracks"],
            params["nonces"],
            params["workers"],
            tig_path,
            hyperparams=params.get("hyperparams", "null"),
        )
        params["baselines"] = baselines

        generate_problem_files(params, problem_name, env)

    launch_deepevolve(problem_name, params, env, resume)


if __name__ == "__main__":
    main()
