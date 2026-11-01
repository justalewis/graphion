"""Spoken descriptions for mathematics.

The defect these cover had no symptom. Typst refuses a `math.equation`
carrying no `alt`, Pandoc's Typst writer emits a bare `$...$`, and
`lint.check_alt_text` reads Markdown image syntax, so an article with one
equation in it rendered through `_compile_typst`'s fallback path, shipped
without the PDF/UA-1 conformance identifier, and linted clean. It had
never fired only because neither journal in this install had set an
equation yet.

Two halves, then. That every equation now carries alt text, and that an
expression this cannot read aloud says so rather than guessing: a formula
read half right is present and wrong in a galley that passes every audit,
which is worse than one a reader is told is undescribed.
"""
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math_alt

pandoc = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(pandoc is None, reason="Pandoc is not on PATH")


# ---------- the vocabulary it reads ----------

READABLE = [
    ("n", "n"),
    ("a^2 + b^2 = c^2", "a squared plus b squared equals c squared"),
    ("R^2", "R squared"),
    ("x^3", "x cubed"),
    ("x^{10}", "x to the 10"),
    ("x_i", "x sub i"),
    ("p < .05", "p is less than .05"),
    (r"\mu = 0", "mu equals 0"),
    (r"\Sigma", "capital sigma"),
    (r"\bar{x}", "x bar"),
    (r"\frac{1}{2}", "1 over 2"),
    (r"\sqrt{2}", "the square root of 2"),
    (r"\log n", "log n"),
    (r"100\%", "100 percent"),
    (r"\text{Var}", "Var"),
    (r"x \leq y", "x is less than or equal to y"),
]


@pytest.mark.parametrize("tex,spoken", READABLE)
def test_an_expression_in_the_vocabulary_is_read_aloud(tex, spoken):
    assert math_alt.speak(tex) == spoken


def test_letters_are_read_one_at_a_time():
    """`xy` is a product and not a word, so it is not handed over as one:
    a screen reader given "xy" guesses at a syllable."""
    assert math_alt.speak("xy") == "x y"


def test_a_number_stays_a_number():
    """A screen reader already reads ".05" aloud. Spelling it out here
    would put a second, worse number reader in the pipeline."""
    assert ".05" in math_alt.speak("p = .05")


# ---------- what it declines, and why ----------

DECLINED = [
    # Outside the vocabulary altogether.
    (r"\sum_{i=1}^{n} x_i", "a summation"),
    (r"\int_0^1 f(x)\,dx", "an integral"),
    (r"\begin{bmatrix}1\end{bmatrix}", "an environment"),
    (r"\lim_{x \to 0} f(x)", "a limit"),
    # Reads two ways depending on the field, and the expression cannot say
    # which: "is similar to" in geometry, "is distributed as" in statistics.
    (r"x \sim y", "a tilde"),
    # Absolute value, norm, conditional probability, matrix determinant.
    ("|x|", "a bar delimiter"),
    # Grouping the page shows and speech does not.
    (r"\frac{\frac{a}{b}}{c}", "a nested fraction"),
    ("a^{b^c}", "a nested superscript"),
    (r"x^{\frac{1}{2}}", "a fraction in a superscript"),
]


@pytest.mark.parametrize("tex,why", DECLINED)
def test_an_expression_it_cannot_read_declines_whole(tex, why):
    assert math_alt.speak(tex) is None, why


def test_a_compound_fraction_says_where_it_ends():
    """"a plus b over c" is the same words either grouping would produce,
    so the reading carries the marker the page does not have to."""
    assert math_alt.speak(r"\frac{a+b}{c}") == (
        "the fraction a plus b over c end fraction"
    )
    assert math_alt.speak(r"\sqrt{a+b}") == (
        "the square root of a plus b end root"
    )


def test_an_unknown_macro_declines_rather_than_dropping_out():
    """Reading `\\oplus` as nothing would turn a direct sum into "a b"."""
    assert math_alt.speak(r"a \oplus b") is None


def test_unbalanced_braces_decline():
    assert math_alt.speak(r"\frac{a}{b") is None
    assert math_alt.speak("a}b") is None


def test_an_empty_expression_has_nothing_to_say():
    assert math_alt.speak("") is None
    assert math_alt.speak("   ") is None


# ---------- resolving one expression ----------

def test_an_author_description_wins():
    fm = {"math-alt": {"a^2 + b^2 = c^2": "the Pythagorean theorem"}}
    alt, source = math_alt.alt_for(
        "a^2 + b^2 = c^2", math_alt.author_descriptions(fm)
    )
    assert alt == "the Pythagorean theorem"
    assert source == math_alt.AUTHOR


def test_an_author_description_matches_across_spacing():
    """The key is matched on whitespace alone, so an editor can write it
    with the spacing they find readable."""
    fm = {"math-alt": {"a^2  +  b^2 = c^2": "the Pythagorean theorem"}}
    alt, source = math_alt.alt_for(
        "a^2 + b^2  =  c^2", math_alt.author_descriptions(fm)
    )
    assert source == math_alt.AUTHOR
    assert alt == "the Pythagorean theorem"


