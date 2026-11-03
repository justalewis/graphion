"""Calling the two external checkers.

Both are optional, so the module's job is to find them, call them, and come
back with something either way. The tests here are about the one place that
went wrong: how the binary is named when it is called.

On Windows neither tool is an executable. verapdf installs a `verapdf.BAT`
launcher and npm writes a `pa11y.CMD` shim, and `shutil.which` finds both
through PATHEXT. `CreateProcess` will not run either from the bare name, so
`subprocess.run(["verapdf", ...])` raises FileNotFoundError while
`verapdf_available()` says the tool is there. That is the worst of the
three possible answers: the register would have recorded 115 crashes with
the probe insisting the tool was installed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import validators


class _Ran:
    """Captures the argv a call would have used."""

    def __init__(self, stdout="{}", returncode=0):
        self.argv = None
        self._stdout = stdout
        self._returncode = returncode

    def __call__(self, argv, **kwargs):
        self.argv = argv
        return subprocess.CompletedProcess(argv, self._returncode,
                                           stdout=self._stdout, stderr="")


def test_verapdf_is_called_by_the_path_that_was_resolved(tmp_path, monkeypatch):
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.7 pretend")
    resolved = r"C:\Users\someone\verapdf\verapdf.BAT"
    monkeypatch.setattr(validators.shutil, "which", lambda name: resolved)
    ran = _Ran()
    monkeypatch.setattr(validators.subprocess, "run", ran)

    passed, report = validators.run_verapdf(pdf)

    assert ran.argv[0] == resolved
    assert ran.argv[0] != "verapdf"
    assert passed is True
    assert report["passed"] is True


def test_pa11y_is_called_by_the_path_that_was_resolved(tmp_path, monkeypatch):
    html = tmp_path / "article.html"
    html.write_text("<p>Body.</p>", encoding="utf-8")
    resolved = r"C:\Users\someone\node\pa11y.CMD"
    monkeypatch.setattr(validators.shutil, "which", lambda name: resolved)
    ran = _Ran(stdout="[]")
    monkeypatch.setattr(validators.subprocess, "run", ran)

    passed, issues = validators.run_pa11y(html)

    assert ran.argv[0] == resolved
    assert passed is True
    assert issues == []


def test_a_tool_that_is_absent_is_reported_rather_than_called(tmp_path,
                                                              monkeypatch):
    """The caller is what decides whether to record, and it needs an answer
    it can act on rather than an exception."""
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.7 pretend")
    monkeypatch.setattr(validators.shutil, "which", lambda name: None)

    assert validators.verapdf_available() is False
    passed, report = validators.run_verapdf(pdf)
    assert passed is False
    assert "not on PATH" in report["error"]


def test_a_missing_file_is_reported_rather_than_handed_to_the_tool(
        tmp_path, monkeypatch):
    monkeypatch.setattr(validators.shutil, "which",
                        lambda name: r"C:\somewhere\verapdf.BAT")
    ran = _Ran()
    monkeypatch.setattr(validators.subprocess, "run", ran)

    passed, report = validators.run_verapdf(tmp_path / "never-rendered.pdf")

    assert passed is False
    assert report["error"] == "PDF not found"
    assert ran.argv is None


def test_a_timeout_comes_back_as_a_result_not_an_exception(tmp_path,
                                                           monkeypatch):
    """A galley verapdf cannot finish on is a fact about the galley, and the
    register has a level for it."""
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.7 pretend")
    monkeypatch.setattr(validators.shutil, "which",
                        lambda name: r"C:\somewhere\verapdf.BAT")

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 120)

    monkeypatch.setattr(validators.subprocess, "run", timeout)

    passed, report = validators.run_verapdf(pdf)

    assert passed is False
    assert "timed out" in report["error"]
