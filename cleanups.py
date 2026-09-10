"""Stage 2: deterministic Markdown cleanup passes.

Each pass is a pure function: (text, log) -> text. They are composed in
`run_all`. Every transformation is logged. Passes are idempotent: running
the full pipeline twice produces the same output.

When the user's working `clean.py` draft arrives, refine these passes
against it (they should converge in behavior, with this module being the
production refactor: testable, logged, idempotent).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import yaml


@dataclass
class CleanupLog:
    entries: List[str] = field(default_factory=list)

    def record(self, name: str, count: int, note: str = ""):
        if count == 0 and not note:
            return
        msg = f"  - {name}: {count} change(s)"
        if note:
            msg += f" ({note})"
        self.entries.append(msg)

    def add(self, line: str):
        self.entries.append(line)

    def render(self) -> str:
        return "\n".join(self.entries)


# ---------- individual passes ----------

def _strip_class_wrapper(text: str, classname: str) -> tuple[str, int]:
    """Strip `[...]{.classname}` wrappers, preserving the inner content.

    Handles nested brackets and multi-line spans by walking backward from
    each `]{.classname}` marker to find the matching `[`. Plain regex with
    `[^\\[\\]]` can't do this because real-world highlights routinely
    contain markdown links, internal `[bracket]` paraphrases, and span
    multiple lines.
    """
    marker = "]{." + classname + "}"
    out: list[str] = []
    i = 0
    count = 0
    n = len(text)
    while i < n:
        close = text.find(marker, i)
        if close == -1:
            out.append(text[i:])
            break
        depth = 1
        j = close - 1
        while j >= i and depth > 0:
            c = text[j]
            if c == "]":
                depth += 1
            elif c == "[":
                depth -= 1
            j -= 1
        if depth == 0:
            open_pos = j + 1
            inner = text[open_pos + 1: close]
            out.append(text[i:open_pos])
            out.append(inner)
            i = close + len(marker)
            count += 1
        else:
            out.append(text[i: close + len(marker)])
            i = close + len(marker)
    return "".join(out), count


def strip_highlighter_spans(text: str, log: CleanupLog) -> str:
    """Strip `[text]{.mark}` (Word highlighter annotation)."""
    new_text, count = _strip_class_wrapper(text, "mark")
    log.record("strip_highlighter_spans", count)
    return new_text


def strip_underline_spans(text: str, log: CleanupLog) -> str:
    """Strip `[text]{.underline}` (Word underline annotation, typically
    wrapping a URL inside a markdown link). The link itself stays intact
    and renders with the journal's link styling."""
    new_text, count = _strip_class_wrapper(text, "underline")
    log.record("strip_underline_spans", count)
    return new_text


def unescape_quoted_brackets(text: str, log: CleanupLog) -> str:
    """`\\[` -> `[` and `\\]` -> `]`. Pandoc over-escapes these."""
    n1 = text.count(r"\[")
    n2 = text.count(r"\]")
    text = text.replace(r"\[", "[").replace(r"\]", "]")
    log.record("unescape_quoted_brackets", n1 + n2)
    return text


def reassemble_heading_linebreaks(text: str, log: CleanupLog) -> str:
    r"""Merge multi-line headings separated by literal pipe or hard return.

    Pandoc emits Word's multi-line headings as e.g.::

        # First half \|Second half

    Or sometimes as two adjacent heading lines that should be one. We
    handle the explicit pipe form (most common); we leave the rare
    adjacent-heading form for hand-editing since auto-merging there has
    high false-positive risk.
    """
    # Only the ESCAPED pipe, which is the Word artifact. A spaced " | " is the
    # documented convention for a deliberate forced break (see
    # split_pipes_to_linebreaks in the journal filter); matching that here
    # silently undid every break an editor asked for.
    pattern = re.compile(r"^(#{1,6}\s.+?)\s*\\\|\s*(.+)$", re.MULTILINE)
    count = 0

    def _merge(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)} {m.group(2)}"

    text = pattern.sub(_merge, text)
    log.record("reassemble_heading_linebreaks", count)
    return text


def strip_orphan_page_numbers(text: str, log: CleanupLog) -> str:
    """Drop a lone 1-3 digit number on its own line at end of file.

    Conservative: only the trailing tail of the document. A single number
    mid-text could be intentional (e.g., a list).
    """
    pattern = re.compile(r"\n+\s*\d{1,3}\s*\n?\s*\Z")
    new_text, count = pattern.subn("\n", text)
    log.record("strip_orphan_page_numbers", count)
    return new_text.rstrip() + "\n"