def test_an_author_description_wins_over_a_reading_it_could_have_made():
    fm = {"math-alt": {"n": "the number of students in the study"}}
    alt, _ = math_alt.alt_for("n", math_alt.author_descriptions(fm))
    assert alt == "the number of students in the study"


def test_an_unreadable_expression_falls_back_to_the_placeholder():
    alt, source = math_alt.alt_for(r"\sum_{i=1}^{n} x_i")
    assert source == math_alt.UNDESCRIBED_SOURCE
    assert math_alt.is_undescribed(alt)


def test_the_placeholder_is_never_empty():
    """An empty alt costs the galley its conformance identifier, which is
    the whole reason this is a placeholder and not an omission."""
    assert math_alt.undescribed().strip()


def test_a_written_description_is_not_read_as_the_placeholder():
    assert not math_alt.is_undescribed("a squared plus b squared")


def test_a_non_mapping_front_matter_value_is_ignored():
    """An editor who types a list where a map goes should lose the
    descriptions, not the render."""
    assert math_alt.author_descriptions({"math-alt": ["a^2"]}) == {}
    assert math_alt.author_descriptions({}) == {}


# ---------- finding math in a body ----------

def test_inline_and_display_math_are_both_found():
    body = textwrap.dedent("""\
        Prose with $n$ in it.

        $$a^2 + b^2 = c^2$$

        More prose with $x_i$ after.
        """)
    found = math_alt.expressions(body)
    assert [expr.tex for expr in found] == ["a^2 + b^2 = c^2", "n", "x_i"]
    assert [expr.display for expr in found] == [True, False, False]


def test_a_shell_variable_in_code_is_not_an_equation():
    """A technical writing volume sets `$PATH` in an example, and Pandoc
    does not read that as math either."""
    body = textwrap.dedent("""\
        Run it like this:

        ```bash
        echo $PATH && cd $HOME
        ```

        And inline, `export $EDITOR`, which is also not math.
        """)
    assert math_alt.expressions(body) == []


def test_a_pair_of_prices_is_not_an_equation():
    """Pandoc declines a closing dollar sign followed by a digit, and so
    does this: the two have to agree or the count is wrong."""
    assert math_alt.expressions("It went from $5 to $10 a copy.") == []


def test_a_body_with_no_math_finds_none():
    assert math_alt.expressions("Ordinary prose, costing $20.") == []


# ---------- the filter, and the alt text it carries into Typst ----------

MATH_DOC = textwrap.dedent("""\
    Inline $a^2 + b^2 = c^2$ and a display equation:

    $$\\sum_{i=1}^{n} x_i$$
    """)


def _to_typst(md: str) -> str:
    import pypandoc

    import conversion

    out = pypandoc.convert_text(
        md, to="typst", format="markdown",
        extra_args=["--wrap=preserve"] + conversion._math_alt_filter_args(),
    )
    return out


@needs_pandoc
def test_the_filter_leaves_pandoc_to_write_the_math():
    """Reimplementing the TeX to Typst translation here would be a second,
    worse copy of it, so the filter only wraps what Pandoc wrote."""
    typ = _to_typst(MATH_DOC)
    assert "$a^2 + b^2 = c^2$" in typ
    assert "sum_(i = 1)^n x_i" in typ


@needs_pandoc
def test_every_equation_comes_out_carrying_an_alt():
    import conversion

    filled = conversion._fill_math_alt(_to_typst(MATH_DOC))
    assert 'alt: "a squared plus b squared equals c squared"' in filled
    assert f'alt: "{math_alt.UNDESCRIBED}"' in filled
    assert "GRAPHION-MATH-ALT" not in filled


@needs_pandoc
def test_an_author_description_reaches_the_galley():
    import conversion

    fm = {"math-alt": {r"\sum_{i=1}^{n} x_i": "the sum of x sub i over i"}}
    filled = conversion._fill_math_alt(_to_typst(MATH_DOC), fm)
    assert 'alt: "the sum of x sub i over i"' in filled
    assert math_alt.UNDESCRIBED not in filled


@needs_pandoc
def test_a_description_with_a_quotation_mark_survives_the_literal():
    """The alt sits in a Typst string literal, which is what cost the
    author and short-title sentinels beside this one their own escaping."""
    import conversion

    fm = {"math-alt": {"a^2 + b^2 = c^2": 'what Euclid calls "the square"'}}
    filled = conversion._fill_math_alt(_to_typst(MATH_DOC), fm)
    assert r'alt: "what Euclid calls \"the square\""' in filled


@needs_pandoc
def test_math_is_left_alone_outside_typst():
    """The HTML galley already carries real MathML with a TeX annotation,
    so there is nothing here for this filter to add and a raw Typst inline
    would be a regression."""
    import pypandoc

    import conversion

    html = pypandoc.convert_text(
        MATH_DOC, to="html5", format="markdown",
        extra_args=["--mathml"] + conversion._math_alt_filter_args(),
    )
    assert "GRAPHION-MATH-ALT" not in html
    assert "math.equation" not in html
    assert "<math" in html
