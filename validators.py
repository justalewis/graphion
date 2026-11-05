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


# ---------- epubcheck ----------

# The W3C's own validator for the container. `epub_a11y` writes real
# `dcterms:conformsTo` and `a11y:certifiedBy` claims into the package
# document, and until this existed nothing read the file back: the register
# carried four kinds and none of them opened an EPUB.
#
# Distributed as a jar with a launcher beside it, so the path is resolved
# the way `PANDOC_PATH` is, and called by the path `shutil.which` returned
# for the reason `run_verapdf` explains: on Windows the launcher is
# `epubcheck.bat` and `CreateProcess` will not run it from the bare name.
EPUBCHECK_ENV = "EPUBCHECK_PATH"


def epubcheck_binary() -> Optional[str]:
    """Where epubcheck is, or None."""
    named = os.environ.get(EPUBCHECK_ENV)
    if named and Path(named).exists():
        return named
    return shutil.which("epubcheck")


def epubcheck_available() -> bool:
    return epubcheck_binary() is not None


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
        return False, {
            "error": "epubcheck not on PATH; see "
                     "https://www.w3.org/publishing/epubcheck/",
            "passed": False,
        }
    if not Path(epub_path).exists():
        return False, {"error": "EPUB not found", "passed": False}

    binary = epubcheck_binary()
    with tempfile.TemporaryDirectory() as workspace:
        out = Path(workspace) / "epubcheck.json"
        try:
            result = subprocess.run(
                [binary, str(epub_path), "--json", str(out), "--quiet"],
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
    "EPUBCHECK_ENV",
]