def convert_pandoc_div_footnotes_to_native(text: str, log: CleanupLog) -> str:
    """Convert Pandoc Div-style footnote markup to canonical Pandoc
    footnote syntax (`[^id]` references, `[^id]: ` definitions).

    Pandoc HTML→Markdown round-trips emit footnotes as Div blocks with
    anchor identifiers, looking like this in the source:

        Body text[\\[1\\]](#footnote-2) ...

        1.  ::: {#footnote-2}
            For a more comprehensive look at how the question...
            [?](#footnote-ref-2)
            ::: 2.  ::: {#footnote-3}
            ...
            :::

    The body has `[N](#footnote-X)` links pointing INTO the divs;
    each div has a `[?](#footnote-ref-N)` back-arrow pointing back to
    the body location. This format doesn't survive `unfragment_works_cited`
    (the divs get merged into the trailing Works Cited entry and
    Pandoc's Typst writer can no longer emit proper labels), and even
    when parsed correctly, page-bottom footnotes don't work because
    these divs are floating content rather than `Note` AST nodes.

    Convert to canonical Pandoc footnote syntax:

        Body text[^footnote-2] ...

        [^footnote-2]: For a more comprehensive look...

    Pandoc's native footnote handling then takes over: clickable
    superscript markers in HTML, page-bottom footnotes in PDF, and
    Pandoc auto-generates the back-arrows. The footnote IDs are
    preserved verbatim (e.g., `footnote-2`) so we don't have to
    re-number — Pandoc renders the visual numbers based on body
    appearance order regardless of label content.
    """
    # 1. Find every div-style footnote definition, including any
    # leading numbered-list marker the round-trip may have introduced.
    # DOTALL so content can span newlines; non-greedy on content so
    # the first `:::` after the opening is treated as the closing.
    pattern = re.compile(
        r"(?:^|(?<=\s))"           # at start or after whitespace
        r"(?:\d+\.\s+)?"            # optional list marker like "1.  "
        r":::\s*\{#footnote-([^\s}]+)\}"  # opening: ::: {#footnote-N}
        r"\s*(.*?)"                 # content (non-greedy)
        r"\s*:::",                  # closing :::
        re.DOTALL,
    )

    definitions: dict[str, str] = {}
    order: list[str] = []

    def collect(m: "re.Match") -> str:
        fid = m.group(1)
        content = m.group(2)
        # Strip the back-arrow link found inside footnote content.
        content = re.sub(
            r"\s*\[[^\]]*\]\(#footnote-ref-[^)]+\)\s*",
            " ",
            content,
        )
        # Collapse runs of whitespace (the content was indented inside
        # the div, which produces hard newlines we don't want in the
        # final [^N]: definition).
        content = re.sub(r"\s+", " ", content).strip()
        if fid not in definitions:
            definitions[fid] = content
            order.append(fid)
        # Replace the div with nothing — definitions go to the bottom.
        return ""

    new_text, n_def = pattern.subn(collect, text)

    # 2. Rewrite body references to canonical Pandoc footnotes.
    # Two formats are commonly produced by Pandoc HTML round-trips:
    #
    #   (a) `[\[1\]](#footnote-2)`         — escaped-brackets text
    #   (b) `^^[[1]](#footnote-2){#footnote-ref-2}^^`  — superscript +
    #        link + attribute-ID (the attribute makes the body location
    #        targetable from the footnote's back-arrow link).
    #
    # We use a permissive regex that matches both — link text can
    # contain anything that isn't a newline, and the trailing
    # `{#footnote-ref-N}` attribute (if present) is consumed and
    # discarded. Outer `^^...^^` superscript markers are stripped if
    # they bracket the now-converted footnote ref (since `[^N]` is
    # rendered as a superscript automatically).
    body_ref = re.compile(
        r"(?P<sup_open>\^\^)?"
        r"\[[^\n]*?\]\(#footnote-(?P<id>[^\s)]+)\)"
        r"(?P<attr>\{#footnote-ref-[^}]+\})?"
        r"(?P<sup_close>\^\^)?"
    )
    def _replace_body_ref(m: "re.Match") -> str:
        return f"[^{m.group('id')}]"
    new_text, n_ref = body_ref.subn(_replace_body_ref, new_text)

    # 3. Strip any orphan back-arrow links that survived outside divs.
    new_text = re.sub(
        r"\[[^\n]*?\]\(#footnote-ref-[^)]+\)", "", new_text,
    )
    # Also strip orphan `{#footnote-ref-N}` attribute blocks.
    new_text = re.sub(r"\{#footnote-ref-[^}]+\}", "", new_text)

    # 4. Clean up the trailing artifacts left when divs got embedded in
    # a numbered list squashed onto one line: numerals + spaces that
    # used to mark list items now have nothing to mark.
    # e.g., "1825-1846.   2.   3.   4." after stripping. The trailing
    # naked "N.  " markers are safe to drop.
    #
    # Only when divs were actually converted, and only for one- or two-digit
    # markers. A bare number and period at the end of a line is also the shape
    # of the year closing a works-cited entry, so running this unconditionally
    # deleted the publication year from every citation ending "Routledge,
    # 2020." and left a dangling comma. Orphan list markers cannot appear
    # unless this pass removed the list they belonged to, and a list marker is
    # never four digits.
    if n_def:
        new_text = re.sub(r"(?<=\s)\d{1,2}\.\s+(?=\d{1,2}\.\s|$)", "", new_text)
        new_text = re.sub(r"(?<=\s)\d{1,2}\.\s*$", "", new_text, flags=re.MULTILINE)

    # 5. Append the collected definitions at the end of the document,
    # separated by blank lines so Pandoc parses each as a standalone
    # footnote definition.
    if definitions:
        new_text = new_text.rstrip()
        new_text += "\n\n" + "\n\n".join(
            f"[^{fid}]: {definitions[fid]}" for fid in order
        ) + "\n"
        log.record(
            "convert_pandoc_div_footnotes_to_native",
            len(definitions),
            f"converted {len(definitions)} Pandoc Div footnote(s) to [^N]: syntax "
            f"(rewrote {n_ref} body reference(s))",
        )

    return new_text


