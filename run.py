"""
TIG Job Scheduling - DeepEvolve Launcher

Run this script every time you want to start or resume an evolution run.
Reads configuration from .env (created by setup.sh).
"""

import json
import os
import sys

VERBOSE = "--verbose" in sys.argv

# ─── Environment check ────────────────────────────────────────────────────────
_conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
if _conda_env != "deepevolve":
    print(f"\033[1;33mWarning: conda environment is '{_conda_env or 'not active'}' - expected 'deepevolve'.\033[0m")
    print("Run:  conda activate deepevolve && python run.py")
    print("Continuing anyway - imports may fail if dependencies are missing.\n")
import shutil
import subprocess
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

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

# ─── Colours (kept for non-menu output e.g. baseline, launch banner) ──────────
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def c(colour, text):
    return f"{colour}{text}{NC}"


# ─── Rich helpers ─────────────────────────────────────────────────────────────
def header():
    console.print()
    console.print(Panel(
        "[bold cyan]TIG Job Scheduling  ·  DeepEvolve Launcher[/bold cyan]",
        box=box.DOUBLE_EDGE,
        expand=False,
        padding=(0, 6),
    ))
    console.print()


def section(title: str):
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    console.print("[dim]" + "─" * 50 + "[/dim]")

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
def prompt_int(prompt: str, default: int, min_val: int = 1, max_val: int = 100000) -> int:
    def _validate(val):
        try:
            n = int(val)
            if min_val <= n <= max_val:
                return True
            return f"Enter a number between {min_val} and {max_val}"
        except ValueError:
            return "Please enter a whole number"

    result = inquirer.text(
        message=prompt,
        default=str(default),
        validate=_validate,
        invalid_message="Invalid value",
    ).execute()
    return int(result)


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
        console.print("  [yellow]![/yellow] ideas.md not found — AI will run without your guidance.")
        return ""
    content = IDEAS_FILE.read_text(encoding="utf-8")
    if "[FILL IN" in content:
        console.print()
        console.print(Panel(
            "[yellow]ideas.md still has unfilled [FILL IN] placeholders.[/yellow]\n"
            "Consider editing it before this run for better results.",
            box=box.ROUNDED, padding=(0, 2), expand=False,
        ))
        inquirer.confirm(
            message="Continue anyway?",
            default=True,
        ).execute()
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
        checkpoints = find_checkpoints()
        if not checkpoints:
            console.print("\n[yellow]All previous runs deleted.[/yellow]")
            return None, False

        section("Previous Runs")
        console.print()

        # Build a summary table — tracks shown as count to keep width manageable
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                      padding=(0, 2))
        table.add_column("#",          style="bold", width=3)
        table.add_column("Algorithm",  style="cyan")
        table.add_column("Evolving")
        table.add_column("Tracks",     justify="center")
        table.add_column("Progress",   justify="right")
        table.add_column("Baseline",   justify="right")

        for i, ckpt in enumerate(checkpoints, 1):
            meta      = ckpt["meta"]
            module    = meta.get("evolve_module") or "all files"
            tracks    = meta.get("tracks", [])
            track_str = "all tracks" if len(tracks) == len(TRACKS) else ", ".join(tracks)
            iters     = meta.get("max_iterations", "?")
            current   = ckpt["iteration"]
            baselines = meta.get("baselines", {})
            avg_bl    = f"{sum(baselines.values())/len(baselines):.0f}" if baselines else "—"
            table.add_row(
                str(i),
                meta.get("algo_name", "?"),
                module,
                track_str,
                f"{current}/{iters}",
                avg_bl,
            )

        console.print(Panel(table, box=box.ROUNDED, padding=(0, 1), expand=False))

        # Build choices
        choices = [
            Choice(("resume", ckpt["problem"]),
                   name=f"Resume  {ckpt['problem']}")
            for ckpt in checkpoints
        ]
        choices += [
            Separator(),
            Choice(("new",    None), name="Start a new run"),
            Choice(("delete", None), name="Delete a previous run"),
        ]

        action, value = inquirer.select(
            message="What would you like to do?",
            choices=choices,
        ).execute()

        if action == "resume":
            return value, True
        elif action == "new":
            return None, False
        else:
            del_choices = [
                Choice(ckpt["path"], name=ckpt["problem"])
                for ckpt in checkpoints
            ]
            target = inquirer.select(
                message="Which run do you want to delete?",
                choices=del_choices,
            ).execute()
            console.print()
            confirmed = inquirer.confirm(
                message=f"Delete '{target.name}'? This cannot be undone.",
                default=False,
            ).execute()
            if confirmed:
                shutil.rmtree(target, ignore_errors=True)
                console.print(f"  [green]✓[/green] Deleted [bold]{target.name}[/bold].")
            else:
                console.print("  [yellow]Cancelled.[/yellow]")


