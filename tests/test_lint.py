"""Unit tests for lint.py checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lint


def _check(title: str, short_title: str):
    return lint.check_short_title_matches_title(
        {}, {"title": title, "short-title": short_title}, ""
    )


def test_typo_in_short_title_is_flagged():
    """The short title shows only in the running header, so a typo there
    survives every proofread of the article itself."""
    result = _check(
        "Magnifying Dissent: the Capital Appeals Process", "Maginifying Dissent"
    )
    assert result.level == "warn"
    assert "maginifying" in result.summary


def test_clean_truncation_passes():
    result = _check(
        "Magnifying Dissent: the Capital Appeals Process", "Magnifying Dissent"
    )
    assert result.level == "pass"


def test_acronym_and_punctuation_survive():
    assert _check(
        "Against AI Empire and the Critwashing of Generative AI", "Against AI Empire"
    ).level == "pass"
    assert _check(
        "Facing What's Human: From Dialogic Intertextuality", "Facing What's Human"
    ).level == "pass"


def test_plural_in_title_is_not_a_typo():
    """A singular in the short title against a plural in the title is normal."""
    assert _check("A Study of Literacy in Prisons", "Prison Literacy").level == "pass"
    assert _check("Reading Narratives of Recovery", "Recovery Narrative").level == "pass"
    assert _check("Teaching Bodies and Archives", "Teaching Body").level == "pass"
    assert _check("Studies in Literacy", "Study of Literacy").level == "pass"


def test_deliberate_rephrasing_warns():
    """Advisory only: this cannot tell a rewording from a slip, and says so."""
    result = _check("A Study of Literacy in Prisons", "Carceral Literacy")
    assert result.level == "warn"
    assert any("rephrases" in d for d in result.details)


def test_missing_values_do_not_warn():
    """check_short_title_length already reports an empty short title."""
    assert _check("Some Title", "").level == "pass"
    assert _check("", "Some Short Title").level == "pass"


def test_stopwords_are_ignored():
    """Function words carry no signal and appear in almost any title."""
    assert _check("Reading in the Dark", "Reading Through the Dark").level == "pass"


def test_check_is_registered():
    assert lint.check_short_title_matches_title in lint.DEFAULT_CHECKS