def repair_footnote_definitions(text: str, log: CleanupLog) -> str:
    """Unescape and unsplit Pandoc's broken footnote-definition output.

    The DOCX writer often emits `\\[^1\\]:` (with backslash-escaped
    brackets) instead of the canonical `[^1]:`, and concatenates the
    first footnote definition onto the trailing paragraph instead of
    starting a new line. Both defeats footnote recognition on the
    next render pass. We unescape and force a blank line before each
    definition so Pandoc emits a proper `<section class="footnotes">`.
    """
    # 1. Unescape `\[^X\]:` → `[^X]:`. X is the footnote id (alphanumeric).
    text, n_unescape = re.subn(r"\\\[\^([^\]]+)\\\]:", r"[^\1]:", text)
    # 2. Ensure each footnote definition starts on its own paragraph.
    text, n_split = re.subn(
        r"([^\n])(\s*\[\^[^\]]+\]:)",
        r"\1\n\n\2",
        text,
    )
    if n_unescape or n_split:
        log.record(
            "repair_footnote_definitions",
            n_unescape + n_split,
            f"unescape={n_unescape} split={n_split}",
        )
    return text


def convert_single_cell_tables_to_blockquotes(text: str, log: CleanupLog) -> str:
    """Convert grid tables that have only one column to Markdown
    blockquotes.

    DOCX text boxes, sidebar callouts, and "shaded paragraph" callouts
    all come through Pandoc as 1-column grid tables. Rendering them as
    actual tables is wrong: they're not data tables, they're pull-out
    callouts. Blockquotes get the right visual treatment in HTML
    (left rule + indent) and in Typst (indented italic), so we
    transform here.

    Multi-column tables (genuine data tables) are left untouched.
    """
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    n_converted = 0

    def is_separator(line: str) -> bool:
        s = line.strip()
        if not s.startswith("+"):
            return False
        # Separator chars are only +, -, :, =, whitespace.
        return all(c in "+-=: \t" for c in s)

    def column_count(sep: str) -> int:
        # Number of `+` minus 1 gives column count.
        return max(0, sep.count("+") - 1)

    while i < len(lines):
        line = lines[i]
        if is_separator(line) and column_count(line) == 1:
            # Try to find the closing separator and collect cell rows.
            j = i + 1
            cell_lines: List[str] = []
            valid = False
            while j < len(lines):
                inner = lines[j]
                if is_separator(inner) and column_count(inner) == 1:
                    valid = True
                    break
                stripped = inner.strip()
                # Cell row in a grid table starts and ends with `|`.
                if stripped.startswith("|") and stripped.endswith("|"):
                    # Strip the leading + trailing pipe; keep the cell text.
                    content = stripped[1:-1].rstrip()
                    cell_lines.append(content)
                    j += 1
                    continue
                # Anything else aborts the conversion (could be a
                # continuation row that didn't get split correctly).
                break

            if valid:
                # Build blockquote. Trim leading/trailing blank cells.
                while cell_lines and not cell_lines[0].strip():
                    cell_lines.pop(0)
                while cell_lines and not cell_lines[-1].strip():
                    cell_lines.pop()
                # Add a blank line before the blockquote if needed.
                if out and out[-1].strip():
                    out.append("")
                for cl in cell_lines:
                    s = cl.strip()
                    if s:
                        out.append("> " + s)
                    else:
                        out.append(">")
                out.append("")  # blank line after blockquote
                i = j + 1
                n_converted += 1
                continue

        out.append(line)
        i += 1

    if n_converted:
        log.record(
            "convert_single_cell_tables_to_blockquotes",
            n_converted,
            "converted 1-column grid tables to blockquotes (callout boxes / text boxes)",
        )
    return "\n".join(out)


def split_oneline_grid_tables(text: str, log: CleanupLog) -> str:
    """Re-split grid tables that Pandoc emitted as one physical line.

    Pandoc's `--wrap=none` (used during DOCX ingest) sometimes collapses
    an entire grid table onto a single line: separator rows + cell rows
    + separator rows all concatenated. The downstream MD→HTML/Typst
    pass then fails to recognize it as a table and treats the whole
    thing as a paragraph — running smart-typography over the `---`
    separators and producing em-dashes in the rendered output. This
    pass walks each line, finds all grid-table boundary tokens
    (`+---+`-style separator runs), and re-splits the line so each
    separator and each cell row lives on its own line.
    """
    sep_re = re.compile(r"\+[\-+:]{3,}\+")

    def fix_line(line: str) -> str:
        seps = list(sep_re.finditer(line))
        if len(seps) < 2:
            return line
        out_parts: List[str] = []
        cursor = 0
        for m in seps:
            # Text before this separator is a cell row (or whitespace).
            between = line[cursor:m.start()].strip()
            if between:
                out_parts.append(between)
            out_parts.append(m.group(0))
            cursor = m.end()
        tail = line[cursor:].strip()
        if tail:
            out_parts.append(tail)
        return "\n".join(out_parts)

    new_lines = []
    n_split = 0
    for line in text.split("\n"):
        fixed = fix_line(line)
        if fixed != line:
            n_split += 1
        new_lines.append(fixed)
    if n_split:
        log.record(
            "split_oneline_grid_tables",
            n_split,
            "re-split collapsed grid tables onto multiple lines",
        )
    return "\n".join(new_lines)


def normalize_dashes(text: str, log: CleanupLog) -> str:
    """Pandoc's `--smart` should handle this, but verify.

    Unicode em-dashes -> `---`, en-dashes -> `--`. (We keep ASCII so the
    Markdown round-trips cleanly; Pandoc's smart-typography on output
    will re-render them as Unicode in HTML/PDF.)
    """
    em = text.count("—")
    en = text.count("–")
    text = text.replace("—", "---").replace("–", "--")
    log.record("normalize_dashes", em + en, f"em={em} en={en}")
    return text


