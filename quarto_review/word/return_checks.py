"""Identify returned Word changes that prose reconciliation cannot represent."""

from __future__ import annotations

from hashlib import sha256
from pathlib import PurePosixPath

from lxml import etree

from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage
from quarto_review.word.relationships import internal_target, relationship_part


def unsupported_changes(before: WordPackage, after: WordPackage) -> list[dict]:
    """Report changed drawings, embedded objects, headers, and footers.

    Compare relationship contents rather than their numeric identifiers. Ordinary
    Word saves can rename relationships and record editing-session attributes
    without changing the content that the author needs to reconcile.
    """

    def inventory(package: WordPackage) -> dict[str, tuple]:
        relationships = {}
        parts = {}

        def related(owner: str, identifier: str, visiting: frozenset[str]):
            if owner not in relationships:
                name = relationship_part(owner)
                relationships[owner] = (
                    {node.get("Id"): node for node in package.xml(name)}
                    if name in package.parts
                    else {}
                )
            record = relationships[owner].get(identifier)
            if record is None:
                return ("missing-relationship", identifier)
            target = record.get("Target", "")
            if record.get("TargetMode") == "External":
                return ("external", record.get("Type"), target)
            name = internal_target(owner, target)
            if name in visiting:
                return ("cycle", record.get("Type"))
            if name not in parts:
                if name not in package.parts:
                    return ("missing-part", name)
                if name.endswith(".xml"):
                    parts[name] = element(package.xml(name), name, visiting | {name})
                else:
                    parts[name] = sha256(package.parts[name]).hexdigest()
            return (record.get("Type"), parts[name])

        def element(node, owner: str, visiting: frozenset[str]):
            attributes = []
            for name, value in node.attrib.items():
                attribute = etree.QName(name)
                if attribute.localname in {"paraId", "textId"} or (
                    attribute.namespace == NS["w"]
                    and attribute.localname.startswith("rsid")
                ):
                    continue
                if attribute.namespace == NS["r"]:
                    value = related(owner, value, visiting)
                elif node.tag.endswith("}docPr") and name == "id":
                    continue
                attributes.append((name, value))
            return (
                node.tag,
                tuple(sorted(attributes)),
                node.text if node.text and node.text.strip() else "",
                tuple(element(child, owner, visiting) for child in node),
            )

        result = {}
        object_tags = {
            tag("w", name) for name in ("drawing", "pict", "object", "altChunk")
        }
        headers, footers = [], []
        for name in package.stories():
            root = package.xml(name)
            stem = PurePosixPath(name).stem
            if stem.startswith(("header", "footer")):
                collection = headers if stem.startswith("header") else footers
                collection.append(element(root, name, frozenset({name})))
            else:
                # An object may contain a drawing. Compare only the outer object.
                result[name] = tuple(
                    element(node, name, frozenset({name}))
                    for node in root.iter()
                    if node.tag in object_tags
                    and not any(
                        parent.tag in object_tags for parent in node.iterancestors()
                    )
                )
        result["headers"] = tuple(sorted(headers, key=repr))
        result["footers"] = tuple(sorted(footers, key=repr))
        return result

    original, returned = inventory(before), inventory(after)
    return [
        {
            "kind": "unsupported-content",
            "id": name,
            "reason": (
                "The returned headers or footers changed; reconcile these with the Quarto layout"
                if name in {"headers", "footers"}
                else "A drawing, image, or embedded object changed; reconcile its source asset before importing"
            ),
        }
        for name in sorted(original.keys() | returned.keys())
        if original.get(name, ()) != returned.get(name, ())
    ]
