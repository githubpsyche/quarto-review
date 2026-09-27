"""Extract native comments, reply links, ranges, and revision records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.records import WordAnchor, WordComment, WordReview, WordRevision

__all__ = ["read_review", "visible_text"]

TEXT_REVISIONS = {"ins", "del", "moveFrom", "moveTo"}
PROPERTY_REVISIONS = {
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "cellIns",
    "cellDel",
    "cellMerge",
}
REVISION_TAGS = {tag("w", name) for name in TEXT_REVISIONS | PROPERTY_REVISIONS}
REVISION_TAGS.update({tag("w14", "conflictIns"), tag("w14", "conflictDel")})
TEXT_TAGS = {tag("w", "t"), tag("w", "delText"), tag("m", "t")}


def visible_text(element: etree._Element, view: str = "all") -> str:
    """Read visible text while retaining paragraph, tab, and break boundaries.

    Args:
        element: An XML subtree containing Word text.
        view: ``all`` includes both sides of revisions. ``proposed`` omits
            deletions; ``original`` omits insertions. Field instructions are
            excluded in every view.
    """
    if view not in {"all", "proposed", "original"}:
        raise ValueError(f"Unknown text view: {view}")
    pieces: list[str] = []

    def visit(node: etree._Element) -> None:
        if view == "proposed" and node.tag == tag("w14", "conflictDel"):
            return
        if view == "original" and node.tag == tag("w14", "conflictIns"):
            return
        if view == "proposed" and node.tag in {tag("w", "del"), tag("w", "moveFrom")}:
            return
        if view == "original" and node.tag in {tag("w", "ins"), tag("w", "moveTo")}:
            return
        if node.tag in {tag("w", name) for name in PROPERTY_REVISIONS}:
            return
        if node.tag in TEXT_TAGS:
            pieces.append(node.text or "")
        elif node.tag == tag("w", "tab"):
            pieces.append("\t")
        elif node.tag in {tag("w", "br"), tag("w", "cr")}:
            pieces.append("\n")
        elif node.tag in {tag("w", "drawing"), tag("w", "pict")}:
            pieces.append("\ufffc")
        else:
            for child in node:
                visit(child)
            if node.tag == tag("w", "p"):
                marks = node.find("./w:pPr/w:rPr", NS)
                omitted = (
                    view != "all"
                    and marks is not None
                    and marks.find("./w:del" if view == "proposed" else "./w:ins", NS)
                    is not None
                )
                if not omitted:
                    pieces.append("\n")

    visit(element)
    return "".join(pieces)


def _comments(package: WordPackage) -> dict[str, WordComment]:
    if "word/comments.xml" not in package.parts:
        return {}
    records: dict[str, WordComment] = {}
    paragraph_ids: dict[str, str] = {}
    for element in package.xml("word/comments.xml"):
        identifier = element.get(tag("w", "id"))
        if identifier is None or identifier in records:
            raise ReviewError("word/comments.xml: missing or duplicate comment ID")
        paragraphs = element.findall("./w:p", NS)
        paragraph_id = paragraphs[-1].get(tag("w14", "paraId")) if paragraphs else None
        if paragraph_id is not None:
            if paragraph_id in paragraph_ids:
                raise ReviewError(
                    f"Duplicate final comment paragraph ID {paragraph_id}"
                )
            paragraph_ids[paragraph_id] = identifier
        records[identifier] = WordComment(
            id=identifier,
            author=element.get(tag("w", "author")),
            date=element.get(tag("w", "date")),
            initials=element.get(tag("w", "initials")),
            paragraph_id=paragraph_id,
            text=visible_text(element).removesuffix("\n"),
            xml=etree.tostring(element, encoding="unicode"),
        )

    if "word/commentsExtended.xml" in package.parts:
        for element in package.xml("word/commentsExtended.xml"):
            paragraph_id = element.get(tag("w15", "paraId"))
            identifier = paragraph_ids.get(paragraph_id)
            if identifier is None:
                raise ReviewError(
                    f"Comment extension refers to unknown paragraph {paragraph_id}"
                )
            parent = element.get(tag("w15", "paraIdParent"))
            if parent is not None and parent not in paragraph_ids:
                raise ReviewError(
                    f"Comment {identifier} has an unknown reply parent {parent}"
                )
            records[identifier] = replace(
                records[identifier],
                parent_id=paragraph_ids.get(parent),
                resolved=element.get(tag("w15", "done")) in {"1", "true"},
            )

    durable_ids: dict[str, str] = {}
    if "word/commentsIds.xml" in package.parts:
        for element in package.xml("word/commentsIds.xml"):
            identifier = paragraph_ids.get(element.get(tag("w16cid", "paraId")))
            durable = element.get(tag("w16cid", "durableId"))
            if identifier is not None and durable is not None:
                if durable in durable_ids:
                    raise ReviewError(f"Duplicate durable comment ID {durable}")
                durable_ids[durable] = identifier
                records[identifier] = replace(records[identifier], durable_id=durable)
    if "word/commentsExtensible.xml" in package.parts:
        for element in package.xml("word/commentsExtensible.xml"):
            identifier = durable_ids.get(element.get(tag("w16cex", "durableId")))
            if identifier is not None:
                records[identifier] = replace(
                    records[identifier], date_utc=element.get(tag("w16cex", "dateUtc"))
                )
    for identifier in records:
        seen: set[str] = set()
        cursor: str | None = identifier
        while cursor is not None:
            if cursor in seen:
                raise ReviewError(
                    f"Comment {identifier} belongs to a cyclic reply chain"
                )
            seen.add(cursor)
            cursor = records[cursor].parent_id
    return records


def _story(
    name: str, root: etree._Element
) -> tuple[str, dict[str, list[WordAnchor]], list[WordRevision]]:
    chunks: list[str] = []
    position = 0
    active: dict[str, int] = {}
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    references: dict[str, list[int]] = defaultdict(list)
    revisions: list[WordRevision] = []
    tree = root.getroottree()

    def append(text: str) -> None:
        nonlocal position
        chunks.append(text)
        position += len(text)

    def visit(node: etree._Element) -> None:
        start = position
        if node.tag == tag("w", "commentRangeStart"):
            identifier = node.get(tag("w", "id"))
            if identifier is None or identifier in active:
                raise ReviewError(f"{name}: duplicate or missing comment start ID")
            active[identifier] = position
        elif node.tag == tag("w", "commentRangeEnd"):
            identifier = node.get(tag("w", "id"))
            if identifier not in active:
                raise ReviewError(f"{name}: comment {identifier} ends without a start")
            ranges[identifier].append((active.pop(identifier), position))
        elif node.tag == tag("w", "commentReference"):
            identifier = node.get(tag("w", "id"))
            if identifier is not None:
                references[identifier].append(position)
        elif node.tag in TEXT_TAGS:
            append(node.text or "")
        elif node.tag == tag("w", "tab"):
            append("\t")
        elif node.tag in {tag("w", "br"), tag("w", "cr")}:
            append("\n")
        elif node.tag in {tag("w", "drawing"), tag("w", "pict")}:
            append("\ufffc")
        elif node.tag not in {tag("w", kind) for kind in PROPERTY_REVISIONS}:
            for child in node:
                visit(child)
            if node.tag == tag("w", "p"):
                append("\n")
        if node.tag in REVISION_TAGS:
            revisions.append(
                WordRevision(
                    id=node.get(tag("w", "id"), ""),
                    kind=etree.QName(node).localname,
                    story=name,
                    path=tree.getpath(node),
                    author=node.get(tag("w", "author")),
                    date=node.get(tag("w", "date")),
                    text=visible_text(node),
                    start=start,
                    end=position,
                    xml=etree.tostring(node, encoding="unicode"),
                )
            )

    visit(root)
    if active:
        raise ReviewError(f"{name}: unclosed comment ranges {', '.join(active)}")
    text = "".join(chunks)
    anchors: dict[str, list[WordAnchor]] = {}
    for identifier in ranges.keys() | references.keys():
        offsets = ranges.get(identifier) or [(p, p) for p in references[identifier]]
        anchors[identifier] = [
            WordAnchor(name, start, end, text[start:end]) for start, end in offsets
        ]
    return text, anchors, revisions


def read_review(package: WordPackage) -> WordReview:
    """Extract review records directly from their native package parts.

    The result includes every comment, including replies with no separate range,
    and recognizes text, move, and property revisions. Original XML is retained
    for fields that are not represented by the common metadata model.
    """
    comments = _comments(package)
    stories: dict[str, str] = {}
    revisions: list[WordRevision] = []
    for name in package.stories():
        text, anchors, changes = _story(name, package.xml(name))
        stories[name] = text
        revisions.extend(changes)
        for identifier, ranges in anchors.items():
            if identifier not in comments:
                raise ReviewError(
                    f"{name}: anchor refers to missing comment {identifier}"
                )
            comments[identifier] = replace(
                comments[identifier],
                anchors=comments[identifier].anchors + tuple(ranges),
            )
    return WordReview(tuple(comments.values()), tuple(revisions), stories)