def repair_pandoc_bold_escape(text: str, log: CleanupLog) -> str:
    """Repair Pandoc's broken close-of-bold escape inside DOCX-derived
    Markdown.

    When Pandoc renders bold text from a DOCX cell that lives inside a
    blockquote inside a grid table (a common shape for pedagogical
    handouts), it sometimes emits the closing `**` with one asterisk
    escaped: `**Directions: ... class!\\**`. The leading backslash makes
    the first `*` literal, so the bold span never closes — the rendered
    HTML shows the literal asterisks and (worse) opens an unclosed
    emphasis that bleeds into the following cell.

    The pattern `\\**` (backslash + two asterisks, with no second
    backslash) is virtually unique to this Pandoc bug — in legitimate
    Markdown an author who wants literal `**` would escape BOTH
    asterisks as `\\*\\*`. So we treat any `\\**` as a misplaced bold
    close and replace it with `**`.
    """
    # `\**` followed by zero-or-more spaces — captures the common case
    # where the broken close sits right before a cell delimiter or end
    # of line. Don't touch `\*\*` (both escaped — legitimate literal).
    pattern = re.compile(r"(?<!\\)\\\*\*")
    new_text, n = pattern.subn("**", text)
    if n:
        log.record(
            "repair_pandoc_bold_escape",
            n,
            "fixed broken close-of-bold (Pandoc DOCX writer quirk)",
        )
    return new_text


def normalize_smart_quotes(text: str, log: CleanupLog) -> str:
    """Leave Unicode curly quotes as-is; Pandoc handles them.

    This pass exists as an idempotent no-op placeholder so the pipeline
    surface is stable. If we discover the source consistently has
    straight quotes that need curling, do it here.
    """
    log.record("normalize_smart_quotes", 0, "no-op (pandoc default)")
    return text


# ---------- conservative list normalization ----------

_LIST_CUE_RE = re.compile(
    r"(?:the\s+(?:\w+\s+)?(?:stories|points|reasons|examples|cases)\s+(?:we\s+)?(?:focus|consider|examine|discuss)\s+(?:on\s+)?are[:.])\s*$",
    re.IGNORECASE,
)


