"""Concatenate rendered PDFs without throwing away their tagging.

A tagged PDF keeps its structure in two places the page objects know nothing
about: a tree of structure elements hanging off the catalog's
/StructTreeRoot, and a number tree (/ParentTree) mapping each page's marked
content back up into that tree. Copying pages carries the marked content and
leaves both behind, so the obvious concatenation of six conformant galleys is
one untagged file: no headings, no reading order, no alt text reaching a
screen reader, and no tagged link annotations. That is four of the failures
an audit reports against a bound issue, and all four are already answered in
the parts.

So the tree is rebuilt rather than inferred. Each source's elements are
copied with /Pg pointing at the page that page became, its /ParentTree keys
shifted past every source before it, and each copied page's /StructParents
shifted to match. What the combined file carries is the tagging Typst
validated chapter by chapter; nothing here reads the content.

Three things do not survive a plain copy and each one fails quietly. A
/ParentTree key is a per-document counter, so two sources both start at 0 and
the second overwrites the first, which costs every page of the first source
its parents. An /OBJR is what makes a link annotation tagged, and it points
at the annotation object, which the page copy replaced with a new one; a
dangling /OBJR is itself a conformance error, so one that cannot be
repointed is dropped and counted rather than written out. And an element /ID
has to be unique across a document, while Typst numbers them per chapter
from the same origin, so each source's ids are prefixed and the /IDTree is
rebuilt over the prefixed names.

The combined file claims PDF/UA-1 only when every source claimed it. The
merge carries conformance; it cannot create it, and a part rendered without
the identifier is named in the report instead of being averaged away.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence
from xml.sax.saxutils import escape as _xml_escape

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    StreamObject,
    create_string_object,
)

# Entries on a structure element that the merge has to rewrite rather than
# carry. Everything else (/S, /T, /Alt, /ActualText, /E, /Lang, /A, /C, /R)
# is the source's own description of its own content and is copied as it
# stands.
_REWRITTEN = frozenset({"/P", "/Pg", "/K", "/ID"})

_UA_PART_RE = re.compile(r"pdfuaid:part\s*(?:>\s*|=\s*['\"])(\d)")


@dataclass
class MergeReport:
    """What the merge carried, and what it could not."""
    pages: int = 0
    sources: int = 0
    elements: int = 0
    parent_tree_keys: int = 0
    tagged_annotations: int = 0
    dropped_annotations: int = 0
    ids: int = 0
    outline_items: int = 0
    pages_tagged: int = 0
    claims_pdf_ua: bool = False
    untagged_sources: list = field(default_factory=list)
    unconformant_sources: list = field(default_factory=list)
    unresolved_pages: list = field(default_factory=list)

    def summary(self) -> str:
        """One line for a log or a status message; no em-dashes, by house style.

        The page and part counts are left out on purpose: every caller has
        already said those, and what cannot be seen by opening the file is
        whether the structure came across.
        """
        bits = [
            f"{self.elements} structure elements",
            f"{self.parent_tree_keys} parent-tree keys",
            f"{self.tagged_annotations} tagged annotations",
        ]
        if self.dropped_annotations:
            bits.append(f"{self.dropped_annotations} annotations left untagged")
        if self.unresolved_pages:
            bits.append(f"{len(self.unresolved_pages)} pages not reachable "
                        "from the tree")
        bits.append("PDF/UA-1" if self.claims_pdf_ua else "no conformance claim")
        return "; ".join(bits)


def _number_tree_items(node) -> list:
    """Flatten a number tree to (key, value) pairs, in key order.

    Typst writes /Nums directly, but a number tree may be split over /Kids
    and a reader has to handle both or it silently sees no parents at all.
    """
    if node is None:
        return []
    node = node.get_object()
    items: list = []
    nums = node.get("/Nums")
    if nums is not None:
        nums = nums.get_object()
        for i in range(0, len(nums) - 1, 2):
            items.append((int(nums[i].get_object()), nums[i + 1]))
    kids = node.get("/Kids")
    if kids is not None:
        for kid in kids.get_object():
            items.extend(_number_tree_items(kid))
    items.sort(key=lambda pair: pair[0])
    return items


def _as_text(value) -> str:
    value = value.get_object() if isinstance(value, IndirectObject) else value
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def _declared_ua_part(reader: PdfReader) -> Optional[int]:
    """The PDF/UA part a document's XMP claims, or None if it claims none."""
    meta = reader.trailer["/Root"].get("/Metadata")
    if meta is None:
        return None
    try:
        raw = meta.get_object().get_data().decode("utf-8", "replace")
    except Exception:
        return None
    match = _UA_PART_RE.search(raw)
    return int(match.group(1)) if match else None