# ─── Initial baseline run ─────────────────────────────────────────────────────
def run_baseline(algo: dict, tracks: list, nonces: int, workers: int, tig_path: str, hyperparams: dict = None) -> dict:
    """
    Build and test the algorithm as-is to establish per-track baselines.
    Returns {track: quality} dict.
    """
    console.print()
    console.print(Panel(
        "[cyan]Running initial baseline evaluation...[/cyan]",
        box=box.ROUNDED, padding=(0, 2), expand=False,
    ))

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

    if hyperparams is None:
        hyperparams = {t: "null" for t in tracks}

    baselines = {}
    for track in tracks:
        track_id   = f"n=50,s={track}"
        track_hyper = hyperparams.get(track, "null")
        print(f"  Testing {track} ({nonces} nonces, hyperparams={track_hyper})...", end=" ", flush=True)
        cmd_test = [
            "docker", "run", "--rm",
            "-v", f"{tig_path}:/app",
            DOCKER_IMAGE,
            "test_algorithm", algo_name, track_id, track_hyper,
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
    console.print()
    console.print(Panel(
        f"[bold]Baseline avg_quality:[/bold]  [green]{avg:.0f}[/green]",
        box=box.ROUNDED, padding=(0, 2), expand=False,
    ))
    return baselines


# ─── Evolution menu ───────────────────────────────────────────────────────────
def evolution_menu(tig_path: str, env: dict) -> dict:
    algorithms = detect_algorithms(tig_path)
    if not algorithms:
        console.print(f"[red]No algorithms found in {tig_path}/tig-algorithms/src/job_scheduling/[/red]")
        sys.exit(1)

    # ── Algorithm ──
    section("Algorithm")
    algo = inquirer.select(
        message="Which algorithm do you want to evolve?",
        choices=[
            Choice(a, name=f"{a['name']}  ({a['type']})")
            for a in algorithms
        ],
    ).execute()

    evolve_mode   = "full"
    evolve_module = None
    evolve_tracks = TRACKS

    # ── File selection (modular only) ──
    if algo["type"] == "modular":
        track_files  = detect_track_files(algo)
        all_rs_files = [f for f in algo["files"] if f != "mod.rs"]

        if track_files:
            section("Evolution Mode")
            mode = inquirer.select(
                message="Choose what to evolve:",
                choices=[
                    Choice("single", name="Evolve a single file"),
                    Choice("full",   name="Evolve full algorithm (all files)"),
                ],
            ).execute()

            if mode == "single":
                evolve_mode = "single_track"
                section("File to Evolve")
                track_names       = sorted(track_files.keys())
                sorted_track_files = [track_files[t] for t in track_names]
                non_track         = [f for f in all_rs_files if f not in track_files.values()]
                all_evolvable     = sorted_track_files + non_track

                file_choices = [
                    Choice(track_files[t], name=f"{t}  ({track_files[t]})")
                    for t in track_names
                ]
                if non_track:
                    file_choices.append(Separator())
                    for f in non_track:
                        file_choices.append(Choice(f, name=f"{f}  (shared — affects all tracks)"))

                evolve_module = inquirer.select(
                    message="Which file to evolve?",
                    choices=file_choices,
                ).execute()
                matched_track = [t for t, f in track_files.items() if f == evolve_module]
                evolve_tracks = matched_track if matched_track else TRACKS
            else:
                evolve_mode   = "full"
                evolve_module = None
        else:
            section("File to Evolve")
            console.print("  [yellow]No track-specific files detected — choose a shared module.[/yellow]\n")
            evolve_mode   = "single_track"
            evolve_module = inquirer.select(
                message="Which module file to evolve?",
                choices=[
                    Choice(f, name=f"{f}  (shared — affects all tracks)")
                    for f in all_rs_files
                ],
            ).execute()
            evolve_tracks = TRACKS
            console.print(f"  [yellow]![/yellow] {evolve_module} is shared — changes affect all tracks.")

    # ── Tracks ──
    section("Tracks to Test")
    selected_tracks = inquirer.checkbox(
        message="Select tracks to test  (space to tick, enter to confirm):",
        choices=[Choice(t, name=t, enabled=True) for t in TRACKS],
        validate=lambda result: len(result) > 0,
        invalid_message="Select at least one track.",
        transformer=lambda result: ", ".join(result),
    ).execute()

    # ── Run parameters ──
    section("Run Parameters")
    nonces    = prompt_int("Nonces per track", default=100, min_val=1,   max_val=10000)
    workers   = prompt_int("Workers",          default=16,  min_val=1,   max_val=256)
    max_iters = prompt_int("Max iterations",   default=20,  min_val=1,   max_val=500)

    # ── Hyperparameters ──
    section("Hyperparameters")

    use_hyperparams = inquirer.confirm(
        message="Use hyperparameters? (if unsure, select No)",
        default=False,
    ).execute()

    def _validate_hyper(val):
        from prompt_toolkit.validation import ValidationError, Validator
        if not val or val.strip() == "":
            return True
        try:
            json.loads(val)
            return True
        except Exception:
            raise ValidationError(
                message='Invalid JSON — e.g. {"flow":"flow_shop"} or leave blank',
                cursor_position=len(val),
            )

    hyperparams = {}
    if use_hyperparams:
        console.print('  [yellow]Enter hyperparameters for each track. Leave blank for null.[/yellow]')
        console.print('  [yellow]Must be exact JSON e.g. {"flow":"flow_shop"} or {"effort":"high"}[/yellow]\n')
        for track in selected_tracks:
            raw = inquirer.text(
                message=f"{track}:",
                default="",
                validate=_validate_hyper,
                invalid_message='Must be valid JSON e.g. {"flow":"flow_shop"} or leave blank',
            ).execute()
            hyperparams[track] = raw.strip() if raw.strip() else "null"
    else:
        for track in selected_tracks:
            hyperparams[track] = "null"

    # ── Provider ──
    section("LLM Provider")
    default_provider = env.get("LLM_PROVIDER", "openai")
    provider_map = {"openai": "OpenAI (GPT)", "claude": "Anthropic (Claude)", "gemini": "Google (Gemini)"}
    provider = inquirer.select(
        message="Which LLM provider?",
        choices=[
            Choice("openai",  name="OpenAI  (GPT)"),
            Choice("claude",  name="Anthropic  (Claude)"),
            Choice("gemini",  name="Google  (Gemini)"),
        ],
        default=default_provider,
    ).execute()

    # ── Confirmation summary ──
    console.print()
    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column(style="bold cyan", no_wrap=True)
    summary.add_column()
    summary.add_row("Algorithm",   f"{algo['name']}  ({algo['type']})")
    summary.add_row("Evolving",    evolve_module or "all files")
    summary.add_row("Tracks",      ", ".join(selected_tracks))
    summary.add_row("Nonces",      str(nonces))
    summary.add_row("Workers",     str(workers))
    summary.add_row("Iterations",  str(max_iters))
    non_null = {t: v for t, v in hyperparams.items() if v != "null"}
    if not non_null:
        hyper_display = "null (all tracks)"
    elif len(non_null) == 1:
        t, v = next(iter(non_null.items()))
        hyper_display = f"{t}: {v}"
    else:
        hyper_display = f"{len(non_null)} tracks with custom hyperparams"
    summary.add_row("Hyperparams", hyper_display)
    summary.add_row("Provider",    provider_map.get(provider, provider))
    console.print(Panel(summary, title="[bold]Ready to Launch[/bold]", box=box.ROUNDED, padding=(0, 2), expand=False))

    confirmed = inquirer.confirm(message="Launch DeepEvolve with these settings?", default=True).execute()
    if not confirmed:
        console.print("[yellow]Cancelled. Run again to make new selections.[/yellow]")
        sys.exit(0)
    console.print()

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
    hyperparams  = params.get("hyperparams", {t: "null" for t in tracks})
    if isinstance(hyperparams, str):
        hyperparams = {t: hyperparams for t in tracks}
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
    hyperparams_repr = json.dumps(hyperparams)
    content = content.replace('"__HYPERPARAMS__"', hyperparams_repr)
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

    launch_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    launch_table.add_column(style="bold cyan", no_wrap=True)
    launch_table.add_column()
    launch_table.add_row("Algorithm",  params.get("algo_name", ""))
    launch_table.add_row("Evolving",   module if params.get("evolve_module") else "full algorithm")
    launch_table.add_row("Tracks",     ", ".join(params.get("tracks", [])))
    launch_table.add_row("Nonces",     str(params.get("nonces", "")))
    launch_table.add_row("Iterations", str(max_iters))
    launch_table.add_row("Provider",   provider)
    if resume:
        launch_table.add_row("Mode", "[yellow]Resuming from checkpoint[/yellow]")

    console.print()
    console.print(Panel(
        launch_table,
        title="[bold cyan]Launching DeepEvolve[/bold cyan]",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    ))
    console.print()

    sub_env = os.environ.copy()
    if VERBOSE:
        sub_env["DEEPEVOLVE_VERBOSE"] = "1"
    subprocess.run(cmd, cwd=str(DEEPEVOLVE_DIR), env=sub_env, check=False)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    header()

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
            console.print(f"  [green]✓[/green] Resuming: [bold]{problem_name}[/bold]")
            # Check if the run has already reached its iteration limit
            ckpt_dir = DEEPEVOLVE_DIR / "examples" / problem_name / "ckpt"
            existing_ckpts = sorted(ckpt_dir.glob("checkpoint_*"), key=lambda p: p.name) if ckpt_dir.exists() else []
            current_iter = int(existing_ckpts[-1].name.split("_")[-1]) if existing_ckpts else 0
            max_iters = params.get("max_iterations", 0)
            if current_iter >= max_iters:
                console.print()
                console.print(Panel(
                    f"[yellow]This run completed all {max_iters} iteration(s).[/yellow]\n"
                    "How many more iterations would you like to add?",
                    box=box.ROUNDED, padding=(0, 2),
                    expand=False,
                ))
                extra = prompt_int("Additional iterations", default=5, min_val=1, max_val=500)
                params["max_iterations"] = max_iters + extra
                meta_file.write_text(json.dumps(params, indent=2))
                console.print(f"  [green]✓[/green] Extended to [bold]{params['max_iterations']}[/bold] total iterations.")
        else:
            console.print("  [yellow]Run metadata not found — starting fresh.[/yellow]")
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