_WORKS_CITED_HEADING_RE = re.compile(
    # Match either a Markdown heading ("# Works Cited") or a bare line
    # ("Works Cited" on its own). Pandoc doesn't always promote Word's
    # works-cited paragraph to a heading if the author didn't style it.
    r"^(?:#{1,6}\s+)?(works cited|references|bibliography)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _ensure_works_cited_heading(text: str) -> str:
    """If `Works Cited` (or References / Bibliography) appears as a bare
    line, promote it to an H1 so downstream rendering treats it as a
    section. Idempotent."""
    def _promote(m: re.Match) -> str:
        existing = m.group(0)
        if existing.lstrip().startswith("#"):
            return existing
        return "# " + m.group(1)
    return _WORKS_CITED_HEADING_RE.sub(_promote, text)


# Strong signals that a paragraph IS the start of a new citation entry.
# Anything not matching these (and following a paragraph that doesn't end
# in clear terminal punctuation) is treated as a continuation.
_NEW_ENTRY_RE = re.compile(
    r"^\s*("
    r"---\.|—\.|--\."                                              # MLA same-author dash
    r"|\"[A-Z]|“[A-Z]|'[A-Z]|‘[A-Z]"                     # Quoted title (anonymous works)
    r"|[A-Z][\w'\-]+,\s+[A-Z]"                                     # `Surname, First` (most MLA)
    r"|[A-Z][\w'\-]+\s+[A-Z][\w'\-]+,\s+[A-Z]"                     # `Two-word Surname, First`
    r"|\*[A-Z]"                                                    # *Italic title* (title-led entry; ambiguous, see check below)
    r")"
)


def unfragment_works_cited(text: str, log: CleanupLog) -> str:
    """Merge fragmented Works Cited entries back into single paragraphs.

    Word's "Enter" between visually-hanging-indent citation lines gets
    converted to Markdown paragraph breaks by Pandoc, fragmenting one
    citation across many paragraphs. Indented continuations also come
    through as Markdown blockquotes (`>` prefix).

    Heuristic: in the Works Cited section, a paragraph is a continuation
    of the prior entry unless it (a) matches a strong "new entry" pattern
    AND (b) the prior entry ends in terminal punctuation. Both conditions
    must hold for a break to be preserved.

    Stops at the next heading or footnote definition.
    """
    # Make sure "Works Cited" is a heading so downstream styling and
    # this function's own search can recognize the section boundary.
    text = _ensure_works_cited_heading(text)

    m = _WORKS_CITED_HEADING_RE.search(text)
    if not m:
        return text

    head_end = m.end()
    head = text[:head_end]
    body = text[head_end:]

    stop_match = re.search(r"\n(#{1,6}\s|\[\^[^\]]+\]:)", body)
    if stop_match:
        body_section = body[:stop_match.start() + 1]
        tail = body[stop_match.start() + 1:]
    else:
        body_section = body
        tail = ""

    paragraphs = [p.strip() for p in re.split(r"\n\n+", body_section) if p.strip()]

    def starts_new_entry(s: str) -> bool:
        s = re.sub(r"^>\s*", "", s).strip()
        return bool(_NEW_ENTRY_RE.match(s))

    def ends_terminally(s: str) -> bool:
        s = s.rstrip().rstrip("*").rstrip()  # ignore trailing italic close
        if not s:
            return True
        if s[-1] in ".!?)":
            return True
        # Markdown angle-bracket URL close: `<https://...>`
        if s.endswith(">"):
            return True
        # Citation ending with a bare URL (Pandoc converts to Markdown link
        # but the visible content is the URL)
        if re.search(r"https?://[\w./?#\-=&%_]+$", s):
            return True
        return False

    merged: list[str] = []
    current: list[str] = []
    merge_count = 0
    for p in paragraphs:
        # Strip leading blockquote prefix lines so the merged citation is clean
        clean = re.sub(r"^>\s*", "", p, flags=re.MULTILINE).strip()

        if not current:
            current = [clean]
            continue

        prior = current[-1] if current else ""
        prior_terminal = ends_terminally(" ".join(current))
        is_new = starts_new_entry(clean)

        if is_new and prior_terminal:
            merged.append(" ".join(current))
            current = [clean]
        else:
            current.append(clean)
            merge_count += 1

    if current:
        merged.append(" ".join(current))

    new_body_section = "\n\n".join(merged) + ("\n" if merged else "")
    log.record(
        "unfragment_works_cited",
        merge_count,
        f"merged {merge_count} continuation paragraph(s) into prior entries",
    )
    return head + "\n\n" + new_body_section + tail


def conservative_list_normalization(text: str, log: CleanupLog) -> str:
    """No-op for now. The spec calls for conservative behavior; without a
    library of real-world inputs the safe default is to leave lists alone
    and surface ambiguity to the editor in the in-browser pane.
    """
    log.record("conservative_list_normalization", 0, "no-op (manual review)")
    return text


# ---------- front-matter extraction ----------

@dataclass
class ExtractedFrontMatter:
    title: Optional[str] = None
    authors: List[dict] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    abstract: Optional[str] = None
    body_after_strip: str = ""


# Author-affiliation regex. We accept em-dash, en-dash, triple-hyphen,
# and double-hyphen as the separator, because authors paste from many
# sources. But the regex alone isn't enough — body prose often contains
# the same separators mid-sentence (e.g., "face the world--fatalistically").
# So we follow up with `_is_author_affil_line`, which adds shape and
# length constraints that body sentences fail.
_AUTHOR_AFFIL_RE = re.compile(
    r"^(?P<name>.+?)\s*(?:—|–|---|--)\s*(?P<aff>.+)$"
)

# Tokens / punctuation that almost never appear inside a real author name
# but do appear in body prose. Hitting any of these in `name` disqualifies
# the line as an author/affiliation header. We deliberately allow `.` so
# initials (J. K. Rowling) survive; the word-count check below catches
# longer prose passages.
_BODY_PROSE_MARKERS_NAME = re.compile(r"""[?!;:"*()\[\]/]""")
# Same idea for affiliations: an affiliation rarely contains quotes,
# semicolons, asterisks, italic markers, or sentence-internal lowercase
# transitions.
_BODY_PROSE_MARKERS_AFF = re.compile(r"""[?!;"*]|\.\s+[a-z]""")


def _looks_like_name(s: str) -> bool:
    """Does this string look like a person's name (1–6 capitalized words)?

    Allowed: "Justin Lewis", "J.K. Rowling", "Min-Zhan Lu",
    "Lewis, Justin", "Sano-Franchini, J.".
    Rejected: anything starting lowercase, sentence-shaped strings, very
    long strings.
    """
    s = s.strip()
    if not s or len(s) > 80:
        return False
    if not s[0].isalpha() or not s[0].isupper():
        return False
    words = s.split()
    if not (1 <= len(words) <= 6):
        return False
    if _BODY_PROSE_MARKERS_NAME.search(s):
        return False
    return True


def _looks_like_affiliation(s: str) -> bool:
    """Does this string look like a university/affiliation line?

    Allowed: "University of Washington", "Iowa State University",
    "Independent scholar".
    Rejected: anything containing body-prose markers, very long strings,
    or strings starting with lowercase.
    """
    s = s.strip()
    if not s or len(s) > 120:
        return False
    if not s[0].isalpha() or not s[0].isupper():
        return False
    words = s.split()
    if not (1 <= len(words) <= 18):
        return False
    if _BODY_PROSE_MARKERS_AFF.search(s):
        return False
    return True


def _is_author_affil_line(s: str) -> bool:
    """Strict check: line matches the author-affiliation shape AND both
    halves pass name/affiliation validation. The strictness is what
    keeps mid-sentence em-dashes in body prose from being misread as
    author/affil delimiters during ingest."""
    s = s.strip()
    m = _AUTHOR_AFFIL_RE.match(s)
    if not m:
        return False
    return _looks_like_name(m.group("name")) and _looks_like_affiliation(m.group("aff"))


def _skip_blanks(lines, i):
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def extract_lics_front_matter(text: str) -> ExtractedFrontMatter:
    """Parse LiCS submission preamble.

    LiCS convention (from spec):

        [Title]                         (optional; absent in some submissions)
        [Author 1] — [Affiliation 1]
        [Author 2] — [Affiliation 2]
        Keywords
        [semicolon-separated list]
        Abstract
        [abstract paragraph]
        [first heading or body]

    Returns the parsed pieces plus the body with preamble stripped.
    """
    fm = ExtractedFrontMatter()
    lines = text.split("\n")
    i = _skip_blanks(lines, 0)
    if i >= len(lines):
        fm.body_after_strip = text
        return fm

    first = lines[i].strip()

    # Decide whether the first line is a title or an author.
    # If it has the author-affil shape, it's an author (no title in this preamble).
    # Otherwise, treat it as the title.
    if first.startswith("#"):
        fm.body_after_strip = "\n".join(lines[i:])
        return fm

    if not _is_author_affil_line(first):
        fm.title = first.lstrip("*_ ").rstrip("*_ ") or None
        i += 1

    # Authors: consume consecutive author-affil lines (blank lines between are OK).
    while True:
        j = _skip_blanks(lines, i)
        if j >= len(lines):
            i = j
            break
        cand = lines[j].strip()
        if cand.startswith("#"):
            i = j
            break
        if cand.lower() in {"keywords", "keyword", "abstract"}:
            i = j
            break
        m = _AUTHOR_AFFIL_RE.match(cand)
        if m and _looks_like_name(m.group("name")) and _looks_like_affiliation(m.group("aff")):
            fm.authors.append(
                {"name": m.group("name").strip(), "affiliation": m.group("aff").strip()}
            )
            i = j + 1
            continue
        # Bare author name (no affiliation): accept only if we've already
        # seen one AND it passes the name shape check.
        if fm.authors and _looks_like_name(cand):
            fm.authors.append({"name": cand, "affiliation": None})
            i = j + 1
            continue
        i = j
        break

    # Keywords block.
    i = _skip_blanks(lines, i)
    if i < len(lines) and lines[i].strip().lower().startswith("keyword"):
        label_line = lines[i].strip()
        i += 1
        kw_lines = []
        # Manuscripts write this both ways: "Keywords: a; b; c" keeps the
        # values on the label line, while a bare "Keywords" puts them on the
        # lines below. Reading past an inline list swallowed it and then hit
        # "Abstract", leaving the article with no keywords at all.
        _, separator, inline = label_line.partition(":")
        if separator and inline.strip():
            kw_lines.append(inline.strip())
        else:
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    if kw_lines:
                        break
                    i += 1
                    continue
                if line.lower() == "abstract" or line.startswith("#"):
                    break
                kw_lines.append(line)
                i += 1
        raw_kw = " ".join(kw_lines)
        fm.keywords = [k.strip() for k in re.split(r"[;,]", raw_kw) if k.strip()]

    # Abstract block.
    i = _skip_blanks(lines, i)
    if i < len(lines) and lines[i].strip().lower() == "abstract":
        i += 1
        abs_lines = []
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("#"):
                break
            abs_lines.append(line)
            i += 1
        fm.abstract = "\n".join(abs_lines).strip() or None

    fm.body_after_strip = "\n".join(lines[i:]).lstrip("\n")
    return fm


def yaml_block(front_matter: dict) -> str:
    """Render YAML block with `---` fences, suitable for prepending to Markdown."""
    body = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True, width=10_000)
    return f"---\n{body}---\n\n"


