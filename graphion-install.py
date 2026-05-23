#!/usr/bin/env python3
"""Graphion install wrapper.

A first-run setup walkthrough for editors who haven't run a Python
project before. Checks prerequisites (Python, git, Pandoc), installs
the Python dependencies, optionally seeds the database, optionally
sets up the Claude API key, and prints clear next steps.

Run from the project root:

    python graphion-install.py

Safe to re-run — every step is idempotent. If you've already done a
step, this script confirms it and moves on.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


# ---------- terminal output helpers ----------

# Cheap ANSI color, no dependency. Disabled when stdout isn't a TTY,
# when NO_COLOR is set, or on Windows shells that don't process ANSI.
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        # Windows 10+ cmd does ANSI when conhost is up to date,
        # but be conservative.
        return os.environ.get("WT_SESSION") is not None or \
            os.environ.get("ANSICON") is not None or \
            "TERM" in os.environ
    return True


_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def header(text: str) -> None:
    bar = "=" * max(60, len(text) + 4)
    print()
    print(_c("1;36", bar))
    print(_c("1;36", "  " + text))
    print(_c("1;36", bar))


def step(n: int, total: int, text: str) -> None:
    print()
    print(_c("1;33", f"Step {n}/{total}: {text}"))
    print(_c("33", "-" * (len(f"Step {n}/{total}: {text}"))))


def ok(text: str) -> None:
    print(f"  {_c('32', 'OK')}  {text}")


def warn(text: str) -> None:
    print(f"  {_c('33', 'WARN')}  {text}")


def fail(text: str) -> None:
    print(f"  {_c('31', 'FAIL')}  {text}")


def info(text: str) -> None:
    print(f"  {_c('37', '...')}  {text}")


def ask(prompt: str, default: str = "y") -> bool:
    """Ask a yes/no question. Pressing enter accepts the default."""
    suffix = "[Y/n]" if default.lower() == "y" else "[y/N]"
    while True:
        try:
            ans = input(f"  {_c('1;36', '?')}  {prompt} {suffix} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if ans == "":
            return default.lower() == "y"
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("    (please answer y or n)")


def run(cmd: list[str], capture: bool = False) -> tuple[int, str]:
    """Run a command, return (exit_code, output_if_captured)."""
    try:
        if capture:
            r = subprocess.run(
                cmd, capture_output=True, text=True, check=False,
            )
            return r.returncode, (r.stdout + r.stderr).strip()
        else:
            r = subprocess.run(cmd, check=False)
            return r.returncode, ""
    except FileNotFoundError:
        return 127, "command not found"


# ---------- platform-specific install hints ----------

def _platform_hint(tool: str) -> str:
    sys_ = platform.system()
    if tool == "git":
        if sys_ == "Windows":
            return "Install from https://git-scm.com/download/win"
        if sys_ == "Darwin":
            return "Install with `brew install git` or from https://git-scm.com/"
        return "Install with `sudo apt install git` (Debian/Ubuntu) or your distro's package manager"
    if tool == "pandoc":
        if sys_ == "Windows":
            return "Install from https://github.com/jgm/pandoc/releases (download the .msi)"
        if sys_ == "Darwin":
            return "Install with `brew install pandoc`"
        return "Install with `sudo apt install pandoc` (Debian/Ubuntu)"
    if tool == "python":
        if sys_ == "Windows":
            return "Install from https://www.python.org/downloads/ (check 'Add Python to PATH' during install)"
        if sys_ == "Darwin":
            return "Install with `brew install python@3.12` or from https://www.python.org/downloads/"
        return "Install with `sudo apt install python3.12 python3-pip` (Debian/Ubuntu)"
    return ""


# ---------- checks ----------

def check_python() -> bool:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 11):
        ok(f"Python {version_str} (you're running this script with it, so it's installed)")
        return True
    fail(f"Python {version_str} found, but Graphion needs 3.11+")
    info(_platform_hint("python"))
    return False


def check_git() -> bool:
    code, out = run(["git", "--version"], capture=True)
    if code == 0:
        ok(f"git found: {out}")
        return True
    fail("git not found on PATH")
    info(_platform_hint("git"))
    return False


def check_pandoc() -> bool:
    code, out = run(["pandoc", "--version"], capture=True)
    if code == 0:
        first = out.splitlines()[0] if out else "pandoc"
        ok(f"Pandoc found: {first}")
        # Soft-check version: Graphion needs Pandoc 3+
        try:
            parts = first.split()
            for p in parts:
                if p[0].isdigit() and "." in p:
                    major = int(p.split(".")[0])
                    if major < 3:
                        warn(f"Pandoc {p} found, but Graphion expects 3.0+. Some output may misbehave.")
                    break
        except Exception:
            pass
        return True
    fail("Pandoc not found on PATH")
    info(_platform_hint("pandoc"))
    return False


def check_in_project_dir() -> bool:
    here = Path.cwd()
    needed = ["app.py", "requirements.txt", "seed.py"]
    missing = [f for f in needed if not (here / f).exists()]
    if not missing:
        ok(f"Running from Graphion project directory: {here}")
        return True
    fail(f"Not in the Graphion project directory (missing: {', '.join(missing)})")
    info("`cd` into the directory where you cloned Graphion and re-run this script.")
    return False


def check_python_packages() -> tuple[bool, list[str]]:
    """Return (all_installed, missing_list)."""
    core_packages = [
        "flask", "flask_login", "pypandoc", "docx", "yaml",
        "mistune", "lxml", "requests", "typst", "pypdf",
    ]
    missing = []
    for pkg in core_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        ok(f"All {len(core_packages)} core Python packages installed")
        return True, []
    warn(f"{len(missing)} core packages missing: {', '.join(missing)}")
    return False, missing


def check_db_seeded() -> bool:
    db_path = Path("data/graphion.db")
    if not db_path.exists():
        info("Database not yet created (this is normal on first install)")
        return False
    try:
        import sqlite3
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM journals")
        j_count = cur.fetchone()[0]
        con.close()
        if user_count > 0:
            ok(f"Database initialized: {user_count} user(s), {j_count} journal(s)")
            return True
        warn("Database exists but no users — seed didn't complete")
        return False
    except Exception as exc:
        warn(f"Could not read database: {exc}")
        return False


def check_claude_key() -> str:
    """Return 'set', 'unset', or 'invalid_format'."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return "unset"
    if not key.startswith("sk-ant-"):
        return "invalid_format"
    return "set"


