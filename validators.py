"""Output validators: PDF/UA accessibility (verapdf) and HTML
accessibility (pa11y).

Both are external CLI tools, not pip dependencies. Functions here check
availability and call them gracefully — if the tool isn't installed
the UI displays a "tool not found" notice rather than crashing.

Install hints:
  - verapdf:  https://verapdf.org/  (Java; download zip, add `verapdf` to PATH)
  - pa11y-ci: `npm install -g pa11y-ci`  (Node.js dependency)
  - epubcheck: https://www.w3.org/publishing/epubcheck/  (Java; add the
    `epubcheck` launcher to PATH, or point `EPUBCHECK_PATH` at it)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def verapdf_available() -> bool:
    return shutil.which("verapdf") is not None


def run_verapdf(pdf_path: Path) -> Tuple[bool, Dict]:
    """Validate a PDF against PDF/UA-1 (the formal accessibility
    profile). Returns (passed, report_dict)."""
    if not verapdf_available():
        return False, {
            "error": "verapdf CLI not on PATH; download from https://verapdf.org/",
            "passed": False,
        }
    if not pdf_path.exists():
        return False, {"error": "PDF not found", "passed": False}
    # Invoked by the path `shutil.which` resolved, not by the bare name. On
    # Windows the launcher is `verapdf.BAT`, which `which` finds through
    # PATHEXT and `CreateProcess` will not run from the name alone: the call
    # raises FileNotFoundError while the availability probe says yes, which
    # is the worst of the three outcomes. `run_pa11y` below already resolves
    # for the same reason.
    binary = shutil.which("verapdf")
    try:
        result = subprocess.run(
            [binary, "--flavour", "ua1", "--format", "json", str(pdf_path)],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, {"error": "verapdf timed out (120s)", "passed": False}

    try:
        report = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError:
        report = {"raw_stdout": result.stdout, "raw_stderr": result.stderr}

    # verapdf exit code 0 = compliant; non-zero = not compliant
    passed = result.returncode == 0
    report["passed"] = passed
    return passed, report


def pa11y_available() -> bool:
    return shutil.which("pa11y") is not None or shutil.which("pa11y-ci") is not None


# Set to force the sandbox flags on or off rather than letting the rule
# below decide. "0", "false", "no" and the empty string turn them off.
PA11Y_SANDBOX_ENV = "GRAPHION_PA11Y_NO_SANDBOX"


def pa11y_needs_no_sandbox() -> bool:
    """Whether Chromium has to be told to drop its sandbox.

    pa11y drives headless Chromium through puppeteer, and Chromium
    refuses to start as root unless `--no-sandbox` is passed. The
    container runs as root, so in production that refusal is every pa11y
    run failing; on a developer's machine the flag is an unnecessary
    loosening of a real protection.

    So the test is the condition Chromium objects to rather than a
    setting somebody has to remember: being root. `os.geteuid` does not
    exist on Windows, where the question does not arise.
    """
    forced = os.environ.get(PA11Y_SANDBOX_ENV)
    if forced is not None:
        return forced.strip().lower() not in ("", "0", "false", "no")
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def pa11y_launch_config() -> Dict:
    """What pa11y passes to `puppeteer.launch`.

    `--disable-dev-shm-usage` is here for the same reason as the sandbox
    flag and not as a precaution: Docker gives a container 64 MB of
    /dev/shm by default, Chromium puts its shared memory there, and it
    crashes partway through a page rather than failing to start. Both are
    about running in a container, which is why they travel together.
    """
    return {"chromeLaunchConfig": {"args": ["--no-sandbox",
                                            "--disable-dev-shm-usage"]}}


def run_pa11y(html_path: Path) -> Tuple[bool, List[Dict]]:
    """Run pa11y accessibility audit against an HTML file. Returns
    (no_issues_found, list_of_issues). Each issue is a dict with
    `code`, `type`, `message`, `selector`, `context`.

    Chromium's launch arguments can only be reached through a config
    file, so one is written beside the run where the environment needs it
    and left out entirely where it does not. The file is temporary for
    the reason `run_epubcheck`'s report is: a validator that left
    something behind beside the galley would be writing into content it
    was only asked to read.
    """
    if not pa11y_available():
        return False, [{"error": "pa11y not installed (npm install -g pa11y)"}]
    if not html_path.exists():
        return False, [{"error": f"HTML not found: {html_path}"}]
    binary = shutil.which("pa11y") or shutil.which("pa11y-ci")
    argv = [binary, "--reporter", "json"]
    with tempfile.TemporaryDirectory() as workspace:
        if pa11y_needs_no_sandbox():
            config = Path(workspace) / "pa11y.json"
            config.write_text(json.dumps(pa11y_launch_config()),
                              encoding="utf-8")
            argv += ["--config", str(config)]
        argv.append(str(html_path))
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, [{"error": "pa11y timed out (120s)"}]
    try:
        issues = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError:
        return False, [{"error": "could not parse pa11y output", "raw": result.stdout}]
    if isinstance(issues, dict):
        # Some pa11y versions wrap output in {"issues": [...]}.
        issues = issues.get("issues", [])
    return len(issues) == 0, issues


__all__ = [
    "verapdf_available",
    "run_verapdf",
    "pa11y_available",
    "pa11y_needs_no_sandbox",
    "pa11y_launch_config",
    "run_pa11y",
]


# ---------- epubcheck ----------

# The W3C's own validator for the container. `epub_a11y` writes real
# `dcterms:conformsTo` and `a11y:certifiedBy` claims into the package
# document, and until this existed nothing read the file back: the register
# carried four kinds and none of them opened an EPUB.
#
# Resolved the way `PANDOC_PATH` is, and called by the path rather than the
# name for the reason `run_verapdf` explains: a launcher is `epubcheck.bat`
# on Windows and `CreateProcess` will not run it from the bare name.
EPUBCHECK_ENV = "EPUBCHECK_PATH"


def epubcheck_binary() -> Optional[str]:
    """Where epubcheck is, or None.

    Two shapes, because the tool comes in two. Some distributions put an
    `epubcheck` launcher on PATH; the W3C's own release is a jar with its
    `lib/` beside it and nothing to put on PATH at all, so
    `EPUBCHECK_PATH` may name either and `epubcheck_argv` decides how to
    call what it finds. Supporting only the launcher would have meant the
    probe saying no on a machine where the tool was sitting installed.
    """
    named = os.environ.get(EPUBCHECK_ENV)
    if named and Path(named).exists():
        return named
    return shutil.which("epubcheck")


def epubcheck_argv(target: str, epub_path: Path, report: Path) -> list:
    """How to call what `epubcheck_binary` found.

    A jar is run through the JVM; a launcher is run directly. The jar needs
    its `lib/` where the release put it, so the path is passed as given
    rather than copied anywhere.
    """
    argv = []
    if str(target).lower().endswith(".jar"):
        java = shutil.which("java") or "java"
        argv = [java, "-jar", str(target)]
    else:
        argv = [str(target)]
    return argv + [str(epub_path), "--json", str(report), "--quiet"]


def epubcheck_available() -> bool:
    """Whether epubcheck can actually be called, not merely found.

    A jar with no JVM to run it is a tool that is not installed, and
    answering yes there is the pairing `run_verapdf` warns about: the probe
    gates the call, so a yes it cannot honour turns into a crash per
    article rather than a notice.
    """
    target = epubcheck_binary()
    if target is None:
        return False
    if str(target).lower().endswith(".jar"):
        return shutil.which("java") is not None
    return True


def run_epubcheck(epub_path: Path) -> Tuple[bool, Dict]:
    """Validate an EPUB container. Returns (passed, report_dict).

    The verdict is read off the report and not off the exit code, which is
    the rule `assess.read_declaration` already follows for verapdf and for
    the same reason: a checker exits non-zero both for a file that does not
    conform and for one it could not open, and only the first of those is
    about the document. An EPUB with warnings and no errors is a pass here,
    because epubcheck warns about things a reading system tolerates.

    The report goes to a temp file rather than stdout, because epubcheck
    writes its progress there and the JSON would arrive mixed in with it.
    """
    if not epubcheck_available():
        target = epubcheck_binary()
        if target and str(target).lower().endswith(".jar"):
            error = (f"epubcheck is at {target} but no java was found to run "
                     f"it; install a JRE or put java on PATH")
        else:
            error = ("epubcheck not on PATH; see "
                     "https://www.w3.org/publishing/epubcheck/, or point "
                     f"{EPUBCHECK_ENV} at the launcher or the jar")
        return False, {"error": error, "passed": False}
    if not Path(epub_path).exists():
        return False, {"error": "EPUB not found", "passed": False}

    binary = epubcheck_binary()
    with tempfile.TemporaryDirectory() as workspace:
        out = Path(workspace) / "epubcheck.json"
        try:
            result = subprocess.run(
                epubcheck_argv(binary, Path(epub_path), out),
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, {"error": "epubcheck timed out (120s)",
                           "passed": False}
        except OSError as exc:
            return False, {"error": f"epubcheck could not be run: {exc}",
                           "passed": False}
        try:
            report = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, {
                "error": "epubcheck wrote no readable report",
                "raw_stdout": result.stdout[-2000:],
                "raw_stderr": result.stderr[-2000:],
                "passed": False,
            }

    messages = report.get("messages") or []
    counts: Dict[str, int] = {}
    for message in messages:
        severity = str(message.get("severity") or "").upper()
        counts[severity] = counts.get(severity, 0) + 1
    passed = not (counts.get("ERROR") or counts.get("FATAL"))
    report["passed"] = passed
    report["severity_counts"] = counts
    return passed, report


__all__ = [
    "verapdf_available", "run_verapdf",
    "pa11y_available", "run_pa11y",
    "epubcheck_available", "run_epubcheck", "epubcheck_binary",
    "epubcheck_argv",
    "EPUBCHECK_ENV",
]