def build_yaml_front_matter(text: str, log: CleanupLog, issue_metadata: Optional[dict] = None) -> str:
    """Find LiCS-style preamble, extract, emit YAML front matter prefix.

    If `text` already starts with a YAML block, leave it alone (idempotence).
    """
    if text.lstrip().startswith("---\n"):
        log.record("build_yaml_front_matter", 0, "already has front matter")
        return text

    fm = extract_lics_front_matter(text)
    if not fm.title and not fm.authors:
        log.record("build_yaml_front_matter", 0, "no preamble detected")
        return text

    # External metadata (docx pre-scan, issue config) wins over body extraction:
    # external sources are semantically more authoritative than heuristic parsing.
    extra = dict(issue_metadata or {})

    payload: dict = {}
    title = extra.pop("title", None) or fm.title
    if title:
        payload["title"] = title
    if "subtitle" in extra:
        payload["subtitle"] = extra.pop("subtitle")
    if fm.authors:
        payload["author"] = [
            {k: v for k, v in a.items() if v is not None} for a in fm.authors
        ]
    if "author" in extra:
        payload["author"] = extra.pop("author")
    if fm.abstract:
        payload["abstract"] = fm.abstract
    if "abstract" in extra:
        payload["abstract"] = extra.pop("abstract")
    if fm.keywords:
        payload["keywords"] = fm.keywords
    if "keywords" in extra:
        payload["keywords"] = extra.pop("keywords")
    for k, v in extra.items():
        payload[k] = v

    out = yaml_block(payload) + fm.body_after_strip
    log.record(
        "build_yaml_front_matter",
        1,
        f"title={bool(fm.title)} authors={len(fm.authors)} keywords={len(fm.keywords)} abstract={bool(fm.abstract)}",
    )
    return out


# ---------- pipeline ----------

Pass = Callable[[str, CleanupLog], str]

# Pandoc's HTML endnote block ends each note with a back-reference arrow,
# either as a link or bare. Nothing else in a manuscript uses this character.
_ENDNOTE_BACKREF_RE = re.compile(r"[ \t]*\[?↩︎?\]?(?:\{[^}]*\})?(?:\([^)]*\))?")

# An ordered-list item, which is what a flattened endnote becomes.
_ORDERED_ITEM_RE = re.compile(r"^\s{0,3}\d+[.)]\s")

# Any heading that already introduces the notes.
_NOTES_HEADING_RE = re.compile(r"^#{1,6}\s*(notes|endnotes)\s*$", re.IGNORECASE)


