"""Spoken descriptions for mathematics.

ISO 14289-1 wants a spoken equivalent for a formula the way it wants alt
text for a picture, and Typst enforces that: a `math.equation` carrying no
`alt` aborts a PDF/UA-1 compile. Pandoc's Typst writer emits a bare
`$...$`, so one equation anywhere in an article sent
`conversion._compile_typst` down its fallback path and the galley shipped
with no conformance identifier. Nothing reported it either, which is the
worse half: `lint.check_alt_text` matches Markdown image syntax, and an
equation is not an image, so the article linted clean.

What a formula sounds like is a judgement rather than a transcription, so
this module is deliberately narrow. `speak()` reads only a vocabulary it
can read unambiguously and returns None for everything else, and
`alt_for()` then falls back to a placeholder naming the equation as
undescribed. That is the trade `pdf_ingest.undescribed_alt` makes for a
figure whose page printed no caption: in the document imperfectly beats
absent, and the shortfall stays countable because
`lint.check_math_alt_text` goes on reporting it.

Declining is the point rather than a shortfall of the vocabulary. A
formula read half right is the failure this archive least wants, because
it is present and wrong and no conformance check can see it: a reader
hearing "a over b over c" for a nested fraction has been told something
false in a galley that passes every audit. So anything whose reading
depends on grouping that the page shows and speech does not carries an
explicit end marker, and anything outside the vocabulary declines whole
rather than in part. The tilde is the plainest case: it reads "is similar
to" in geometry and "is distributed as" in statistics, the expression
cannot say which, and so this does not guess.

An author's own description always wins, and is kept by hand in the
article's `math-alt` front matter, keyed by the expression as written.
Nothing can derive what an author means a formula to say, in the same way
that nothing can tell a photograph of a document from a photograph of
anything else, which is why `images-of-text` is kept by hand too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

UNDESCRIBED = "Undescribed equation"

_UNDESCRIBED_RE = re.compile(r"^Undescribed equation\b")


def undescribed() -> str:
    """The placeholder for an equation nothing can read aloud.

    It says only that an equation is there, which is little, and is still
    what keeps the galley conformant: an empty `alt` costs the article its
    PDF/UA-1 identifier, and leaving the equation out costs the reader the
    equation.
    """
    return UNDESCRIBED


def is_undescribed(alt: str) -> bool:
    return bool(_UNDESCRIBED_RE.match((alt or "").strip()))


# ---------- the vocabulary ----------
#
# Every entry here reads one way and no other. A symbol that reads two ways
# depending on the field is left out, so an expression holding it declines.

_GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta",
    "eta", "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu",
    "xi", "pi", "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi",
    "psi", "omega",
}

_GREEK_CAPS = {
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon",
    "Phi", "Psi", "Omega",
}

_RELATIONS = {
    "=": "equals",
    "<": "is less than",
    ">": "is greater than",
    "\\ne": "is not equal to",
    "\\neq": "is not equal to",
    "\\le": "is less than or equal to",
    "\\leq": "is less than or equal to",
    "\\ge": "is greater than or equal to",
    "\\geq": "is greater than or equal to",
    "\\approx": "is approximately equal to",
    "\\equiv": "is equivalent to",
    "\\propto": "is proportional to",
    "\\to": "goes to",
    "\\rightarrow": "goes to",
}

_OPERATORS = {
    "+": "plus",
    "-": "minus",
    "\\pm": "plus or minus",
    "\\mp": "minus or plus",
    "\\times": "times",
    "\\cdot": "times",
    "\\div": "divided by",
    "/": "divided by",
}

_SYMBOLS = {
    "\\infty": "infinity",
    "\\%": "percent",
    "\\&": "and",
    "\\dots": "and so on",
    "\\ldots": "and so on",
    "\\cdots": "and so on",
}

_FUNCTIONS = {
    "\\log": "log",
    "\\ln": "natural log",
    "\\sin": "sine",
    "\\cos": "cosine",
    "\\tan": "tangent",
    "\\max": "max",
    "\\min": "min",
    "\\det": "determinant",
}

_ACCENTS = {
    "\\bar": "bar",
    "\\overline": "bar",
    "\\hat": "hat",
    "\\widehat": "hat",
    "\\tilde": "tilde",
    "\\dot": "dot",
}

_DELIMITERS = {
    "(": "open paren",
    ")": "close paren",
    "[": "open bracket",
    "]": "close bracket",
    "\\{": "open brace",
    "\\}": "close brace",
    ",": "comma",
}

# Spacing and sizing macros carry no sound at all.
_SILENT = {
    "\\,", "\\;", "\\:", "\\!", "\\ ", "\\quad", "\\qquad", "\\left",
    "\\right", "\\displaystyle", "\\limits", "\\nolimits",
}

_LITERAL_GROUP = {"\\text", "\\mathrm", "\\textrm", "\\operatorname"}

_FRACTIONS = {"\\frac", "\\dfrac", "\\tfrac"}

_SCRIPTS = ("^", "_")


class _Decline(Exception):
    """Raised anywhere the reading would be a guess."""


_TOKEN_RE = re.compile(
    r"\\[A-Za-z]+|\\.|\d+(?:\.\d+)?|\.\d+|[A-Za-z]|[{}^_]|\S"
)


def _tokenize(tex: str) -> list:
    """Split TeX into tokens, single letters included.

    Letters come out one at a time because `xy` is a product and not a
    word: handed "xy" a screen reader guesses at a syllable, handed "x y"
    it reads the two factors.
    """
    out = []
    pos = 0
    for match in _TOKEN_RE.finditer(tex):
        if tex[pos:match.start()].strip():
            raise _Decline
        pos = match.end()
        out.append(match.group(0))
    if tex[pos:].strip():
        raise _Decline
    return out


def _nest(tokens: list) -> list:
    """Turn a flat token list into a tree, each braced group a list."""
    stack: list = [[]]
    for tok in tokens:
        if tok == "{":
            stack.append([])
        elif tok == "}":
            if len(stack) == 1:
                raise _Decline
            group = stack.pop()
            stack[-1].append(group)
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise _Decline
    return stack[0]


def _flatten(node) -> list:
    if isinstance(node, list):
        out = []
        for child in node:
            out.extend(_flatten(child))
        return out
    return [node]


def _is_atom(node) -> bool:
    """Whether a node reads as one thing, so it needs no end marker."""
    return len(_flatten(node)) == 1


def _as_nodes(node) -> list:
    return node if isinstance(node, list) else [node]


def _operand(nodes: list, i: int):
    if i >= len(nodes):
        raise _Decline
    return nodes[i], i + 1


def _literal_group(node) -> str:
    """The text of a `\\text{...}` group, read as written."""
    tokens = _flatten(node)
    for tok in tokens:
        if not re.fullmatch(r"[A-Za-z0-9.]+|-", tok):
            raise _Decline
    return "".join(tokens)


def _say_script(node, marker: str) -> str:
    """Read a superscript or subscript.

    A script holding another script, or a fraction, declines: `a^{b^c}`
    read flat is "a to the b to the c", which is the same words either
    grouping would produce.
    """
    tokens = _flatten(node)
    if any(tok in _SCRIPTS or tok in _FRACTIONS or tok == "\\sqrt"
           for tok in tokens):
        raise _Decline
    inner = " ".join(_say(_as_nodes(node)))
    if not inner:
        raise _Decline
    if marker == "^":
        if inner == "2":
            return "squared"
        if inner == "3":
            return "cubed"
        return f"to the {inner}"
    return f"sub {inner}"


def _say_fraction(num, den, *, nested: bool) -> list:
    if nested:
        raise _Decline
    said_num = " ".join(_say(_as_nodes(num), in_fraction=True))
    said_den = " ".join(_say(_as_nodes(den), in_fraction=True))
    if not said_num or not said_den:
        raise _Decline
    if _is_atom(num) and _is_atom(den):
        return [said_num, "over", said_den]
    # Where either side is more than one thing the page shows the grouping
    # and speech does not, so the reading has to say where it ends.
    return ["the fraction", said_num, "over", said_den, "end fraction"]


def _say_root(node) -> list:
    said = " ".join(_say(_as_nodes(node)))
    if not said:
        raise _Decline
    if _is_atom(node):
        return ["the square root of", said]
    return ["the square root of", said, "end root"]


def _say(nodes: list, *, in_fraction: bool = False) -> list:
    out: list = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if isinstance(node, list):
            out.extend(_say(node, in_fraction=in_fraction))
            i += 1
            continue
        tok = node
        if tok in _SCRIPTS:
            operand, i = _operand(nodes, i + 1)
            out.append(_say_script(operand, tok))
            continue
        if tok in _FRACTIONS:
            num, i = _operand(nodes, i + 1)
            den, i = _operand(nodes, i)
            out.extend(_say_fraction(num, den, nested=in_fraction))
            continue
        if tok == "\\sqrt":
            arg, i = _operand(nodes, i + 1)
            out.extend(_say_root(arg))
            continue
        if tok in _ACCENTS:
            arg, i = _operand(nodes, i + 1)
            if not _is_atom(arg):
                raise _Decline
            out.append(" ".join(_say(_as_nodes(arg))))
            out.append(_ACCENTS[tok])
            continue
        if tok == "\\vec":
            arg, i = _operand(nodes, i + 1)
            if not _is_atom(arg):
                raise _Decline
            out.append("vector")
            out.append(" ".join(_say(_as_nodes(arg))))
            continue
        if tok in _LITERAL_GROUP:
            arg, i = _operand(nodes, i + 1)
            out.append(_literal_group(arg))
            continue
        i += 1
        if tok in _SILENT:
            continue
        for table in (_RELATIONS, _OPERATORS, _SYMBOLS, _FUNCTIONS,
                      _DELIMITERS):
            if tok in table:
                out.append(table[tok])
                break
        else:
            if tok.startswith("\\"):
                name = tok[1:]
                if name in _GREEK:
                    out.append(name)
                elif name in _GREEK_CAPS:
                    out.append(f"capital {name.lower()}")
                else:
                    raise _Decline
            elif re.fullmatch(r"\d+(?:\.\d+)?|\.\d+", tok):
                # Digits stay digits. A screen reader already reads ".05"
                # as "point zero five", and spelling it out here would put
                # a second, worse number reader in the pipeline.
                out.append(tok)
            elif re.fullmatch(r"[A-Za-z]", tok):
                out.append(tok)
            else:
                raise _Decline
    return out


def speak(tex: str) -> Optional[str]:
    """Read an expression aloud, or return None rather than guess."""
    if not (tex or "").strip():
        return None
    try:
        said = _say(_nest(_tokenize(tex)))
    except (_Decline, RecursionError):
        return None
    text = re.sub(r"\s+", " ", " ".join(word for word in said if word)).strip()
    return text or None


# ---------- resolving one expression ----------

AUTHOR = "author"
GENERATED = "generated"
UNDESCRIBED_SOURCE = "undescribed"


def normalize(tex: str) -> str:
    """The key an expression is matched on, in the front matter and here.

    Whitespace only, so an author who writes the key with the spacing they
    find readable still matches the expression in the body.
    """
    return " ".join((tex or "").split())


def author_descriptions(fm: dict) -> dict:
    """The `math-alt` map from an article's front matter, keyed normalized."""
    raw = (fm or {}).get("math-alt") or {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        text = " ".join(str(value).split())
        if text:
            out[normalize(str(key))] = text
    return out


def alt_for(tex: str, descriptions: Optional[dict] = None) -> tuple:
    """Resolve one expression to (alt text, where the text came from)."""
    written = (descriptions or {}).get(normalize(tex))
    if written:
        return written, AUTHOR
    said = speak(tex)
    if said:
        return said, GENERATED
    return undescribed(), UNDESCRIBED_SOURCE


# ---------- finding math in a Markdown body ----------

_FENCE_RE = re.compile(r"^(?P<fence>```+|~~~+).*?^(?P=fence)[ \t]*$",
                       re.M | re.S)
_INLINE_CODE_RE = re.compile(r"`+[^`]*`+")
_DISPLAY_RE = re.compile(r"\$\$(?P<tex>.+?)\$\$", re.S)
_INLINE_RE = re.compile(r"(?<!\\)\$(?P<tex>[^\s$][^$]*?)(?<![\s\\])\$(?!\d)")


@dataclass
class MathExpr:
    tex: str
    display: bool


def expressions(body: str) -> list:
    """Every expression in a Markdown body, the display ones first.

    Pandoc decides what is math when a galley renders, and the filter takes
    its expressions from that decision rather than from this one, so a
    disagreement here costs a count in an advisory check and never a wrong
    galley: an expression this misses still gets its alt text, and one it
    invents is reported and renders nothing. Code is stripped first, since
    a technical writing volume sets `$PATH` in a shell example and Pandoc
    does not read that as math either.
    """
    text = _FENCE_RE.sub(" ", body or "")
    text = _INLINE_CODE_RE.sub(" ", text)
    found = []
    for match in _DISPLAY_RE.finditer(text):
        found.append(MathExpr(tex=match.group("tex").strip(), display=True))
    text = _DISPLAY_RE.sub(" ", text)
    for match in _INLINE_RE.finditer(text):
        found.append(MathExpr(tex=match.group("tex").strip(), display=False))
    return [expr for expr in found if expr.tex]
