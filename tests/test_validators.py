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


# ---------- epubcheck, the fifth kind ----------

class _Wrote:
    """A run that writes epubcheck's JSON report where it was asked to."""

    def __init__(self, payload, returncode=0):
        self.argv = None
        self._payload = payload
        self._returncode = returncode

    def __call__(self, argv, **kwargs):
        import json

        self.argv = argv
        target = Path(argv[argv.index("--json") + 1])
        target.write_text(json.dumps(self._payload), encoding="utf-8")
        return subprocess.CompletedProcess(argv, self._returncode,
                                           stdout="", stderr="")


def test_epubcheck_is_called_by_the_path_that_was_resolved(tmp_path,
                                                           monkeypatch):
    """The third tool is a Java launcher too, so it meets the same wall:
    `epubcheck.bat` is found through PATHEXT and will not run from the bare
    name."""
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    resolved = r"C:\Users\someone\epubcheck\epubcheck.bat"
    monkeypatch.setattr(validators.shutil, "which", lambda name: resolved)
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)
    ran = _Wrote({"messages": []})
    monkeypatch.setattr(validators.subprocess, "run", ran)

    passed, report = validators.run_epubcheck(epub)

    assert ran.argv[0] == resolved
    assert ran.argv[0] != "epubcheck"
    assert passed is True
    assert report["passed"] is True


def test_an_error_in_the_container_is_a_failure(tmp_path, monkeypatch):
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setattr(validators.shutil, "which", lambda n: "epubcheck")
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)
    monkeypatch.setattr(validators.subprocess, "run", _Wrote(
        {"messages": [{"severity": "ERROR", "message": "mimetype deflated"}]}))

    passed, report = validators.run_epubcheck(epub)

    assert passed is False
    assert report["severity_counts"]["ERROR"] == 1


def test_warnings_without_errors_pass(tmp_path, monkeypatch):
    """epubcheck warns about what a reading system tolerates, so a warning
    is not the container failing."""
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setattr(validators.shutil, "which", lambda n: "epubcheck")
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)
    monkeypatch.setattr(validators.subprocess, "run", _Wrote(
        {"messages": [{"severity": "WARNING", "message": "unused resource"}]}))

    passed, report = validators.run_epubcheck(epub)

    assert passed is True
    assert report["severity_counts"]["WARNING"] == 1


def test_the_verdict_is_read_off_the_report_not_the_exit_code(tmp_path,
                                                              monkeypatch):
    """A checker exits non-zero both for a file that does not conform and
    for one it could not open, and only the first is about the document.
    `assess.read_declaration` reads verapdf the same way and for the same
    reason."""
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setattr(validators.shutil, "which", lambda n: "epubcheck")
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)
    monkeypatch.setattr(validators.subprocess, "run",
                        _Wrote({"messages": []}, returncode=1))

    passed, _report = validators.run_epubcheck(epub)

    assert passed is True


def test_an_unreadable_report_is_not_a_verdict(tmp_path, monkeypatch):
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setattr(validators.shutil, "which", lambda n: "epubcheck")
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)

    def wrote_nothing(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="boom", stderr="")

    monkeypatch.setattr(validators.subprocess, "run", wrote_nothing)

    passed, report = validators.run_epubcheck(epub)

    assert passed is False
    assert report["error"]


def test_the_env_override_wins_over_the_path(tmp_path, monkeypatch):
    """Distributed as a jar with a launcher beside it, so it is often not on
    PATH at all; `PANDOC_PATH` is the precedent."""
    launcher = tmp_path / "epubcheck.bat"
    launcher.write_text("rem", encoding="utf-8")
    monkeypatch.setenv(validators.EPUBCHECK_ENV, str(launcher))
    monkeypatch.setattr(validators.shutil, "which", lambda n: "somewhere-else")

    assert validators.epubcheck_binary() == str(launcher)


def test_a_missing_tool_is_reported_and_not_guessed_at(monkeypatch):
    monkeypatch.delenv(validators.EPUBCHECK_ENV, raising=False)
    monkeypatch.setattr(validators.shutil, "which", lambda n: None)

    assert not validators.epubcheck_available()
    passed, report = validators.run_epubcheck(Path("nowhere.epub"))
    assert passed is False
    assert "epubcheck" in report["error"]


def test_a_jar_is_run_through_the_jvm(tmp_path, monkeypatch):
    """The W3C's own release is a jar with its `lib/` beside it and nothing
    to put on PATH, so supporting only a launcher would have had the probe
    say no on a machine where the tool was sitting installed."""
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"PK\x03\x04 pretend")
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setenv(validators.EPUBCHECK_ENV, str(jar))
    monkeypatch.setattr(validators.shutil, "which",
                        lambda name: r"C:\java\bin\java.exe"
                        if name == "java" else None)
    ran = _Wrote({"messages": []})
    monkeypatch.setattr(validators.subprocess, "run", ran)

    passed, _report = validators.run_epubcheck(epub)

    assert ran.argv[0].endswith("java.exe")
    assert ran.argv[1] == "-jar"
    assert ran.argv[2] == str(jar)
    assert passed is True


def test_a_launcher_is_run_directly(tmp_path, monkeypatch):
    launcher = tmp_path / "epubcheck.bat"
    launcher.write_text("rem", encoding="utf-8")
    epub = tmp_path / "article.epub"
    epub.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setenv(validators.EPUBCHECK_ENV, str(launcher))
    ran = _Wrote({"messages": []})
    monkeypatch.setattr(validators.subprocess, "run", ran)

    validators.run_epubcheck(epub)

    assert ran.argv[0] == str(launcher)
    assert "-jar" not in ran.argv