class _SourceCopier:
    """Copies one source document's structure tree into the writer.

    The source's pages are already in the writer; `object_map` says what they
    became, so an element's /Pg and an /OBJR's /Obj can be repointed at the
    copies rather than at objects in a file the combined document never
    references.
    """

    def __init__(self, writer: PdfWriter, struct_root: DictionaryObject,
                 object_map: dict, key_offset: int, id_prefix: str):
        self.writer = writer
        self.struct_root = struct_root
        self.object_map = object_map
        self.key_offset = key_offset
        self.id_prefix = id_prefix
        # Source element idnum to the reference it became, so a /ParentTree
        # value can be repointed once the whole tree has been walked.
        self.element_map: dict = {}
        self.ids: list = []
        self.elements = 0
        self.tagged_annotations = 0
        self.dropped_annotations = 0

    # -- the tree ---------------------------------------------------------

    def copy_part(self, parent_ref: IndirectObject,
                  title: str) -> Optional[IndirectObject]:
        """Copy this source as one /Part under the combined document.

        A galley's tree is rooted in a single /Document element. The bound
        issue is the document now, so that element becomes the /Part it has
        become, titled with the chapter's own title so a tree walker can name
        the division it is in. A source shaped some other way is wrapped in a
        /Part instead, which keeps one child per source either way.
        """
        kids = self.struct_root.get("/K")
        if kids is None:
            return None
        kids = kids.get_object()
        if isinstance(kids, DictionaryObject):
            kids = ArrayObject([kids])
        if len(kids) == 1:
            only = kids[0].get_object()
            if isinstance(only, DictionaryObject) and only.get("/S") == "/Document":
                ref = self._copy_element(only, parent_ref)
                part = ref.get_object()
                part[NameObject("/S")] = NameObject("/Part")
                if title:
                    part[NameObject("/T")] = create_string_object(title)
                return ref

        part = DictionaryObject()
        ref = self.writer._add_object(part)
        part.update({
            NameObject("/Type"): NameObject("/StructElem"),
            NameObject("/S"): NameObject("/Part"),
            NameObject("/P"): parent_ref,
            NameObject("/K"): ArrayObject(
                [self._copy_kid(kid, ref) for kid in kids]),
        })
        if title:
            part[NameObject("/T")] = create_string_object(title)
        self.elements += 1
        return ref

    def _copy_element(self, src: DictionaryObject,
                      parent_ref: IndirectObject) -> IndirectObject:
        source_id = (src.indirect_reference.idnum
                     if src.indirect_reference is not None else None)
        if source_id is not None and source_id in self.element_map:
            # Already copied. A structure tree is a tree, so this should not
            # happen; it is cheap insurance against a source that reaches one
            # element from two places, where copying twice would leave the
            # /ParentTree pointing at whichever copy came last, and against a
            # cycle, which would otherwise recurse until the stack gave out.
            return self.element_map[source_id]

        dest = DictionaryObject()
        ref = self.writer._add_object(dest)
        # The reference is registered and reserved before the children are
        # copied, because each child's /P has to point back at this element.
        if source_id is not None:
            self.element_map[source_id] = ref
        for key, value in src.items():
            if key in _REWRITTEN:
                continue
            dest[NameObject(key)] = self._carry(value)
        dest[NameObject("/Type")] = NameObject("/StructElem")
        dest[NameObject("/P")] = parent_ref
        page = self._remap(src.get("/Pg"))
        if page is not None:
            dest[NameObject("/Pg")] = page
        if "/ID" in src:
            unique = self.id_prefix + _as_text(src["/ID"])
            dest[NameObject("/ID")] = create_string_object(unique)
            self.ids.append((unique, ref))
        if "/K" in src:
            dest[NameObject("/K")] = self._copy_kid(src["/K"], ref)
        self.elements += 1
        return ref

    def _copy_kid(self, kid, parent_ref: IndirectObject):
        obj = kid.get_object() if isinstance(kid, IndirectObject) else kid
        if isinstance(obj, (NumberObject, int)):
            # A marked-content id, numbered within its page. The page's
            # content stream is copied byte for byte, so it still holds.
            return NumberObject(int(obj))
        if isinstance(obj, ArrayObject):
            return ArrayObject([self._copy_kid(k, parent_ref) for k in obj])
        if not isinstance(obj, DictionaryObject):
            return NullObject()
        kind = obj.get("/Type")
        if kind == "/MCR":
            return self._copy_marked_content(obj)
        if kind == "/OBJR":
            return self._copy_object_reference(obj)
        return self._copy_element(obj, parent_ref)

    def _copy_marked_content(self, src: DictionaryObject) -> DictionaryObject:
        dest = DictionaryObject({
            NameObject("/Type"): NameObject("/MCR"),
            NameObject("/MCID"): NumberObject(int(src.get("/MCID", 0))),
        })
        page = self._remap(src.get("/Pg"))
        if page is not None:
            dest[NameObject("/Pg")] = page
        return dest

    def _copy_object_reference(self, src: DictionaryObject):
        """Repoint an /OBJR at the annotation the page copy produced.

        This is the entry that makes a link annotation tagged. The annotation
        it names belongs to the source file, so without the repoint the
        combined document holds a reference into nothing: worse than an
        untagged link, because a reader following the tree lands on a missing
        object. One that cannot be repointed is dropped and counted.
        """
        target = self._remap(src.get("/Obj"))
        if target is None:
            self.dropped_annotations += 1
            return NullObject()
        dest = DictionaryObject({
            NameObject("/Type"): NameObject("/OBJR"),
            NameObject("/Obj"): target,
        })
        page = self._remap(src.get("/Pg"))
        if page is not None:
            dest[NameObject("/Pg")] = page
        self.tagged_annotations += 1
        return dest

    def _carry(self, value):
        """Copy an entry that the merge does not rewrite."""
        if isinstance(value, IndirectObject):
            mapped = self._remap(value)
            if mapped is not None:
                return mapped
            return value.clone(self.writer)
        if isinstance(value, (DictionaryObject, ArrayObject)):
            return value.clone(self.writer)
        return value

    def _remap(self, ref):
        if not isinstance(ref, IndirectObject):
            return None
        return self.object_map.get(ref.idnum)

    # -- the parent tree --------------------------------------------------

    def parent_tree_pairs(self) -> list:
        """This source's /ParentTree, shifted past the sources before it."""
        pairs = []
        for key, value in _number_tree_items(self.struct_root.get("/ParentTree")):
            pairs.append((key + self.key_offset, self._repoint_parents(value)))
        return pairs

    def _repoint_parents(self, value):
        obj = value.get_object() if isinstance(value, IndirectObject) else value
        if isinstance(obj, ArrayObject):
            # One parent per marked-content id on the page. The spec wants
            # the array itself indirect.
            return self.writer._add_object(ArrayObject(
                [self._element(entry) for entry in obj]))
        return self._element(value)

    def _element(self, ref):
        if not isinstance(ref, IndirectObject):
            return NullObject()
        return self.element_map.get(ref.idnum, NullObject())

    def next_key(self) -> int:
        """How far the next source's keys have to be shifted past this one.

        The declared /ParentTreeNextKey is taken at its word only where the
        tree agrees with it: a producer that under-declares would have the
        next source's keys land on top of this one's, which is the collision
        the whole shift exists to prevent.
        """
        keys = [k for k, _ in _number_tree_items(
            self.struct_root.get("/ParentTree"))]
        highest = (max(keys) + 1) if keys else 0
        declared = self.struct_root.get("/ParentTreeNextKey")
        if declared is not None:
            return max(int(declared.get_object()), highest)
        return highest


