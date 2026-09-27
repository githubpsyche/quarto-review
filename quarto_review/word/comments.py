"""Write native comment threads and the metadata that links their replies."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from hashlib import sha256
from pathlib import PurePosixPath

from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.word.namespaces import COMMENT_PARTS, NS, tag
from quarto_review.word.package import WordPackage, parse_xml
from quarto_review.word.reader import visible_text
from quarto_review.word.records import WordComment

__all__ = ["write_comments"]


def _identifier(value: str, used: set[str]) -> str:
    """Allocate a nonzero, positive 32-bit identifier without collisions."""
    counter = 0
    while True:
        digest = sha256(f"{value}:{counter}".encode()).hexdigest()[:8]
        candidate = f"{(int(digest, 16) & 0x7FFFFFFF) or 1:08X}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _set_optional(element: etree._Element, name: str, value: str | None) -> None:
    if value is None:
        element.attrib.pop(name, None)
    else:
        element.set(name, value)


def _comment_xml(comment: WordComment, paragraph_id: str) -> etree._Element:
    element = (
        parse_xml(comment.xml.encode())
        if comment.xml is not None
        else etree.Element(tag("w", "comment"))
    )
    element.set(tag("w", "id"), comment.id)
    _set_optional(element, tag("w", "author"), comment.author)
    _set_optional(element, tag("w", "date"), comment.date)
    _set_optional(element, tag("w", "initials"), comment.initials)
    if visible_text(element).removesuffix("\n") != comment.text or len(element) == 0:
        for child in list(element):
            element.remove(child)
        for line in comment.text.split("\n"):
            paragraph = etree.SubElement(element, tag("w", "p"))
            run = etree.SubElement(paragraph, tag("w", "r"))
            text = etree.SubElement(run, tag("w", "t"))
            text.set(tag("xml", "space"), "preserve")
            text.text = line
    paragraphs = element.findall("./w:p", NS)
    if not paragraphs:
        paragraphs = [etree.SubElement(element, tag("w", "p"))]
    paragraphs[-1].set(tag("w14", "paraId"), paragraph_id)
    return element


def _previous_nodes(
    package: WordPackage, part: str, attribute: str
) -> dict[str, etree._Element]:
    if part not in package.parts:
        return {}
    return {
        element.get(attribute): element
        for element in package.xml(part)
        if element.get(attribute) is not None
    }


def _register_parts(package: WordPackage) -> None:
    path = "word/_rels/document.xml.rels"
    relationships = (
        package.xml(path)
        if path in package.parts
        else etree.Element(tag("pr", "Relationships"), nsmap={None: NS["pr"]})
    )
    content_types = package.xml("[Content_Types].xml")
    used_ids = {element.get("Id") for element in relationships}
    for name, relation_type, content_type in COMMENT_PARTS.values():
        existing = [
            element for element in relationships if element.get("Type") == relation_type
        ]
        if len(existing) > 1:
            raise ReviewError(f"Multiple relationships point to {name}")
        if existing:
            relation = existing[0]
        else:
            number = 1
            while f"rIdReview{number}" in used_ids:
                number += 1
            identifier = f"rIdReview{number}"
            used_ids.add(identifier)
            relation = etree.SubElement(relationships, tag("pr", "Relationship"))
            relation.set("Id", identifier)
            relation.set("Type", relation_type)
        relation.set("Target", PurePosixPath(name).name)
        relation.attrib.pop("TargetMode", None)
        overrides = [
            element
            for element in content_types
            if element.get("PartName") == f"/{name}"
        ]
        if not overrides:
            override = etree.SubElement(content_types, tag("ct", "Override"))
            override.set("PartName", f"/{name}")
            override.set("ContentType", content_type)
        elif len(overrides) != 1 or overrides[0].get("ContentType") != content_type:
            raise ReviewError(f"Conflicting content type for {name}")
    package.set_xml(path, relationships)
    package.set_xml("[Content_Types].xml", content_types)


def write_comments(package: WordPackage, comments: Sequence[WordComment]) -> None:
    """Write comments and modern thread metadata into an existing package.

    Anchors in document stories are left unchanged. The caller must create or
    remap those anchors separately when moving comments into a new document.
    Existing comment XML preserves formatting and extension fields when the
    comment body has not changed. New or edited bodies use ordinary paragraphs.

    Raises:
        ReviewError: Identifiers, parents, or existing package relationships
            conflict. This function does not write a file.
    """
    by_id = {comment.id: comment for comment in comments}
    if len(by_id) != len(comments) or any(not key.isdecimal() for key in by_id):
        raise ReviewError("Word comments need unique numeric IDs")
    for comment in comments:
        seen: set[str] = set()
        cursor: str | None = comment.id
        while cursor is not None:
            if cursor not in by_id:
                raise ReviewError(
                    f"Comment {comment.id} refers to missing parent {cursor}"
                )
            if cursor in seen:
                raise ReviewError(
                    f"Comment {comment.id} belongs to a cyclic reply chain"
                )
            seen.add(cursor)
            cursor = by_id[cursor].parent_id

    paragraph_ids = {
        comment.id: comment.paragraph_id for comment in comments if comment.paragraph_id
    }
    durable_ids = {
        comment.id: comment.durable_id for comment in comments if comment.durable_id
    }
    if len(set(paragraph_ids.values())) != len(paragraph_ids):
        raise ReviewError("Duplicate final comment paragraph IDs")
    if len(set(durable_ids.values())) != len(durable_ids):
        raise ReviewError("Duplicate durable comment IDs")
    used_paragraphs, used_durable = (
        set(paragraph_ids.values()),
        set(durable_ids.values()),
    )
    for comment in comments:
        if comment.id not in paragraph_ids:
            paragraph_ids[comment.id] = _identifier(
                f"paragraph:{comment.id}", used_paragraphs
            )
        if comment.id not in durable_ids:
            durable_ids[comment.id] = _identifier(f"comment:{comment.id}", used_durable)

    roots = {
        "comments": etree.Element(
            tag("w", "comments"), nsmap={"w": NS["w"], "w14": NS["w14"]}
        ),
        "extended": etree.Element(tag("w15", "commentsEx"), nsmap={"w15": NS["w15"]}),
        "ids": etree.Element(
            tag("w16cid", "commentsIds"), nsmap={"w16cid": NS["w16cid"]}
        ),
        "extensible": etree.Element(
            tag("w16cex", "commentsExtensible"), nsmap={"w16cex": NS["w16cex"]}
        ),
    }
    old_extended = _previous_nodes(
        package, COMMENT_PARTS["extended"][0], tag("w15", "paraId")
    )
    old_ids = _previous_nodes(package, COMMENT_PARTS["ids"][0], tag("w16cid", "paraId"))
    old_extensible = _previous_nodes(
        package, COMMENT_PARTS["extensible"][0], tag("w16cex", "durableId")
    )
    for comment in comments:
        paragraph_id, durable_id = paragraph_ids[comment.id], durable_ids[comment.id]
        roots["comments"].append(_comment_xml(comment, paragraph_id))
        extended = (
            deepcopy(old_extended[paragraph_id])
            if paragraph_id in old_extended
            else etree.Element(tag("w15", "commentEx"))
        )
        extended.set(tag("w15", "paraId"), paragraph_id)
        extended.set(tag("w15", "done"), "1" if comment.resolved else "0")
        _set_optional(
            extended, tag("w15", "paraIdParent"), paragraph_ids.get(comment.parent_id)
        )
        roots["extended"].append(extended)
        identity = (
            deepcopy(old_ids[paragraph_id])
            if paragraph_id in old_ids
            else etree.Element(tag("w16cid", "commentId"))
        )
        identity.set(tag("w16cid", "paraId"), paragraph_id)
        identity.set(tag("w16cid", "durableId"), durable_id)
        roots["ids"].append(identity)
        extensible = (
            deepcopy(old_extensible[durable_id])
            if durable_id in old_extensible
            else etree.Element(tag("w16cex", "commentExtensible"))
        )
        extensible.set(tag("w16cex", "durableId"), durable_id)
        date_utc = comment.date_utc
        if date_utc is None and comment.xml is None:
            date_utc = comment.date
        _set_optional(extensible, tag("w16cex", "dateUtc"), date_utc)
        roots["extensible"].append(extensible)
    for key, root in roots.items():
        package.set_xml(COMMENT_PARTS[key][0], root)
    _register_parts(package)
