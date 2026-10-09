"""Self-contained HTML galley: one file, nothing beside it.

The rendered article.html links its stylesheet (`<link href="article.css">`)
and its figures (`<img src="assets/...">`) by relative path. That works when
Flask serves the article directory, and inside the OJS package ZIP, but a
lone downloaded article.html opens unstyled with broken images. This module
inlines both: local stylesheets become `<style>` blocks and local images
become `data:` URIs.

Only files inside the article directory are read. Remote URLs (the Google
Fonts @import, embedded iframes, links) are left alone, so the galley still
needs a network connection for webfonts and embeds, as any web page does.
"""
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r"""\bhref\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_STYLESHEET_RE = re.compile(r"""\brel\s*=\s*(["'])[^"']*\bstylesheet\b[^"']*\1""", re.IGNORECASE)
_IMG_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE | re.DOTALL)
_REMOTE_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)


def _local_file(base_dir: Path, ref: str) -> Path | None:
    """Resolve a relative reference to a file inside base_dir, or None."""
    if not ref or _REMOTE_RE.match(ref):
        return None
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    base = base_dir.resolve()
    target = (base / ref).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None  # path escapes the article directory
    return target if target.is_file() else None


def _inline_stylesheet(match: re.Match, base_dir: Path) -> str:
    tag = match.group(0)
    if not _STYLESHEET_RE.search(tag):
        return tag
    href = _HREF_RE.search(tag)
    css_file = _local_file(base_dir, href.group(2)) if href else None
    if css_file is None:
        return tag
    css = css_file.read_text(encoding="utf-8")
    # A literal "</style" inside the CSS would close the block early.
    css = re.sub(r"</(style)", r"<\\/\1", css, flags=re.IGNORECASE)
    return f"<style>\n/* {css_file.name} */\n{css}\n</style>"


def _inline_image(match: re.Match, base_dir: Path) -> str:
    prefix, quote, src = match.group(1), match.group(2), match.group(3)
    img_file = _local_file(base_dir, src)
    if img_file is None:
        return match.group(0)
    mime = mimetypes.guess_type(img_file.name)[0] or "application/octet-stream"
    data = base64.b64encode(img_file.read_bytes()).decode("ascii")
    return f"{prefix}{quote}data:{mime};base64,{data}{quote}"


def inline_resources(html: str, base_dir: Path) -> str:
    """Return html with local stylesheets and images embedded."""
    html = _LINK_RE.sub(lambda m: _inline_stylesheet(m, base_dir), html)
    html = _IMG_SRC_RE.sub(lambda m: _inline_image(m, base_dir), html)
    return html


def build(article_path: Path) -> str:
    """Self-contained version of an article's rendered article.html."""
    html_path = article_path / "article.html"
    return inline_resources(html_path.read_text(encoding="utf-8"), article_path)
