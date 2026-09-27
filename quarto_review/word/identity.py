"""Retain source identifiers in a standard custom-XML document part."""

from __future__ import annotations

import json

from lxml import etree

from quarto_review.errors import ReviewError
from quarto_review.word.namespaces import NS, tag
from quarto_review.word.package import WordPackage

PART = "customXml/quartoReview.xml"
NAMESPACE = "urn:quarto-review:exchange:v1"


def read_identity(package: WordPackage) -> dict:
    """Read an export identity without trusting it to name local files."""
    # Word renames custom XML parts to itemN.xml on save. The namespace,
    # not the ZIP member name, identifies our retained export record.
    matches = []
    for name in package.parts:
        if not name.startswith("customXml/") or not name.endswith(".xml"):
            continue
        root = package.xml(name)
        if root.tag == f"{{{NAMESPACE}}}review":
            matches.append(root)
        elif name == PART:
            raise ReviewError("Unexpected content in the review identity part")
    if not matches:
        return {}
    if len(matches) != 1:
        raise ReviewError("Multiple review identity parts are present")
    root = matches[0]
    try:
        value = json.loads(root.text or "{}")
    except ValueError as error:
        raise ReviewError("The review identity part contains invalid JSON") from error
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ReviewError("Unsupported review identity version")
    return value


def write_identity(package: WordPackage, values: dict) -> None:
    """Embed identities and register the part using an ordinary customXml relation."""
    root = etree.Element(f"{{{NAMESPACE}}}review", nsmap={None: NAMESPACE})
    root.text = json.dumps({**values, "version": 1}, ensure_ascii=False)
    package.set_xml(PART, root)
    name = "word/_rels/document.xml.rels"
    relationships = (
        package.xml(name)
        if name in package.parts
        else etree.Element(tag("pr", "Relationships"), nsmap={None: NS["pr"]})
    )
    relation = next(
        (node for node in relationships if node.get("Target") == "../" + PART), None
    )
    if relation is None:
        used = {node.get("Id") for node in relationships}
        number = 1
        while f"rIdReviewIdentity{number}" in used:
            number += 1
        etree.SubElement(
            relationships,
            tag("pr", "Relationship"),
            Id=f"rIdReviewIdentity{number}",
            Type=NS["r"] + "/customXml",
            Target="../" + PART,
        )
    package.set_xml(name, relationships)
    types = package.xml("[Content_Types].xml")
    if not any(node.get("PartName") == "/" + PART for node in types):
        etree.SubElement(
            types,
            tag("ct", "Override"),
            PartName="/" + PART,
            ContentType="application/xml",
        )
    package.set_xml("[Content_Types].xml", types)
