"""Regression tests for the JATS XML emitter."""
import sys
import types
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.modules.setdefault("pypandoc", types.ModuleType("pypandoc"))

import jats


def test_jats_elements_serialize_without_a_default_namespace():
    root = etree.Element("article", nsmap=jats.NSMAP)
    etree.SubElement(root, "front")

    reparsed = etree.fromstring(etree.tostring(root))

    assert etree.QName(reparsed).namespace is None
    assert reparsed.xpath("/article/front")
    assert reparsed.nsmap["xlink"] == "http://www.w3.org/1999/xlink"
    assert reparsed.nsmap["mml"] == "http://www.w3.org/1998/Math/MathML"