def test_a_jar_with_no_java_is_a_tool_that_is_not_installed(tmp_path,
                                                            monkeypatch):
    """The probe gates the call, so a yes it cannot honour turns into a
    crash per article rather than a notice. That is the pairing
    `run_verapdf` warns about, and it cost 115 of them once."""
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"PK\x03\x04 pretend")
    monkeypatch.setenv(validators.EPUBCHECK_ENV, str(jar))
    monkeypatch.setattr(validators.shutil, "which", lambda name: None)

    assert not validators.epubcheck_available()

    passed, report = validators.run_epubcheck(tmp_path / "article.epub")

    assert passed is False
    assert "java" in report["error"]


# ---------- Chromium will not run as root ----------
#
# pa11y drives headless Chromium through puppeteer, and Chromium refuses
# to start as root unless `--no-sandbox` is passed. The container runs as
# root, so without this every pa11y run in production fails; on a
# developer's machine the flag is a real protection being dropped for no
# reason. `run_pa11y` built its argv with no way to pass launch arguments
# at all, which is why this is a change to the module and not to the
# Dockerfile alone.


def _pa11y_argv(tmp_path, monkeypatch):
    """Run pa11y against a throwaway page and hand back the argv used."""
    html = tmp_path / "article.html"
    html.write_text("<p>Body.</p>", encoding="utf-8")
    monkeypatch.setattr(validators.shutil, "which", lambda name: "/usr/bin/pa11y")
    ran = _Ran(stdout="[]")
    monkeypatch.setattr(validators.subprocess, "run", ran)
    validators.run_pa11y(html)
    return ran.argv


def test_root_is_what_decides_rather_than_a_setting(monkeypatch):
    """The test is the condition Chromium objects to, so nothing has to be
    remembered when the app is deployed."""
    monkeypatch.delenv(validators.PA11Y_SANDBOX_ENV, raising=False)
    monkeypatch.setattr(validators.os, "geteuid", lambda: 0, raising=False)
    assert validators.pa11y_needs_no_sandbox() is True

    monkeypatch.setattr(validators.os, "geteuid", lambda: 1000, raising=False)
    assert validators.pa11y_needs_no_sandbox() is False


def test_windows_has_no_geteuid_and_is_not_root(monkeypatch):
    """The question does not arise there, and asking it must not raise."""
    monkeypatch.delenv(validators.PA11Y_SANDBOX_ENV, raising=False)
    monkeypatch.delattr(validators.os, "geteuid", raising=False)

    assert validators.pa11y_needs_no_sandbox() is False


@pytest.mark.parametrize("value,wanted", [
    ("1", True), ("true", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False),
])
def test_the_environment_can_force_it_either_way(monkeypatch, value, wanted):
    monkeypatch.setenv(validators.PA11Y_SANDBOX_ENV, value)
    # Set regardless of what the machine running the tests is.
    monkeypatch.setattr(validators.os, "geteuid", lambda: 1000, raising=False)

    assert validators.pa11y_needs_no_sandbox() is wanted


def test_a_config_is_passed_only_where_the_sandbox_has_to_go(tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv(validators.PA11Y_SANDBOX_ENV, "0")
    argv = _pa11y_argv(tmp_path, monkeypatch)

    assert "--config" not in argv
    assert argv[-1].endswith("article.html")


def test_the_config_names_both_container_flags(tmp_path, monkeypatch):
    """`--disable-dev-shm-usage` travels with the sandbox flag rather than
    being a precaution: Docker gives a container 64 MB of /dev/shm and
    Chromium crashes partway through a page without it."""
    import json

    monkeypatch.setenv(validators.PA11Y_SANDBOX_ENV, "1")
    seen = {}

    html = tmp_path / "article.html"
    html.write_text("<p>Body.</p>", encoding="utf-8")
    monkeypatch.setattr(validators.shutil, "which", lambda name: "/usr/bin/pa11y")

    def capture(argv, **kwargs):
        # Read the config while the run is in flight, because the file is
        # temporary and gone by the time run_pa11y returns.
        path = Path(argv[argv.index("--config") + 1])
        seen["config"] = json.loads(path.read_text(encoding="utf-8"))
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.setattr(validators.subprocess, "run", capture)
    validators.run_pa11y(html)

    args = seen["config"]["chromeLaunchConfig"]["args"]
    assert "--no-sandbox" in args
    assert "--disable-dev-shm-usage" in args
    # The page is still the last word, after the config that was added.
    assert seen["argv"][-1].endswith("article.html")
    assert seen["argv"][0] == "/usr/bin/pa11y"


def test_the_config_file_does_not_outlive_the_run(tmp_path, monkeypatch):
    """A validator asked only to read a galley must not leave a file where
    it looked, which is why `run_epubcheck` writes its report to a temp
    directory too."""
    monkeypatch.setenv(validators.PA11Y_SANDBOX_ENV, "1")
    written = {}

    html = tmp_path / "article.html"
    html.write_text("<p>Body.</p>", encoding="utf-8")
    monkeypatch.setattr(validators.shutil, "which", lambda name: "/usr/bin/pa11y")

    def capture(argv, **kwargs):
        written["path"] = Path(argv[argv.index("--config") + 1])
        assert written["path"].exists()
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.setattr(validators.subprocess, "run", capture)
    validators.run_pa11y(html)

    assert not written["path"].exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["article.html"]
