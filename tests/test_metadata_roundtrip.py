"""Regression tests for conversion.read/write_article_metadata."""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion


def _scratch_article(initial_yaml_body: str) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".versions").mkdir(exist_ok=True)
    (tmp / "article.md").write_text(initial_yaml_body, encoding="utf-8")
    return tmp


def test_round_trip_basic():
    article = _scratch_article(
        "---\ntitle: Foo\nshort-title: F\nshort-authors: A\n---\n\nbody.\n"
    )
    try:
        fm, body = conversion.read_article_metadata(article)
        assert fm["title"] == "Foo"
        fm["doi"] = "10.1/x"
        conversion.write_article_metadata(article, fm, body)
        fm2, _ = conversion.read_article_metadata(article)
        assert fm2["title"] == "Foo"
        assert fm2["doi"] == "10.1/x"
    finally:
        shutil.rmtree(article)


def test_sanitize_newlines_in_title():
    """If title has an embedded newline, sanitizer collapses to a space.
    Without the sanitizer the resulting YAML can parse ambiguously."""
    article = _scratch_article("---\ntitle: x\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {"title": "Against AI Empire and the \nCritwashing of Generative AI"},
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        fm = yaml.safe_load(raw[4:end])
        assert fm["title"] == "Against AI Empire and the Critwashing of Generative AI"
    finally:
        shutil.rmtree(article)


def test_sanitize_whitespace_in_authors():
    """Author names with stray whitespace/newlines normalize cleanly."""
    article = _scratch_article("---\ntitle: x\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {
                "title": "T",
                "author": [
                    {"name": "Maggie  Fernandes\n", "affiliation": "  UoA  "},
                    {"name": "Jenny\tSano-Franchini", "affiliation": "WVU"},
                ],
            },
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        fm = yaml.safe_load(raw[4:end])
        assert fm["author"][0]["name"] == "Maggie Fernandes"
        assert fm["author"][0]["affiliation"] == "UoA"
        assert fm["author"][1]["name"] == "Jenny Sano-Franchini"
    finally:
        shutil.rmtree(article)


def test_field_order_canonical():
    """Canonical field order: title first, then author, etc."""
    article = _scratch_article("---\nstatus: draft\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {
                "status": "draft",
                "footer": "Journal X 1.1",
                "short-title": "ST",
                "abstract": "An abstract.",
                "title": "T",
                "author": [{"name": "A"}],
                "short-authors": "SA",
            },
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        yaml_block = raw[4:end]
        # First three lines should be title, author, abstract (in that order)
        first_keys = [line.split(":")[0] for line in yaml_block.splitlines() if line and not line.startswith((" ", "-"))][:5]
        assert first_keys[:3] == ["title", "author", "abstract"]
    finally:
        shutil.rmtree(article)


def test_round_trip_preserves_body():
    article = _scratch_article(
        "---\ntitle: T\n---\n\n# Heading\n\nBody paragraph with `code` and *italics*.\n"
    )
    try:
        fm, body = conversion.read_article_metadata(article)
        assert "Heading" in body
        conversion.write_article_metadata(article, fm, body)
        _, body2 = conversion.read_article_metadata(article)
        assert body == body2
    finally:
        shutil.rmtree(article)
