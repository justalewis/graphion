"""What the EPUB says about what a reader can do with it.

EPUB Accessibility 1.1 asks a publication to declare how it can be read:
`schema:accessMode` for the senses the content comes through,
`schema:accessModeSufficient` for the ones that are enough on their own,
`schema:accessibilityFeature` for what has been done to help, and
`schema:accessibilityHazard`. Without them a library catalogue has nothing
to tell a reader about the file before they download it, which is most of
the point of putting them there.

Pandoc 3 writes some of this already, and that is the part worth knowing.
It emits `accessMode: textual`, `accessModeSufficient: textual`,
`accessibilityFeature: alternativeText, readingOrder, structuralNavigation,
tableOfContents`, and `accessibilityHazard: none`, the same set for every
file it converts. Two of those are claims about content it has not looked
at. `alternativeText` is asserted whether or not a single figure carries
a description, and `accessModeSufficient: textual` says a reader who cannot
see the pictures is missing nothing. For a chapter with an undescribed
figure both are false, and a false accessibility claim is worse than a
missing one: it tells a reader the book will work for them.

So this module replaces that block rather than adding to it, and it decides
each value from the article. The counts come from `lint`, which already
works them out, so what the EPUB declares and what the accessibility page
reports cannot drift apart.

`dcterms:conformsTo` is the conformance claim itself and is written only
where the article's own checks support it. WCAG 2.1 AA includes 1.4.5,
images of text, so a chapter that sets text as a picture does not conform
however well it is described, and the claim is left off rather than
qualified. `accessibilitySummary` is written either way and says what is
true, including the part no check settles.

Pandoc's `--epub-metadata` cannot carry any of this: the `<meta property>`
elements in that file are dropped and its own defaults written instead, so
the package document is edited after the fact. An EPUB is a zip whose first
entry must be an uncompressed `mimetype`, which is the one thing a rewrite
has to get right and the one thing a reader checks first.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

CONFORMS_TO = "EPUB Accessibility 1.1 - WCAG 2.1 Level AA"

# The properties this module owns. Anything matching these is taken out of
# the package document before ours goes in, so running twice leaves one
# copy and Pandoc's defaults never sit beside a contradicting value.
_OWNED = re.compile(
    r"[ \t]*<meta\s+property=\"(?:schema:access[^\"]*|dcterms:conformsTo"
    r"|a11y:certifiedBy)\"[^>]*>.*?</meta>\s*\n?",
    re.S,
)
_METADATA_END = re.compile(r"(\s*)</metadata>")


@dataclass
class Claim:
    """What one article can say about itself, and what it cannot."""

    access_modes: List[str] = field(default_factory=list)
    sufficient: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    hazards: List[str] = field(default_factory=lambda: ["none"])
    summary: str = ""
    conforms_to: Optional[str] = None
    certified_by: Optional[str] = None

    def as_meta(self) -> str:
        """The package document lines, in the order a reader of the OPF
        would want them."""
        rows = []
        for mode in self.access_modes:
            rows.append(("schema:accessMode", mode))
        for mode in self.sufficient:
            rows.append(("schema:accessModeSufficient", mode))
        for feature in self.features:
            rows.append(("schema:accessibilityFeature", feature))
        for hazard in self.hazards:
            rows.append(("schema:accessibilityHazard", hazard))
        if self.summary:
            rows.append(("schema:accessibilitySummary", self.summary))
        if self.conforms_to:
            rows.append(("dcterms:conformsTo", self.conforms_to))
            if self.certified_by:
                rows.append(("a11y:certifiedBy", self.certified_by))
        return "".join(
            f'    <meta property="{name}">{_escape(value)}</meta>\n'
            for name, value in rows
        )


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def describe(fm: dict, body: str, certifier: str = "") -> Claim:
    """Read one article and say what its EPUB can claim.

    The counts come from `lint`, which already works them out for the
    accessibility page; deriving them again here would be a second reader
    of the same thing, and this codebase has lost a figure count that way
    before.
    """
    import lint

    figures = lint.check_alt_text({}, fm, body).units
    equations = lint.check_math_alt_text({}, fm, body).units
    unreadable = lint.check_unreadable_characters({}, fm, body).units
    images_of_text = lint.check_images_of_text({}, fm, body).units

    total = figures.get("figures", 0)
    described = figures.get("figures-described", 0)
    owed = total - described
    of_text = images_of_text.get("images-of-text", 0)
    maths = equations.get("equations", 0)
    maths_owed = equations.get("equations-undescribed", 0)

    claim = Claim()
    claim.access_modes = ["textual"] + (["visual"] if total else [])

    # Textual alone is enough only where nothing is carried by a picture:
    # every figure described, and none of them setting words as an image,
    # since a description of a page of text is not the text.
    if total and (owed or of_text):
        claim.sufficient = ["textual,visual"]
    else:
        claim.sufficient = ["textual"]

    claim.features = ["structuralNavigation", "tableOfContents", "readingOrder"]
    if total and not owed:
        claim.features.append("alternativeText")
    if maths:
        # Pandoc's EPUB writer emits real MathML with a TeX annotation, and
        # that is what this feature names: the markup, which a screen reader
        # can walk. Whether a formula also carries a reading somebody wrote
        # is a separate affordance, and it is the conformance claim below
        # that turns on it, not this one.
        claim.features.append("MathML")

    claim.summary = _summarise(total, described, of_text, maths, maths_owed,
                               unreadable.get("unreadable-characters", 0))

    # The claim itself, only where the checks bear it. 1.4.5 is Level AA,
    # so a chapter that sets text as a picture does not conform however
    # well it is described; it gets the discoverability metadata, which is
    # required of every publication, and no conformance line.
    settled = (not owed and not of_text and not maths_owed
               and not unreadable.get("unreadable-characters", 0))
    if settled:
        claim.conforms_to = CONFORMS_TO
        claim.certified_by = certifier or None
    return claim


def _summarise(total, described, of_text, maths, maths_owed, unreadable) -> str:
    """Prose a reader meets before they download, in plain terms.

    It says what is not true as well as what is. A summary that lists only
    the good news is the same failure as a conformance claim nothing
    checked, in a field a catalogue prints verbatim.
    """
    parts = []
    if not total:
        parts.append("Text only; the chapter carries no figures.")
    elif described == total:
        parts.append(f"All {total} figure(s) carry a written description.")
    else:
        parts.append(f"{described} of {total} figure(s) carry a written "
                     f"description; {total - described} do not, and a reader "
                     f"who cannot see them will miss what they show.")
    if of_text:
        parts.append(f"{of_text} figure(s) set text as a picture, so those "
                     f"words are not available as text, cannot be searched "
                     f"or resized, and are described rather than transcribed.")
    if maths:
        if maths_owed:
            parts.append(f"{maths_owed} of {maths} equation(s) have no spoken "
                         f"description.")
        else:
            parts.append(f"All {maths} equation(s) are marked up as MathML "
                         f"and carry a spoken description.")
    if unreadable:
        parts.append(f"{unreadable} character(s) in the text have no meaning "
                     f"outside the font that wrote them.")
    parts.append("Headings, lists and navigation are structural throughout.")
    return " ".join(parts)


def stamp(epub_path: Path, claim: Claim) -> bool:
    """Write the claim into the EPUB's package document.

    Returns False where there is no package document to write to, which is
    a broken EPUB and not this module's to fix.

    The file is rebuilt rather than patched in place, because a zip entry
    cannot grow where it sits. `mimetype` goes back first and uncompressed:
    that is what a reading system looks at before it trusts anything else
    in the container, and a rewrite that deflates it produces a file that
    opens nowhere.
    """
    epub_path = Path(epub_path)
    with zipfile.ZipFile(epub_path) as zin:
        names = zin.namelist()
        opf_names = [n for n in names if n.lower().endswith(".opf")]
        if not opf_names:
            return False
        opf_name = opf_names[0]
        contents = {n: zin.read(n) for n in names}

    opf = contents[opf_name].decode("utf-8")
    opf = _OWNED.sub("", opf)
    match = _METADATA_END.search(opf)
    if not match:
        return False
    opf = opf[:match.start()] + "\n" + claim.as_meta() + "  </metadata>" \
        + opf[match.end():]
    contents[opf_name] = opf.encode("utf-8")

    temp = epub_path.with_suffix(".epub.tmp")
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in contents:
            zout.writestr("mimetype", contents["mimetype"],
                          compress_type=zipfile.ZIP_STORED)
        for name in names:
            if name == "mimetype":
                continue
            zout.writestr(name, contents[name])
    shutil.move(str(temp), str(epub_path))
    return True


def read_claim(epub_path: Path) -> dict:
    """What an EPUB currently declares, by property name.

    Reading it back is how the tests check what was written, and how
    anybody checks a file somebody else produced.
    """
    with zipfile.ZipFile(Path(epub_path)) as zin:
        opf_names = [n for n in zin.namelist() if n.lower().endswith(".opf")]
        if not opf_names:
            return {}
        opf = zin.read(opf_names[0]).decode("utf-8")
    found: dict = {}
    for name, value in re.findall(
            r"<meta\s+property=\"([^\"]+)\"[^>]*>(.*?)</meta>", opf, re.S):
        found.setdefault(name, []).append(value.strip())
    return found


__all__ = ["CONFORMS_TO", "Claim", "describe", "stamp", "read_claim"]