# ---------- main flow ----------

def main() -> int:
    header("Graphion install walkthrough")
    print(textwrap.dedent("""\
        This script walks you through getting Graphion running on your
        machine. It runs each prerequisite check, offers to install what's
        missing, and ends with a working app. Safe to re-run at any time.

        All commands shown here are run for you automatically — you don't
        need to copy-paste anything. If a step asks a yes/no question,
        pressing Enter accepts the default (shown in CAPS).
    """))

    total_steps = 6

    # ---- Step 1: project directory ----
    step(1, total_steps, "Confirm you're in the Graphion project directory")
    if not check_in_project_dir():
        return 1

    # ---- Step 2: Python ----
    step(2, total_steps, "Check Python version")
    if not check_python():
        return 1

    # ---- Step 3: git + Pandoc ----
    step(3, total_steps, "Check external tools")
    git_ok = check_git()
    pandoc_ok = check_pandoc()
    if not pandoc_ok:
        print()
        print("  Graphion requires Pandoc to convert Word documents and emit")
        print("  HTML/PDF/EPUB/JATS output. Install it (see hint above) and")
        print("  re-run this script. git is optional once Graphion is cloned,")
        print("  but recommended for receiving future updates.")
        return 1

    # ---- Step 4: Python packages ----
    step(4, total_steps, "Install Python dependencies")
    all_installed, missing = check_python_packages()
    if not all_installed:
        print()
        if ask("Install missing Python packages now via `pip install -r requirements.txt`?"):
            print()
            code, _ = run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            if code != 0:
                fail("pip install returned a non-zero exit code; see output above")
                print()
                print("  Common causes:")
                print("   - No internet connection")
                print("   - WeasyPrint native libraries missing (this is OPTIONAL — see Help → Advanced Tools)")
                print("   - Permission issues — try `python -m pip install --user -r requirements.txt`")
                if not ask("Continue anyway? (some optional features will be unavailable)", default="n"):
                    return 1
            else:
                ok("Python packages installed")
        else:
            warn("Skipping package install — Graphion won't run until they're installed")
            return 1

    # ---- Step 5: seed the database ----
    step(5, total_steps, "Initialize the database and admin user")
    if check_db_seeded():
        info("Database is already seeded — skipping. (Run `python seed.py` manually to re-seed.)")
    else:
        print()
        print("  The seed script creates `data/graphion.db`, applies the schema,")
        print("  registers the LiCS example journal, and prompts for an admin")
        print("  username + password.")
        print()
        if ask("Run `python seed.py` now?"):
            print()
            code, _ = run([sys.executable, "seed.py"])
            if code != 0:
                warn("seed.py returned a non-zero exit code")
                if not ask("Continue anyway?", default="n"):
                    return 1
            else:
                ok("Database seeded")
        else:
            warn("Skipping seed — you'll need to run `python seed.py` before the app can be used")

    # ---- Step 6: optional Claude API key ----
    step(6, total_steps, "Optional: set up the Claude API key")
    key_state = check_claude_key()
    if key_state == "set":
        ok("ANTHROPIC_API_KEY is set in this shell. The Stylize button will work.")
    elif key_state == "invalid_format":
        warn("ANTHROPIC_API_KEY is set but doesn't start with `sk-ant-` — check the value")
    else:
        info("ANTHROPIC_API_KEY is not set. Claude features (Stylize, alt-text, table repair)")
        info("will be greyed out in the UI, but the rest of Graphion works fine without them.")
        print()
        print("  To enable Claude features later:")
        print("   1. Get an API key from https://console.anthropic.com/")
        print("   2. Set the env var BEFORE starting the app:")
        sys_ = platform.system()
        if sys_ == "Windows":
            print("        cmd:        set ANTHROPIC_API_KEY=sk-ant-your-key")
            print("        PowerShell: $env:ANTHROPIC_API_KEY = \"sk-ant-your-key\"")
            print("        Permanent:  setx ANTHROPIC_API_KEY \"sk-ant-your-key\"")
            print("                    (then close and reopen the terminal)")
        else:
            print("        Bash/Zsh:   export ANTHROPIC_API_KEY=sk-ant-your-key")
            print("        Permanent:  add the export line to ~/.bashrc or ~/.zshrc")

    # ---- All done ----
    header("Setup complete")
    print()
    print("  To start Graphion now, run:")
    print()
    print(f"      {_c('1;32', 'python app.py')}")
    print()
    print("  Then open in your browser:")
    print()
    print(f"      {_c('1;34', 'http://127.0.0.1:5050/')}")
    print()
    print("  Sign in with the admin credentials you created during seed.")
    print()
    print("  Optional advanced tools (verapdf, pa11y, WeasyPrint, OCR, etc.)")
    print("  are documented at:")
    print()
    print(f"      {_c('34', 'docs/help/14-advanced-tools.md')}")
    print()
    print("  On Windows, you can install all of them at once by running")
    print("  `install-graphion-deps.ps1` as Administrator.")
    print()

    # Offer to launch the app right now.
    if ask("Launch the app now?"):
        print()
        info("Starting `python app.py` — press Ctrl+C to stop.")
        run([sys.executable, "app.py"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print(_c("33", "Cancelled by user. Re-run any time with `python graphion-install.py`."))
        sys.exit(130)
