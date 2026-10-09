"""Unit tests for standalone_html.py (self-contained HTML galley)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone_html


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

HTML = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="article.css">
<link rel="stylesheet" href="https://fonts.example.com/f.css">
<link rel="icon" href="favicon.ico">
</head><body>
<img src="assets/media/image1.png" alt="A figure." />
<img src="https://example.com/remote.png" alt="Remote." />
<img src="../outside.png" alt="Outside." />
<iframe src="https://cdn.knightlab.com/timeline.html"></iframe>
</body></html>"""


def _article(tmp_path):
    (tmp_path / "article.css").write_text("body { color: #1a1a1a; }", encoding="utf-8")
    (tmp_path / "favicon.ico").write_bytes(b"ico")
    media = tmp_path / "assets" / "media"
    media.mkdir(parents=True)
    (media / "image1.png").write_bytes(PNG)
    (tmp_path.parent / "outside.png").write_bytes(PNG)
    (tmp_path / "article.html").write_text(HTML, encoding="utf-8")
    return tmp_path


def test_local_stylesheet_is_inlined(tmp_path):
    out = standalone_html.build(_article(tmp_path))
    assert '<link rel="stylesheet" href="article.css">' not in out
    assert "<style>" in out and "color: #1a1a1a" in out


def test_local_image_becomes_data_uri(tmp_path):
    out = standalone_html.build(_article(tmp_path))
    assert 'src="data:image/png;base64,' in out
    assert "assets/media/image1.png" not in out


def test_remote_and_non_stylesheet_refs_are_left_alone(tmp_path):
    out = standalone_html.build(_article(tmp_path))
    assert "https://fonts.example.com/f.css" in out
    assert '<link rel="icon" href="favicon.ico">' in out
    assert 'src="https://example.com/remote.png"' in out
    assert "https://cdn.knightlab.com/timeline.html" in out


def test_paths_outside_the_article_are_not_read(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    out = standalone_html.build(_article(art))  # writes ../outside.png too
    assert 'src="../outside.png"' in out


def test_closing_style_tag_in_css_cannot_end_the_block(tmp_path):
    art = _article(tmp_path)
    (art / "article.css").write_text("/* </style><script>x</script> */", encoding="utf-8")
    out = standalone_html.build(art)
    assert out.count("</style>") == 1


def test_idempotent(tmp_path):
    art = _article(tmp_path)
    once = standalone_html.build(art)
    assert standalone_html.inline_resources(once, art) == once
