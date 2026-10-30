"""Binding tagged PDFs into one without losing the tagging.

Every article in an issue passed PDF/UA-1 and the bound issue failed four
checks at once (not tagged, no document title, no XMP metadata, link
annotation not tagged), because adding a page to a writer copies the page
and leaves the catalog behind. The structure tree, the parent tree that
reaches it from each page, and the marked-content flag all live there.

The parts here are built by hand rather than rendered, so the suite needs
neither Pandoc nor Typst, and so each test can hold one thing wrong: a part
that claims no conformance, a part with no tree at all, two parts whose
element ids collide. The one that matters most is the parent tree. Its keys
are a per-document counter, so two parts both begin at 0; a merge that does
not shift them writes a file in which every page of the first part resolves
into the second part's elements, and nothing about that file looks wrong
until a screen reader reads the wrong paragraph.
"""
import re
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                           DictionaryObject, IndirectObject, NameObject,
                           NumberObject, create_string_object)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf_tags


_XMP_WITH_UA = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>
   <pdfuaid:part>1</pdfuaid:part>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

_XMP_WITHOUT_UA = _XMP_WITH_UA.replace("   <pdfuaid:part>1</pdfuaid:part>\n", "")


def build_part(path: Path, *, pages: int = 2, title: str = "A Part",
               ua: bool = True, tagged: bool = True, alt: str = None,
               link: bool = False, element_id: str = None,
               role_map: dict = None, declared_next_key: int = None) -> Path:
    """Write a small tagged PDF with one /P element per page.

    The content streams carry real marked-content operators even though
    nothing here parses them, so a part looks to any other tool like what it
    claims to be.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)

    page_refs = []
    for index, page in enumerate(writer.pages):
        stream = DecodedStreamObject()
        stream.set_data(b"/P <</MCID 0>> BDC BT ET EMC")
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Tabs")] = NameObject("/S")
        page_refs.append(page.indirect_reference)

    annot_ref = None
    if link:
        annot = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(n) for n in (10, 10, 90, 30)]),
            NameObject("/Border"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(0)]),
            NameObject("/A"): DictionaryObject({
                NameObject("/S"): NameObject("/URI"),
                NameObject("/URI"): create_string_object(
                    "https://writingspaces.org/"),
            }),
        })
        annot_ref = writer._add_object(annot)
        writer.pages[0][NameObject("/Annots")] = ArrayObject([annot_ref])

    if not tagged:
        writer.add_metadata({"/Title": title})
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    struct_tree = DictionaryObject()
    struct_tree_ref = writer._add_object(struct_tree)
    document = DictionaryObject()
    document_ref = writer._add_object(document)

    kids = ArrayObject()
    parent_nums = ArrayObject()
    for index, page_ref in enumerate(page_refs):
        element = DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"),
            NameObject("/S"): NameObject("/P"),
            NameObject("/P"): document_ref,
            NameObject("/Pg"): page_ref,
            NameObject("/K"): NumberObject(0),
        })
        if alt and index == 0:
            element[NameObject("/S")] = NameObject("/Figure")
            element[NameObject("/Alt")] = create_string_object(alt)
        if element_id and index == 0:
            element[NameObject("/ID")] = create_string_object(element_id)
        element_ref = writer._add_object(element)
        kids.append(element_ref)
        page_ref.get_object()[NameObject("/StructParents")] = NumberObject(index)
        parent_nums.append(NumberObject(index))
        parent_nums.append(writer._add_object(ArrayObject([element_ref])))

    if annot_ref is not None:
        link_element = DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"),
            NameObject("/S"): NameObject("/Link"),
            NameObject("/P"): document_ref,
            NameObject("/Pg"): page_refs[0],
            NameObject("/K"): ArrayObject([DictionaryObject({
                NameObject("/Type"): NameObject("/OBJR"),
                NameObject("/Obj"): annot_ref,
                NameObject("/Pg"): page_refs[0],
            })]),
        })
        kids.append(writer._add_object(link_element))

    document.update({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Document"),
        NameObject("/P"): struct_tree_ref,
        NameObject("/K"): kids,
    })
    struct_tree.update({
        NameObject("/Type"): NameObject("/StructTreeRoot"),
        NameObject("/K"): ArrayObject([document_ref]),
        NameObject("/ParentTree"): writer._add_object(
            DictionaryObject({NameObject("/Nums"): parent_nums})),
        NameObject("/ParentTreeNextKey"): NumberObject(
            len(page_refs) if declared_next_key is None else declared_next_key),
    })
    if role_map:
        struct_tree[NameObject("/RoleMap")] = writer._add_object(
            DictionaryObject({NameObject(k): NameObject(v)
                              for k, v in role_map.items()}))
    if element_id:
        struct_tree[NameObject("/IDTree")] = writer._add_object(
            DictionaryObject({NameObject("/Names"): ArrayObject(
                [create_string_object(element_id), kids[0]])}))

    root = writer._root_object
    root[NameObject("/StructTreeRoot")] = struct_tree_ref
    root[NameObject("/MarkInfo")] = DictionaryObject({
        NameObject("/Marked"): BooleanObject(True)})
    root[NameObject("/Lang")] = create_string_object("en")
    writer.add_metadata({"/Title": title})
    writer.xmp_metadata = (_XMP_WITH_UA if ua else _XMP_WITHOUT_UA).format(
        title=title).encode("utf-8")
    with path.open("wb") as handle:
        writer.write(handle)
    return path


# ---------- reading a merged file back ----------

def elements(path: Path) -> list:
    """Every structure element in the file, as (role, dict)."""
    reader = PdfReader(str(path))
    struct_tree = reader.trailer["/Root"].get("/StructTreeRoot")
    if struct_tree is None:
        return []
    found = []

    def walk(obj):
        value = obj.get_object() if isinstance(obj, IndirectObject) else obj
        if isinstance(value, ArrayObject):
            for item in value:
                walk(item)
            return
        if not isinstance(value, DictionaryObject):
            return
        if value.get("/Type") in ("/MCR", "/OBJR"):
            found.append((str(value.get("/Type")), value))
            return
        found.append((str(value.get("/S")), value))
        walk(value.get("/K") or ArrayObject())

    walk(struct_tree.get_object()["/K"])
    return found


def parent_tree(path: Path) -> dict:
    reader = PdfReader(str(path))
    struct_tree = reader.trailer["/Root"]["/StructTreeRoot"].get_object()
    nums = struct_tree["/ParentTree"].get_object()["/Nums"]
    return {int(nums[i].get_object()): nums[i + 1]
            for i in range(0, len(nums) - 1, 2)}


def truth(value) -> bool:
    """A PDF boolean reads back as a BooleanObject, which is not a bool."""
    value = value.get_object() if isinstance(value, IndirectObject) else value
    return getattr(value, "value", value) is True


def xmp_text(path: Path) -> str:
    reader = PdfReader(str(path))
    meta = reader.trailer["/Root"].get("/Metadata")
    if meta is None:
        return ""
    return meta.get_object().get_data().decode("utf-8", "replace")


@pytest.fixture
def two_parts(tmp_path):
    return [
        (build_part(tmp_path / "one.pdf", title="One"), "One"),
        (build_part(tmp_path / "two.pdf", title="Two"), "Two"),
    ]


# ---------- the catalog an audit reads ----------

def test_the_bound_file_is_tagged(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    catalog = PdfReader(str(out)).trailer["/Root"]
    assert "/StructTreeRoot" in catalog
    assert truth(catalog["/MarkInfo"].get_object()["/Marked"])
    assert str(catalog["/Lang"]) == "en"
    assert truth(catalog["/ViewerPreferences"].get_object()["/DisplayDocTitle"])


def test_the_title_is_in_the_xmp_where_an_audit_looks_for_it(tmp_path, two_parts):
    # A /Title in the Info dictionary is not what ISO 14289-1 clause 5 reads.
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="Writing Spaces 1.1")
    raw = xmp_text(out)
    assert "Writing Spaces 1.1" in raw
    assert re.search(r"<dc:title>.*Writing Spaces 1\.1.*</dc:title>", raw, re.S)
    assert PdfReader(str(out)).metadata.title == "Writing Spaces 1.1"
    # The metadata stream dictionary has to say what it is: PDF 32000-1
    # clause 14.3.2, which pypdf's own xmp_metadata setter leaves out.
    stream = PdfReader(str(out)).trailer["/Root"]["/Metadata"].get_object()
    assert stream["/Type"] == "/Metadata"
    assert stream["/Subtype"] == "/XML"


def test_a_title_with_markup_characters_is_escaped(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out,
                                title="Reading & Writing <Spaces>")
    raw = xmp_text(out)
    assert "Reading &amp; Writing &lt;Spaces&gt;" in raw
    assert "<Spaces>" not in raw


# ---------- the parent tree, which is where a merge goes wrong ----------

def test_every_page_resolves_to_its_own_part(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    reader = PdfReader(str(out))
    nums = parent_tree(out)
    # Which /Part each page's parents sit under, found by walking /P upward.
    def part_of(element):
        while element is not None and element.get("/S") != "/Part":
            parent = element.get("/P")
            element = parent.get_object() if isinstance(parent, IndirectObject) else None
        return element

    parts_seen = []
    for page in reader.pages:
        key = page.get("/StructParents")
        assert key is not None, "a page lost its way into the parent tree"
        value = nums[int(key)].get_object()
        assert len(value) > 0
        owner = part_of(value[0].get_object())
        assert owner is not None, "a page's parents hang under no /Part"
        parts_seen.append(str(owner.get("/T")))
    # Four pages, two per part, each resolving into the part it came from.
    assert parts_seen == ["One", "One", "Two", "Two"]


def test_parent_tree_keys_do_not_collide(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    nums = parent_tree(out)
    assert sorted(nums) == [0, 1, 2, 3]
    assert report.parent_tree_keys == 4
    struct_tree = PdfReader(str(out)).trailer["/Root"]["/StructTreeRoot"].get_object()
    assert int(struct_tree["/ParentTreeNextKey"]) == 4


def test_an_under_declared_next_key_cannot_make_the_keys_collide(tmp_path):
    """A part whose tree says it ends sooner than it does.

    Taking /ParentTreeNextKey at its word would lay the second part's keys
    over the first's, and the first part's pages would then resolve into the
    second part's elements with nothing about the file to show it.
    """
    parts = [
        (build_part(tmp_path / "one.pdf", title="One", pages=3,
                    declared_next_key=1), "One"),
        (build_part(tmp_path / "two.pdf", title="Two", pages=2), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.unresolved_pages == []
    assert sorted(parent_tree(out)) == [0, 1, 2, 3, 4]
    assert [int(page["/StructParents"])
            for page in PdfReader(str(out)).pages] == [0, 1, 2, 3, 4]


def test_struct_parents_are_shifted_with_the_keys(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    keys = [int(p["/StructParents"]) for p in PdfReader(str(out)).pages]
    assert keys == [0, 1, 2, 3]


def test_every_page_reference_points_inside_the_bound_file(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    reader = PdfReader(str(out))
    page_ids = {page.indirect_reference.idnum for page in reader.pages}
    checked = 0
    for _, element in elements(out):
        page = element.get("/Pg")
        if page is None:
            continue
        assert isinstance(page, IndirectObject)
        assert page.idnum in page_ids, "/Pg points at a page from another file"
        checked += 1
    assert checked > 0


# ---------- what the tree carries ----------

def test_each_part_becomes_one_division_under_one_document(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    struct_tree = PdfReader(str(out)).trailer["/Root"]["/StructTreeRoot"].get_object()
    top = struct_tree["/K"]
    assert len(top) == 1
    document = top[0].get_object()
    assert document["/S"] == "/Document"
    divisions = [kid.get_object() for kid in document["/K"]]
    assert [str(d["/S"]) for d in divisions] == ["/Part", "/Part"]
    assert [str(d["/T"]) for d in divisions] == ["One", "Two"]


def test_alt_text_survives_the_merge(tmp_path):
    parts = [
        (build_part(tmp_path / "one.pdf", title="One",
                    alt="A flowchart of five stages"), "One"),
        (build_part(tmp_path / "two.pdf", title="Two",
                    alt="A photograph of a menu"), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    found = {str(e["/Alt"]) for _, e in elements(out) if "/Alt" in e}
    assert found == {"A flowchart of five stages", "A photograph of a menu"}


def test_a_tagged_link_annotation_is_repointed_at_the_bound_annotation(tmp_path):
    # The /OBJR is what makes a link tagged, and it names the annotation
    # object, which the page copy replaced. Left alone it points into a file
    # the bound issue does not contain.
    parts = [
        (build_part(tmp_path / "one.pdf", title="One", link=True), "One"),
        (build_part(tmp_path / "two.pdf", title="Two", link=True), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.tagged_annotations == 2
    assert report.dropped_annotations == 0

    reader = PdfReader(str(out))
    held = set()
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            held.add(annot.idnum)
    assert len(held) == 2
    references = [e for kind, e in elements(out) if kind == "/OBJR"]
    assert len(references) == 2
    for reference in references:
        # raw_get, because subscripting resolves the reference away and the
        # whole point is which object it names.
        assert reference.raw_get("/Obj").idnum in held
        assert reference["/Obj"]["/Subtype"] == "/Link"


def test_tab_order_is_set_on_every_page(tmp_path, two_parts):
    # ISO 14289-1 clause 7.18.3; a part that never set it still gets it.
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    assert all(page.get("/Tabs") == "/S" for page in PdfReader(str(out)).pages)


def test_role_maps_from_every_part_are_merged(tmp_path):
    parts = [
        (build_part(tmp_path / "one.pdf", title="One",
                    role_map={"/Em": "/Span"}), "One"),
        (build_part(tmp_path / "two.pdf", title="Two",
                    role_map={"/Terms": "/Part"}), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    struct_tree = PdfReader(str(out)).trailer["/Root"]["/StructTreeRoot"].get_object()
    role_map = struct_tree["/RoleMap"].get_object()
    assert {str(k): str(v) for k, v in role_map.items()} == {
        "/Em": "/Span", "/Terms": "/Part"}


def test_bookmarks_name_the_parts_that_have_a_title(tmp_path):
    parts = [
        (build_part(tmp_path / "front.pdf", title="Front"), ""),
        (build_part(tmp_path / "one.pdf", title="One"), "Chapter One"),
        (build_part(tmp_path / "two.pdf", title="Two"), "Chapter Two"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.outline_items == 2
    outline = PdfReader(str(out)).outline
    assert [str(item["/Title"]) for item in outline] == [
        "Chapter One", "Chapter Two"]


# ---------- element ids, which collide silently ----------

def test_colliding_element_ids_are_made_unique(tmp_path):
    # Typst numbers ids from the same origin in every document, so two
    # chapters both carry U1x0y0 and the bound file would hold the id twice.
    parts = [
        (build_part(tmp_path / "one.pdf", title="One",
                    element_id="U1x0y0"), "One"),
        (build_part(tmp_path / "two.pdf", title="Two",
                    element_id="U1x0y0"), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.ids == 2
    ids = [str(e["/ID"]) for _, e in elements(out) if "/ID" in e]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(i.endswith("U1x0y0") for i in ids)


def test_the_id_tree_is_rebuilt_sorted_and_complete(tmp_path):
    parts = [
        (build_part(tmp_path / "one.pdf", title="One",
                    element_id="zebra"), "One"),
        (build_part(tmp_path / "two.pdf", title="Two",
                    element_id="aardvark"), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    struct_tree = PdfReader(str(out)).trailer["/Root"]["/StructTreeRoot"].get_object()
    names = struct_tree["/IDTree"].get_object()["/Names"]
    keys = [str(names[i]) for i in range(0, len(names) - 1, 2)]
    assert keys == sorted(keys)
    assert {str(e["/ID"]) for _, e in elements(out) if "/ID" in e} == set(keys)
    # Each name resolves to the element that carries it.
    for i in range(0, len(names) - 1, 2):
        assert str(names[i + 1].get_object()["/ID"]) == str(names[i])


# ---------- conformance is carried, not asserted ----------

def test_conformance_is_claimed_when_every_part_claims_it(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    assert report.claims_pdf_ua is True
    assert report.unconformant_sources == []
    assert "<pdfuaid:part>1</pdfuaid:part>" in xmp_text(out)


def test_one_unconformant_part_withholds_the_claim(tmp_path):
    parts = [
        (build_part(tmp_path / "one.pdf", title="One"), "One"),
        (build_part(tmp_path / "two.pdf", title="Two", ua=False), "Two"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.claims_pdf_ua is False
    assert report.unconformant_sources == ["two.pdf"]
    # Structure, title and language still come across; only the claim does not.
    assert "pdfuaid:part" not in xmp_text(out)
    assert "<dc:title>" in xmp_text(out)
    assert "/StructTreeRoot" in PdfReader(str(out)).trailer["/Root"]
    assert report.elements > 0


def test_an_untagged_part_is_named_and_its_pages_still_bind(tmp_path):
    parts = [
        (build_part(tmp_path / "one.pdf", title="One"), "One"),
        (build_part(tmp_path / "flat.pdf", title="Flat", tagged=False), "Flat"),
    ]
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(parts, out, title="An Issue")
    assert report.untagged_sources == ["flat.pdf"]
    assert report.claims_pdf_ua is False
    assert report.pages == 4
    # The tagged part is still a division of the bound document.
    struct_tree = PdfReader(str(out)).trailer["/Root"]["/StructTreeRoot"].get_object()
    document = struct_tree["/K"][0].get_object()
    assert [str(k.get_object()["/T"]) for k in document["/K"]] == ["One"]


def test_every_tagged_page_is_reachable_from_the_tree(tmp_path, two_parts):
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    assert report.pages_tagged == 4
    assert report.unresolved_pages == []


def test_an_unreachable_page_withholds_the_claim_and_is_numbered(tmp_path,
                                                                 two_parts,
                                                                 monkeypatch):
    """The failure with no symptom, forced by shifting one key out of range.

    A page whose /StructParents is not a key in the tree renders identically
    and reads as tagged; only following the reference says otherwise, which
    is why the merge follows it before writing rather than trusting that its
    own offsets agreed.
    """
    real = pdf_tags._SourceCopier.parent_tree_pairs

    def shifted(self):
        pairs = real(self)
        return [(key + 100, value) for key, value in pairs]

    monkeypatch.setattr(pdf_tags._SourceCopier, "parent_tree_pairs", shifted)
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")

    assert report.unresolved_pages == [1, 2, 3, 4]
    assert report.claims_pdf_ua is False
    assert "pdfuaid:part" not in xmp_text(out)
    assert "4 pages not reachable" in report.summary()


def test_the_summary_names_what_came_across_without_an_em_dash(tmp_path,
                                                               two_parts):
    out = tmp_path / "issue.pdf"
    report = pdf_tags.concatenate_tagged(two_parts, out, title="An Issue")
    summary = report.summary()
    assert "structure elements" in summary
    assert "parent-tree keys" in summary
    assert "PDF/UA-1" in summary
    # House style: app-generated prose carries no em-dashes.
    assert "—" not in summary


# ---------- the whole file holds together ----------

def test_a_merged_file_can_be_merged_again(tmp_path, two_parts):
    # An issue is re-assembled whenever an article changes, and a bound issue
    # is a valid part: the merge must not depend on a part having exactly one
    # /Document at the top, or on its ids being unprefixed.
    once = tmp_path / "once.pdf"
    pdf_tags.concatenate_tagged(two_parts, once, title="An Issue")
    twice = tmp_path / "twice.pdf"
    report = pdf_tags.concatenate_tagged(
        [(once, "Volume One"), (once, "Volume One Again")], twice,
        title="A Collection")
    assert report.pages == 8
    assert report.claims_pdf_ua is True
    assert sorted(parent_tree(twice)) == list(range(8))
    keys = [int(p["/StructParents"]) for p in PdfReader(str(twice)).pages]
    assert keys == list(range(8))
