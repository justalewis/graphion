"""Output validators: PDF/UA accessibility (verapdf) and HTML
accessibility (pa11y).

Both are external CLI tools, not pip dependencies. Functions here check
availability and call them gracefully — if the tool isn't installed
the UI displays a "tool not found" notice rather than crashing.

Install hints:
  - verapdf:  https://verapdf.org/  (Java; download zip, add `verapdf` to PATH)
  - pa11y-ci: `npm install -g pa11y-ci`  (Node.js dependency)
"""
from __future__ import annotations

import json
import shutil
import subprocess
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


def run_pa11y(html_path: Path) -> Tuple[bool, List[Dict]]:
    """Run pa11y accessibility audit against an HTML file. Returns
    (no_issues_found, list_of_issues). Each issue is a dict with
    `code`, `type`, `message`, `selector`, `context`.
    """
    if not pa11y_available():
        return False, [{"error": "pa11y not installed (npm install -g pa11y)"}]
    if not html_path.exists():
        return False, [{"error": f"HTML not found: {html_path}"}]
    binary = shutil.which("pa11y") or shutil.which("pa11y-ci")
    try:
        result = subprocess.run(
            [binary, "--reporter", "json", str(html_path)],
            capture_output=True, text=True, timeout=120,
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
    "run_pa11y",
]