def _page_object_map(reader: PdfReader, added: Sequence) -> dict:
    """Source idnum to the reference it became, for pages and annotations.

    A page's annotations are copied with the page and in the same order, so
    position is what identifies a copy; nothing else survives that both files
    share.
    """
    mapping: dict = {}
    for src, dest in zip(reader.pages, added):
        if src.indirect_reference is not None and dest.indirect_reference is not None:
            mapping[src.indirect_reference.idnum] = dest.indirect_reference
        src_annots = src.get("/Annots") or []
        dest_annots = dest.get("/Annots") or []
        for src_annot, dest_annot in zip(src_annots, dest_annots):
            if (isinstance(src_annot, IndirectObject)
                    and isinstance(dest_annot, IndirectObject)):
                mapping[src_annot.idnum] = dest_annot
    return mapping


_XMP_TEMPLATE = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
   <dc:title>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{title}</rdf:li>
    </rdf:Alt>
   </dc:title>
   <dc:language>
    <rdf:Bag>
     <rdf:li>{lang}</rdf:li>
    </rdf:Bag>
   </dc:language>
   <pdf:Producer>{producer}</pdf:Producer>
   <xmp:CreatorTool>{creator}</xmp:CreatorTool>{ua}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


def _xmp_packet(title: str, lang: str, producer: str, creator: str,
                ua_part: Optional[int]) -> bytes:
    """An XMP packet carrying the title an audit actually looks for.

    A document title in the Info dictionary is not what ISO 14289-1 clause 5
    reads; the title has to be in XMP as dc:title, and the identifier saying
    the file claims PDF/UA lives there too. A concatenation has neither,
    which is why an audit reports a bound issue as having no metadata at all.
    """
    ua = ""
    if ua_part:
        ua = f"\n   <pdfuaid:part>{int(ua_part)}</pdfuaid:part>"
    return _XMP_TEMPLATE.format(
        title=_xml_escape(title or ""),
        lang=_xml_escape(lang or "en"),
        producer=_xml_escape(producer),
        creator=_xml_escape(creator),
        ua=ua,
    ).encode("utf-8")