def restore_flattened_endnotes(text: str, log: CleanupLog) -> str:
    """Recover endnotes that arrived as an ordinary numbered list.

    A DOCX read through an HTML intermediate, which is what the Mammoth ingest
    engine does and what an editor round trip can do, turns Pandoc's endnote
    section into a plain ordered list whose items end with a back-reference
    arrow. The notes are no longer footnotes at that point: `journal-filter.lua`
    finds no `Note` elements to collect, so the galley gets no "Notes" heading
    and no page of its own, and the arrows print as literal characters.

    This strips the arrows and, where the list is not already introduced by a
    notes heading, supplies one. The heading is all the rest of the pipeline
    needs: the filter matches a notes heading at any level and adds the page
    break and the hanging-indent block itself.

    The arrow is the discriminator, so a manuscript that simply ends on a
    numbered list is left alone.
    """
    if "↩" not in text:
        log.record("restore_flattened_endnotes", 0)
        return text

    lines = text.split("\n")
    arrow_rows = [i for i, line in enumerate(lines) if "↩" in line]
    cleaned = [_ENDNOTE_BACKREF_RE.sub("", line).rstrip() for line in lines]

    # Walk back from the first arrow to the top of its list block.
    start = arrow_rows[0]
    while start > 0:
        previous = cleaned[start - 1]
        if _ORDERED_ITEM_RE.match(previous) or (previous.strip() and previous.startswith((" ", "\t"))):
            start -= 1
            continue
        if not previous.strip() and start - 2 >= 0 and _ORDERED_ITEM_RE.match(cleaned[start - 2]):
            start -= 1
            continue
        break

    # Is a notes heading already in front of it?
    has_heading = False
    for i in range(start - 1, -1, -1):
        candidate = cleaned[i].strip()
        if not candidate:
            continue
        if _NOTES_HEADING_RE.match(candidate):
            has_heading = True
        break

    if not has_heading:
        cleaned[start:start] = ["# Notes", ""]

    log.record(
        "restore_flattened_endnotes",
        len(arrow_rows),
        "back-references stripped" + ("" if has_heading else "; Notes heading added"),
    )
    return "\n".join(cleaned)


def merge_continued_headings(text: str, log: CleanupLog) -> str:
    r"""Join a heading that Word split across two paragraphs.

    An author who ends a heading line with Enter rather than Shift+Enter
    leaves two Heading paragraphs where they meant one heading of two lines.
    Pandoc faithfully emits two headings, and each then gets a full heading's
    space above and below, opening a gap in the middle of the title::

        # DEATH ROW, ABOLITION, AND WRITING STUDIES:
        # A LITERATURE REVIEW

    Merging is only safe with a signal that the first line is unfinished, so
    this requires it to end in a colon, comma, or an opening conjunction, and
    requires both headings to be at the same level. A genuine section followed
    by a subsection does not look like that.

    The two are joined with the " | " forced-break convention rather than a
    space, so the title still sets as two lines; see split_pipes_to_linebreaks
    in the journal filter.
    """
    lines = text.split("\n")
    out: List[str] = []
    count = 0
    i = 0
    heading = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

    while i < len(lines):
        m = heading.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue

        level, first = m.group(1), m.group(2)
        # Look past blank lines for an immediately following heading.
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        nxt = heading.match(lines[j]) if j < len(lines) else None

        unfinished = first.rstrip().endswith((":", ",")) or bool(
            re.search(r"\b(and|or|of|in|through|for|with)$", first.rstrip(), re.I)
        )
        if nxt and nxt.group(1) == level and unfinished and "|" not in first:
            out.append(f"{level} {first.rstrip()} | {nxt.group(2)}")
            count += 1
            i = j + 1
            continue

        out.append(lines[i])
        i += 1

    log.record("merge_continued_headings", count, "split headings rejoined")
    return "\n".join(out)


def normalize_scene_breaks(text: str, log: CleanupLog) -> str:
    r"""Turn a lone-asterisk scene break into an explicit thematic break.

    Manuscripts mark a scene break with a centered asterisk. Pandoc emits that
    Word paragraph as ``**\***``: bold, wrapping an escaped asterisk. The
    bold-escape repair below then unescapes it into ``*****``, which Markdown
    happens to read as a thematic break, so the ornament survived by accident
    and rendered as whatever the template draws for a rule. In LiCS that was a
    hairline across the measure, which is not what the author wrote.

    Normalizing to ``---`` states the intent, keeps the bold-escape repair away
    from it, and leaves the appearance to the journal's template. The LiCS
    templates render a thematic break as a centered asterisk.

    The first paragraph is never converted: a ``---`` at the very top would
    read as the opening of a YAML front matter block.
    """
    parts = re.split(r"(\n{2,})", text)
    paragraphs = parts[0::2]
    separators = parts[1::2]
    count = 0

    for index, para in enumerate(paragraphs):
        if index == 0:
            continue
        stripped = para.strip()
        if not stripped or "*" not in stripped:
            continue
        # Nothing but asterisks, backslashes and spaces: an ornament, not text.
        if re.fullmatch(r"[\s\\*]+", stripped):
            paragraphs[index] = "---"
            count += 1

    if not count:
        log.record("normalize_scene_breaks", 0)
        return text

    rebuilt: List[str] = []
    for index, para in enumerate(paragraphs):
        rebuilt.append(para)
        if index < len(separators):
            rebuilt.append(separators[index])
    log.record("normalize_scene_breaks", count, "asterisk ornaments made explicit")
    return "".join(rebuilt)


# A paragraph consisting of nothing but an image, which is how Pandoc emits a
# DOCX drawing. `alt` is captured so we can tell an already-captioned figure
# from a bare one.
_FIG_IMAGE_RE = re.compile(
    r"^!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)(?P<attrs>\{[^}]*\})?$"
)

