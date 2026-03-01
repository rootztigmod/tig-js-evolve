"""
TIG Job Scheduling - DeepEvolve Setup

Collects configuration, installs dependencies, and writes .env.
Run via:  ./setup.sh   (which bootstraps conda then calls this script)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Confirm

console = Console()

SCRIPT_DIR = Path(__file__).parent.resolve()
ENV_FILE   = SCRIPT_DIR / ".env"

COMMON_MONOREPO_PATHS = [
    Path.home() / "tig-monorepo",
    Path.home() / "work" / "tig-monorepo",
    Path.home() / "projects" / "tig-monorepo",
    Path("/opt/tig-monorepo"),
]

CONDA_SEARCH_PATHS = [
    Path.home() / "miniconda3" / "etc" / "profile.d" / "conda.sh",
    Path.home() / "anaconda3"  / "etc" / "profile.d" / "conda.sh",
    Path("/opt/conda/etc/profile.d/conda.sh"),
    Path("/usr/local/conda/etc/profile.d/conda.sh"),
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def header():
    console.print()
    console.print(Panel(
        "[bold cyan]TIG Job Scheduling - DeepEvolve Setup[/bold cyan]",
        box=box.DOUBLE_EDGE,
        expand=False,
        padding=(0, 4),
    ))
    console.print()


def step(n: int, total: int, title: str):
    console.print(f"\n[bold][{n}/{total}] {title}[/bold]")


def ok(msg: str):
    console.print(f"  [green]✓[/green] {msg}")


def warn(msg: str):
    console.print(f"  [yellow]![/yellow] {msg}")


def err(msg: str):
    console.print(f"  [red]✗[/red] {msg}")


def mask_key(key: str) -> str:
    return key[:8] + "••••••" if len(key) >= 8 else "••••••"


def validate_key(url: str, headers: list[str]) -> str:
    """Returns HTTP status code as string."""
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
           "--max-time", "10", url] + headers
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except Exception:
        return "000"


def check_api_key(key: str, provider: str) -> bool:
    """Validate key, print result. Returns True if ok to continue."""
    console.print(f"  Validating key...", end=" ")
    if provider == "anthropic":
        code = validate_key(
            "https://api.anthropic.com/v1/models",
            ["-H", f"x-api-key: {key}", "-H", "anthropic-version: 2023-06-01"],
        )
        valid_codes, fail_codes = ["200"], ["401"]
    elif provider == "openai":
        code = validate_key(
            "https://api.openai.com/v1/models",
            ["-H", f"Authorization: Bearer {key}"],
        )
        valid_codes, fail_codes = ["200"], ["401"]
    else:  # gemini
        code = validate_key(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            [],
        )
        valid_codes, fail_codes = ["200"], ["400", "403"]

    if code in valid_codes:
        console.print("[green]OK[/green]")
        return True
    elif code in fail_codes:
        console.print("[red]FAILED[/red]")
        err(f"Invalid key (HTTP {code}). Please check and re-run setup.")
        return False
    else:
        console.print(f"[yellow]Could not verify (HTTP {code}) — continuing anyway[/yellow]")
        return True


def prompt_api_key(label: str) -> str:
    """Prompt for an API key with masked echo simulation."""
    import getpass
    console.print(f"\n  Enter your {label} API key:")
    key = getpass.getpass("  ")
    if key:
        console.print(f"  [green]Key received:[/green] {mask_key(key)}")
    return key


# ─── Already set up? ──────────────────────────────────────────────────────────

def check_already_setup():
    if ENV_FILE.exists():
        console.print(Panel(
            "[green]Setup already complete.[/green]\n\n"
            "Run [bold]conda activate deepevolve && python run.py[/bold] to start evolving.\n\n"
            "To redo setup: [bold]rm .env && ./setup.sh[/bold]",
            title="Setup",
            box=box.ROUNDED,
            padding=(1, 4),
            expand=False,
        ))
        sys.exit(0)


# ─── Step 1: System packages ──────────────────────────────────────────────────

def check_system_packages():
    step(1, 5, "Checking system packages")
    missing = []
    for tool in ("curl", "git", "docker"):
        if not shutil.which(tool):
            missing.append(tool)

    if "docker" in missing:
        err("Docker not found — required to build and test algorithms.")
        console.print("  Install from: [link]https://docs.docker.com/engine/install/ubuntu/[/link]")
        console.print("  Then re-run this script.")
        sys.exit(1)

    for tool in ("curl", "git"):
        if tool in missing:
            warn(f"{tool} not found — installing...")
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "-q", tool],
                check=True, capture_output=True,
            )

    ok("System packages OK")


# ─── Step 2: Conda ────────────────────────────────────────────────────────────

def find_conda() -> str:
    for p in CONDA_SEARCH_PATHS:
        if p.exists():
            return str(p)
    return ""


def setup_conda() -> str:
    step(2, 5, "Checking conda")
    conda_sh = find_conda()
    if not conda_sh:
        warn("Conda not found — installing Miniconda...")
        installer = Path("/tmp/miniconda_installer.sh")
        subprocess.run([
            "curl", "-fsSL",
            "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh",
            "-o", str(installer),
        ], check=True)
        subprocess.run(["bash", str(installer), "-b", "-p",
                        str(Path.home() / "miniconda3")], check=True)
        installer.unlink(missing_ok=True)
        conda_sh = str(Path.home() / "miniconda3" / "etc" / "profile.d" / "conda.sh")
        ok("Miniconda installed")
    else:
        ok("Conda found")
    return conda_sh


# ─── Step 3: Python environment ───────────────────────────────────────────────

def setup_python_env():
    step(3, 5, "Setting up Python environment")
    result = subprocess.run(
        ["conda", "env", "list"], capture_output=True, text=True
    )
    if "deepevolve" in result.stdout:
        warn("Environment 'deepevolve' already exists — skipping creation")
    else:
        console.print("  Creating conda environment 'deepevolve' (Python 3.11)...")
        subprocess.run(
            ["conda", "create", "-n", "deepevolve", "python=3.11", "-y", "-q"],
            check=True,
        )
        ok("Environment created")

    console.print("  Installing dependencies...")
    subprocess.run(
        ["conda", "run", "-n", "deepevolve", "pip", "install",
         "-r", str(SCRIPT_DIR / "requirements-mini.txt"), "-q"],
        check=True,
    )
    ok("Dependencies installed")


# ─── Step 4: Locate tig-monorepo ──────────────────────────────────────────────

def find_monorepo() -> str:
    step(4, 5, "Locating tig-monorepo")

    auto_found = None
    for p in COMMON_MONOREPO_PATHS:
        if (p / "tig-algorithms" / "src" / "job_scheduling").exists():
            auto_found = str(p)
            break

    if auto_found:
        console.print(f"  Found: [bold]{auto_found}[/bold]")
        confirmed = inquirer.confirm(
            message="Is this the correct tig-monorepo path?",
            default=True,
        ).execute()
        if confirmed:
            ok(f"tig-monorepo: {auto_found}")
            return auto_found

    console.print()
    warn("tig-monorepo not found automatically.")
    console.print("  If you don't have it yet, clone it with:")
    console.print("  [bold]git clone https://github.com/tig-foundation/tig-monorepo.git ~/tig-monorepo[/bold]")
    console.print()

    path = inquirer.text(
        message="Enter full path to tig-monorepo:",
        default=str(Path.home() / "tig-monorepo"),
    ).execute()

    path = path.strip().replace("~", str(Path.home()))
    if not (Path(path) / "tig-algorithms" / "src" / "job_scheduling").exists():
        err(f"'{path}' does not look like a valid tig-monorepo.")
        console.print(f"  Expected: {path}/tig-algorithms/src/job_scheduling")
        console.print("  Please clone tig-monorepo and re-run setup.")
        sys.exit(1)

    ok(f"tig-monorepo: {path}")
    return path


# ─── Step 5: API Keys ─────────────────────────────────────────────────────────

def setup_api_keys() -> tuple[str, str, str, str]:
    step(5, 5, "Configuring API keys")
    console.print()

    provider_choice = inquirer.select(
        message="Which LLM provider will you be using?",
        choices=[
            Choice("openai",    name="OpenAI  (GPT)"),
            Choice("claude",    name="Anthropic  (Claude)"),
            Choice("gemini",    name="Google  (Gemini)"),
        ],
    ).execute()

    openai_key     = ""
    anthropic_key  = ""
    gemini_key     = ""

    if provider_choice == "openai":
        key = prompt_api_key("OpenAI")
        if not key:
            err("OpenAI API key cannot be empty.")
            sys.exit(1)
        if not check_api_key(key, "openai"):
            sys.exit(1)
        openai_key = key

    elif provider_choice == "claude":
        key = prompt_api_key("Anthropic")
        if not key:
            err("Anthropic API key cannot be empty.")
            sys.exit(1)
        if not check_api_key(key, "anthropic"):
            sys.exit(1)
        anthropic_key = key
        openai_key = prompt_optional_openai_key()

    else:  # gemini
        key = prompt_api_key("Gemini")
        if not key:
            err("Gemini API key cannot be empty.")
            sys.exit(1)
        if not check_api_key(key, "gemini"):
            sys.exit(1)
        gemini_key = key
        openai_key = prompt_optional_openai_key()

    return provider_choice, openai_key, anthropic_key, gemini_key


def prompt_optional_openai_key() -> str:
    import getpass
    console.print()
    console.print(Panel(
        "[yellow]Note:[/yellow] The research phase uses [bold]gpt-4o-mini[/bold] (OpenAI) for web search.\n"
        "Providing an OpenAI key enables this — recommended but optional.",
        box=box.ROUNDED,
        padding=(0, 2),
        expand=False,
    ))
    console.print()
    console.print("  Enter OpenAI key for web search (or press Enter to skip):")
    key = getpass.getpass("  ")
    if not key:
        warn("Web search disabled — research will run without internet search.")
        return "sk-dummy-no-web-search"
    console.print(f"  [green]Key received:[/green] {mask_key(key)}")
    if not check_api_key(key, "openai"):
        sys.exit(1)
    return key


# ─── Write .env ───────────────────────────────────────────────────────────────

def write_env(monorepo_path: str, provider: str,
              openai_key: str, anthropic_key: str,
              gemini_key: str, conda_sh: str):
    ENV_FILE.write_text(
        f"# Generated by setup.py - do not commit this file\n"
        f"TIG_MONOREPO_PATH={monorepo_path}\n"
        f"LLM_PROVIDER={provider}\n"
        f"OPENAI_API_KEY={openai_key}\n"
        f"ANTHROPIC_API_KEY={anthropic_key}\n"
        f"GEMINI_API_KEY={gemini_key}\n"
        f"CONDA_SH={conda_sh}\n"
    )


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(monorepo_path: str, provider: str):
    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Provider",  provider)
    table.add_row("Monorepo",  monorepo_path)
    table.add_row("Next step", "conda activate deepevolve && python run.py")

    console.print(Panel(
        table,
        title="[bold green]Setup complete![/bold green]",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    ))
    console.print()
    console.print(Panel(
        "[yellow]IMPORTANT:[/yellow] Activate the conda environment every time you open a new terminal:\n\n"
        "  [bold]conda activate deepevolve[/bold]\n"
        "  [bold]python run.py[/bold]\n\n"
        "If you see [bold]ModuleNotFoundError[/bold], the environment is not active.",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    ))
    console.print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    header()
    check_already_setup()
    check_system_packages()
    conda_sh = setup_conda()
    setup_python_env()
    monorepo_path = find_monorepo()
    provider, openai_key, anthropic_key, gemini_key = setup_api_keys()
    write_env(monorepo_path, provider, openai_key, anthropic_key, gemini_key, conda_sh)
    print_summary(monorepo_path, provider)


if __name__ == "__main__":
    main()