def concatenate_tagged(
    parts: Sequence,
    out_path: Path,
    *,
    title: str,
    lang: str = "en",
    producer: str = "Graphion",
    creator: str = "Graphion",
    outline: bool = True,
) -> MergeReport:
    """Bind `parts` into one tagged PDF at `out_path`.

    `parts` is a sequence of (path, title) pairs in reading order; the title
    names the division in the structure tree and the bookmark, and may be
    empty for a part that is not a chapter, such as the front matter.
    """
    # Walked more than once below, so a generator would come up empty on the
    # second pass and quietly bind an issue with no structure at all.
    parts = list(parts)
    writer = PdfWriter()
    report = MergeReport()
    copiers: list = []
    readers: list = []        # held so the copiers' page maps stay valid
    first_pages: list = []
    key_offset = 0

    for index, (path, part_title) in enumerate(parts):
        reader = PdfReader(str(path))
        readers.append(reader)
        first_pages.append(len(writer.pages))

        added = [writer.add_page(page) for page in reader.pages]
        object_map = _page_object_map(reader, added)

        if _declared_ua_part(reader) is None:
            report.unconformant_sources.append(Path(path).name)

        struct_root = reader.trailer["/Root"].get("/StructTreeRoot")
        if struct_root is None:
            report.untagged_sources.append(Path(path).name)
            copiers.append(None)
            continue
        struct_root = struct_root.get_object()

        copier = _SourceCopier(writer, struct_root, object_map,
                               key_offset, f"s{index:03d}-")
        copiers.append(copier)

        # A page's /StructParents is a key into the combined parent tree now,
        # so it shifts by the same offset the keys do.
        for src, dest in zip(reader.pages, added):
            parents = src.get("/StructParents")
            if parents is not None:
                dest[NameObject("/StructParents")] = NumberObject(
                    int(parents) + key_offset)
            # PDF/UA wants an explicit tab order on a page that carries
            # annotations (ISO 14289-1 clause 7.18.3); setting it on every
            # page costs nothing and does not rely on the part having had it.
            dest[NameObject("/Tabs")] = NameObject("/S")
        key_offset += copier.next_key()

    report.pages = len(writer.pages)
    report.sources = len(parts)

    # The combined tree: one /Document, with each source as a /Part under it.
    document = DictionaryObject()
    document_ref = writer._add_object(document)
    struct_tree = DictionaryObject()
    struct_tree_ref = writer._add_object(struct_tree)

    part_refs = ArrayObject()
    parent_pairs: list = []
    role_map = DictionaryObject()
    ids: list = []
    for copier, (path, part_title) in zip(copiers, parts):
        if copier is None:
            continue
        ref = copier.copy_part(document_ref, part_title)
        if ref is not None:
            part_refs.append(ref)
        parent_pairs.extend(copier.parent_tree_pairs())
        ids.extend(copier.ids)
        source_roles = copier.struct_root.get("/RoleMap")
        if source_roles is not None:
            for role, standard in source_roles.get_object().items():
                role_map[NameObject(role)] = NameObject(str(standard))
        report.elements += copier.elements
        report.tagged_annotations += copier.tagged_annotations
        report.dropped_annotations += copier.dropped_annotations

    document.update({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Document"),
        NameObject("/P"): struct_tree_ref,
        NameObject("/K"): part_refs,
    })
    if title:
        document[NameObject("/T")] = create_string_object(title)

    parent_pairs.sort(key=lambda pair: pair[0])
    nums = ArrayObject()
    for key, value in parent_pairs:
        nums.append(NumberObject(key))
        nums.append(value)
    struct_tree.update({
        NameObject("/Type"): NameObject("/StructTreeRoot"),
        NameObject("/K"): ArrayObject([document_ref]),
        NameObject("/ParentTree"): writer._add_object(
            DictionaryObject({NameObject("/Nums"): nums})),
        NameObject("/ParentTreeNextKey"): NumberObject(key_offset),
    })
    if role_map:
        struct_tree[NameObject("/RoleMap")] = writer._add_object(role_map)
    if ids:
        # An /IDTree is required once any element carries an /ID, and its
        # names have to be sorted. The prefixes are what makes them unique,
        # so they are sorted after prefixing, not before.
        names = ArrayObject()
        for unique, ref in sorted(ids, key=lambda pair: pair[0]):
            names.append(create_string_object(unique))
            names.append(ref)
        struct_tree[NameObject("/IDTree")] = writer._add_object(
            DictionaryObject({NameObject("/Names"): names}))
    report.parent_tree_keys = len(parent_pairs)
    report.ids = len(ids)

    # The keys and the pages' /StructParents come from the same offsets, so
    # they agree by construction. Checking it anyway is cheap and it is the
    # one failure with no symptom: a page whose key is not in the tree reads
    # as tagged, renders identically, and reaches a screen reader with
    # nothing above it.
    keys = {key for key, _ in parent_pairs}
    for index, page in enumerate(writer.pages):
        marked = page.get("/StructParents")
        if marked is None:
            continue
        report.pages_tagged += 1
        if int(marked) not in keys:
            report.unresolved_pages.append(index + 1)

    root = writer._root_object
    root[NameObject("/StructTreeRoot")] = struct_tree_ref
    root[NameObject("/MarkInfo")] = DictionaryObject({
        NameObject("/Marked"): BooleanObject(True),
        NameObject("/Suspects"): BooleanObject(False),
    })
    # pypdf exposes no public setter for the catalog's /Lang entry.
    root[NameObject("/Lang")] = create_string_object(lang)
    writer.add_metadata({"/Title": title})
    writer.create_viewer_preferences()
    writer.viewer_preferences.display_doctitle = True

    # Conformance is carried, not asserted: a part that did not claim
    # PDF/UA-1 leaves the combined file with structure, a title and a
    # language, and no identifier claiming more than that.
    report.claims_pdf_ua = (
        not report.unconformant_sources
        and not report.untagged_sources
        and not report.dropped_annotations
        and not report.unresolved_pages
        and bool(part_refs)
    )
    # Written as a stream rather than through pypdf's xmp_metadata setter,
    # which omits the /Type and /Subtype the metadata stream dictionary is
    # required to carry (PDF 32000-1 clause 14.3.2) and which arrived later
    # than the pypdf floor in requirements.txt. Left uncompressed, so a tool
    # can find the packet in the raw bytes.
    packet = StreamObject()
    packet.set_data(_xmp_packet(title, lang, producer, creator,
                               1 if report.claims_pdf_ua else None))
    packet[NameObject("/Type")] = NameObject("/Metadata")
    packet[NameObject("/Subtype")] = NameObject("/XML")
    root[NameObject("/Metadata")] = writer._add_object(packet)

    if outline:
        for page_index, (path, part_title) in zip(first_pages, parts):
            if part_title:
                writer.add_outline_item(part_title, page_index)
                report.outline_items += 1

    out_path = Path(out_path)
    with out_path.open("wb") as handle:
        writer.write(handle)
    return report