# A paragraph that opens like a caption. Anchored at the start so prose that
# merely mentions "Figure 1" partway through a sentence is not mistaken for
# one. Word's caption punctuation varies, hence the character class.
_FIG_CAPTION_RE = re.compile(
    r"^(?:\*\*)?(?P<kind>Figure|Fig\.|Table|Chart|Image)\s*(?P<num>\d+)(?:\*\*)?"
    r"\s*[.:\-–—]?\s+(?P<text>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)

# A markdown heading, which bounds the search below.
_FIG_HEADING_RE = re.compile(r"^#{1,6}\s")

# Outer limit on how far either side of an image to look for its caption. The
# search normally stops earlier, at a heading or another image; this is only a
# backstop for long unbroken runs of prose. The sample article that prompted
# this pass separates caption from image by four list paragraphs.
_CAPTION_SEARCH_RADIUS = 8


def pair_figure_captions(text: str, log: CleanupLog) -> str:
    r"""Attach orphaned "Figure N." paragraphs to the images they describe.

    Word keeps captions in their own paragraphs, and frequently inside text
    boxes, so Pandoc emits them as ordinary prose some distance from the
    image rather than as a caption. The image itself arrives as a bare
    ``![](path)`` carrying no alt text, which means no ``<figure>`` element,
    no auto-numbering, and nothing for ``@fig:`` to point at.

    This pass pairs each uncaptioned image with the nearest caption-shaped
    paragraph and rewrites the two into the single form that
    ``figures-filter.lua`` expects::

        ![Flowchart of the appeals process.](assets/media/image1.png){#fig:1}

    The leading "Figure 1." is dropped from the caption text: the filter
    numbers figures in document order and supplies its own label, so keeping
    it would render "Figure 1: Figure 1. Flowchart ...".

    A caption following the image wins over one the same distance before it,
    since that is the commoner arrangement; the sample article that prompted
    this has the caption above, which is why both directions are searched.

    Idempotent. An image that already carries caption text is left alone,
    and a paired caption paragraph is consumed, so a second run finds
    nothing to do.
    """
    # Split into paragraphs while keeping the exact separators, so rejoining
    # cannot silently reflow blank-line runs elsewhere in the document.
    parts = re.split(r"(\n{2,})", text)
    paras = parts[0::2]
    seps = parts[1::2]

    image_positions = []
    for i, para in enumerate(paras):
        m = _FIG_IMAGE_RE.match(para.strip())
        if m and not m.group("alt").strip():
            image_positions.append(i)

    if not image_positions:
        log.record("pair_figure_captions", 0)
        return text

    image_set = set(image_positions)
    consumed: set[int] = set()
    count = 0

    def scan(origin: int, step: int):
        """Walk outward from an image looking for a caption paragraph.

        Stops at a heading or another image rather than at a fixed distance:
        a caption belongs to the figure sharing its run of content, however
        many list items or paragraphs Word happened to leave between them.
        """
        j = origin + step
        while 0 <= j < len(paras) and abs(j - origin) <= _CAPTION_SEARCH_RADIUS:
            para = paras[j].strip()
            if _FIG_HEADING_RE.match(para) or j in image_set:
                return None
            if j not in consumed:
                cm = _FIG_CAPTION_RE.match(para)
                if cm:
                    return (j, cm)
            j += step
        return None

    for i in image_positions:
        m = _FIG_IMAGE_RE.match(paras[i].strip())
        after = scan(i, 1)
        before = scan(i, -1)
        if after and before:
            # A caption below the figure wins a tie; that is the commoner
            # arrangement, though this sample keeps it above.
            found = after if (after[0] - i) <= (i - before[0]) else before
        else:
            found = after or before
        if not found:
            continue

        j, cm = found
        consumed.add(j)
        caption = " ".join(cm.group("text").split())
        attrs = m.group("attrs") or ""
        inner = attrs[1:-1].strip() if attrs else ""
        if "#fig:" not in inner:
            inner = f"#fig:{cm.group('num')} {inner}".strip()
        paras[i] = f"![{caption}]({m.group('path')}){{{inner}}}"
        count += 1

    if not count:
        log.record("pair_figure_captions", 0)
        return text

    kept = [i for i in range(len(paras)) if i not in consumed]
    chunks: List[str] = []
    for position, i in enumerate(kept):
        chunks.append(paras[i])
        if position < len(kept) - 1:
            chunks.append(seps[i] if i < len(seps) else "\n\n")

    log.record("pair_figure_captions", count, "caption paragraphs attached to images")
    return "".join(chunks)


DEFAULT_PASSES: List[Pass] = [
    strip_highlighter_spans,
    strip_underline_spans,
    unescape_quoted_brackets,
    reassemble_heading_linebreaks,
    # After the Word-artifact merge above, so the " | " it writes survives.
    merge_continued_headings,
    # Before the scene-break and heading work below, so the "# Notes" heading
    # it inserts is in place for everything downstream.
    restore_flattened_endnotes,
    # Before repair_pandoc_bold_escape, which would otherwise turn an asterisk
    # ornament into "*****" and thereby into an accidental thematic break.
    normalize_scene_breaks,
    split_oneline_grid_tables,
    convert_single_cell_tables_to_blockquotes,
    convert_pandoc_div_footnotes_to_native,
    repair_footnote_definitions,
    conservative_list_normalization,
    strip_orphan_page_numbers,
    normalize_dashes,
    repair_pandoc_bold_escape,
    normalize_smart_quotes,
    unfragment_works_cited,
    # Runs last so caption text has already had its dashes and quotes
    # normalized before it is folded into the image.
    pair_figure_captions,
]


def run_all(
    text: str,
    issue_metadata: Optional[dict] = None,
    passes: Optional[List[Pass]] = None,
) -> tuple[str, CleanupLog]:
    """Run all cleanup passes followed by front-matter extraction.

    Returns (cleaned_text, log).
    """
    log = CleanupLog()
    log.add(f"# Cleanup pass log")
    log.add(f"Input length: {len(text):,} chars")

    chosen = passes if passes is not None else DEFAULT_PASSES
    for fn in chosen:
        text = fn(text, log)

    text = build_yaml_front_matter(text, log, issue_metadata=issue_metadata)

    log.add(f"Output length: {len(text):,} chars")
    return text, log
