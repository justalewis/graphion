"""Regressions in the Writing Spaces Lua filter, and the routes that serve
the second galley.

The filter's work only shows up once Pandoc has run, so these tests shell
out to it and skip where it is missing; the rest of the suite stays
Pandoc-free on purpose.
"""
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
FILTER = REPO / "content" / "journals" / "writing-spaces" / "template" / "journal-filter.lua"

pandoc = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(pandoc is None, reason="Pandoc is not on PATH")


TEMPLATE = FILTER.with_name("article.html.j2")


def _render(md: str) -> str:
    """Render through the real template, because metadata only reaches the
    output that way: without it Pandoc emits the body alone and the licence
    URL this is about never appears."""
    out = subprocess.run(
        [pandoc, "-f", "markdown+yaml_metadata_block", "-t", "html5",
         "--standalone", f"--template={TEMPLATE}", f"--lua-filter={FILTER}"],
        input=md, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return out.stdout


DOC = textwrap.dedent("""\
    ---
    title: A Chapter
    license-url: https://creativecommons.org/licenses/by-nc-nd/4.0/
    ---

    # First Section

    Body text citing <https://www.jstor.org/stable/a-very-long-identifier-here>.
    """)


@needs_pandoc
def test_metadata_urls_are_not_given_break_points():
    """The filter inserts soft break points into long URLs so a Works Cited
    entry cannot run off the measure. Walking the whole document applied
    that to metadata as well, and the licence URL reached its href as
    "https:/<wbr>/<wbr>creativecommons<wbr>.org/...", which no longer
    resolves."""
    html = _render(DOC)
    assert "licenses/by-nc-nd/4.0/" in html
    meta_line = [l for l in html.splitlines() if "creativecommons.org" in l]
    assert meta_line, "licence URL did not reach the output"
    assert all("<wbr>" not in l for l in meta_line), meta_line


@needs_pandoc
def test_body_urls_still_get_break_points():
    """The guard that matters: fixing the metadata must not stop the body
    URLs breaking, which is what the filter is for."""
    html = _render(DOC)
    body = html[html.find("First Section"):]
    assert "<wbr>" in body


@needs_pandoc
def test_body_headings_are_demoted_so_the_title_keeps_the_only_h1():
    """"# First Section" in the Markdown is an h1 by default, which leaves a
    chapter with a dozen of them and no document heading."""
    html = _render(DOC)
    assert html.count("<h1") == 1, "the title should be the only h1"
    assert "First Section" in html
    assert "<h2" in html, "the body heading should have been demoted"


# ---------- routes ----------


def test_the_teacher_galley_has_routes_to_serve_it():
    """A galley nothing can serve is a galley nobody gets."""
    import app as app_module

    flask_app = app_module.create_app()
    rules = {r.endpoint: str(r) for r in flask_app.url_map.iter_rules()}
    assert "serve_teacher_pdf" in rules
    assert "serve_teacher_html" in rules
    assert rules["serve_teacher_pdf"].endswith("teacher-resources.pdf")
    assert rules["serve_teacher_html"].endswith("teacher-resources.html")
